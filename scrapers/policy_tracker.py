"""
정책·규제 추적: watchlist.json의 policy_queries로 Google News RSS를 검색합니다.
헤드라인은 언론 보도라서 '미검증' 표시로 나가며, 법안 통과 여부 등은 원문(의회·AP 등)으로 확인하세요.
"""

import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional

from config import POLICY_QUERIES
from scrapers import news_scraper
from scrapers.retry import call_with_retry

logger = logging.getLogger(__name__)

PER_QUERY = 3


def fetch_policy_news(queries: Optional[List[str]] = None, now: Optional[datetime] = None) -> List[Dict]:
    """[{'query', 'articles': [{'title', 'source', 'url', 'published'}]}]; queries with no hits are omitted"""
    queries = POLICY_QUERIES if queries is None else queries
    now = now or datetime.now(timezone.utc)
    results = []
    for query in queries:
        try:
            articles = call_with_retry(
                lambda: news_scraper.google_news_query(query, now, lookback_days=7), f"policy news '{query}'")
        except Exception as e:
            logger.error(f"Policy news unavailable for '{query}': {e}")
            continue
        merged = news_scraper._merge(articles, now, lookback_days=7)[:PER_QUERY]
        if merged:
            results.append({'query': query, 'articles': merged})
    return results
