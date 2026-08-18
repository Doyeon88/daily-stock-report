"""
Financial Modeling Prep (FMP) scraper
Fetches financial statements (income statement, balance sheet, cash flow, key metrics)
"""

import json
import logging
import time
from typing import Dict, List, Optional

import requests

from config import FMP_API_KEY, FINANCIALS_FILE, MAX_RETRIES, RETRY_DELAY

logger = logging.getLogger(__name__)

FMP_BASE_URL = 'https://financialmodelingprep.com/api/v3'


def fetch_financials(tickers: List[str]) -> Dict[str, Dict]:
    """
    Fetch financial statement data for a list of tickers

    Args:
        tickers: List of ticker symbols to fetch data for

    Returns:
        Dict mapping ticker symbol to its financial data
    """
    financials_data = {}

    if not FMP_API_KEY:
        logger.warning("FMP_API_KEY not configured, skipping financial data collection")
        _save_financials_data(financials_data)
        return financials_data

    for ticker in tickers:
        data = _fetch_single_ticker_financials(ticker)
        if data is not None:
            financials_data[ticker] = data
        else:
            logger.error(f"Failed to fetch financials for {ticker} after {MAX_RETRIES} attempts")

    _save_financials_data(financials_data)

    return financials_data


def _fetch_single_ticker_financials(ticker: str) -> Optional[Dict]:
    """
    Fetch financial statement data for a single ticker with retry logic.
    Each statement is fetched independently so a failure on one endpoint
    doesn't force re-fetching endpoints that already succeeded.

    Args:
        ticker: Ticker symbol

    Returns:
        Dict of financial data, or None if any statement failed after retries
    """
    income_statement = _get_json_with_retry(
        f'{FMP_BASE_URL}/income-statement/{ticker}',
        params={'limit': 1, 'apikey': FMP_API_KEY}
    )
    balance_sheet = _get_json_with_retry(
        f'{FMP_BASE_URL}/balance-sheet-statement/{ticker}',
        params={'limit': 1, 'apikey': FMP_API_KEY}
    )
    cash_flow = _get_json_with_retry(
        f'{FMP_BASE_URL}/cash-flow-statement/{ticker}',
        params={'limit': 1, 'apikey': FMP_API_KEY}
    )
    key_metrics = _get_json_with_retry(
        f'{FMP_BASE_URL}/key-metrics/{ticker}',
        params={'limit': 1, 'apikey': FMP_API_KEY}
    )

    if income_statement is None and balance_sheet is None and cash_flow is None and key_metrics is None:
        return None

    data = {
        'ticker': ticker,
        'income_statement': income_statement[0] if income_statement else None,
        'balance_sheet': balance_sheet[0] if balance_sheet else None,
        'cash_flow': cash_flow[0] if cash_flow else None,
        'key_metrics': key_metrics[0] if key_metrics else None,
    }

    logger.info(f"✓ Fetched financial data for {ticker}")
    return data


def _get_json_with_retry(url: str, params: Dict) -> Optional[list]:
    """
    Perform a GET request with retry logic, returning the parsed JSON list

    Args:
        url: Request URL
        params: Query parameters

    Returns:
        Parsed JSON response as a list, or None if all retries failed
    """
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            return _get_json(url, params)
        except Exception as e:
            logger.warning(
                f"Attempt {attempt}/{MAX_RETRIES} failed to fetch {url}: {str(e)}"
            )
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_DELAY)

    return None


def _get_json(url: str, params: Dict) -> list:
    """
    Perform a GET request and return the parsed JSON response

    Args:
        url: Request URL
        params: Query parameters

    Returns:
        Parsed JSON response as a list

    Raises:
        ValueError: If the API returns an error payload or unexpected format
    """
    response = requests.get(url, params=params, timeout=10)
    response.raise_for_status()
    result = response.json()

    if isinstance(result, dict):
        error_message = result.get('Error Message') or result.get('error')
        raise ValueError(f"FMP API error for {url}: {error_message or result}")

    if not isinstance(result, list):
        raise ValueError(f"Unexpected FMP API response format for {url}: {type(result)}")

    return result


def _save_financials_data(financials_data: Dict[str, Dict]) -> None:
    """
    Save collected financial data to the configured JSON file

    Args:
        financials_data: Dict of financial data keyed by ticker
    """
    try:
        with open(FINANCIALS_FILE, 'w', encoding='utf-8') as f:
            json.dump(financials_data, f, ensure_ascii=False, indent=2, default=str)
        logger.info(f"Financial data saved to {FINANCIALS_FILE}")
    except Exception as e:
        logger.error(f"Failed to save financial data: {str(e)}")
