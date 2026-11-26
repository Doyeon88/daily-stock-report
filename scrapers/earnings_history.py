"""
실적 서프라이즈와 발표 후 주가 반응 (Yahoo Finance, 키 없음)

최근 실적 발표마다 EPS 예상치·실제치·서프라이즈(%)와, 발표를 소화한 첫 거래일의 주가 등락률을 보여 줍니다.
발표 시각이 장 마감 후(오후)면 다음 거래일 종가를 발표일 종가와, 장 시작 전(오전)이면 발표일 종가를 전날 종가와 비교합니다.
"""

import logging
import math
from datetime import date, datetime
from typing import Dict, List, Optional, Sequence, Tuple

import pytz
import yfinance as yf

from config import TIMEZONE
from scrapers.retry import call_with_retry

logger = logging.getLogger(__name__)

MAX_QUARTERS = 8
AFTER_CLOSE_HOUR = 12      # 미국 동부 시각 정오 이후 발표 = 장 마감 후로 본다


def _num(value) -> Optional[float]:
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(value) else value


def reaction_pct(closes: Sequence[Tuple[date, float]], event_day: date, after_close: bool) -> Optional[float]:
    """
    Price change on the first session that traded on the news

    Args:
        closes: (day, close) pairs, oldest first
        event_day: day the results came out (exchange time)
        after_close: True when the results came after the close (the next session reacts)
    """
    if after_close:
        base = [c for d, c in closes if d <= event_day]
        after = [c for d, c in closes if d > event_day]
    else:
        base = [c for d, c in closes if d < event_day]
        after = [c for d, c in closes if d >= event_day]
    if not base or not after or not base[-1]:
        return None
    return round((after[0] / base[-1] - 1) * 100, 2)


def parse_earnings(records: List[Dict], closes: Sequence[Tuple[date, float]], today: date) -> Optional[Dict]:
    """
    Args:
        records: [{'when': datetime (exchange time), 'estimate', 'reported', 'surprise_pct'}] from Yahoo
        closes: daily (day, close) pairs, oldest first
        today: reference date; upcoming dates (no reported EPS yet) are skipped

    Returns:
        {'rows': [{'date', 'timing', 'estimate', 'reported', 'surprise_pct', 'reaction_pct'}] newest first,
         'beats', 'misses', 'count', 'avg_abs_reaction'} or None when there is no reported quarter
    """
    rows = []
    for r in records:
        when, reported = r.get('when'), _num(r.get('reported'))
        if when is None or reported is None:
            continue
        day = when.date() if isinstance(when, datetime) else when
        if day > today:
            continue
        after_close = isinstance(when, datetime) and when.hour >= AFTER_CLOSE_HOUR
        estimate, surprise = _num(r.get('estimate')), _num(r.get('surprise_pct'))
        if surprise is None and estimate not in (None, 0):
            surprise = (reported - estimate) / abs(estimate) * 100
        rows.append({
            'date': day.isoformat(),
            'timing': '장 마감 후' if after_close else '장 시작 전',
            'estimate': estimate, 'reported': reported,
            'surprise_pct': round(surprise, 1) if surprise is not None else None,
            'reaction_pct': reaction_pct(closes, day, after_close),
        })
    rows.sort(key=lambda row: row['date'], reverse=True)
    rows = rows[:MAX_QUARTERS]
    if not rows:
        return None
    reactions = [abs(row['reaction_pct']) for row in rows if row['reaction_pct'] is not None]
    return {
        'rows': rows,
        'count': len(rows),
        'beats': sum(1 for row in rows if (row['surprise_pct'] or 0) > 0),
        'misses': sum(1 for row in rows if (row['surprise_pct'] or 0) < 0),
        'avg_abs_reaction': round(sum(reactions) / len(reactions), 1) if reactions else None,
    }


def _records(frame) -> List[Dict]:
    records = []
    for when, row in frame.iterrows():
        records.append({
            'when': when.to_pydatetime() if hasattr(when, 'to_pydatetime') else when,
            'estimate': row.get('EPS Estimate'), 'reported': row.get('Reported EPS'),
            'surprise_pct': row.get('Surprise(%)'),
        })
    return records


def fetch_earnings_history(tickers: List[str], today: Optional[date] = None) -> Dict[str, Dict]:
    """ticker -> parse_earnings result; tickers without data are left out"""
    today = today or datetime.now(pytz.timezone(TIMEZONE)).date()
    results = {}
    for ticker in tickers:
        try:
            stock = yf.Ticker(ticker)
            frame = call_with_retry(lambda: stock.get_earnings_dates(limit=MAX_QUARTERS + 4),
                                    f"{ticker} earnings dates")
            if frame is None or getattr(frame, 'empty', True):
                continue
            history = call_with_retry(lambda: stock.history(period='3y', interval='1d'), f"{ticker} 3y history")
            closes = [(index.date(), float(close)) for index, close in history['Close'].dropna().items()]
            parsed = parse_earnings(_records(frame), closes, today)
            if parsed:
                results[ticker] = parsed
        except Exception as e:
            logger.error(f"{ticker}: earnings history unavailable: {e}")
    return results
