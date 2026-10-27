"""
Unit tests for scrapers/stock_details.py
"""

from datetime import date, datetime
from unittest.mock import MagicMock

import pandas as pd
import pytest

from scrapers import stock_details


def _info(**overrides):
    info = {
        'regularMarketTime': 1000, 'postMarketPrice': 105.0, 'postMarketTime': 2000,
        'fiftyTwoWeekHigh': 200.0, 'fiftyTwoWeekLow': 100.0, 'averageVolume10days': 1000,
        'shortPercentOfFloat': 0.0808, 'shortRatio': 1.2, 'dateShortInterest': 1790726400,
        'targetMeanPrice': 120.0, 'numberOfAnalystOpinions': 10, 'recommendationKey': 'buy',
        'fiftyDayAverage': 110.0, 'twoHundredDayAverage': 90.0, 'marketCap': 5e9,
    }
    info.update(overrides)
    return info


def test_info_section_derives_values_from_price_and_volume():
    result = stock_details.info_section(_info(), price=100.0, volume=1500)

    assert result['volume_ratio'] == 1.5
    assert result['range_position'] == 0.0          # at the 52-week low
    assert result['vs_ma50'] == -9.09
    assert result['vs_ma200'] == 11.11
    assert result['upside'] == 20.0                 # target 120 vs price 100
    assert result['short_percent_float'] == 8.1
    assert result['short_as_of'] == '2026-09-30'
    assert result['analyst_count'] == 10
    assert result['recommendation'] == 'buy'
    assert result['after_hours_price'] == 105.0
    assert result['after_hours_change'] == 5.0


def test_after_hours_quote_is_ignored_when_older_than_the_regular_session():
    # post-market time before the regular session time = a leftover from the previous day
    result = stock_details.info_section(_info(postMarketTime=500), price=100.0, volume=1000)

    assert result['after_hours_price'] is None
    assert result['after_hours_change'] is None


def test_info_section_tolerates_missing_fields():
    result = stock_details.info_section({}, price=None, volume=None)

    assert all(value is None for value in result.values())


def test_info_section_falls_back_to_the_price_in_info():
    result = stock_details.info_section(_info(regularMarketPrice=150.0), price=None, volume=1000)

    assert result['upside'] == -20.0                # target 120 vs price 150
    assert result['range_position'] == 50.0


def test_technical_section_rsi_extremes_and_returns():
    rising = pd.Series([100.0 + i for i in range(30)])
    falling = pd.Series([200.0 - i for i in range(30)])

    up = stock_details.technical_section(rising)
    down = stock_details.technical_section(falling)

    assert up['rsi14'] == 100.0
    assert down['rsi14'] == 0.0
    assert up['return_5d'] == 4.03                  # 129 vs 124
    assert up['return_20d'] == 18.35                # 129 vs 109
    assert down['return_5d'] < 0


def test_technical_section_needs_enough_history():
    with pytest.raises(ValueError):
        stock_details.technical_section(pd.Series([1.0, 2.0, 3.0]))


def test_earnings_section_picks_the_next_upcoming_date():
    calendar = {'Earnings Date': [date(2026, 10, 23), date(2026, 11, 3)]}

    result = stock_details.earnings_section(calendar, today=date(2026, 10, 27))

    assert result == {'earnings_date': '2026-11-03', 'days_to_earnings': 7}


def test_earnings_section_with_only_past_or_missing_dates():
    none = {'earnings_date': None, 'days_to_earnings': None}

    assert stock_details.earnings_section({'Earnings Date': [date(2026, 10, 23)]}, date(2026, 10, 27)) == none
    assert stock_details.earnings_section({}, date(2026, 10, 27)) == none
    assert stock_details.earnings_section(None, date(2026, 10, 27)) == none


def test_earnings_section_accepts_datetimes_and_counts_today():
    calendar = {'Earnings Date': [datetime(2026, 10, 27, 16, 0)]}

    result = stock_details.earnings_section(calendar, today=date(2026, 10, 27))

    assert result == {'earnings_date': '2026-10-27', 'days_to_earnings': 0}


def test_fetch_stock_details_keeps_other_sections_when_one_fails(monkeypatch):
    monkeypatch.setattr('scrapers.retry.time.sleep', lambda _: None)

    class FakeStock:
        @property
        def info(self):
            raise RuntimeError('yahoo down')

        def history(self, period, interval):
            # newest bar unfinished (NaN) as Yahoo returns during a session
            return pd.DataFrame({'Close': [100.0 + i for i in range(30)] + [float('nan')]})

        calendar = {'Earnings Date': [date(2026, 11, 3)]}

    monkeypatch.setattr(stock_details.yf, 'Ticker', MagicMock(return_value=FakeStock()))

    result = stock_details.fetch_stock_details(
        ['AAA'], {'AAA': {'price': 129.0, 'volume': 10}}, today=date(2026, 10, 27)
    )

    details = result['AAA']
    assert 'volume_ratio' not in details            # the info section failed...
    assert details['rsi14'] == 100.0                # ...technicals and earnings survived
    assert details['return_5d'] == 4.03             # computed from the last finished bar, not the NaN one
    assert details['days_to_earnings'] == 7
