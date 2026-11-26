"""
1년치 일봉(종가·고가·저가) 수집: 기술적 신호와 리스크 지표(processors.signals)의 재료 (Yahoo Finance, 키 없음)
"""

import logging
from typing import Dict, List

import yfinance as yf

from scrapers.retry import call_with_retry

logger = logging.getLogger(__name__)

BENCHMARK = 'QQQ'
PERIOD = '1y'


def fetch_price_history(tickers: List[str], benchmark: str = BENCHMARK) -> Dict:
    """symbol -> DataFrame with Close/High/Low (oldest first, NaN rows dropped); the benchmark is included"""
    results = {}
    for symbol in list(tickers) + [benchmark]:
        try:
            frame = call_with_retry(lambda: yf.Ticker(symbol).history(period=PERIOD, interval='1d'),
                                    f"{symbol} {PERIOD} history")
            frame = frame[['Close', 'High', 'Low']].dropna()
            if not frame.empty:
                results[symbol] = frame
        except Exception as e:
            logger.error(f"{symbol}: price history unavailable: {e}")
    return results
