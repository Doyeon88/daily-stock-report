"""
Technical analysis module
Calculates common technical indicators (SMA, RSI, MACD) from historical price data
"""

import json
import logging
import time
from typing import Dict, List, Optional

import pandas as pd
import yfinance as yf

from config import TECHNICALS_FILE, MAX_RETRIES, RETRY_DELAY

logger = logging.getLogger(__name__)


def calculate_indicators(tickers: List[str]) -> Dict[str, Dict]:
    """
    Calculate technical indicators for a list of tickers

    Args:
        tickers: List of ticker symbols to analyze

    Returns:
        Dict mapping ticker symbol to its technical indicator data
    """
    technicals_data = {}

    for ticker in tickers:
        data = _calculate_single_ticker_indicators(ticker)
        if data is not None:
            technicals_data[ticker] = data
        else:
            logger.error(f"Failed to calculate technical indicators for {ticker} after {MAX_RETRIES} attempts")

    _save_technicals_data(technicals_data)

    return technicals_data


def _calculate_single_ticker_indicators(ticker: str) -> Optional[Dict]:
    """
    Calculate technical indicators for a single ticker with retry logic

    Args:
        ticker: Ticker symbol

    Returns:
        Dict of technical indicator values, or None if all retries failed
    """
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            history = yf.Ticker(ticker).history(period="6mo")

            if history.empty:
                raise ValueError(f"No historical data available for {ticker}")

            close = history['Close']

            sma_20 = close.rolling(window=20).mean().iloc[-1]
            sma_50 = close.rolling(window=50).mean().iloc[-1]
            rsi_14 = _calculate_rsi(close, window=14)
            macd, macd_signal = _calculate_macd(close)

            data = {
                'ticker': ticker,
                'sma_20': _safe_float(sma_20),
                'sma_50': _safe_float(sma_50),
                'rsi_14': _safe_float(rsi_14),
                'macd': _safe_float(macd),
                'macd_signal': _safe_float(macd_signal),
            }

            logger.info(f"✓ Calculated technical indicators for {ticker}")
            return data

        except Exception as e:
            logger.warning(
                f"Attempt {attempt}/{MAX_RETRIES} failed to calculate indicators for {ticker}: {str(e)}"
            )
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_DELAY)

    return None


def _calculate_rsi(close: pd.Series, window: int = 14) -> float:
    """
    Calculate the Relative Strength Index (RSI)

    Args:
        close: Series of closing prices
        window: Lookback window

    Returns:
        Latest RSI value
    """
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)

    avg_gain = gain.rolling(window=window).mean()
    avg_loss = loss.rolling(window=window).mean()

    rs = avg_gain / avg_loss.replace(0, float('nan'))
    rsi = 100 - (100 / (1 + rs))

    return rsi.iloc[-1]


def _calculate_macd(close: pd.Series):
    """
    Calculate the MACD line and signal line

    Args:
        close: Series of closing prices

    Returns:
        Tuple of (latest MACD value, latest signal value)
    """
    ema_12 = close.ewm(span=12, adjust=False).mean()
    ema_26 = close.ewm(span=26, adjust=False).mean()
    macd_line = ema_12 - ema_26
    signal_line = macd_line.ewm(span=9, adjust=False).mean()

    return macd_line.iloc[-1], signal_line.iloc[-1]


def _safe_float(value) -> Optional[float]:
    """
    Convert a value to float, returning None if it is NaN or conversion fails

    Args:
        value: Value to convert

    Returns:
        float or None
    """
    try:
        value = float(value)
        return value if value == value else None  # filters out NaN
    except (TypeError, ValueError):
        return None


def _save_technicals_data(technicals_data: Dict[str, Dict]) -> None:
    """
    Save collected technical indicator data to the configured JSON file

    Args:
        technicals_data: Dict of technical data keyed by ticker
    """
    try:
        with open(TECHNICALS_FILE, 'w', encoding='utf-8') as f:
            json.dump(technicals_data, f, ensure_ascii=False, indent=2, default=str)
        logger.info(f"Technical analysis data saved to {TECHNICALS_FILE}")
    except Exception as e:
        logger.error(f"Failed to save technical analysis data: {str(e)}")
