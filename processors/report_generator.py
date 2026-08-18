"""
Report generator
Builds a human-readable report from collected stock data
"""

import logging
from datetime import datetime
from typing import Dict

logger = logging.getLogger(__name__)


def generate_report(stock_data: Dict[str, Dict]) -> Dict:
    """
    Generate a report dictionary from collected stock data

    Args:
        stock_data: Mapping of ticker -> stock data (from yfinance_scraper.fetch_stock_data)

    Returns:
        dict: Report data compatible with notifications.fcm_notifier.send_report
              (and the underlying send_report_notification), containing 'title',
              'summary', 'insights', 'timestamp' and 'stocks_count'
    """
    timestamp = datetime.now().isoformat()
    tickers = list(stock_data.keys())

    valid_entries = {
        ticker: data for ticker, data in stock_data.items() if data.get('error') is None
    }
    failed_tickers = [ticker for ticker in tickers if ticker not in valid_entries]

    insights = []
    for ticker, data in valid_entries.items():
        arrow = '▲' if data['change'] >= 0 else '▼'
        insights.append(
            f"{ticker}: ${data['price']:.2f} {arrow} {data['change_percent']:+.2f}%"
        )

    for ticker in failed_tickers:
        insights.append(f"{ticker}: data unavailable ({stock_data[ticker].get('error')})")

    summary = (
        f"{len(valid_entries)}/{len(tickers)} stocks updated successfully"
        if tickers
        else "No stocks tracked"
    )

    report = {
        'title': '📈 Daily Stock Report',
        'summary': summary,
        'insights': insights,
        'timestamp': timestamp,
        'stocks_count': len(tickers),
        'stock_data': stock_data,
    }

    logger.info(f"Generated report: {summary}")
    return report
