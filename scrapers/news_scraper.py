"""
News scraper using the NewsAPI service
Fetches recent news articles related to each tracked ticker
"""

import json
import logging
import time
from typing import Dict, List, Optional

import requests

from config import (
    NEWSAPI_KEY, NEWS_FILE, NEWS_SOURCES, NEWS_LANGUAGE, NEWS_LIMIT,
    MAX_RETRIES, RETRY_DELAY
)

logger = logging.getLogger(__name__)

NEWSAPI_BASE_URL = 'https://newsapi.org/v2/everything'


def fetch_news(tickers: List[str]) -> Dict[str, List[Dict]]:
    """
    Fetch recent news articles for a list of tickers

    Args:
        tickers: List of ticker symbols to fetch news for

    Returns:
        Dict mapping ticker symbol to a list of news articles
    """
    news_data = {}

    if not NEWSAPI_KEY:
        logger.warning("NEWSAPI_KEY not configured, skipping news collection")
        _save_news_data(news_data)
        return news_data

    for ticker in tickers:
        articles = _fetch_single_ticker_news(ticker)
        if articles is not None:
            news_data[ticker] = articles
        else:
            logger.error(f"Failed to fetch news for {ticker} after {MAX_RETRIES} attempts")
            news_data[ticker] = []

    _save_news_data(news_data)

    return news_data


def _fetch_single_ticker_news(ticker: str) -> Optional[List[Dict]]:
    """
    Fetch news articles for a single ticker with retry logic

    Args:
        ticker: Ticker symbol

    Returns:
        List of article dicts, or None if all retries failed
    """
    params = {
        'q': ticker,
        'language': NEWS_LANGUAGE,
        'sortBy': 'publishedAt',
        'pageSize': NEWS_LIMIT,
        # NEWS_SOURCES in config.py holds bare domain names (e.g. 'reuters');
        # only append '.com' when no TLD is already present.
        'domains': ','.join(
            source if '.' in source else f'{source}.com'
            for source in NEWS_SOURCES
        ),
        'apiKey': NEWSAPI_KEY,
    }

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = requests.get(NEWSAPI_BASE_URL, params=params, timeout=10)
            response.raise_for_status()
            payload = response.json()

            if payload.get('status') != 'ok':
                raise ValueError(f"NewsAPI error: {payload.get('message', payload)}")

            articles = [
                {
                    'title': article.get('title'),
                    'source': (article.get('source') or {}).get('name'),
                    'url': article.get('url'),
                    'published_at': article.get('publishedAt'),
                    'description': article.get('description'),
                }
                for article in payload.get('articles', [])
            ]

            logger.info(f"✓ Fetched {len(articles)} news article(s) for {ticker}")
            return articles

        except Exception as e:
            logger.warning(
                f"Attempt {attempt}/{MAX_RETRIES} failed to fetch news for {ticker}: {str(e)}"
            )
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_DELAY)

    return None


def _save_news_data(news_data: Dict[str, List[Dict]]) -> None:
    """
    Save collected news data to the configured JSON file

    Args:
        news_data: Dict of news articles keyed by ticker
    """
    try:
        with open(NEWS_FILE, 'w', encoding='utf-8') as f:
            json.dump(news_data, f, ensure_ascii=False, indent=2, default=str)
        logger.info(f"News data saved to {NEWS_FILE}")
    except Exception as e:
        logger.error(f"Failed to save news data: {str(e)}")
