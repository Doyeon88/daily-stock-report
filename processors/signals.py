"""
기술적 신호와 리스크 지표 (계산만, 네트워크 없음)

기술적 신호(종목별): MACD(12·26·9) 교차, 볼린저밴드(20일·2σ) 이탈, 50일선 돌파·이탈, 50/200일선 골든·데드크로스,
ATR(14일, 하루 평균 변동폭). 짧은 한국어 라벨로 만들어 모바일 화면에 한 줄씩 보여 줍니다.
리스크(관심 종목 전체): 연환산 변동성, 최대낙폭, QQQ 대비 베타, 종목 간 수익률 상관(0.6 이상 쌍).
상장한 지 얼마 안 된 종목은 기간이 짧아 일부 값이 비어 있습니다.
"""

from itertools import combinations
from typing import Dict, List, Optional

import pandas as pd

MACD_FAST, MACD_SLOW, MACD_SIGNAL = 12, 26, 9
BB_PERIOD, BB_WIDTH = 20, 2.0
ATR_PERIOD = 14
CROSS_LOOKBACK = 3          # MACD·50일선: 최근 3거래일 안의 교차만 신호로 본다
MA_CROSS_LOOKBACK = 10      # 50/200일선 교차: 최근 10거래일
MIN_OVERLAP = 60            # 베타·상관에 필요한 최소 공통 거래일
HIGH_CORR = 0.6             # 변동성 큰 소형 성장주에서는 0.6 이상이면 대체로 같이 움직인다
MAX_PAIRS = 8
TRADING_DAYS = 252


def _round(value, digits=2) -> Optional[float]:
    return None if value is None or pd.isna(value) else round(float(value), digits)


def _crossed(diff: pd.Series, lookback: int) -> Optional[str]:
    """'up' if diff turned from <=0 to >0 within the last `lookback` bars, 'down' for the reverse, else None"""
    diff = diff.dropna()
    for i in range(1, min(lookback, len(diff) - 1) + 1):
        before, after = diff.iloc[-i - 1], diff.iloc[-i]
        if before <= 0 < after:
            return 'up'
        if before >= 0 > after:
            return 'down'
    return None


def technical_signals(frame: pd.DataFrame) -> Optional[Dict]:
    """
    Args:
        frame: daily rows with Close, High, Low, oldest first

    Returns:
        {'macd', 'macd_signal', 'macd_hist', 'bb_upper', 'bb_lower', 'bb_pct', 'ma50', 'ma200', 'atr14', 'atr_pct',
         'labels': [{'text', 'tone'}]} or None with fewer than 35 days
    """
    close = frame['Close'].astype(float)
    if len(close) < MACD_SLOW + MACD_SIGNAL:
        return None
    last = float(close.iloc[-1])
    labels: List[Dict] = []

    macd = close.ewm(span=MACD_FAST, adjust=False).mean() - close.ewm(span=MACD_SLOW, adjust=False).mean()
    signal = macd.ewm(span=MACD_SIGNAL, adjust=False).mean()
    hist = macd - signal
    cross = _crossed(hist, CROSS_LOOKBACK)
    if cross == 'up':
        labels.append({'text': 'MACD 골든크로스(최근 3일)', 'tone': 'up'})
    elif cross == 'down':
        labels.append({'text': 'MACD 데드크로스(최근 3일)', 'tone': 'down'})

    mid = close.rolling(BB_PERIOD).mean()
    std = close.rolling(BB_PERIOD).std()
    upper, lower = mid + BB_WIDTH * std, mid - BB_WIDTH * std
    bb_pct = None
    if not pd.isna(upper.iloc[-1]) and upper.iloc[-1] > lower.iloc[-1]:
        bb_pct = (last - lower.iloc[-1]) / (upper.iloc[-1] - lower.iloc[-1]) * 100
        if last > upper.iloc[-1]:
            labels.append({'text': '볼린저밴드 상단 돌파(단기 과열)', 'tone': 'up'})
        elif last < lower.iloc[-1]:
            labels.append({'text': '볼린저밴드 하단 이탈(단기 과매도)', 'tone': 'down'})

    ma50 = close.rolling(50).mean() if len(close) >= 50 else None
    ma200 = close.rolling(200).mean() if len(close) >= 200 else None
    if ma50 is not None:
        price_cross = _crossed(close - ma50, CROSS_LOOKBACK)
        if price_cross == 'up':
            labels.append({'text': '50일선 돌파(최근 3일)', 'tone': 'up'})
        elif price_cross == 'down':
            labels.append({'text': '50일선 이탈(최근 3일)', 'tone': 'down'})
    if ma50 is not None and ma200 is not None:
        ma_cross = _crossed(ma50 - ma200, MA_CROSS_LOOKBACK)
        if ma_cross == 'up':
            labels.append({'text': '골든크로스(50일선이 200일선 위로, 최근 10일)', 'tone': 'up'})
        elif ma_cross == 'down':
            labels.append({'text': '데드크로스(50일선이 200일선 아래로, 최근 10일)', 'tone': 'down'})
        else:
            above = ma50.iloc[-1] > ma200.iloc[-1]
            labels.append({'text': '50일선이 200일선 위(상승 추세)' if above else '50일선이 200일선 아래(하락 추세)',
                           'tone': 'up' if above else 'down'})

    high, low = frame['High'].astype(float), frame['Low'].astype(float)
    previous = close.shift(1)
    true_range = pd.concat([high - low, (high - previous).abs(), (low - previous).abs()], axis=1).max(axis=1)
    atr = true_range.ewm(alpha=1 / ATR_PERIOD, adjust=False).mean().iloc[-1]
    atr_pct = atr / last * 100 if last else None
    if atr_pct is not None:
        labels.append({'text': f'하루 평균 변동폭(ATR) {atr_pct:.1f}%', 'tone': ''})

    return {
        'macd': _round(macd.iloc[-1], 3), 'macd_signal': _round(signal.iloc[-1], 3), 'macd_hist': _round(hist.iloc[-1], 3),
        'bb_upper': _round(upper.iloc[-1]), 'bb_lower': _round(lower.iloc[-1]), 'bb_pct': _round(bb_pct, 0),
        'ma50': _round(ma50.iloc[-1]) if ma50 is not None else None,
        'ma200': _round(ma200.iloc[-1]) if ma200 is not None else None,
        'atr14': _round(atr), 'atr_pct': _round(atr_pct, 1),
        'labels': labels,
    }


def build_signals(history: Dict[str, pd.DataFrame], tickers: List[str]) -> Dict[str, Dict]:
    """ticker -> technical_signals result for the tickers with enough history"""
    results = {}
    for ticker in tickers:
        frame = history.get(ticker)
        if frame is not None:
            signals = technical_signals(frame)
            if signals:
                results[ticker] = signals
    return results


def _daily_closes(frame: pd.DataFrame) -> pd.Series:
    """Closes indexed by calendar day (time zone dropped) so different symbols line up"""
    series = frame['Close'].astype(float).copy()
    index = pd.DatetimeIndex(series.index)
    series.index = (index.tz_localize(None) if index.tz is not None else index).normalize()
    return series[~series.index.duplicated(keep='last')]


def risk_metrics(history: Dict[str, pd.DataFrame], tickers: List[str], benchmark: str = 'QQQ') -> Dict:
    """
    Returns:
        {'benchmark', 'per_ticker': {t: {'days', 'return_pct', 'vol_annual', 'max_drawdown', 'beta'}},
         'high_corr_pairs': [{'a', 'b', 'corr'}], 'avg_corr'}; {} without data
    """
    closes = {t: _daily_closes(history[t]) for t in tickers if t in history}
    if not closes:
        return {}
    returns = pd.DataFrame({t: s.pct_change() for t, s in closes.items()})
    bench = _daily_closes(history[benchmark]).pct_change() if benchmark in history else None

    per_ticker = {}
    for ticker, series in closes.items():
        daily = returns[ticker].dropna()
        entry = {'days': int(len(series)),
                 'return_pct': _round((series.iloc[-1] / series.iloc[0] - 1) * 100, 1),
                 'vol_annual': _round(daily.std() * TRADING_DAYS ** 0.5 * 100, 1) if len(daily) >= 20 else None,
                 'max_drawdown': _round((series / series.cummax() - 1).min() * 100, 1),
                 'beta': None}
        if bench is not None:
            joined = pd.concat([daily, bench], axis=1, join='inner').dropna()
            if len(joined) >= MIN_OVERLAP and joined.iloc[:, 1].var() > 0:
                entry['beta'] = _round(joined.iloc[:, 0].cov(joined.iloc[:, 1]) / joined.iloc[:, 1].var(), 2)
        per_ticker[ticker] = entry

    corr = returns.corr(min_periods=MIN_OVERLAP)
    pairs = []
    for a, b in combinations(corr.columns, 2):
        value = corr.loc[a, b]
        if not pd.isna(value):
            pairs.append({'a': a, 'b': b, 'corr': round(float(value), 2)})
    high = sorted((p for p in pairs if p['corr'] >= HIGH_CORR), key=lambda p: -p['corr'])[:MAX_PAIRS]
    return {
        'benchmark': benchmark,
        'per_ticker': per_ticker,
        'high_corr_pairs': high,
        'avg_corr': _round(sum(p['corr'] for p in pairs) / len(pairs), 2) if pairs else None,
    }
