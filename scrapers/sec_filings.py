"""
SEC EDGAR filings (official source, no API key)

Recent 8-K / 10-Q / 10-K filings and the number of Form 4 (insider transaction) filings per ticker.
SEC rejects (403) automated clients that do not give a contact address in the User-Agent header,
so SEC_USER_AGENT must be set; without it this step is skipped. Observed from a test machine:
User-Agents containing "github" (a repository URL, a GitHub noreply address) are rejected too,
a plain email address is accepted.
"""

import logging
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional

import pytz
import requests

from config import SEC_LOOKBACK_DAYS, SEC_USER_AGENT, TIMEZONE
from scrapers.retry import call_with_retry

logger = logging.getLogger(__name__)

REQUEST_TIMEOUT = 20
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


def _get_json(url: str) -> Dict:
    response = requests.get(url, headers={'User-Agent': SEC_USER_AGENT}, timeout=REQUEST_TIMEOUT)
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
        dict: {'filings': [{'form', 'date', 'label', 'url'}], 'form4_count': int}
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

    return {'filings': filings[:MAX_FILINGS_PER_TICKER], 'form4_count': form4_count}


def fetch_sec_filings(tickers: List[str], today: Optional[date] = None) -> Dict[str, Dict]:
    """
    Fetch recent SEC filings for each ticker

    Args:
        tickers: Stock ticker symbols
        today: Reference date (defaults to today in TIMEZONE)

    Returns:
        dict: ticker -> {'filings': [...], 'form4_count': int}; tickers that failed are left out
    """
    if not SEC_USER_AGENT:
        # SEC answers 403 to requests without a contact address, so do not even try
        logger.warning("SEC filings skipped: set SEC_USER_AGENT to something like 'daily-stock-report name me@example.com'")
        return {}

    today = today or datetime.now(pytz.timezone(TIMEZONE)).date()
    since = (today - timedelta(days=SEC_LOOKBACK_DAYS)).isoformat()
    logger.info(f"Fetching SEC filings since {since} for {len(tickers)} ticker(s): {tickers}")

    try:
        listing = call_with_retry(
            lambda: _get_json('https://www.sec.gov/files/company_tickers.json'), "SEC ticker list"
        )
    except Exception as e:
        logger.error(
            f"SEC ticker list unavailable (a 403 means SEC rejected the User-Agent: use a plain "
            f"contact email and no 'github' in it): {e}"
        )
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
                f"SEC filings for {ticker}",
            )
            results[ticker] = parse_recent_filings(submissions, cik, since)
        except Exception as e:
            logger.error(f"SEC filings unavailable for {ticker}: {e}")

    return results
