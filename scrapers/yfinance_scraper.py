"""
Yahoo Finance stock data scraper
Fetches current price, daily change, and volume for tracked stocks
"""

import logging
import time
from typing import Dict, List

import yfinance as yf

from config import MAX_RETRIES, RETRY_DELAY

logger = logging.getLogger(__name__)


def _fetch_ticker_data(ticker: str) -> Dict:
    """
    Fetch stock data for a single ticker, retrying on failure

    Args:
        ticker: Stock ticker symbol

    Returns:
        dict: Stock data for the ticker, or an error entry if all retries fail
    """
    last_error = None

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            stock = yf.Ticker(ticker)
            info = stock.fast_info

            last_price = info.get('lastPrice') if hasattr(info, 'get') else info['lastPrice']
            previous_close = (
                info.get('previousClose') if hasattr(info, 'get') else info['previousClose']
            )
            volume = info.get('lastVolume') if hasattr(info, 'get') else info['lastVolume']

            if last_price is None or previous_close is None:
                raise ValueError(f"Missing price data for {ticker}")

            change = last_price - previous_close
            change_percent = (change / previous_close * 100) if previous_close else 0.0

            return {
                'ticker': ticker,
                'price': round(float(last_price), 2),
                'previous_close': round(float(previous_close), 2),
                'change': round(float(change), 2),
                'change_percent': round(float(change_percent), 2),
                'volume': int(volume) if volume is not None else None,
                'error': None,
            }

        except Exception as e:
            last_error = e
            logger.warning(
                f"Attempt {attempt}/{MAX_RETRIES} failed to fetch data for {ticker}: {str(e)}"
            )
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_DELAY)

    logger.error(f"Failed to fetch data for {ticker} after {MAX_RETRIES} attempts: {last_error}")
    return {
        'ticker': ticker,
        'price': None,
        'previous_close': None,
        'change': None,
        'change_percent': None,
        'volume': None,
        'error': str(last_error) if last_error else 'Unknown error',
    }


def fetch_stock_data(tickers: List[str]) -> Dict[str, Dict]:
    """
    Fetch current stock data for a list of tickers

    Args:
        tickers: List of stock ticker symbols

    Returns:
        dict: Mapping of ticker -> stock data
    """
    logger.info(f"Fetching stock data for {len(tickers)} ticker(s): {tickers}")

    results = {}
    for ticker in tickers:
        results[ticker] = _fetch_ticker_data(ticker)

    success_count = sum(1 for data in results.values() if data['error'] is None)
    logger.info(f"Fetched stock data for {success_count}/{len(tickers)} ticker(s) successfully")

    return results
