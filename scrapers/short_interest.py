"""
Short interest scraper using the Finnhub API
Fetches short interest / short volume data for tracked tickers
"""

import json
import logging
import time
from typing import Dict, List, Optional

import requests

from config import FINNHUB_API_KEY, SHORT_INTEREST_FILE, MAX_RETRIES, RETRY_DELAY

logger = logging.getLogger(__name__)

FINNHUB_BASE_URL = 'https://finnhub.io/api/v1'


def fetch_short_interest(tickers: List[str]) -> Dict[str, Dict]:
    """
    Fetch short interest data for a list of tickers

    Args:
        tickers: List of ticker symbols to fetch data for

    Returns:
        Dict mapping ticker symbol to its short interest data
    """
    short_data = {}

    if not FINNHUB_API_KEY:
        logger.warning("FINNHUB_API_KEY not configured, skipping short interest collection")
        _save_short_interest_data(short_data)
        return short_data

    for ticker in tickers:
        data = _fetch_single_ticker_short_interest(ticker)
        if data is not None:
            short_data[ticker] = data
        else:
            logger.error(f"Failed to fetch short interest for {ticker} after {MAX_RETRIES} attempts")

    _save_short_interest_data(short_data)

    return short_data


def _fetch_single_ticker_short_interest(ticker: str) -> Optional[Dict]:
    """
    Fetch short interest data for a single ticker with retry logic

    Args:
        ticker: Ticker symbol

    Returns:
        Dict of short interest data, or None if all retries failed
    """
    params = {'symbol': ticker, 'token': FINNHUB_API_KEY}

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = requests.get(
                f'{FINNHUB_BASE_URL}/stock/short-interest',
                params=params,
                timeout=10
            )
            response.raise_for_status()
            payload = response.json()

            if isinstance(payload, dict) and payload.get('error'):
                raise ValueError(f"Finnhub error: {payload.get('error')}")

            records = payload.get('data', []) if isinstance(payload, dict) else payload
            latest = records[0] if records else {}

            data = {
                'ticker': ticker,
                'short_interest': latest.get('shortInterest'),
                'days_to_cover': latest.get('daysToCover'),
                'settlement_date': latest.get('settlementDate'),
            }

            logger.info(f"✓ Fetched short interest data for {ticker}")
            return data

        except Exception as e:
            logger.warning(
                f"Attempt {attempt}/{MAX_RETRIES} failed to fetch short interest for {ticker}: {str(e)}"
            )
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_DELAY)

    return None


def _save_short_interest_data(short_data: Dict[str, Dict]) -> None:
    """
    Save collected short interest data to the configured JSON file

    Args:
        short_data: Dict of short interest data keyed by ticker
    """
    try:
        with open(SHORT_INTEREST_FILE, 'w', encoding='utf-8') as f:
            json.dump(short_data, f, ensure_ascii=False, indent=2, default=str)
        logger.info(f"Short interest data saved to {SHORT_INTEREST_FILE}")
    except Exception as e:
        logger.error(f"Failed to save short interest data: {str(e)}")
