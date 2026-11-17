"""
종목별 '중요 내용 5가지'의 재료

- text: AI에 주는 자료(수집한 제목·발췌·애널리스트 변경·컨센서스·공시). 이 안의 내용만 정리하게 합니다.
- fallback: AI를 못 쓸 때 수치로만 만든 항목
"""

from typing import Dict, List, Optional

MAX_ITEMS = 8


def _money(v) -> str:
    return f"${v:,.2f}"


def _article_lines(articles: List[Dict]) -> List[str]:
    lines = []
    for a in articles[:MAX_ITEMS]:
        text = f"- [{(a.get('published') or '')[:10]}] {a.get('title', '')}"
        if a.get('source'):
            text += f" ({a['source']})"
        if a.get('summary') and a.get('summary_source') == 'ai' and a.get('summary_basis') == 'body':
            text += f" / 본문 요약: {a['summary'].replace(chr(10), ' ')[:700]}"
        elif a.get('snippet'):
            text += f" / 발췌: {a['snippet'][:300]}"
        lines.append(text)
    return lines


def _rating_line(r: Dict) -> str:
    grade = f"{r['from_grade']} → {r['to_grade']}" if r.get('from_grade') and r.get('to_grade') else (r.get('to_grade') or r.get('action') or '')
    target = ''
    if r.get('target') is not None:
        target = f", 목표가 {_money(r['prior_target']) + ' → ' if r.get('prior_target') is not None else ''}{_money(r['target'])}"
    return f"{r['date']} {r['firm']}: {grade}{target}"


def build_material(
    ticker: str, details: Optional[Dict], news: List[Dict], analyst_articles: List[Dict],
    analyst: Optional[Dict], filings: Optional[Dict],
) -> Dict:
    """
    Returns:
        {'text': str, 'fallback': [str]}; text is '' when there is nothing collected at all
    """
    d, analyst, filings = details or {}, analyst or {}, filings or {}
    sections, fallback = [], []

    facts = []
    if d.get('target_mean') is not None:
        up = f"(현재가 대비 {d['upside']:+.1f}%)" if d.get('upside') is not None else ''
        facts.append(f"애널리스트 평균 목표가 {_money(d['target_mean'])}{up}"
                     + (f", 의견 {d['recommendation']}" if d.get('recommendation') else '')
                     + (f", {d['analyst_count']}명" if d.get('analyst_count') else ''))
        fallback.append(facts[-1] + ' (Yahoo 집계)')
    if d.get('days_to_earnings') is not None and d.get('earnings_date'):
        facts.append(f"다음 실적 발표 {d['earnings_date']} (D-{d['days_to_earnings']})")
        fallback.append(facts[-1])
    if d.get('rsi14') is not None:
        facts.append(f"RSI {d['rsi14']:.0f}, 5일 수익률 {d.get('return_5d')}%, 20일 수익률 {d.get('return_20d')}%")
    if facts:
        sections.append('[지표]\n' + '\n'.join(f'- {f}' for f in facts))

    ratings = analyst.get('ratings') or []
    if ratings:
        sections.append('[최근 애널리스트 의견 변경]\n' + '\n'.join(f'- {_rating_line(r)}' for r in ratings))
        fallback.append(f"최근 7일 애널리스트 의견·목표가 변경 {len(ratings)}건 (최근: {_rating_line(ratings[0])})")

    eps = analyst.get('eps_trend') or []
    if eps:
        lines = []
        for e in eps:
            parts = [f"7일 {e['change_7d_pct']:+.1f}%" if e.get('change_7d_pct') is not None else None,
                     f"30일 {e['change_30d_pct']:+.1f}%" if e.get('change_30d_pct') is not None else None]
            lines.append(f"- EPS 컨센서스 {e['label']} {_money(e['current'])} ({', '.join(p for p in parts if p) or '변화 정보 없음'})")
        sections.append('[EPS 컨센서스]\n' + '\n'.join(lines))
        fallback.append(lines[0][2:] + ' (Yahoo 집계)')

    if analyst_articles:
        sections.append('[애널리스트·리포트 관련 기사]\n' + '\n'.join(_article_lines(analyst_articles)))
    if news:
        sections.append('[뉴스]\n' + '\n'.join(_article_lines(news)))

    filing_rows = filings.get('filings') or []
    if filing_rows:
        sections.append('[최근 공시]\n' + '\n'.join(
            f"- {f['date']} {f['form']}" + (f" ({f['summary']})" if f.get('summary') else '') for f in filing_rows[:MAX_ITEMS]))
        counts: Dict[str, int] = {}
        for f in filing_rows:
            counts[f['form']] = counts.get(f['form'], 0) + 1
        fallback.append('최근 7일 공시 ' + ', '.join(f'{k} {v}건' for k, v in counts.items()) + ' (SEC/Yahoo)')

    tags = [a.get('tag') for a in news if a.get('tag')]
    if tags:
        fallback.append(f"뉴스 {len(tags)}건 키워드 분류: 호재 {tags.count('호재')}, 악재 {tags.count('악재')}, 중립 {tags.count('중립')}")

    text = f"종목: {ticker}\n\n" + '\n\n'.join(sections) if sections else ''
    return {'text': text, 'fallback': fallback}
