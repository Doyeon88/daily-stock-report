"""
Unit tests for scrapers/competitor_scraper.py
"""

from unittest.mock import MagicMock

from scrapers import competitor_scraper


def _quote(change_percent, error=None):
    return {'price': 1.0, 'change_percent': change_percent, 'error': error}


def test_compare_stocks_returns_peer_and_market_changes(monkeypatch):
    monkeypatch.setattr(competitor_scraper, 'COMPETITOR_MAP', {'BE': ['FCEL', 'PLUG'], 'BWXT': ['RTX']})
    monkeypatch.setattr(competitor_scraper, 'MARKET_CONTEXT', [('^GSPC', 'S&P 500')])
    fetch = MagicMock(return_value={
        'FCEL': _quote(3.36), 'PLUG': _quote(0.0), 'RTX': _quote(-1.2), '^GSPC': _quote(0.71),
    })
    monkeypatch.setattr(competitor_scraper.yfinance_scraper, 'fetch_stock_data', fetch)

    result = competitor_scraper.compare_stocks(['BE', 'BWXT'])

    assert sorted(fetch.call_args[0][0]) == ['FCEL', 'PLUG', 'RTX', '^GSPC']   # one batch for everything
    assert result['peers'] == {
        'BE': [{'ticker': 'FCEL', 'change_percent': 3.36}, {'ticker': 'PLUG', 'change_percent': 0.0}],
        'BWXT': [{'ticker': 'RTX', 'change_percent': -1.2}],
    }
    assert result['market'] == [{'ticker': '^GSPC', 'name': 'S&P 500', 'change_percent': 0.71}]


def test_symbols_that_failed_are_left_out(monkeypatch):
    monkeypatch.setattr(competitor_scraper, 'COMPETITOR_MAP', {'BE': ['FCEL', 'GONE']})
    monkeypatch.setattr(competitor_scraper, 'MARKET_CONTEXT', [('BTC-USD', 'Bitcoin')])
    monkeypatch.setattr(competitor_scraper.yfinance_scraper, 'fetch_stock_data', MagicMock(return_value={
        'FCEL': _quote(1.0), 'GONE': _quote(None, error='no data'), 'BTC-USD': _quote(None, error='timeout'),
    }))

    result = competitor_scraper.compare_stocks(['BE'])

    assert result['peers'] == {'BE': [{'ticker': 'FCEL', 'change_percent': 1.0}]}
    assert result['market'] == []


def test_ticker_without_competitors_gets_an_empty_list(monkeypatch):
    monkeypatch.setattr(competitor_scraper, 'COMPETITOR_MAP', {})
    monkeypatch.setattr(competitor_scraper, 'MARKET_CONTEXT', [])
    monkeypatch.setattr(competitor_scraper.yfinance_scraper, 'fetch_stock_data', MagicMock(return_value={}))

    assert competitor_scraper.compare_stocks(['ZZZ']) == {'peers': {'ZZZ': []}, 'market': []}
