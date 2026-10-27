"""
Competitor and market comparison

Same-day price change of each ticker's competitors (config.COMPETITOR_MAP) and of the
market indices shown as context (config.MARKET_CONTEXT), using the existing price scraper.
"""

import logging
from typing import Dict, List

from config import COMPETITOR_MAP, MARKET_CONTEXT
from scrapers import yfinance_scraper

logger = logging.getLogger(__name__)


def compare_stocks(tickers: List[str]) -> Dict:
    """
    Fetch the price change of competitors and market indices

    Args:
        tickers: Tracked stock ticker symbols

    Returns:
        dict: {'peers': {ticker: [{'ticker', 'change_percent'}]},
               'market': [{'ticker', 'name', 'change_percent'}]}
              Symbols whose price could not be fetched are left out.
    """
    peers_by_ticker = {ticker: COMPETITOR_MAP.get(ticker, []) for ticker in tickers}
    symbols = sorted(
        {peer for peers in peers_by_ticker.values() for peer in peers}
        | {symbol for symbol, _ in MARKET_CONTEXT}
    )
    quotes = yfinance_scraper.fetch_stock_data(symbols)

    def change(symbol: str):
        quote = quotes.get(symbol) or {}
        return quote.get('change_percent') if quote.get('error') is None else None

    return {
        'peers': {
            ticker: [
                {'ticker': peer, 'change_percent': change(peer)}
                for peer in peers if change(peer) is not None
            ]
            for ticker, peers in peers_by_ticker.items()
        },
        'market': [
            {'ticker': symbol, 'name': name, 'change_percent': change(symbol)}
            for symbol, name in MARKET_CONTEXT if change(symbol) is not None
        ],
    }
