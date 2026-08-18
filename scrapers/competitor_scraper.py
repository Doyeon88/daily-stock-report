"""
Competitor comparison module
Fetches basic stock metrics for each tracked ticker's competitors and builds
a side-by-side comparison
"""

import json
import logging
import time
from typing import Dict, List, Optional

import yfinance as yf

from config import COMPETITOR_MAP, COMPETITORS_FILE, MAX_RETRIES, RETRY_DELAY

logger = logging.getLogger(__name__)


def compare_stocks(tickers: List[str]) -> Dict[str, Dict]:
    """
    Build a competitor comparison for each tracked ticker

    Args:
        tickers: List of ticker symbols to build comparisons for

    Returns:
        Dict mapping ticker symbol to its competitor comparison data
    """
    competitors_data = {}

    for ticker in tickers:
        competitor_tickers = COMPETITOR_MAP.get(ticker, [])

        if not competitor_tickers:
            logger.info(f"No competitors configured for {ticker}, skipping")
            competitors_data[ticker] = {}
            continue

        comparison = {}
        for competitor in competitor_tickers:
            data = _fetch_single_competitor_metrics(competitor)
            if data is not None:
                comparison[competitor] = data
            else:
                logger.error(
                    f"Failed to fetch competitor data for {competitor} "
                    f"after {MAX_RETRIES} attempts"
                )

        competitors_data[ticker] = comparison
        logger.info(f"✓ Built competitor comparison for {ticker}")

    _save_competitors_data(competitors_data)

    return competitors_data


def _fetch_single_competitor_metrics(ticker: str) -> Optional[Dict]:
    """
    Fetch basic comparison metrics for a single competitor ticker with retry logic

    Args:
        ticker: Competitor ticker symbol

    Returns:
        Dict of comparison metrics, or None if all retries failed
    """
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            info = yf.Ticker(ticker).info

            data = {
                'ticker': ticker,
                'name': info.get('shortName') or info.get('longName'),
                'current_price': info.get('currentPrice') or info.get('regularMarketPrice'),
                'market_cap': info.get('marketCap'),
                'pe_ratio': info.get('trailingPE'),
                'fifty_two_week_high': info.get('fiftyTwoWeekHigh'),
                'fifty_two_week_low': info.get('fiftyTwoWeekLow'),
            }

            logger.info(f"✓ Fetched competitor metrics for {ticker}")
            return data

        except Exception as e:
            logger.warning(
                f"Attempt {attempt}/{MAX_RETRIES} failed to fetch competitor metrics "
                f"for {ticker}: {str(e)}"
            )
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_DELAY)

    return None


def _save_competitors_data(competitors_data: Dict[str, Dict]) -> None:
    """
    Save collected competitor comparison data to the configured JSON file

    Args:
        competitors_data: Dict of competitor comparisons keyed by ticker
    """
    try:
        with open(COMPETITORS_FILE, 'w', encoding='utf-8') as f:
            json.dump(competitors_data, f, ensure_ascii=False, indent=2, default=str)
        logger.info(f"Competitor comparison data saved to {COMPETITORS_FILE}")
    except Exception as e:
        logger.error(f"Failed to save competitor comparison data: {str(e)}")
