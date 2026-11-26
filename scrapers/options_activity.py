"""
옵션 시장의 기대 변동폭과 풋/콜 비율 (Yahoo Finance 옵션 체인, 키 없음)

- 기대 변동폭: 현재가에 가장 가까운 행사가(ATM)의 콜+풋 가격(스트래들). 만기까지 시장이 예상하는 대략의 변동 폭입니다.
  다음 실적 발표가 45일 안이면 발표 직후 만기를 써서 '이번 실적 기대 변동'으로 표시합니다.
- 풋/콜 비율: 해당 만기의 미결제약정(OI)과 거래량 기준. 1보다 크면 하락 대비(풋)가 많다는 뜻입니다.
- 이상 거래: 거래량이 미결제약정의 2배 이상이고 일정 규모 이상인 계약(신규 베팅 가능성).
Yahoo 비공식 자료이고 소형주는 호가가 얇아 값이 튈 수 있습니다.
"""

import logging
import math
from datetime import date, datetime
from typing import Dict, List, Optional, Sequence

import pytz
import yfinance as yf

from config import TIMEZONE
from scrapers.retry import call_with_retry

logger = logging.getLogger(__name__)

EARNINGS_WINDOW_DAYS = 45
MIN_DAYS_TO_EXPIRY = 7
UNUSUAL_MIN_VOLUME = 300
UNUSUAL_VOLUME_TO_OI = 2.0
MAX_UNUSUAL = 3


def _num(value) -> Optional[float]:
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(value) else value


def choose_expiry(expiries: Sequence[str], today: date, earnings_date: Optional[str] = None):
    """(expiry, for_earnings): the first expiry after a near earnings date, else the first one 7+ days away"""
    dates = sorted(d for d in expiries if d >= today.isoformat())
    if earnings_date:
        days = (date.fromisoformat(earnings_date) - today).days
        if 0 <= days <= EARNINGS_WINDOW_DAYS:
            after = [d for d in dates if d > earnings_date]
            if after:
                return after[0], True
    later = [d for d in dates if (date.fromisoformat(d) - today).days >= MIN_DAYS_TO_EXPIRY]
    return (later[0] if later else (dates[-1] if dates else None)), False


def _mid(row: Dict) -> Optional[float]:
    bid, ask, last = _num(row.get('bid')), _num(row.get('ask')), _num(row.get('lastPrice'))
    if bid and ask and ask >= bid:
        return (bid + ask) / 2
    return last or None


def analyze_chain(calls: List[Dict], puts: List[Dict], spot: float) -> Optional[Dict]:
    """
    Args:
        calls/puts: option rows with 'strike', 'bid', 'ask', 'lastPrice', 'volume', 'openInterest', 'impliedVolatility'
        spot: current stock price

    Returns:
        {'atm_strike', 'straddle', 'expected_move_pct', 'iv_atm', 'put_call_oi', 'put_call_volume', 'unusual'}
        or None when there is no usable at-the-money pair
    """
    if not spot or not calls or not puts:
        return None
    put_by_strike = {_num(p.get('strike')): p for p in puts}
    call_by_strike = {_num(c.get('strike')): c for c in calls}
    strikes = sorted((s for s in call_by_strike if s is not None and s in put_by_strike), key=lambda s: abs(s - spot))
    for strike in strikes[:3]:
        call, put = call_by_strike[strike], put_by_strike[strike]
        call_mid, put_mid = _mid(call), _mid(put)
        if call_mid and put_mid:
            break
    else:
        return None

    def total(rows, key):
        return sum(_num(r.get(key)) or 0 for r in rows)

    call_oi, put_oi = total(calls, 'openInterest'), total(puts, 'openInterest')
    call_vol, put_vol = total(calls, 'volume'), total(puts, 'volume')
    ivs = [v for v in (_num(call.get('impliedVolatility')), _num(put.get('impliedVolatility'))) if v]

    unusual = []
    for side, rows in (('콜', calls), ('풋', puts)):
        for r in rows:
            volume, oi = _num(r.get('volume')) or 0, _num(r.get('openInterest')) or 0
            if volume >= UNUSUAL_MIN_VOLUME and volume >= UNUSUAL_VOLUME_TO_OI * max(oi, 1):
                unusual.append({'side': side, 'strike': _num(r.get('strike')), 'volume': int(volume), 'oi': int(oi)})
    unusual.sort(key=lambda u: -u['volume'])

    straddle = call_mid + put_mid
    return {
        'atm_strike': strike,
        'straddle': round(straddle, 2),
        'expected_move_pct': round(straddle / spot * 100, 1),
        'iv_atm': round(sum(ivs) / len(ivs) * 100, 1) if ivs else None,
        'put_call_oi': round(put_oi / call_oi, 2) if call_oi else None,
        'put_call_volume': round(put_vol / call_vol, 2) if call_vol else None,
        'unusual': unusual[:MAX_UNUSUAL],
    }


def fetch_options(tickers: List[str], stock_data: Dict[str, Dict], details: Dict[str, Dict],
                  today: Optional[date] = None) -> Dict[str, Dict]:
    """ticker -> analyze_chain result plus 'expiry', 'for_earnings', 'earnings_date'; no options -> left out"""
    today = today or datetime.now(pytz.timezone(TIMEZONE)).date()
    results = {}
    for ticker in tickers:
        spot = (stock_data.get(ticker) or {}).get('price')
        if not spot:
            continue
        try:
            stock = yf.Ticker(ticker)
            expiries = call_with_retry(lambda: stock.options, f"{ticker} option expiries")
            earnings_date = (details.get(ticker) or {}).get('earnings_date')
            expiry, for_earnings = choose_expiry(list(expiries or []), today, earnings_date)
            if not expiry:
                continue
            chain = call_with_retry(lambda: stock.option_chain(expiry), f"{ticker} option chain {expiry}")
            result = analyze_chain(chain.calls.to_dict('records'), chain.puts.to_dict('records'), spot)
            if result:
                result.update({'expiry': expiry, 'for_earnings': for_earnings,
                               'earnings_date': earnings_date if for_earnings else None})
                results[ticker] = result
        except Exception as e:
            logger.error(f"{ticker}: options unavailable: {e}")
    return results
