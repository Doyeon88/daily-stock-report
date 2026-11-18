"""
Tests for per-year consensus (scrapers/consensus.py)
"""

from scrapers import consensus

EPS = [{'period': '0q', 'avg': 0.1}, {'period': '0y', 'avg': 0.5, 'low': 0.3, 'high': 0.9, 'numberOfAnalysts': 8, 'growth': 1.0},
       {'period': '+1y', 'avg': 2.0, 'low': 1.0, 'high': 3.0, 'numberOfAnalysts': 7, 'growth': 3.0}]
REV = [{'period': '0y', 'avg': 1.0e9, 'low': 9e8, 'high': 1.1e9, 'growth': 0.9, 'numberOfAnalysts': 9},
       {'period': '+1y', 'avg': 2.5e9, 'low': 2.0e9, 'high': 3.0e9, 'growth': 1.5}]


def test_year_rows_have_revenue_eps_per_and_fiscal_year():
    rows = consensus.parse_estimates(EPS, REV, 2026, 20.0)
    assert [r['label'] for r in rows] == ['올해', '내년']
    assert rows[0]['fiscal_year'] == 2026 and rows[1]['fiscal_year'] == 2027
    assert rows[0]['per'] == 40.0 and rows[1]['per'] == 10.0
    assert rows[0]['analysts'] == 8 and rows[0]['revenue_high'] == 1.1e9


def test_per_is_empty_for_losses_and_unknown_price_or_year():
    rows = consensus.parse_estimates([{'period': '0y', 'avg': -0.2}], [], None, 20.0)
    assert rows[0]['per'] is None and rows[0]['fiscal_year'] is None and rows[0]['revenue'] is None
    assert consensus.parse_estimates(EPS, REV, 2026, None)[0]['per'] is None
    assert consensus.parse_estimates([{'period': '0y', 'avg': float('nan')}], [], 2026, 5) == []


def test_manual_rows_are_marked_and_converted():
    rows = consensus.manual_rows('AAOI', 40.0, {'AAOI': {'2028': {'revenue_m': 3100, 'eps': 5.0, 'source': '내 추정'}}})
    assert rows == [{'label': '2028년(직접 입력)', 'fiscal_year': 2028, 'revenue': 3.1e9, 'eps': 5.0,
                     'analysts': None, 'per': 8.0, 'source': 'manual', 'note': '내 추정'}]
    assert consensus.manual_rows('XXX', 40.0, {}) == []
    assert consensus.manual_rows('A', 1.0, {'A': {'2028': {}}}) == []
