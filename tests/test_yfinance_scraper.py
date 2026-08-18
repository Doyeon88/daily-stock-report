"""
Unit tests for scrapers/yfinance_scraper.py
"""

from unittest.mock import MagicMock, patch

from scrapers import yfinance_scraper


def _make_fast_info(last_price, previous_close, volume):
    return {
        'lastPrice': last_price,
        'previousClose': previous_close,
        'lastVolume': volume,
    }


@patch('scrapers.yfinance_scraper.yf.Ticker')
def test_fetch_stock_data_success(mock_ticker_cls):
    mock_ticker = MagicMock()
    mock_ticker.fast_info = _make_fast_info(105.0, 100.0, 123456)
    mock_ticker_cls.return_value = mock_ticker

    result = yfinance_scraper.fetch_stock_data(['AAPL'])

    assert result['AAPL']['error'] is None
    assert result['AAPL']['price'] == 105.0
    assert result['AAPL']['previous_close'] == 100.0
    assert result['AAPL']['change'] == 5.0
    assert result['AAPL']['change_percent'] == 5.0
    assert result['AAPL']['volume'] == 123456


@patch('scrapers.yfinance_scraper.time.sleep', return_value=None)
@patch('scrapers.yfinance_scraper.yf.Ticker')
def test_fetch_stock_data_retries_then_fails(mock_ticker_cls, _mock_sleep):
    mock_ticker_cls.side_effect = Exception('network error')

    result = yfinance_scraper.fetch_stock_data(['BADTICKER'])

    assert result['BADTICKER']['error'] is not None
    assert result['BADTICKER']['price'] is None
    assert mock_ticker_cls.call_count == 3


@patch('scrapers.yfinance_scraper.yf.Ticker')
def test_fetch_stock_data_multiple_tickers(mock_ticker_cls):
    def ticker_side_effect(ticker):
        mock_ticker = MagicMock()
        mock_ticker.fast_info = _make_fast_info(50.0, 45.0, 1000)
        return mock_ticker

    mock_ticker_cls.side_effect = ticker_side_effect

    result = yfinance_scraper.fetch_stock_data(['A', 'B'])

    assert set(result.keys()) == {'A', 'B'}
    assert result['A']['error'] is None
    assert result['B']['error'] is None
