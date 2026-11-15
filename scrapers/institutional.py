"""
13F 기관 보유 (13F 시즌에만 표시)

Yahoo Finance의 institutional_holders(13F 집계)를 씁니다. 한계: 분기 말 기준의 지연 데이터이고,
롱 포지션만 나오며, 인덱스·패시브 자금의 기계적 매수가 섞여 있습니다. 신규 대형 보유(예: 특정 운용사)는
SEC 원문(13F-HR, Schedule 13G/13D)에서 확인해야 합니다.
"""

import logging
from datetime import date, datetime
from typing import Dict, List, Optional

import pytz
import yfinance as yf

from config import TIMEZONE
from processors.calendar_events import is_13f_season
from scrapers.retry import call_with_retry

logger = logging.getLogger(__name__)

TOP_HOLDERS = 6


def parse_holders(records: List[Dict]) -> List[Dict]:
    """
    Args:
        records: rows like {'holder', 'shares', 'pct_held', 'pct_change', 'date_reported'}

    Returns:
        biggest holders first, capped: [{'holder', 'shares', 'pct_held', 'pct_change', 'reported'}]
        pct_held/pct_change are in percent; pct_change is the change in shares vs the previous filing
    """
    def f(v):
        try:
            v = float(v)
        except (TypeError, ValueError):
            return None
        return None if v != v else v

    rows = []
    for r in records:
        shares = f(r.get('shares'))
        if not r.get('holder') or shares is None:
            continue
        held, change = f(r.get('pct_held')), f(r.get('pct_change'))
        rows.append({
            'holder': str(r['holder']), 'shares': int(shares),
            'pct_held': round(held * 100, 2) if held is not None else None,
            'pct_change': round(change * 100, 1) if change is not None else None,
            'reported': str(r.get('date_reported') or '')[:10],
        })
    rows.sort(key=lambda r: r['shares'], reverse=True)
    return rows[:TOP_HOLDERS]


def fetch_institutional(tickers: List[str], today: Optional[date] = None) -> Dict[str, Dict]:
    """
    ticker -> {'holders': [...], 'season': True}; empty dict outside the 13F season

    Args:
        tickers: Stock ticker symbols
        today: Reference date (defaults to today in TIMEZONE)
    """
    today = today or datetime.now(pytz.timezone(TIMEZONE)).date()
    if not is_13f_season(today):
        logger.info("Outside the 13F season, skipping institutional holders")
        return {}
    results = {}
    for ticker in tickers:
        try:
            frame = call_with_retry(lambda: yf.Ticker(ticker).institutional_holders, f"{ticker} 13F holders")
            if frame is None or getattr(frame, 'empty', True):
                continue
            records = frame.rename(columns={
                'Holder': 'holder', 'Shares': 'shares', 'pctHeld': 'pct_held',
                'pctChange': 'pct_change', 'Date Reported': 'date_reported',
            }).to_dict('records')
            holders = parse_holders(records)
            if holders:
                results[ticker] = {'holders': holders, 'season': True}
        except Exception as e:
            logger.error(f"{ticker}: 13F holders unavailable: {e}")
    return results
