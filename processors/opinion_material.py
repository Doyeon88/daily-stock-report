"""
항목별 AI 의견의 재료 (네트워크 없음)

종목마다 실적 이력·내부자 거래·공시·희석·옵션·기술적 신호·13F 자료를 짧은 글로 묶고, 어떤 항목에 의견을 달지(sections)를
정합니다. 자료가 없는 항목은 넣지 않습니다. 관심 종목 전체의 리스크(상관·베타·변동성)는 '__market__' 하나로 묶습니다.
"""

from typing import Dict, List, Optional

SECTION_LABELS = {
    'earnings': '실적 서프라이즈·발표 후 반응',
    'insiders': '내부자 거래(Form 4)',
    'filings': '최근 공시(8-K 항목·보도자료)',
    'dilution': '희석·자금조달',
    'options': '옵션 기대 변동',
    'technical': '기술적 신호',
    'institutional': '13F 기관 매매',
}
MARKET_KEY = '__market__'


def _money(value) -> str:
    if value is None:
        return '-'
    value = float(value)
    if abs(value) >= 1e9:
        return f"${value / 1e9:.2f}B"
    if abs(value) >= 1e6:
        return f"${value / 1e6:.1f}M"
    return f"${value:,.0f}"


def _pct(value, digits=1) -> str:
    return '-' if value is None else f"{value:+.{digits}f}%"


def _earnings(entry: Dict, details: Dict) -> List[str]:
    lines = [f"- 최근 {entry['count']}회: 예상 상회 {entry['beats']}회, 하회 {entry['misses']}회, "
             f"발표 후 평균 변동폭 {entry.get('avg_abs_reaction')}%"]
    for row in entry['rows'][:4]:
        lines.append(f"- {row['date']}({row['timing']}) EPS 예상 {row['estimate']} / 실제 {row['reported']}, "
                     f"서프라이즈 {_pct(row['surprise_pct'])}, 다음 거래 반응 {_pct(row['reaction_pct'])}")
    if details.get('earnings_date'):
        lines.append(f"- 다음 실적 발표 {details['earnings_date']} (D-{details.get('days_to_earnings')})")
    return lines


def _insiders(entry: Dict) -> List[str]:
    lines = [f"- 최근 {entry['window_days']}일 장내 매수 {entry['buy_count']}건 {_money(entry['buy_value'])}, "
             f"매도 {entry['sell_count']}건 {_money(entry['sell_value'])}, 순매수 {_money(entry['net_value'])}, "
             f"클러스터 매수 {'있음' if entry['cluster_buy'] else '없음'}, 주식보상·행사 등 {entry['other_count']}건"]
    for t in entry['recent'][:4]:
        lines.append(f"- {t['date']} {t['insider']}({t['position']}) {'매수' if t['kind'] == 'buy' else '매도'} "
                     f"{t['shares'] or '-'}주 {_money(t['value'])}")
    return lines


def _filings(info: Dict) -> List[str]:
    lines = []
    for f in (info.get('filings') or [])[:6]:
        text = f"- {f['date']} {f['form']}" + (f" ({f['label']})" if f.get('label') else '')
        press = f.get('press_release') or {}
        if press.get('summary'):
            text += f" / 보도자료 요약: {press['summary'].replace(chr(10), ' ')[:500]}"
        lines.append(text)
    return lines


def _dilution(entry: Dict) -> List[str]:
    lines = [f"- 희석 위험 판정 {entry['level']}: {', '.join(entry['reasons']) or '특이 사항 없음'}",
             f"- 발행주식 {entry.get('shares_latest')}, 직전 분기 대비 {_pct(entry.get('shares_qoq_pct'))}, "
             f"1년 전 대비 {_pct(entry.get('shares_yoy_pct'))}",
             f"- 현금 {_money(entry.get('cash'))}, 분기 소진 {_money(entry.get('quarterly_burn'))}, "
             f"런웨이 {entry.get('runway_quarters') or '-'}분기(추정)"]
    lines += [f"- {o['date']} {o['form']} ({o['desc']})" for o in entry.get('offerings', [])[:4]]
    return lines


def _options(entry: Dict) -> List[str]:
    target = f"실적 발표({entry['earnings_date']}) 직후 만기" if entry.get('for_earnings') else '가까운 만기'
    lines = [f"- {target} {entry['expiry']}: 기대 변동 ±{entry['expected_move_pct']}% (ATM {entry['atm_strike']} "
             f"스트래들 ${entry['straddle']}), ATM 내재변동성 {entry.get('iv_atm')}%, "
             f"풋/콜 미결제약정 {entry.get('put_call_oi')}, 거래량 {entry.get('put_call_volume')}"]
    lines += [f"- 이상 거래 {u['side']} {u['strike']} 거래량 {u['volume']} (미결제 {u['oi']})" for u in entry.get('unusual', [])]
    return lines


def _technical(entry: Dict, risk_row: Optional[Dict]) -> List[str]:
    lines = [f"- {label['text']}" for label in entry.get('labels', [])]
    lines.append(f"- MACD {entry.get('macd')} / 시그널 {entry.get('macd_signal')}, 볼린저 위치 {entry.get('bb_pct')}%, "
                 f"50일선 {entry.get('ma50')}, 200일선 {entry.get('ma200')}")
    if risk_row:
        lines.append(f"- 1년 변동성 {risk_row.get('vol_annual')}%, 최대낙폭 {risk_row.get('max_drawdown')}%, "
                     f"QQQ 대비 베타 {risk_row.get('beta')}")
    return lines


def _institutional(entry: Dict) -> List[str]:
    s = entry.get('summary') or {}
    lines = [f"- 상위 보유기관 중 늘린 곳 {s.get('increased', 0)}, 줄인 곳 {s.get('decreased', 0)}"]
    lines += [f"- 늘림 {b['holder']} {_pct(b['pct_change'])}" for b in entry.get('buyers', [])[:3]]
    lines += [f"- 줄임 {x['holder']} {_pct(x['pct_change'])}" for x in entry.get('sellers', [])[:3]]
    return lines


def build_ticker_material(ticker: str, name: str, details: Optional[Dict] = None, earnings: Optional[Dict] = None,
                          insiders: Optional[Dict] = None, filings: Optional[Dict] = None,
                          dilution: Optional[Dict] = None, options: Optional[Dict] = None,
                          signals: Optional[Dict] = None, institutional: Optional[Dict] = None,
                          risk_row: Optional[Dict] = None) -> Dict:
    """{'subject', 'text', 'sections': {key: label}}; text is '' when there is nothing to comment on"""
    parts, sections = [], {}

    def add(key, lines):
        if lines:
            sections[key] = SECTION_LABELS[key]
            parts.append(f"[{key}: {SECTION_LABELS[key]}]\n" + '\n'.join(lines))

    add('earnings', _earnings(earnings, details or {}) if earnings else [])
    add('insiders', _insiders(insiders) if insiders else [])
    add('filings', _filings(filings) if filings else [])
    add('dilution', _dilution(dilution) if dilution else [])
    add('options', _options(options) if options else [])
    add('technical', _technical(signals, risk_row) if signals else [])
    add('institutional', _institutional(institutional) if institutional and institutional.get('holders') else [])
    subject = f"{ticker}({name})" if name and name != ticker else ticker
    return {'subject': subject, 'text': '\n\n'.join(parts), 'sections': sections}


def build_market_material(risk: Optional[Dict]) -> Dict:
    """Material for one opinion on the watchlist's combined risk (correlation, beta, volatility)"""
    if not risk or not risk.get('per_ticker'):
        return {'subject': '관심 종목 전체', 'text': '', 'sections': {}}
    lines = [f"- {t}: 기간 수익률 {_pct(r.get('return_pct'))}, 변동성 {r.get('vol_annual')}%, 최대낙폭 {r.get('max_drawdown')}%, "
             f"{risk.get('benchmark')} 대비 베타 {r.get('beta')}" for t, r in risk['per_ticker'].items()]
    pairs = ', '.join(f"{p['a']}-{p['b']} {p['corr']}" for p in risk.get('high_corr_pairs', [])) or '없음'
    lines.append(f"- 상관 0.6 이상 쌍: {pairs}; 평균 상관 {risk.get('avg_corr')}")
    return {'subject': '관심 종목 전체', 'text': '[risk: 리스크·상관]\n' + '\n'.join(lines),
            'sections': {'risk': '관심 종목 전체 리스크·종목 간 상관(사실상 같은 베팅인지)'}}
