"""
이벤트 캘린더(D-day)와 종목별 '다음 이벤트' 체크리스트
"""

from datetime import date, timedelta
from typing import Dict, Iterable, List, Optional

LOOKAHEAD_DAYS = 45
QUARTER_ENDS = ((3, 31), (6, 30), (9, 30), (12, 31))
FILING_WINDOW_DAYS = 45  # 13F 제출 기한: 분기 말 + 45일
SEASON_DAYS_BEFORE = 21
SEASON_DAYS_AFTER = 14


def _parse(d: str) -> Optional[date]:
    try:
        return date.fromisoformat(str(d)[:10])
    except ValueError:
        return None


def thirteen_f_deadlines(today: date) -> List[date]:
    """Upcoming 13F filing deadlines (quarter end + 45 days) from the previous and current year"""
    out = []
    for year in (today.year - 1, today.year):
        for month, day in QUARTER_ENDS:
            out.append(date(year, month, day) + timedelta(days=FILING_WINDOW_DAYS))
    return sorted(out)


def is_13f_season(today: date) -> bool:
    """True from 3 weeks before a 13F deadline (most filings land in the last weeks) until 2 weeks after it"""
    for d in thirteen_f_deadlines(today):
        if d - timedelta(days=SEASON_DAYS_BEFORE) <= today <= d + timedelta(days=SEASON_DAYS_AFTER):
            return True
    return False


def build_calendar(
    today: date, details: Dict[str, Dict], user_events: Iterable[Dict], lookahead: int = LOOKAHEAD_DAYS
) -> List[Dict]:
    """
    Merge earnings dates (Yahoo), user-entered events and 13F deadlines into one sorted list with D-day.

    Each item: {'date', 'dday', 'label', 'tickers', 'verified'}. 'verified' is True for Yahoo's earnings
    dates and the 13F deadlines, and follows the 'verified' flag for events typed into watchlist.json.
    """
    items = []
    for ticker, d in (details or {}).items():
        when = _parse((d or {}).get('earnings_date'))
        if when:
            items.append({'date': when, 'label': f'{ticker} 실적 발표(Yahoo 일정)', 'tickers': [ticker], 'verified': True})
    for ev in user_events or []:
        when = _parse(ev.get('date'))
        if when:
            items.append({'date': when, 'label': ev.get('label', ''), 'tickers': list(ev.get('tickers') or []),
                          'verified': bool(ev.get('verified'))})
    for when in thirteen_f_deadlines(today):
        items.append({'date': when, 'label': '13F 제출 기한(분기 말+45일)', 'tickers': [], 'verified': True})

    result = []
    for it in sorted(items, key=lambda i: i['date']):
        dday = (it['date'] - today).days
        if 0 <= dday <= lookahead:
            result.append({**it, 'date': it['date'].isoformat(), 'dday': dday})
    return result


def build_checklists(tickers: Iterable[str], calendar: List[Dict], manual: Dict[str, List[str]]) -> Dict[str, Dict]:
    """Per ticker: the next dated event touching it plus the user's manual to-check items"""
    out = {}
    for ticker in tickers:
        nxt = next((c for c in calendar if ticker in c['tickers']), None)
        items = list((manual or {}).get(ticker) or [])
        if nxt or items:
            out[ticker] = {'next_event': nxt, 'items': items}
    return out
