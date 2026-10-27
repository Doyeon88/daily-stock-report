"""
Recent SEC filings per ticker: 8-K / 10-Q / 10-K (and Form 4 counts when SEC answers)

Two sources:
 1. SEC EDGAR directly (official; item labels and Form 4 counts). SEC answers 403 to automated clients
    without a contact address in the User-Agent (SEC_USER_AGENT; "github" in it is rejected too), and
    it also refuses some cloud IPs such as GitHub Actions runners whatever the User-Agent says.
 2. Yahoo Finance's filing list (yfinance), used for every ticker SEC could not answer. It needs no
    contact header, but has no Form 4 and gives every 8-K the same generic category, so no label.
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
FORMS_OF_INTEREST = ('8-K', '10-Q', '10-K')
INSIDER_FORMS = ('4', '4/A')
MAX_FILINGS_PER_TICKER = 5

# Common 8-K item codes -> short Korean label (9.01 is just "exhibits", so it is skipped)
ITEM_LABELS = {
    '1.01': '주요 계약 체결',
    '1.02': '주요 계약 종료',
    '2.01': '자산 인수·처분 완료',
    '2.02': '실적 발표',
    '2.03': '채무 발생',
    '3.02': '미등록 주식 발행',
    '5.02': '임원·이사 변동',
    '5.07': '주주총회 결과',
    '7.01': 'Reg FD 공시',
    '8.01': '기타 주요 사건',
}


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
        filings: list of dicts with 'date' (a date object or an ISO string), 'type' and 'edgarUrl';
                 Yahoo returns an empty dict instead of an empty list when it has nothing
        since: Oldest filing date to keep, ISO format

    Returns:
        dict: {'filings': [...], 'form4_count': 0, 'source': 'yahoo'} (same shape as parse_recent_filings)
    """
    rows = []
    for item in filings if isinstance(filings, list) else []:
        filed = str(item.get('date') or '')[:10]   # a date object and an ISO string both give 'YYYY-MM-DD'; no date gives ''
        if item.get('type') in FORMS_OF_INTEREST and filed >= since and item.get('edgarUrl'):
            # Yahoo files every 8-K under the same generic category, so there is no label to show
            rows.append({'form': item['type'], 'date': filed, 'label': '', 'url': item['edgarUrl']})

    rows.sort(key=lambda row: row['date'], reverse=True)
    return {'filings': rows[:MAX_FILINGS_PER_TICKER], 'form4_count': 0, 'source': 'yahoo'}


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
    """Yahoo Finance's filing list; tickers that failed are left out"""
    results = {}
    for ticker in tickers:
        try:
            filings = call_with_retry(lambda: yf.Ticker(ticker).sec_filings, f"Yahoo filing list for {ticker}")
            results[ticker] = parse_yahoo_filings(filings, since)
        except Exception as e:
            logger.error(f"Yahoo filing list unavailable for {ticker}: {e}")
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
