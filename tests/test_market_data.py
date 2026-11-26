"""
Unit tests for the newer per-ticker data: earnings surprises and reactions, insider trades, dilution,
options' expected move, technical signals and watchlist risk (no network; data shapes follow yfinance)
"""

from datetime import date, datetime, timedelta

import numpy as np
import pandas as pd
import pytest

from processors import signals
from scrapers import dilution, earnings_history, insiders, options_activity

TODAY = date(2026, 11, 26)


# ---------- earnings surprises ----------

CLOSES = [(date(2026, 10, 21), 100.0), (date(2026, 10, 22), 102.0), (date(2026, 10, 23), 112.2),
          (date(2026, 7, 27), 50.0), (date(2026, 7, 28), 45.0)]


def test_reaction_after_the_close_uses_the_next_session():
    closes = sorted(CLOSES)
    assert earnings_history.reaction_pct(closes, date(2026, 10, 22), after_close=True) == 10.0      # 102 -> 112.2
    assert earnings_history.reaction_pct(closes, date(2026, 7, 28), after_close=False) == -10.0     # 50 -> 45
    assert earnings_history.reaction_pct(closes, date(2026, 10, 23), after_close=True) is None      # no next session yet


def test_parse_earnings_skips_upcoming_dates_and_counts_beats():
    records = [
        {'when': datetime(2027, 2, 4, 16), 'estimate': 1.12, 'reported': float('nan'), 'surprise_pct': float('nan')},
        {'when': datetime(2026, 10, 22, 16), 'estimate': 0.68, 'reported': 0.94, 'surprise_pct': 39.15},
        {'when': datetime(2026, 7, 28, 8), 'estimate': 0.5, 'reported': 0.4, 'surprise_pct': None},
    ]
    result = earnings_history.parse_earnings(records, sorted(CLOSES), TODAY)
    assert [r['date'] for r in result['rows']] == ['2026-10-22', '2026-07-28']
    assert result['rows'][0]['timing'] == '장 마감 후' and result['rows'][1]['timing'] == '장 시작 전'
    assert result['rows'][1]['surprise_pct'] == -20.0          # computed when Yahoo leaves it out
    assert (result['beats'], result['misses'], result['avg_abs_reaction']) == (1, 1, 10.0)
    assert earnings_history.parse_earnings(records[:1], [], TODAY) is None


# ---------- insider trades ----------

def _trade(day, text, insider, value=None, shares=1000, position='Officer'):
    return {'Start Date': pd.Timestamp(day), 'Text': text, 'Insider': insider, 'Position': position,
            'Shares': shares, 'Value': value, 'Transaction': ''}


def test_insider_buys_and_sells_are_summed_and_grants_counted_apart():
    result = insiders.parse_insider_transactions([
        _trade('2026-11-16', 'Sale at price 178.53 per share.', 'JOSHI  AMAN', value=919072.0),
        _trade('2026-11-10', 'Purchase at price 12.50 per share.', 'DOE JANE', value=float('nan')),
        _trade('2026-11-01', 'Stock Award(Grant) at price 0.00 per share.', 'DOE JANE'),
        _trade('2026-06-01', 'Purchase at price 9.00 per share.', 'OLD BUYER', value=9000.0),   # outside 90 days
    ], TODAY)
    assert (result['buy_count'], result['sell_count'], result['other_count']) == (1, 1, 1)
    assert result['buy_value'] == 12500 and result['sell_value'] == 919072     # value from shares x price when missing
    assert result['net_value'] == 12500 - 919072 and result['sellers'] == ['Joshi Aman']
    assert result['cluster_buy'] is False and result['recent'][0]['kind'] == 'sell'


def test_two_insiders_buying_within_30_days_is_a_cluster_buy():
    result = insiders.parse_insider_transactions([
        _trade('2026-11-20', 'Purchase at price 10 per share.', 'A', value=10000.0),
        _trade('2026-11-01', 'Purchase at price 10 per share.', 'B', value=10000.0),
    ], TODAY)
    assert result['cluster_buy'] is True and result['buyers'] == ['A', 'B']
    assert insiders.parse_insider_transactions([], TODAY)['buy_count'] == 0


# ---------- dilution ----------

def test_recent_shelf_offering_and_short_runway_are_high_risk():
    offerings = dilution.offering_filings([
        {'date': date(2026, 11, 10), 'type': '424B5', 'edgarUrl': 'u1'},
        {'date': date(2026, 3, 1), 'type': 'S-3', 'edgarUrl': 'u2'},      # older than 180 days
        {'date': date(2026, 11, 12), 'type': '8-K', 'edgarUrl': 'u3'},
    ], TODAY)
    result = dilution.assess(offerings, [89.9e6, 84.4e6, 79.0e6, 75.0e6, 68.1e6], 605e6,
                             [-361e6, -274e6, -143e6], TODAY)
    assert [o['form'] for o in offerings] == ['424B5']
    assert result['level'] == '높음'
    assert result['runway_quarters'] == 1.9 and result['quarterly_burn'] == 317500000
    assert result['shares_yoy_pct'] == 32.0 and result['shares_qoq_pct'] == 6.5
    assert any('424B5' in r for r in result['reasons'])


def test_ipo_papers_only_are_a_caution_and_cash_positive_companies_are_low():
    ipo = dilution.offering_filings([{'date': date(2026, 6, 1), 'type': 'S-1/A', 'edgarUrl': 'u'}], TODAY)
    assert dilution.assess(ipo, [], None, [], TODAY)['level'] == '주의'
    healthy = dilution.assess([], [100e6, 100e6], 1e9, [50e6, 40e6], TODAY)
    assert (healthy['level'], healthy['runway_quarters'], healthy['reasons']) == ('낮음', None, [])


def test_a_missing_quarter_is_not_replaced_by_an_older_one():
    result = dilution.assess([], [120e6, None, 100e6, 100e6, 80e6], None, [], TODAY)
    assert result['shares_qoq_pct'] is None            # last quarter is missing: no comparison
    assert result['shares_yoy_pct'] == 50.0            # still the quarter four places back


# ---------- options ----------

def test_expiry_after_a_near_earnings_date_is_chosen():
    expiries = ['2026-11-27', '2026-12-04', '2026-12-11', '2027-01-15']
    assert options_activity.choose_expiry(expiries, TODAY, '2026-12-05') == ('2026-12-11', True)
    assert options_activity.choose_expiry(expiries, TODAY, '2027-03-01') == ('2026-12-04', False)   # earnings too far
    assert options_activity.choose_expiry([], TODAY) == (None, False)


def test_straddle_gives_the_expected_move_and_put_call_ratio():
    calls = [{'strike': 95.0, 'bid': 7.0, 'ask': 8.0, 'volume': 10, 'openInterest': 100, 'impliedVolatility': 0.8},
             {'strike': 100.0, 'bid': 4.0, 'ask': 5.0, 'volume': 900, 'openInterest': 100, 'impliedVolatility': 0.7}]
    puts = [{'strike': 100.0, 'bid': 0.0, 'ask': 0.0, 'lastPrice': 5.5, 'volume': float('nan'),
             'openInterest': 300, 'impliedVolatility': 0.9}]
    result = options_activity.analyze_chain(calls, puts, spot=101.0)
    assert result['atm_strike'] == 100.0 and result['straddle'] == 10.0     # call mid 4.5 + put last 5.5
    assert result['expected_move_pct'] == 9.9 and result['iv_atm'] == 80.0
    assert result['put_call_oi'] == 1.5
    assert result['unusual'] == [{'side': '콜', 'strike': 100.0, 'volume': 900, 'oi': 100}]
    assert options_activity.analyze_chain([], puts, 101.0) is None


# ---------- technical signals and risk ----------

def _frame(closes):
    index = pd.date_range('2025-11-01', periods=len(closes), freq='B', tz='America/New_York')
    closes = pd.Series(closes, index=index, dtype=float)
    return pd.DataFrame({'Close': closes, 'High': closes * 1.02, 'Low': closes * 0.98})


def test_sharp_drop_breaks_the_50_day_line_and_the_lower_band():
    result = signals.technical_signals(_frame(list(np.linspace(50, 100, 120)) + [70.0]))
    texts = [label['text'] for label in result['labels']]
    assert '50일선 이탈(최근 3일)' in texts and '볼린저밴드 하단 이탈(단기 과매도)' in texts
    assert any(t.startswith('하루 평균 변동폭(ATR)') for t in texts)
    assert result['ma200'] is None and not any('200일선' in t for t in texts)   # 121 days: no 200-day line yet


def test_golden_cross_is_found_within_ten_days():
    closes = pd.Series(list(np.linspace(100, 60, 220)) + list(np.linspace(60, 160, 60)))
    ma50, ma200 = closes.rolling(50).mean(), closes.rolling(200).mean()
    cross_at = next(i for i in range(201, len(closes)) if ma50[i - 1] <= ma200[i - 1] and ma50[i] > ma200[i])
    frame = _frame(list(closes[:cross_at + 3]))
    texts = [label['text'] for label in signals.technical_signals(frame)['labels']]
    assert any(t.startswith('골든크로스') for t in texts)


def test_short_history_gives_no_signals():
    assert signals.technical_signals(_frame([10.0] * 20)) is None


def test_risk_metrics_find_correlated_pairs_and_beta():
    rng = np.random.default_rng(0)
    market = rng.normal(0, 0.01, 200)
    a = 100 * np.cumprod(1 + 2 * market)
    b = 100 * np.cumprod(1 + 2 * market + rng.normal(0, 0.002, 200))
    c = 100 * np.cumprod(1 + rng.normal(0, 0.02, 200))
    history = {'A': _frame(a), 'B': _frame(b), 'C': _frame(c), 'QQQ': _frame(100 * np.cumprod(1 + market))}
    risk = signals.risk_metrics(history, ['A', 'B', 'C'])
    assert risk['per_ticker']['A']['beta'] == pytest.approx(2.0, abs=0.01)
    assert [(p['a'], p['b']) for p in risk['high_corr_pairs']] == [('A', 'B')]
    assert risk['per_ticker']['C']['max_drawdown'] <= 0 and risk['per_ticker']['A']['vol_annual'] > 0
    assert signals.risk_metrics({}, ['A']) == {}
