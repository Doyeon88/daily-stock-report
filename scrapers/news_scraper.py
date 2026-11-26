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
ANALYST_LOOKBACK_DAYS = 30


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


def _title_key(title: str) -> str:
    """Normalized headline for de-duplication: only letters and digits, lower-cased"""
    return re.sub(r'[^a-z0-9]+', '', (title or '').lower())


def _url_key(url: str) -> str:
    """Normalized link for de-duplication: scheme, leading 'www.', trailing slash and #fragment ignored"""
    cleaned = re.sub(r'#.*$', '', (url or '').strip())
    cleaned = re.sub(r'^https?://', '', cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r'^www\.', '', cleaned, flags=re.IGNORECASE)
    return cleaned.rstrip('/').lower()


def _merge(articles: List[Dict], now: datetime, lookback_days: int = NEWS_LOOKBACK_DAYS,
           limit: Optional[int] = None) -> List[Dict]:
    """Keep recent articles, drop duplicates by title or link (keeping the first seen), newest first, capped"""
    cutoff = now - timedelta(days=lookback_days)
    positions, merged = {}, []
    for article in sorted(
        (a for a in articles if a['published'] >= cutoff), key=lambda a: a['published'], reverse=True
    ):
        entry = {
            'title': article['title'][:MAX_TITLE_LENGTH],
            'source': article['source'],
            'url': article['url'],
            'published': article['published'].astimezone(timezone.utc).isoformat(timespec='minutes'),
            'snippet': (article.get('snippet') or '')[:MAX_SNIPPET_LENGTH],
        }
        # Same story: same normalized headline OR same link (from different sources/search feeds)
        title_key, url_key = _title_key(article['title']), _url_key(article['url'])
        pos = positions.get(title_key)
        if pos is None:
            pos = positions.get(url_key)
        if pos is not None:
            # Keep the slot but prefer the copy that has an excerpt (summary material)
            if not merged[pos]['snippet'] and entry['snippet']:
                merged[pos] = entry
            positions[title_key] = positions[url_key] = pos
            continue
        positions[title_key] = positions[url_key] = len(merged)
        merged.append(entry)
    # 요약 재료가 있는 기사(Finnhub·Yahoo의 발췌문)를 먼저 고르고, 모자라면 발췌문 없는 기사(Google News)로 채운다.
    # 고른 뒤에는 다시 최신순으로 보여 준다.
    ranked = sorted(range(len(merged)), key=lambda i: (not merged[i]['snippet'], i))
    return [merged[i] for i in sorted(ranked[:limit or NEWS_LIMIT])]


ANALYST_WORDS = (
    'price target', 'target price', 'analyst', 'upgrade', 'downgrade', 'initiate', 'initiates', 'initiated',
    'reiterate', 'reiterates', 'rating', 'overweight', 'outperform', 'underperform', 'coverage', 'raises pt',
    'lowers pt', 'cuts pt', 'buy rating', 'sell rating', 'top pick',
)
ANALYST_LIMIT = 16   # 후보 수: 본문을 읽을 수 있고 5줄 이상 요약되는 최신 3개만 화면에 남긴다(main.py)


def is_analyst_article(title: str) -> bool:
    """Headline talks about an analyst report (rating, price target, coverage)"""
    lowered = (title or '').lower()
    return any(w in lowered for w in ANALYST_WORDS)


def _google_analyst_news(ticker: str, now: datetime) -> List[Dict]:
    name = STOCK_NAMES.get(ticker, ticker)
    return google_news_query(f'"{name}" analyst price target', now, lookback_days=ANALYST_LOOKBACK_DAYS)


def _primary_sources():
    """Sources with excerpts and real article links; Google News only fills what these cannot"""
    sources = [('Yahoo Finance', _yahoo_news)]
    if FINNHUB_API_KEY:
        sources.insert(0, ('Finnhub', _finnhub_news))
    return sources


def _sources():
    return _primary_sources() + [('Google News', _google_news)]


def _add_from(articles: List[Dict], sources, ticker: str, now: datetime) -> None:
    for name, fetch in sources:
        try:
            articles += call_with_retry(lambda: fetch(ticker, now), f"{name} for {ticker}")
        except Exception as e:
            logger.error(f"{name} unavailable for {ticker}: {e}")


def _excerpt_count(articles: List[Dict], now: datetime, limit: int, only=None, lookback_days=None) -> int:
    pool = [a for a in articles if only is None or only(a['title'])]
    kwargs = {'lookback_days': lookback_days} if lookback_days else {}
    return sum(1 for a in _merge(pool, now, limit=limit, **kwargs) if a['snippet'])


def _collect_articles(ticker: str, now: datetime) -> List[Dict]:
    """Finnhub and Yahoo first; Google News only when they give fewer than NEWS_LIMIT articles with an excerpt"""
    articles: List[Dict] = []
    _add_from(articles, _primary_sources(), ticker, now)
    if _excerpt_count(articles, now, NEWS_LIMIT) < NEWS_LIMIT:
        _add_from(articles, [('Google News', _google_news)], ticker, now)
    return articles


def fetch_news_bundle(tickers: List[str], now: Optional[datetime] = None) -> Dict[str, Dict[str, List[Dict]]]:
    """
    Recent headlines and analyst-report articles for each ticker

    Returns:
        {'news': {ticker: [article]}, 'analyst': {ticker: [article]}}
        article = {'title', 'source', 'url', 'published' (ISO, UTC), 'snippet'}, newest first.
        'analyst' holds the articles about ratings and price targets from every source (including an extra
        search for them), picked before the cap on 'news' is applied; the same dict objects as in 'news'
        are reused when an article is in both.
    """
    now = now or datetime.now(timezone.utc)
    logger.info(f"Fetching news for {len(tickers)} ticker(s) from: {[name for name, _ in _sources()]} "
                "(Google News only to fill up)")

    news, analyst = {}, {}
    for ticker in tickers:
        articles = _collect_articles(ticker, now)
        # Google's analyst search is the last resort, too: only if the analyst articles found so far lack excerpts
        if _excerpt_count(articles, now, ANALYST_LIMIT, only=is_analyst_article,
                          lookback_days=ANALYST_LOOKBACK_DAYS) < ANALYST_LIMIT:
            _add_from(articles, [('Google News (analyst)', _google_analyst_news)], ticker, now)
        news[ticker] = _merge(articles, now)
        pool = _merge([a for a in articles if is_analyst_article(a['title'])], now, limit=ANALYST_LIMIT,
                      lookback_days=ANALYST_LOOKBACK_DAYS)
        by_url = {a['url']: a for a in news[ticker]}
        analyst[ticker] = [by_url.get(a['url'], a) for a in pool]

    return {'news': news, 'analyst': analyst}


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
    return {ticker: _merge(_collect_articles(ticker, now), now) for ticker in tickers}
