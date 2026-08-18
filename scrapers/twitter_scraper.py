"""
CEO social media monitoring scraper using the Twitter/X API (via tweepy)
Fetches recent tweets from tracked companies' CEOs
"""

import json
import logging
import time
from typing import Dict, List, Optional

from config import (
    TWITTER_API_KEY, TWITTER_API_SECRET,
    TWITTER_ACCESS_TOKEN, TWITTER_ACCESS_TOKEN_SECRET,
    CEO_UPDATES_FILE, CEO_TWEETS_LIMIT, MAX_RETRIES, RETRY_DELAY
)

logger = logging.getLogger(__name__)

# Mapping of ticker -> CEO Twitter/X handle (without '@')
# Extend this mapping as new tickers are tracked
CEO_TWITTER_HANDLES = {
    'BE': 'khsrinivasan',     # Bloom Energy CEO
    'BWXT': None,             # No public handle configured
    'CRCL': None,
    'SECZ': None,
}


def fetch_ceo_tweets(tickers: List[str]) -> Dict[str, List[Dict]]:
    """
    Fetch recent tweets from CEOs of tracked companies

    Args:
        tickers: List of ticker symbols to fetch CEO updates for

    Returns:
        Dict mapping ticker symbol to a list of tweet dicts
    """
    ceo_data = {}

    client = _get_twitter_client()
    if client is None:
        logger.warning("Twitter API credentials not configured, skipping CEO monitoring")
        _save_ceo_data(ceo_data)
        return ceo_data

    for ticker in tickers:
        handle = CEO_TWITTER_HANDLES.get(ticker)
        if not handle:
            logger.info(f"No CEO Twitter handle configured for {ticker}, skipping")
            ceo_data[ticker] = []
            continue

        tweets = _fetch_single_ceo_tweets(client, handle)
        ceo_data[ticker] = tweets if tweets is not None else []

    _save_ceo_data(ceo_data)

    return ceo_data


def _get_twitter_client():
    """
    Create and return a Twitter API client, or None if credentials are missing/invalid

    Returns:
        tweepy.Client instance, or None
    """
    if not all([TWITTER_API_KEY, TWITTER_API_SECRET, TWITTER_ACCESS_TOKEN, TWITTER_ACCESS_TOKEN_SECRET]):
        return None

    try:
        import tweepy
        return tweepy.Client(
            consumer_key=TWITTER_API_KEY,
            consumer_secret=TWITTER_API_SECRET,
            access_token=TWITTER_ACCESS_TOKEN,
            access_token_secret=TWITTER_ACCESS_TOKEN_SECRET,
        )
    except Exception as e:
        logger.error(f"Failed to initialize Twitter client: {str(e)}")
        return None


def _fetch_single_ceo_tweets(client, handle: str) -> Optional[List[Dict]]:
    """
    Fetch recent tweets for a single CEO handle with retry logic

    Args:
        client: tweepy.Client instance
        handle: Twitter/X handle (without '@')

    Returns:
        List of tweet dicts, or None if all retries failed
    """
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            user = client.get_user(username=handle)
            if not user.data:
                logger.warning(f"Twitter user not found: {handle}")
                return []

            response = client.get_users_tweets(
                id=user.data.id,
                max_results=min(max(CEO_TWEETS_LIMIT, 5), 100),
                tweet_fields=['created_at', 'public_metrics']
            )

            tweets = []
            for tweet in (response.data or [])[:CEO_TWEETS_LIMIT]:
                tweets.append({
                    'id': tweet.id,
                    'text': tweet.text,
                    'created_at': str(getattr(tweet, 'created_at', None)),
                })

            logger.info(f"✓ Fetched {len(tweets)} tweet(s) for @{handle}")
            return tweets

        except Exception as e:
            logger.warning(
                f"Attempt {attempt}/{MAX_RETRIES} failed to fetch tweets for @{handle}: {str(e)}"
            )
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_DELAY)

    return None


def _save_ceo_data(ceo_data: Dict[str, List[Dict]]) -> None:
    """
    Save collected CEO tweet data to the configured JSON file

    Args:
        ceo_data: Dict of tweet lists keyed by ticker
    """
    try:
        with open(CEO_UPDATES_FILE, 'w', encoding='utf-8') as f:
            json.dump(ceo_data, f, ensure_ascii=False, indent=2, default=str)
        logger.info(f"CEO update data saved to {CEO_UPDATES_FILE}")
    except Exception as e:
        logger.error(f"Failed to save CEO update data: {str(e)}")
