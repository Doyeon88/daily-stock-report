"""
News headlines per ticker

Sources: Finnhub company news (official, needs FINNHUB_API_KEY, skipped without it) and
Google News RSS (no key, unofficial). Results are merged, de-duplicated and sorted newest first.
"""

import logging
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Dict, List, Optional

import requests

from config import FINNHUB_API_KEY, NEWS_LIMIT, NEWS_LOOKBACK_DAYS, STOCK_NAMES
from scrapers.retry import call_with_retry

logger = logging.getLogger(__name__)

REQUEST_TIMEOUT = 15
MAX_TITLE_LENGTH = 140


def _finnhub_news(ticker: str, now: datetime) -> List[Dict]:
    since = now - timedelta(days=NEWS_LOOKBACK_DAYS)
    response = requests.get(
        'https://finnhub.io/api/v1/company-news',
        params={'symbol': ticker, 'from': since.date().isoformat(), 'to': now.date().isoformat()},
        headers={'X-Finnhub-Token': FINNHUB_API_KEY},  # header, not query: keeps the key out of error messages
        timeout=REQUEST_TIMEOUT,
    )
    response.raise_for_status()
    return [
        {
            'title': article['headline'],
            'source': article.get('source'),
            'url': article['url'],
            'published': datetime.fromtimestamp(article['datetime'], tz=timezone.utc),
        }
        for article in response.json()
        if article.get('headline') and article.get('url') and article.get('datetime')
    ]


def _google_news(ticker: str, now: datetime) -> List[Dict]:
    name = STOCK_NAMES.get(ticker, ticker)
    response = requests.get(
        'https://news.google.com/rss/search',
        params={
            'q': f'"{name}" stock when:{NEWS_LOOKBACK_DAYS}d',
            'hl': 'en-US', 'gl': 'US', 'ceid': 'US:en',
        },
        timeout=REQUEST_TIMEOUT,
    )
    response.raise_for_status()

    articles = []
    for item in ET.fromstring(response.content).iter('item'):
        title = (item.findtext('title') or '').strip()
        link, published = item.findtext('link'), item.findtext('pubDate')
        source = (item.findtext('source') or '').strip() or None
        if source and title.endswith(f' - {source}'):
            title = title[:-len(source) - 3]  # Google appends " - Source" to every title
        if title and link and published:
            articles.append({
                'title': title, 'source': source, 'url': link,
                'published': parsedate_to_datetime(published),
            })
    return articles


def _merge(articles: List[Dict], now: datetime) -> List[Dict]:
    """Keep recent articles, drop duplicate titles (keeping the first seen), newest first, capped"""
    cutoff = now - timedelta(days=NEWS_LOOKBACK_DAYS)
    seen, merged = set(), []
    for article in sorted(
        (a for a in articles if a['published'] >= cutoff), key=lambda a: a['published'], reverse=True
    ):
        key = re.sub(r'[^a-z0-9]+', '', article['title'].lower())
        if key in seen:
            continue
        seen.add(key)
        merged.append({
            'title': article['title'][:MAX_TITLE_LENGTH],
            'source': article['source'],
            'url': article['url'],
            'published': article['published'].astimezone(timezone.utc).isoformat(timespec='minutes'),
        })
    return merged[:NEWS_LIMIT]


def fetch_news(tickers: List[str], now: Optional[datetime] = None) -> Dict[str, List[Dict]]:
    """
    Fetch recent news headlines for each ticker

    Args:
        tickers: Stock ticker symbols
        now: Reference time (defaults to the current time)

    Returns:
        dict: ticker -> list of {'title', 'source', 'url', 'published' (ISO, UTC)}, newest first
    """
    now = now or datetime.now(timezone.utc)
    sources = [('Google News', _google_news)]
    if FINNHUB_API_KEY:
        sources.insert(0, ('Finnhub', _finnhub_news))
    logger.info(f"Fetching news for {len(tickers)} ticker(s) from: {[name for name, _ in sources]}")

    results = {}
    for ticker in tickers:
        articles = []
        for name, fetch in sources:
            try:
                articles += call_with_retry(lambda: fetch(ticker, now), f"{name} news for {ticker}")
            except Exception as e:
                logger.error(f"{name} news unavailable for {ticker}: {e}")
        results[ticker] = _merge(articles, now)

    return results
