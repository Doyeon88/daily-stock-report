"""
애널리스트 변화: 최근 투자의견·목표가 변경(Yahoo)과 EPS 컨센서스 추정치의 7/30일 변화

출처는 Yahoo Finance 집계라서 증권사 원문과 다를 수 있습니다(원문 확인 전까지 '집계 데이터').
"""

import logging
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional

import pytz
import yfinance as yf

from config import TIMEZONE
from scrapers.retry import call_with_retry

logger = logging.getLogger(__name__)

LOOKBACK_DAYS = 7
MAX_CHANGES = 6
PERIOD_LABELS = {'0y': '올해', '+1y': '내년', '0q': '이번 분기', '+1q': '다음 분기'}


def _num(value) -> Optional[float]:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    return None if v != v else v   # NaN -> None


def parse_rating_changes(records: List[Dict], since: date) -> List[Dict]:
    """
    Args:
        records: rows like {'date', 'firm', 'to_grade', 'from_grade', 'action', 'target', 'prior_target'}
        since: oldest date to keep

    Returns:
        newest-first list of {'date', 'firm', 'action', 'to_grade', 'from_grade', 'target', 'prior_target'}
    """
    rows = []
    for r in records:
        d = str(r.get('date') or '')[:10]
        if not d or d < since.isoformat():
            continue
        rows.append({
            'date': d, 'firm': r.get('firm') or '', 'action': (r.get('action') or '').lower(),
            'to_grade': r.get('to_grade') or '', 'from_grade': r.get('from_grade') or '',
            'target': _num(r.get('target')), 'prior_target': _num(r.get('prior_target')),
        })
    rows.sort(key=lambda r: r['date'], reverse=True)
    return rows[:MAX_CHANGES]


def parse_eps_trend(records: List[Dict]) -> List[Dict]:
    """
    Args:
        records: rows like {'period': '0y', 'current', '7daysAgo', '30daysAgo'} (EPS consensus)

    Returns:
        [{'period', 'label', 'current', 'change_7d_pct', 'change_30d_pct'}] for annual periods first
    """
    out = []
    for r in records:
        period, cur = r.get('period'), _num(r.get('current'))
        if period not in PERIOD_LABELS or cur is None:
            continue

        def pct(old):
            old = _num(old)
            return round((cur - old) / abs(old) * 100, 1) if old else None

        out.append({'period': period, 'label': PERIOD_LABELS[period], 'current': round(cur, 3),
                    'change_7d_pct': pct(r.get('7daysAgo')), 'change_30d_pct': pct(r.get('30daysAgo'))})
    order = list(PERIOD_LABELS)
    return sorted(out, key=lambda x: order.index(x['period']))


def _frame_records(frame, rename: Dict[str, str], index_name: str) -> List[Dict]:
    if frame is None or getattr(frame, 'empty', True):
        return []
    df = frame.reset_index()
    first = df.columns[0]
    df = df.rename(columns={first: index_name, **rename})
    return df.to_dict('records')


def fetch_analyst_changes(tickers: List[str], today: Optional[date] = None) -> Dict[str, Dict]:
    """ticker -> {'ratings': [...], 'eps_trend': [...]}; tickers with nothing available are omitted"""
    today = today or datetime.now(pytz.timezone(TIMEZONE)).date()
    since = today - timedelta(days=LOOKBACK_DAYS)
    results = {}
    for ticker in tickers:
        stock = yf.Ticker(ticker)
        entry = {'ratings': [], 'eps_trend': []}
        try:
            frame = call_with_retry(lambda: stock.upgrades_downgrades, f"{ticker} rating changes")
            entry['ratings'] = parse_rating_changes(_frame_records(
                frame, {'Firm': 'firm', 'ToGrade': 'to_grade', 'FromGrade': 'from_grade', 'Action': 'action',
                        'currentPriceTarget': 'target', 'priorPriceTarget': 'prior_target'}, 'date'), since)
        except Exception as e:
            logger.error(f"{ticker}: rating changes unavailable: {e}")
        try:
            frame = call_with_retry(lambda: stock.eps_trend, f"{ticker} EPS trend")
            entry['eps_trend'] = parse_eps_trend(_frame_records(frame, {}, 'period'))
        except Exception as e:
            logger.error(f"{ticker}: EPS trend unavailable: {e}")
        if entry['ratings'] or entry['eps_trend']:
            results[ticker] = entry
    return results
