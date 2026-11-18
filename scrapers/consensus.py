"""
컨센서스: 연도별(올해·내년) 매출·EPS 추정치와 PER, 애널리스트 목표주가(Yahoo 집계)

Yahoo가 주는 것은 올해(0y)와 내년(+1y)까지입니다. 그 뒤 연도(예: 2028)는 watchlist.json의
"consensus_manual"에 직접 넣은 값만 '직접 입력'으로 표시하고, 없으면 '자료 없음'입니다.
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

import yfinance as yf

from config import CONSENSUS_MANUAL
from scrapers.analyst_changes import _frame_records, _num
from scrapers.retry import call_with_retry

logger = logging.getLogger(__name__)

YEAR_PERIODS = (('0y', '올해'), ('+1y', '내년'))


def _by_period(records: List[Dict]) -> Dict[str, Dict]:
    return {str(r.get('period')): r for r in records}


def parse_estimates(earnings: List[Dict], revenue: List[Dict], fiscal_year: Optional[int],
                    price: Optional[float]) -> List[Dict]:
    """
    Rows for this year / next year: label, fiscal year (if known), revenue and EPS (avg/low/high, growth),
    analysts, PER (price / avg EPS when EPS is positive). Periods without any number are skipped.
    """
    eps_rows, revenue_rows = _by_period(earnings), _by_period(revenue)
    rows = []
    for offset, (period, label) in enumerate(YEAR_PERIODS):
        e, r = eps_rows.get(period, {}), revenue_rows.get(period, {})
        eps, revenue = _num(e.get('avg')), _num(r.get('avg'))
        if eps is None and revenue is None:
            continue
        analysts = _num(e.get('numberOfAnalysts')) or _num(r.get('numberOfAnalysts'))
        rows.append({
            'label': label,
            'fiscal_year': fiscal_year + offset if fiscal_year else None,
            'revenue': revenue, 'revenue_low': _num(r.get('low')), 'revenue_high': _num(r.get('high')),
            'revenue_growth': _num(r.get('growth')),
            'eps': eps, 'eps_low': _num(e.get('low')), 'eps_high': _num(e.get('high')),
            'eps_growth': _num(e.get('growth')),
            'analysts': int(analysts) if analysts else None,
            'per': round(price / eps, 1) if price and eps and eps > 0 else None,
            'source': 'yahoo',
        })
    return rows


def manual_rows(ticker: str, price: Optional[float], manual: Optional[Dict] = None) -> List[Dict]:
    """Rows typed into watchlist.json (revenue_m in million dollars)"""
    manual = CONSENSUS_MANUAL if manual is None else manual
    rows = []
    for year, values in sorted((manual.get(ticker) or {}).items()):
        eps, revenue_m = _num(values.get('eps')), _num(values.get('revenue_m'))
        if eps is None and revenue_m is None:
            continue
        rows.append({'label': f'{year}년(직접 입력)', 'fiscal_year': int(year),
                     'revenue': revenue_m * 1e6 if revenue_m is not None else None,
                     'eps': eps, 'analysts': None,
                     'per': round(price / eps, 1) if price and eps and eps > 0 else None,
                     'source': 'manual', 'note': values.get('source') or ''})
    return rows


def fetch_consensus(tickers: List[str]) -> Dict[str, Dict]:
    """ticker -> {'years': [rows], 'targets': {...}|None, 'price': float|None}; tickers without data are omitted"""
    results = {}
    for ticker in tickers:
        stock = yf.Ticker(ticker)
        price, fiscal_year, targets = None, None, None
        try:
            info = call_with_retry(lambda: stock.info, f"{ticker} info")
            price = _num(info.get('currentPrice') or info.get('regularMarketPrice'))
            last_end = _num(info.get('lastFiscalYearEnd'))
            if last_end:
                fiscal_year = (datetime.fromtimestamp(last_end, tz=timezone.utc) + timedelta(days=365)).year
        except Exception as e:
            logger.error(f"{ticker}: price/fiscal year unavailable: {e}")
        try:
            raw = call_with_retry(lambda: stock.analyst_price_targets, f"{ticker} price targets") or {}
            targets = {k: _num(raw.get(k)) for k in ('mean', 'median', 'high', 'low')}
            targets = targets if any(v is not None for v in targets.values()) else None
        except Exception as e:
            logger.error(f"{ticker}: price targets unavailable: {e}")
        rows = []
        try:
            earnings = _frame_records(call_with_retry(lambda: stock.earnings_estimate, f"{ticker} EPS estimate"), {}, 'period')
            revenue = _frame_records(call_with_retry(lambda: stock.revenue_estimate, f"{ticker} revenue estimate"), {}, 'period')
            rows = parse_estimates(earnings, revenue, fiscal_year, price)
        except Exception as e:
            logger.error(f"{ticker}: consensus estimates unavailable: {e}")
        rows += manual_rows(ticker, price)
        if rows or targets:
            results[ticker] = {'years': rows, 'targets': targets, 'price': price}
    return results
