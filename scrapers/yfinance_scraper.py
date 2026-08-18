"""
yfinance-based stock data scraper
Fetches basic stock price and metrics data using the yfinance library
"""

import json
import logging
import time
from typing import Dict, List, Optional

import yfinance as yf

from config import STOCK_DATA_FILE, MAX_RETRIES, RETRY_DELAY

logger = logging.getLogger(__name__)


def fetch_stock_data(tickers: List[str]) -> Dict[str, Dict]:
    """
    Fetch basic stock data (price, volume, market cap, etc.) for a list of tickers

    Args:
        tickers: List of ticker symbols to fetch data for

    Returns:
        Dict mapping ticker symbol to its stock data
    """
    stock_data = {}

    for ticker in tickers:
        data = _fetch_single_ticker(ticker)
        if data is not None:
            stock_data[ticker] = data
        else:
            logger.error(f"Failed to fetch data for {ticker} after {MAX_RETRIES} attempts")

    _save_stock_data(stock_data)

    return stock_data


def _fetch_single_ticker(ticker: str) -> Optional[Dict]:
    """
    Fetch stock data for a single ticker with retry logic

    Args:
        ticker: Ticker symbol

    Returns:
        Dict of stock data, or None if all retries failed
    """
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            stock = yf.Ticker(ticker)
            info = stock.info

            history = stock.history(period="1d")
            current_price = None
            previous_close = None

            if not history.empty:
                current_price = float(history['Close'].iloc[-1])

            previous_close = info.get('previousClose')

            change = None
            change_percent = None
            if current_price is not None and previous_close:
                change = current_price - previous_close
                change_percent = (change / previous_close) * 100

            data = {
                'ticker': ticker,
                'name': info.get('shortName') or info.get('longName'),
                'current_price': current_price,
                'previous_close': previous_close,
                'change': change,
                'change_percent': change_percent,
                'volume': info.get('volume'),
                'avg_volume': info.get('averageVolume'),
                'market_cap': info.get('marketCap'),
                'day_high': info.get('dayHigh'),
                'day_low': info.get('dayLow'),
                'fifty_two_week_high': info.get('fiftyTwoWeekHigh'),
                'fifty_two_week_low': info.get('fiftyTwoWeekLow'),
                'pe_ratio': info.get('trailingPE'),
                'currency': info.get('currency'),
            }

            logger.info(f"✓ Fetched stock data for {ticker}")
            return data

        except Exception as e:
            logger.warning(
                f"Attempt {attempt}/{MAX_RETRIES} failed to fetch data for {ticker}: {str(e)}"
            )
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_DELAY)

    return None


def _save_stock_data(stock_data: Dict[str, Dict]) -> None:
    """
    Save collected stock data to the configured JSON file

    Args:
        stock_data: Dict of stock data keyed by ticker
    """
    try:
        with open(STOCK_DATA_FILE, 'w', encoding='utf-8') as f:
            json.dump(stock_data, f, ensure_ascii=False, indent=2, default=str)
        logger.info(f"Stock data saved to {STOCK_DATA_FILE}")
    except Exception as e:
        logger.error(f"Failed to save stock data: {str(e)}")
