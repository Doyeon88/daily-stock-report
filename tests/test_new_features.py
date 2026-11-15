"""
Tests for the daily-briefing extensions: tagging, valuation, portfolio, calendar, analyst/13F parsing,
watchlist config and the schedule sync
"""

import importlib.util
import json
import os
from datetime import date

import pytest

import config
from processors import calendar_events, portfolio, tagging, valuation
from scrapers import analyst_changes, institutional


def _load_script():
    path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'scripts', 'sync_schedule.py')
    spec = importlib.util.spec_from_file_location('sync_schedule', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ---------- tagging ----------

@pytest.mark.parametrize('title,expected', [
    ('Company beats estimates and raises guidance', tagging.BULLISH),
    ('Shares plunge after delay and downgrade', tagging.BEARISH),
    ('Company to hold investor day', tagging.NEUTRAL),
    ('Wins deal but faces lawsuit', tagging.NEUTRAL),   # one each
])
def test_classify_text(title, expected):
    assert tagging.classify_text(title) == expected


def test_news_is_never_verified_and_filings_always_are():
    assert tagging.tag_news([{'title': 'x'}])[0]['verified'] is False
    tagged = tagging.tag_filings([{'form': '8-K', 'label': '미등록 주식 발행'}, {'form': '10-Q', 'label': ''}])
    assert [t['tag'] for t in tagged] == [tagging.BEARISH, tagging.NEUTRAL]
    assert all(t['verified'] for t in tagged)


def test_overall_tag_tie_is_neutral():
    assert tagging.overall_tag(['호재', '악재']) == '중립'
    assert tagging.overall_tag(['호재', '호재', '악재']) == '호재'
    assert tagging.overall_tag([]) == '중립'


# ---------- valuation ----------

def test_scenario_valuation():
    result = valuation.scenario_valuation(26.0, {'2027': 0.65, '2028': 1.5}, [20, 40])
    assert result['rows'][0] == {'year': '2027', 'eps': 0.65, 'forward_pe': 40.0, 'targets': {'20': 13.0, '40': 26.0}}
    assert result['rows'][1]['forward_pe'] == 17.3


@pytest.mark.parametrize('price,eps', [(None, {'2027': 1}), (10, {}), (0, {'2027': 1})])
def test_scenario_valuation_without_inputs(price, eps):
    assert valuation.scenario_valuation(price, eps, [20]) is None


def test_scenario_valuation_skips_non_positive_eps():
    assert valuation.scenario_valuation(10, {'2027': -1}, [20]) is None


# ---------- portfolio ----------

STOCKS = {
    'A': {'price': 120.0, 'previous_close': 100.0, 'error': None},
    'B': {'price': 50.0, 'previous_close': 50.0, 'error': None},
    'C': {'price': None, 'previous_close': None, 'error': 'x'},
}


def test_portfolio_totals_and_weights():
    result = portfolio.compute_portfolio(
        {'holdings': [{'symbol': 'A', 'shares': 10, 'avg_cost': 100}, {'symbol': 'B', 'shares': 20, 'avg_cost': 40},
                      {'symbol': 'C', 'shares': 5, 'avg_cost': 10}]}, STOCKS)
    a, b, c = result['positions']
    assert (a['pnl'], a['pnl_pct'], a['weight_pct'], a['day_pnl']) == (200.0, 20.0, 54.5, 200.0)
    assert (b['pnl'], b['pnl_pct']) == (200.0, 25.0)
    assert c['value'] is None and c['weight_pct'] is None
    assert result['total_value'] == 2200.0
    assert result['total_pnl'] == 400.0
    assert result['total_pnl_pct'] == round(400 / 1800 * 100, 2)


def test_portfolio_empty_is_none():
    assert portfolio.compute_portfolio({}, STOCKS) is None
    assert portfolio.compute_portfolio({'holdings': []}, STOCKS) is None


def test_public_view_hides_amounts_by_default():
    result = portfolio.compute_portfolio({'holdings': [{'symbol': 'A', 'shares': 10, 'avg_cost': 100}]}, STOCKS)
    public = portfolio.public_view(result)
    dumped = json.dumps(public)
    for secret in ('shares', 'avg_cost', 'value', 'total_cost', '"pnl"'):
        assert secret not in dumped
    assert public['positions'][0] == {'symbol': 'A', 'pnl_pct': 20.0, 'weight_pct': 100.0}
    assert portfolio.public_view(result, include_amounts=True) is result
    assert portfolio.public_view(None) is None


# ---------- calendar ----------

TODAY = date(2026, 11, 15)


def test_calendar_sorted_with_dday_and_verification():
    items = calendar_events.build_calendar(
        TODAY,
        {'BE': {'earnings_date': '2026-11-20'}, 'X': {}},
        [{'date': '2026-11-17', 'label': 'Nvidia', 'tickers': [], 'verified': False},
         {'date': '2026-09-01', 'label': 'past'}, {'date': 'bad', 'label': 'bad'},
         {'date': '2027-06-01', 'label': 'far'}],
    )
    assert [(i['date'], i['dday']) for i in items] == [('2026-11-17', 2), ('2026-11-20', 5)]
    assert items[0]['verified'] is False and items[1]['verified'] is True


def test_13f_deadline_in_calendar_and_season():
    deadlines = calendar_events.thirteen_f_deadlines(date(2026, 11, 15))
    assert date(2026, 11, 14) in deadlines and date(2027, 2, 14) in deadlines
    assert calendar_events.is_13f_season(date(2026, 11, 15))      # just after the Nov 14 deadline
    assert calendar_events.is_13f_season(date(2026, 10, 30))
    assert not calendar_events.is_13f_season(date(2026, 10, 10))
    assert not calendar_events.is_13f_season(date(2026, 12, 20))
    assert not calendar_events.is_13f_season(date(2026, 7, 20))
    cal = calendar_events.build_calendar(date(2027, 1, 20), {}, [])
    assert any('13F' in c['label'] and c['dday'] == 25 for c in cal)


def test_checklists_pick_next_event_per_ticker():
    cal = [{'date': '2026-12-07', 'dday': 22, 'label': '락업', 'tickers': ['E'], 'verified': False}]
    result = calendar_events.build_checklists(['E', 'Z', 'M'], cal, {'M': ['do it']})
    assert result['E']['next_event']['label'] == '락업'
    assert result['M'] == {'next_event': None, 'items': ['do it']}
    assert 'Z' not in result


# ---------- analyst / 13F parsing ----------

def test_parse_rating_changes_filters_sorts_and_cleans_nan():
    rows = analyst_changes.parse_rating_changes([
        {'date': '2026-11-13', 'firm': 'UBS', 'action': 'Up', 'to_grade': 'Buy', 'from_grade': 'Neutral',
         'target': 350.0, 'prior_target': float('nan')},
        {'date': '2026-11-14', 'firm': 'HSBC', 'action': 'init', 'to_grade': 'Buy', 'target': 300},
        {'date': '2026-10-01', 'firm': 'Old', 'action': 'main'},
    ], date(2026, 11, 8))
    assert [r['firm'] for r in rows] == ['HSBC', 'UBS']
    assert rows[1]['prior_target'] is None and rows[1]['target'] == 350.0


def test_parse_eps_trend_changes():
    rows = analyst_changes.parse_eps_trend([
        {'period': '+1y', 'current': 1.1, '7daysAgo': 1.0, '30daysAgo': 2.2},
        {'period': '0y', 'current': 0.5, '7daysAgo': 0.5, '30daysAgo': None},
        {'period': '+5y', 'current': 9},
    ])
    assert [r['period'] for r in rows] == ['0y', '+1y']
    assert rows[1]['change_7d_pct'] == 10.0 and rows[1]['change_30d_pct'] == -50.0
    assert rows[0]['change_30d_pct'] is None


def test_parse_holders_sorted_and_scaled():
    holders = institutional.parse_holders([
        {'holder': 'Small', 'shares': 10, 'pct_held': 0.0001, 'pct_change': None},
        {'holder': 'BlackRock', 'shares': 2200000, 'pct_held': 0.0123, 'pct_change': 1.5, 'date_reported': '2026-09-30'},
        {'holder': None, 'shares': 5},
    ])
    assert [h['holder'] for h in holders] == ['BlackRock', 'Small']
    assert holders[0]['pct_held'] == 1.23 and holders[0]['pct_change'] == 150.0
    assert holders[1]['pct_change'] is None


def test_institutional_skipped_outside_season():
    assert institutional.fetch_institutional(['BE'], today=date(2026, 12, 25)) == {}


# ---------- watchlist config ----------

def test_load_watchlist_falls_back_when_missing_or_broken(tmp_path):
    assert config.load_watchlist(str(tmp_path / 'none.json'))['tickers']
    bad = tmp_path / 'bad.json'
    bad.write_text('{not json')
    assert config.load_watchlist(str(bad))['tickers']
    empty = tmp_path / 'empty.json'
    empty.write_text('{"tickers": []}')
    assert config.load_watchlist(str(empty))['tickers']


def test_repo_watchlist_is_consistent():
    assert 'EROC' in config.STOCKS_TO_TRACK
    assert set(config.COMPETITOR_MAP) == set(config.STOCKS_TO_TRACK) == set(config.STOCK_NAMES)
    assert config.SCENARIO_EPS['EROC']['2028'] == 1.5
    assert config.DAILY_REPORT_TIME == '07:00'


def test_portfolio_comes_from_env_then_file(monkeypatch, tmp_path):
    monkeypatch.setenv('PORTFOLIO_JSON', '{"holdings": [{"symbol": "BE", "shares": 1}]}')
    assert config.load_portfolio()['holdings'][0]['symbol'] == 'BE'
    monkeypatch.setenv('PORTFOLIO_JSON', 'not json')
    assert config.load_portfolio() == {}
    monkeypatch.delenv('PORTFOLIO_JSON')
    assert config.load_portfolio(str(tmp_path / 'none.json')) == {}


def test_portfolio_file_is_git_ignored_and_example_is_committed():
    root = os.path.dirname(os.path.dirname(__file__))
    assert 'portfolio.json' in open(os.path.join(root, '.gitignore')).read().split()
    assert os.path.exists(os.path.join(root, 'portfolio.example.json'))


# ---------- schedule sync ----------

@pytest.mark.parametrize('time_text,days,cron', [
    ('07:00', 'tue-sat', '0 22 * * 1,2,3,4,5'),    # KST morning is the previous UTC evening: weekdays shift back
    ('09:00', 'tue-sat', '0 0 * * 2,3,4,5,6'),     # the old schedule
    ('18:30', 'daily', '30 9 * * *'),
    ('07:15', 'mon,sat', '15 22 * * 0,5'),
])
def test_kst_to_cron(time_text, days, cron):
    assert _load_script().kst_to_cron(time_text, days) == cron


@pytest.mark.parametrize('bad', ['7am', '25:00', '07:60', ''])
def test_kst_to_cron_rejects_bad_time(bad):
    with pytest.raises(ValueError):
        _load_script().kst_to_cron(bad, 'daily')


def test_workflow_cron_matches_watchlist():
    assert _load_script().main(['--check']) == 0
