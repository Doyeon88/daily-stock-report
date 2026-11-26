"""
임원·이사 내부자 거래 상세 (Form 4, Yahoo Finance의 insider_transactions, 키 없음)

최근 90일의 장내 매수·매도를 금액으로 합산하고, 서로 다른 내부자 2명 이상이 30일 안에 장내 매수했으면
'클러스터 매수'로 표시합니다(소형 성장주에서 의미가 큰 신호). 주식 보상(award)·옵션 행사·증여는 매매가 아니라서
금액 합계에서 빼고 건수만 셉니다. Yahoo 자료에는 10b5-1(사전 계획 매매) 여부가 없습니다.
"""

import logging
import math
import re
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional

import pytz
import yfinance as yf

from config import TIMEZONE
from scrapers.retry import call_with_retry

logger = logging.getLogger(__name__)

WINDOW_DAYS = 90
CLUSTER_DAYS = 30
MAX_RECENT = 6
_PRICE = re.compile(r'price\s+\$?([\d,]+(?:\.\d+)?)', re.I)


def _num(value) -> Optional[float]:
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(value) else value


def classify(text: str, transaction: str = '') -> str:
    """'buy' | 'sell' | 'other' from Yahoo's description ('Purchase at price 12.30 per share.', 'Sale at ...')"""
    lowered = f"{text or ''} {transaction or ''}".lower()
    if 'purchase' in lowered or 'buy' in lowered:
        return 'buy'
    if 'sale' in lowered or 'sell' in lowered:
        return 'sell'
    return 'other'


def _day(value) -> Optional[date]:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def has_cluster_buy(buys: List[Dict], days: int = CLUSTER_DAYS) -> bool:
    """Two or more different insiders bought within `days` of each other"""
    ordered = sorted(buys, key=lambda b: b['date'])
    for i, first in enumerate(ordered):
        start = date.fromisoformat(first['date'])
        names = {b['insider'] for b in ordered[i:] if date.fromisoformat(b['date']) - start <= timedelta(days=days)}
        if len(names) >= 2:
            return True
    return False


def parse_insider_transactions(records: List[Dict], today: date, window_days: int = WINDOW_DAYS) -> Dict:
    """
    Args:
        records: rows like Yahoo's {'Shares', 'Value', 'Text', 'Insider', 'Position', 'Transaction', 'Start Date'}
        today: reference date

    Returns:
        {'window_days', 'buy_count', 'sell_count', 'buy_value', 'sell_value', 'net_value', 'buyers', 'sellers',
         'cluster_buy', 'other_count', 'recent': [...]}; counts are 0 when nothing happened in the window
    """
    since = today - timedelta(days=window_days)
    trades, other = [], 0
    for r in records:
        day = _day(r.get('Start Date'))
        if day is None or not since <= day <= today:
            continue
        kind = classify(r.get('Text'), r.get('Transaction'))
        if kind == 'other':
            other += 1
            continue
        shares, value = _num(r.get('Shares')), _num(r.get('Value'))
        price_match = _PRICE.search(str(r.get('Text') or ''))
        price = float(price_match.group(1).replace(',', '')) if price_match else None
        if value is None and shares is not None and price is not None:
            value = shares * price
        trades.append({
            'date': day.isoformat(), 'kind': kind,
            'insider': ' '.join(str(r.get('Insider') or '?').split()).title(),
            'position': ' '.join(str(r.get('Position') or '').split()),
            'shares': int(shares) if shares is not None else None,
            'value': round(value) if value is not None else None,
            'price': price,
        })

    buys = [t for t in trades if t['kind'] == 'buy']
    sells = [t for t in trades if t['kind'] == 'sell']
    buy_value = sum(t['value'] or 0 for t in buys)
    sell_value = sum(t['value'] or 0 for t in sells)
    trades.sort(key=lambda t: (t['date'], t['value'] or 0), reverse=True)
    return {
        'window_days': window_days,
        'buy_count': len(buys), 'sell_count': len(sells),
        'buy_value': buy_value, 'sell_value': sell_value, 'net_value': buy_value - sell_value,
        'buyers': sorted({t['insider'] for t in buys}),
        'sellers': sorted({t['insider'] for t in sells}),
        'cluster_buy': has_cluster_buy(buys),
        'other_count': other,
        'recent': trades[:MAX_RECENT],
    }


def fetch_insider_activity(tickers: List[str], today: Optional[date] = None) -> Dict[str, Dict]:
    """ticker -> parse_insider_transactions result; tickers without data are left out"""
    today = today or datetime.now(pytz.timezone(TIMEZONE)).date()
    results = {}
    for ticker in tickers:
        try:
            frame = call_with_retry(lambda: yf.Ticker(ticker).insider_transactions, f"{ticker} insider transactions")
            if frame is None or getattr(frame, 'empty', True):
                continue
            results[ticker] = parse_insider_transactions(frame.to_dict('records'), today)
        except Exception as e:
            logger.error(f"{ticker}: insider transactions unavailable: {e}")
    return results
