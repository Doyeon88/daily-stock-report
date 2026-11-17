"""
News headlines per ticker

Sources: Finnhub company news (official, needs FINNHUB_API_KEY, skipped without it) and
Google News RSS (no key, unofficial). Results are merged, de-duplicated and sorted newest first.
"""

import html
import logging
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Dict, List, Optional

import requests
import yfinance as yf

from config import FINNHUB_API_KEY, NEWS_LIMIT, NEWS_LOOKBACK_DAYS, STOCK_NAMES
from scrapers.retry import call_with_retry

logger = logging.getLogger(__name__)

REQUEST_TIMEOUT = 15
MAX_TITLE_LENGTH = 140
MAX_SNIPPET_LENGTH = 600


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
            'snippet': (article.get('summary') or '').strip(),
        }
        for article in response.json()
        if article.get('headline') and article.get('url') and article.get('datetime')
    ]


def _yahoo_published(content: Dict, item: Dict) -> Optional[datetime]:
    raw = content.get('pubDate') or content.get('displayTime')
    if raw:
        try:
            return datetime.fromisoformat(str(raw).replace('Z', '+00:00'))
        except ValueError:
            pass
    epoch = item.get('providerPublishTime')
    return datetime.fromtimestamp(epoch, tz=timezone.utc) if epoch else None


def _yahoo_news(ticker: str, now: datetime) -> List[Dict]:
    """Yahoo Finance's news list (yfinance): real article links and Yahoo's own one-paragraph summary"""
    articles = []
    for item in yf.Ticker(ticker).news or []:
        content = item.get('content') or item
        title = (content.get('title') or '').strip()
        url_info = content.get('canonicalUrl') or content.get('clickThroughUrl') or {}
        url = url_info.get('url') if isinstance(url_info, dict) else None
        url = url or item.get('link')
        published = _yahoo_published(content, item)
        provider = content.get('provider')
        source = (provider.get('displayName') if isinstance(provider, dict) else None) or item.get('publisher')
        raw_snippet = content.get('summary') or content.get('description') or ''
        if title and url and published:
            articles.append({
                'title': title, 'source': source, 'url': url, 'published': published,
                'snippet': _rss_snippet(raw_snippet, title),
            })
    return articles


def _rss_snippet(description, title: str) -> str:
    """Plain text of an RSS description; '' when it only repeats the headline (Google News usually does)"""
    text = re.sub(r'\s+', ' ', html.unescape(re.sub(r'<[^>]+>', ' ', description or ''))).strip()
    key = re.sub(r'[^a-z0-9]+', '', text.lower())
    return '' if not text or re.sub(r'[^a-z0-9]+', '', title.lower()) in key else text


def _google_news(ticker: str, now: datetime) -> List[Dict]:
    name = STOCK_NAMES.get(ticker, ticker)
    return google_news_query(f'"{name}" stock', now)


def google_news_query(query: str, now: datetime, lookback_days: int = NEWS_LOOKBACK_DAYS) -> List[Dict]:
    """Google News RSS articles for any search query (also used for policy tracking)"""
    response = requests.get(
        'https://news.google.com/rss/search',
        params={
            'q': f'{query} when:{lookback_days}d',
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
                'snippet': _rss_snippet(item.findtext('description'), title),
            })
    return articles


def _merge(articles: List[Dict], now: datetime, lookback_days: int = NEWS_LOOKBACK_DAYS) -> List[Dict]:
    """Keep recent articles, drop duplicate titles (keeping the first seen), newest first, capped"""
    cutoff = now - timedelta(days=lookback_days)
    positions, merged = {}, []
    for article in sorted(
        (a for a in articles if a['published'] >= cutoff), key=lambda a: a['published'], reverse=True
    ):
        key = re.sub(r'[^a-z0-9]+', '', article['title'].lower())
        entry = {
            'title': article['title'][:MAX_TITLE_LENGTH],
            'source': article['source'],
            'url': article['url'],
            'published': article['published'].astimezone(timezone.utc).isoformat(timespec='minutes'),
            'snippet': (article.get('snippet') or '')[:MAX_SNIPPET_LENGTH],
        }
        if key in positions:
            # Same headline from two sources: keep the position but prefer the copy that has an excerpt
            if not merged[positions[key]]['snippet'] and entry['snippet']:
                merged[positions[key]] = entry
            continue
        positions[key] = len(merged)
        merged.append(entry)
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
    sources = [('Google News', _google_news), ('Yahoo Finance', _yahoo_news)]
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
