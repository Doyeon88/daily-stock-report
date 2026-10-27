"""
Reddit mention ranking per ticker (ApeWisdom, no API key)

ApeWisdom counts ticker mentions in Reddit's stock subreddits (r/wallstreetbets and others) and ranks them.
This is only counts and ranks, no post text: reading Reddit itself needs an approved OAuth app, and
unauthenticated access is blocked (403 / 429).
"""

import logging
from typing import Dict, List, Optional

import requests

from scrapers.retry import call_with_retry

logger = logging.getLogger(__name__)

RANKING_URL = 'https://apewisdom.io/api/v1.0/filter/all-stocks/page/{page}'
REQUEST_TIMEOUT = 20
MAX_PAGES = 10  # the whole ranking is about 7 pages of 100 tickers


def _get_page(page: int) -> Dict:
    response = requests.get(
        RANKING_URL.format(page=page),
        headers={'User-Agent': 'daily-stock-report/1.0'},
        timeout=REQUEST_TIMEOUT,
    )
    response.raise_for_status()
    return response.json()


def parse_row(row: Dict) -> Dict:
    """The fields the report uses from one ApeWisdom ranking row"""
    return {
        'rank': row['rank'],
        'mentions': row['mentions'],
        'upvotes': row['upvotes'],
        'rank_24h_ago': row['rank_24h_ago'],
        'mentions_24h_ago': row['mentions_24h_ago'],
    }


def fetch_reddit_mentions(tickers: List[str]) -> Dict[str, Optional[Dict]]:
    """
    Look the tickers up in ApeWisdom's ranking

    Args:
        tickers: Stock ticker symbols

    Returns:
        dict: ticker -> {'rank', 'mentions', 'upvotes', 'rank_24h_ago', 'mentions_24h_ago'}, or None for a
              ticker that is not in the ranking (nobody mentioned it). If the ranking could not be read
              completely, tickers that were not found are left out, since they might be on a page that
              was not read.
    """
    wanted = {ticker.upper(): ticker for ticker in tickers}
    found: Dict[str, Dict] = {}
    scanned_everything = False

    try:
        first = call_with_retry(lambda: _get_page(1), "Reddit mention ranking")
        pages = min(int(first.get('pages', 1)), MAX_PAGES)
        for page in range(1, pages + 1):
            payload = first if page == 1 else call_with_retry(
                lambda: _get_page(page), f"Reddit mention ranking page {page}"
            )
            for row in payload.get('results', []):
                ticker = wanted.get(str(row.get('ticker', '')).upper())
                if ticker:
                    found[ticker] = parse_row(row)
            if len(found) == len(wanted):
                break
        scanned_everything = True
    except Exception as e:
        logger.error(f"Reddit mention ranking incomplete: {e}")

    results: Dict[str, Optional[Dict]] = dict(found)
    if scanned_everything:
        for ticker in tickers:
            results.setdefault(ticker, None)
    return results
