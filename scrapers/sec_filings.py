"""
Recent SEC filings per ticker: 8-K / 10-Q / 10-K (and Form 4 counts when SEC answers)

Two sources:
 1. SEC EDGAR directly (official; item labels and Form 4 counts). SEC answers 403 to automated clients
    without a contact address in the User-Agent (SEC_USER_AGENT; "github" in it is rejected too), and
    it also refuses some cloud IPs such as GitHub Actions runners whatever the User-Agent says.
 2. Yahoo Finance's filing list (yfinance), used for every ticker SEC could not answer. It needs no
    contact header and has no Form 4. Yahoo gives every 8-K the same generic category, so the 8-K's own
    text (on Yahoo's CDN, which GitHub Actions can reach) is read for its item numbers, and the attached
    press release (EX-99.1) is kept for the AI summary.
"""

import html
import logging
import re
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional

import pytz
import requests
import yfinance as yf

from config import SEC_LOOKBACK_DAYS, SEC_USER_AGENT, TIMEZONE
from scrapers.retry import call_with_retry

logger = logging.getLogger(__name__)

REQUEST_TIMEOUT = 20
REFUSAL_TEXT_LENGTH = 200
DOCUMENT_TIMEOUT = 12
MAX_PRESS_CHARS = 3500          # 보도자료 본문 중 AI에 주는 길이
OFFERING_FORMS = (                                          # 증권 발행(IPO·유상증자·선반등록·ATM) 서류
    'S-1', 'S-1/A', 'S-1MEF', 'F-1', 'F-1/A', 'S-3', 'S-3/A', 'S-3ASR', 'F-3', 'F-3/A',
    '424B3', '424B4', '424B5', '424B7',
)
FORMS_OF_INTEREST = (
    '8-K', '6-K', '10-Q', '10-K',
    *OFFERING_FORMS,
    'SCHEDULE 13D', 'SCHEDULE 13D/A', 'SCHEDULE 13G', 'SCHEDULE 13G/A',  # 5% 이상 보유(2025년부터의 EDGAR 양식명)
    'SC 13D', 'SC 13D/A', 'SC 13G', 'SC 13G/A',                # 이전 양식명
)
EVENT_FORMS = ('8-K', '6-K')    # 보도자료(EX-99.x)가 붙는 수시 공시
INSIDER_FORMS = ('4', '4/A')
MAX_FILINGS_PER_TICKER = 8

# Common 8-K item codes -> short Korean label (9.01 is just "exhibits", so it is skipped)
ITEM_LABELS = {
    '1.01': '주요 계약 체결',
    '1.02': '주요 계약 종료',
    '2.01': '자산 인수·처분 완료',
    '2.02': '실적 발표',
    '2.03': '채무 발생',
    '2.05': '구조조정 비용',
    '2.06': '자산 손상',
    '3.01': '상장 유지 요건 미달',
    '3.02': '미등록 주식 발행',
    '3.03': '주주 권리 변경',
    '4.01': '감사인 변경',
    '4.02': '과거 재무제표 신뢰 불가',
    '5.01': '지배권 변경',
    '5.02': '임원·이사 변동',
    '5.03': '정관 변경',
    '5.07': '주주총회 결과',
    '7.01': 'Reg FD 공시',
    '8.01': '기타 주요 사건',
}


# 양식별 한 줄 설명 (공시 본문은 읽지 않으므로 양식 종류에 대한 설명입니다)
FORM_DESCRIPTIONS = {
    '8-K': '수시 공시(주요 사건 보고)',
    '6-K': '외국 기업 수시 공시',
    '10-Q': '분기보고서(재무제표·MD&A)',
    '10-K': '연간보고서',
    'S-1': '증권 신고서(IPO·상장·유상증자 준비)',
    'S-1/A': '증권 신고서 정정',
    'S-1MEF': '증권 신고서 발행 규모 증액',
    'F-1': '외국 기업 증권 신고서',
    'F-1/A': '외국 기업 증권 신고서 정정',
    'S-3': '선반등록(추가 증권 발행 준비)',
    'S-3/A': '선반등록 정정',
    'S-3ASR': '자동 선반등록(대형 발행사, 즉시 발행 가능)',
    'F-3': '외국 기업 선반등록',
    'F-3/A': '외국 기업 선반등록 정정',
    '424B3': '투자설명서(증권 발행·재판매)',
    '424B4': '최종 투자설명서(증권 발행 조건 확정)',
    '424B5': '투자설명서 보충(유상증자·ATM·전환사채 발행)',
    '424B7': '투자설명서 보충(기존 주주 매도 등록)',
    'SCHEDULE 13D': '5% 이상 보유 신고(경영 참여 의도 가능)',
    'SCHEDULE 13D/A': '5% 이상 보유 변동 신고(13D)',
    'SCHEDULE 13G': '5% 이상 보유 신고(수동적 투자)',
    'SCHEDULE 13G/A': '5% 이상 보유 변동 신고(13G)',
}
FORM_DESCRIPTIONS.update({'SC 13D': FORM_DESCRIPTIONS['SCHEDULE 13D'], 'SC 13D/A': FORM_DESCRIPTIONS['SCHEDULE 13D/A'],
                          'SC 13G': FORM_DESCRIPTIONS['SCHEDULE 13G'], 'SC 13G/A': FORM_DESCRIPTIONS['SCHEDULE 13G/A']})


def describe_form(form: str, label: str = '') -> str:
    """One-line description of a filing: the 8-K item label when known, else what the form is"""
    base = FORM_DESCRIPTIONS.get(form, form)
    return f"{base} · {label}" if label else base


class SecRefusedError(Exception):
    """SEC answered 403: it refuses this client (User-Agent or IP), so asking again cannot help"""


def _visible_text(html_text: str) -> str:
    """Readable text of an HTML page, e.g. the reason SEC gives on its refusal page"""
    without_scripts = re.sub(r'<(script|style).*?</\1>', ' ', html_text, flags=re.S | re.I)
    return ' '.join(html.unescape(re.sub(r'<[^>]+>', ' ', without_scripts)).split())


def _get_json(url: str) -> Dict:
    response = requests.get(url, headers={'User-Agent': SEC_USER_AGENT}, timeout=REQUEST_TIMEOUT)
    if response.status_code == 403:
        # SEC's page names the reason, e.g. "Request Rate Threshold Exceeded" or "Undeclared Automated Tool"
        raise SecRefusedError(f"403 Forbidden: {_visible_text(response.text)[:REFUSAL_TEXT_LENGTH]}")
    response.raise_for_status()
    return response.json()


def describe_items(items: str) -> str:
    """Turn an 8-K item string like '2.02,9.01' into a short label like '실적 발표'"""
    codes = [code.strip() for code in (items or '').split(',') if code.strip() and code.strip() != '9.01']
    return ', '.join(ITEM_LABELS.get(code, f"Item {code}") for code in codes[:2])


def parse_recent_filings(submissions: Dict, cik: int, since: str) -> Dict:
    """
    Extract recent filings from an EDGAR submissions document

    Args:
        submissions: JSON from data.sec.gov/submissions/CIK##########.json
        cik: Company CIK (used to build document links)
        since: Oldest filing date to keep, ISO format

    Returns:
        dict: {'filings': [{'form', 'date', 'label', 'url'}], 'form4_count': int, 'source': 'sec'}
    """
    recent = submissions['filings']['recent']
    count = len(recent['form'])
    items_column = recent.get('items') or [''] * count

    filings, form4_count = [], 0
    for i, form in enumerate(recent['form']):
        filed = recent['filingDate'][i]
        if filed < since:  # ISO dates compare correctly as strings
            continue
        if form in INSIDER_FORMS:
            form4_count += 1
        elif form in FORMS_OF_INTEREST:
            accession = recent['accessionNumber'][i].replace('-', '')
            filings.append({
                'form': form,
                'date': filed,
                'label': describe_items(items_column[i]) if form == '8-K' else '',
                'url': f"https://www.sec.gov/Archives/edgar/data/{cik}/{accession}/{recent['primaryDocument'][i]}",
            })

    return {'filings': filings[:MAX_FILINGS_PER_TICKER], 'form4_count': form4_count, 'source': 'sec'}


def parse_yahoo_filings(filings, since: str) -> Dict:
    """
    Extract recent filings from yfinance's Ticker.sec_filings

    Args:
        filings: list of dicts with 'date' (a date object or an ISO string), 'type', 'edgarUrl' and optionally
                 'exhibits' ({name: Yahoo CDN link}); Yahoo returns an empty dict instead of an empty list
                 when it has nothing
        since: Oldest filing date to keep, ISO format

    Returns:
        dict: {'filings': [...], 'form4_count': 0, 'source': 'yahoo'} (same shape as parse_recent_filings).
        8-K/6-K rows also carry 'doc_url' (the filing itself) and 'press_url' (EX-99.1, usually the press
        release) when Yahoo lists them; the label is filled in later from the filing's text.
    """
    rows = []
    for item in filings if isinstance(filings, list) else []:
        filed = str(item.get('date') or '')[:10]   # a date object and an ISO string both give 'YYYY-MM-DD'; no date gives ''
        if item.get('type') in FORMS_OF_INTEREST and filed >= since and item.get('edgarUrl'):
            # Yahoo files every 8-K under the same generic category, so the label comes from the 8-K's text
            row = {'form': item['type'], 'date': filed, 'label': '', 'url': item['edgarUrl']}
            exhibits = item.get('exhibits') if isinstance(item.get('exhibits'), dict) else {}
            if item['type'] in EVENT_FORMS:
                if exhibits.get(item['type']):
                    row['doc_url'] = exhibits[item['type']]
                press = exhibits.get('EX-99.1') or next(
                    (url for name, url in sorted(exhibits.items()) if name.startswith('EX-99')), None)
                if press:
                    row['press_url'] = press
            rows.append(row)

    rows.sort(key=lambda row: row['date'], reverse=True)
    return {'filings': rows[:MAX_FILINGS_PER_TICKER], 'form4_count': 0, 'source': 'yahoo'}


_ITEM_PATTERN = re.compile(r'\bItem\s*(\d{1,2}\.\d{2})\b', re.I)


def items_from_text(text: str) -> str:
    """8-K item codes found in the filing's text, in order and without repeats, as '2.02,7.01'"""
    codes = []
    for code in _ITEM_PATTERN.findall(text or ''):
        if code not in codes:
            codes.append(code)
    return ','.join(codes)


def document_text(page_html: str, limit: Optional[int] = None) -> str:
    """Plain text of a filing document (EDGAR documents use <div>/<span>, not <p>, so every tag is dropped)"""
    text = _visible_text(page_html or '')
    return text[:limit] if limit else text


def fetch_document_text(url: str, limit: Optional[int] = None) -> str:
    """Best effort: a filing document's plain text from Yahoo's CDN, '' if it cannot be read"""
    try:
        response = requests.get(url, headers={'User-Agent': 'Mozilla/5.0 (compatible; daily-stock-report)'},
                                timeout=DOCUMENT_TIMEOUT)
        response.raise_for_status()
        return document_text(response.text[:2_000_000], limit)
    except Exception as e:
        logger.debug(f"Filing document unreadable {url}: {e}")
        return ''


def add_event_details(result: Dict) -> None:
    """
    For the 8-K/6-K rows of one ticker (in place): label the 8-K items read from the filing's own text and
    keep the press release text (EX-99.1) in '_press_text' for the AI summary (main.py takes it out again)
    """
    for row in result.get('filings', []):
        if row['form'] == '8-K' and not row.get('label') and row.get('doc_url'):
            row['label'] = describe_items(items_from_text(fetch_document_text(row['doc_url'])))
        if row.get('press_url'):
            text = fetch_document_text(row['press_url'], MAX_PRESS_CHARS)
            if text:
                row['_press_text'] = text


def _fetch_from_sec(tickers: List[str], since: str) -> Dict[str, Dict]:
    """SEC EDGAR; tickers that could not be answered are left out"""
    if not SEC_USER_AGENT:
        logger.warning("SEC EDGAR skipped: SEC_USER_AGENT is not set (e.g. 'daily-stock-report name me@example.com')")
        return {}
    if not (SEC_USER_AGENT.isascii() and SEC_USER_AGENT.isprintable()):
        # An HTTP header cannot carry Korean text or line breaks; requests would fail with an obscure error
        logger.warning("SEC EDGAR skipped: SEC_USER_AGENT must be plain ASCII on a single line (no Korean, no line breaks)")
        return {}

    try:
        listing = call_with_retry(
            lambda: _get_json('https://www.sec.gov/files/company_tickers.json'), "SEC ticker list",
            give_up_on=(SecRefusedError,),
        )
    except Exception as e:
        logger.error(f"SEC EDGAR unavailable, using Yahoo Finance instead: {e}")
        return {}
    ciks = {entry['ticker'].upper(): int(entry['cik_str']) for entry in listing.values()}

    results = {}
    for ticker in tickers:
        cik = ciks.get(ticker.upper())
        if cik is None:
            logger.warning(f"{ticker}: not found in the SEC ticker list")
            continue
        try:
            submissions = call_with_retry(
                lambda: _get_json(f"https://data.sec.gov/submissions/CIK{cik:010d}.json"),
                f"SEC filings for {ticker}", give_up_on=(SecRefusedError,),
            )
            results[ticker] = parse_recent_filings(submissions, cik, since)
        except SecRefusedError as e:
            # The remaining tickers would be refused too; do not keep knocking
            logger.error(f"SEC refused the request for {ticker}, using Yahoo Finance for the rest: {e}")
            break
        except Exception as e:
            logger.error(f"SEC filings unavailable for {ticker}: {e}")

    return results


def _fetch_from_yahoo(tickers: List[str], since: str) -> Dict[str, Dict]:
    """Yahoo Finance's filing list (8-K items read from the filing, press releases kept); failed tickers are left out"""
    results = {}
    for ticker in tickers:
        try:
            filings = call_with_retry(lambda: yf.Ticker(ticker).sec_filings, f"Yahoo filing list for {ticker}")
            results[ticker] = parse_yahoo_filings(filings, since)
        except Exception as e:
            logger.error(f"Yahoo filing list unavailable for {ticker}: {e}")
            continue
        try:
            add_event_details(results[ticker])
        except Exception as e:
            logger.error(f"{ticker}: 8-K items / press releases unavailable: {e}")
    return results


def fetch_sec_filings(tickers: List[str], today: Optional[date] = None) -> Dict[str, Dict]:
    """
    Fetch recent filings for each ticker: SEC EDGAR first, Yahoo Finance for what SEC could not answer

    Args:
        tickers: Stock ticker symbols
        today: Reference date (defaults to today in TIMEZONE)

    Returns:
        dict: ticker -> {'filings': [...], 'form4_count': int, 'source': 'sec' | 'yahoo'};
              tickers that no source could answer are left out
    """
    today = today or datetime.now(pytz.timezone(TIMEZONE)).date()
    since = (today - timedelta(days=SEC_LOOKBACK_DAYS)).isoformat()
    logger.info(f"Fetching filings since {since} for {len(tickers)} ticker(s): {tickers}")

    results = _fetch_from_sec(tickers, since)

    missing = [ticker for ticker in tickers if ticker not in results]
    if missing:
        logger.info(f"Using Yahoo Finance's filing list for: {missing}")
        results.update(_fetch_from_yahoo(missing, since))

    return results
