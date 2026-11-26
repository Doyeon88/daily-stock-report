"""
희석·자금조달 점검 (Yahoo Finance: 공시 목록, 분기 재무제표; 키 없음)

- 최근 180일 증권 발행 서류: 선반등록(S-3/F-3), 증자·ATM·전환사채 투자설명서(424B5), 재판매 등록(424B7·424B3),
  IPO·상장 서류(S-1, 424B4)
- 발행주식 수 증가율(직전 분기 대비, 1년 전 대비)
- 현금 런웨이: 현금 ÷ 최근 2개 분기 평균 잉여현금흐름 소진액(설비투자 포함, 추정)
분기 재무는 지연·정정될 수 있어 '추정'으로 표시합니다.
"""

import logging
import math
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional

import pytz
import yfinance as yf

from config import TIMEZONE
from scrapers.retry import call_with_retry
from scrapers.sec_filings import FORM_DESCRIPTIONS, OFFERING_FORMS

logger = logging.getLogger(__name__)

LOOKBACK_DAYS = 180
RECENT_DAYS = 90
MAX_OFFERINGS = 6
# 지금 바로 새 주식을 팔 수 있거나 판 서류 (IPO 서류보다 희석 신호가 강하다)
SHELF_AND_TAKEDOWN = ('S-3', 'S-3/A', 'S-3ASR', 'F-3', 'F-3/A', '424B5', '424B7', '424B3')
SHARE_ROWS = ('Ordinary Shares Number', 'Share Issued')
CASH_ROWS = ('Cash Cash Equivalents And Short Term Investments', 'Cash And Cash Equivalents')


def _num(value) -> Optional[float]:
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(value) else value


def _pct(new: Optional[float], old: Optional[float]) -> Optional[float]:
    return round((new / old - 1) * 100, 1) if new is not None and old else None


def offering_filings(filings, today: date, lookback_days: int = LOOKBACK_DAYS) -> List[Dict]:
    """Securities-offering filings from Yahoo's list, newest first: [{'form', 'date', 'url', 'desc'}]"""
    since = (today - timedelta(days=lookback_days)).isoformat()
    rows = []
    for item in filings if isinstance(filings, list) else []:
        filed = str(item.get('date') or '')[:10]
        if item.get('type') in OFFERING_FORMS and filed >= since:
            rows.append({'form': item['type'], 'date': filed, 'url': item.get('edgarUrl'),
                         'desc': FORM_DESCRIPTIONS.get(item['type'], item['type'])})
    rows.sort(key=lambda r: r['date'], reverse=True)
    return rows[:MAX_OFFERINGS]


def assess(offerings: List[Dict], shares: List[Optional[float]], cash: Optional[float],
           free_cash_flow: List[Optional[float]], today: date) -> Dict:
    """
    Args:
        offerings: offering_filings result
        shares: shares outstanding per quarter, newest first
        cash: latest cash and short-term investments
        free_cash_flow: free cash flow per quarter, newest first (negative = burning cash)

    Returns:
        {'level': '높음' | '주의' | '낮음', 'reasons': [...], 'offerings', 'shares_latest', 'shares_qoq_pct',
         'shares_yoy_pct', 'cash', 'quarterly_burn', 'runway_quarters'}
    """
    # 분기 자리를 지킨 채 비교한다: 중간 분기가 비어 있으면 그 비교는 하지 않는다(엉뚱한 분기와 비교하지 않도록)
    shares_latest = shares[0] if shares else None
    qoq = _pct(shares[0], shares[1]) if len(shares) > 1 and shares[1] is not None else None
    yoy = _pct(shares[0], shares[4]) if len(shares) > 4 and shares[4] is not None else None

    recent_fcf = [f for f in free_cash_flow[:2] if f is not None]
    average = sum(recent_fcf) / len(recent_fcf) if recent_fcf else None
    burn = -average if average is not None and average < 0 else None
    runway = round(cash / burn, 1) if burn and cash is not None else None

    recent_cut = (today - timedelta(days=RECENT_DAYS)).isoformat()
    strong = [o for o in offerings if o['form'] in SHELF_AND_TAKEDOWN and o['date'] >= recent_cut]
    high, caution = [], []
    if strong:
        high.append(f"최근 90일 증권 발행 서류 {', '.join(sorted({o['form'] for o in strong}))}")
    elif offerings:
        caution.append(f"최근 180일 발행 관련 서류 {', '.join(sorted({o['form'] for o in offerings}))} (IPO 서류 포함 가능)")
    if runway is not None and runway < 8:
        (high if runway < 4 else caution).append(f"현금 런웨이 약 {runway}분기(추정)")
    if yoy is not None and yoy > 10:
        (high if yoy > 20 else caution).append(f"발행주식 1년 새 {yoy:+.1f}%")
    elif yoy is None and qoq is not None and qoq > 5:
        caution.append(f"발행주식 직전 분기 대비 {qoq:+.1f}%")

    level = '높음' if high else '주의' if caution else '낮음'
    return {
        'level': level, 'reasons': high + caution, 'offerings': offerings,
        'shares_latest': shares_latest, 'shares_qoq_pct': qoq, 'shares_yoy_pct': yoy,
        'cash': cash, 'quarterly_burn': round(burn) if burn else None, 'runway_quarters': runway,
    }


def _row(frame, names) -> List[Optional[float]]:
    """Values of the first row that exists, newest quarter first ([] if none)"""
    for name in names:
        if frame is not None and not getattr(frame, 'empty', True) and name in frame.index:
            return [_num(v) for v in frame.loc[name].tolist()]
    return []


def _free_cash_flow(cashflow) -> List[Optional[float]]:
    fcf = _row(cashflow, ('Free Cash Flow',))
    if fcf:
        return fcf
    operating, capex = _row(cashflow, ('Operating Cash Flow',)), _row(cashflow, ('Capital Expenditure',))
    return [o + c if o is not None and c is not None else None for o, c in zip(operating, capex)]


def fetch_dilution(tickers: List[str], today: Optional[date] = None) -> Dict[str, Dict]:
    """ticker -> assess result; tickers where nothing could be read are left out"""
    today = today or datetime.now(pytz.timezone(TIMEZONE)).date()
    results = {}
    for ticker in tickers:
        stock = yf.Ticker(ticker)
        try:
            filings = call_with_retry(lambda: stock.sec_filings, f"{ticker} filing list (dilution)")
        except Exception as e:
            logger.error(f"{ticker}: filing list for the dilution check unavailable: {e}")
            filings = []
        try:
            balance = call_with_retry(lambda: stock.quarterly_balance_sheet, f"{ticker} quarterly balance sheet")
            cashflow = call_with_retry(lambda: stock.quarterly_cashflow, f"{ticker} quarterly cash flow")
        except Exception as e:
            logger.error(f"{ticker}: quarterly statements unavailable: {e}")
            balance = cashflow = None
        cash_values = _row(balance, CASH_ROWS)
        result = assess(offering_filings(filings, today), _row(balance, SHARE_ROWS),
                        cash_values[0] if cash_values else None, _free_cash_flow(cashflow), today)
        if result['offerings'] or result['shares_latest'] is not None or result['cash'] is not None:
            results[ticker] = result
    return results
