"""
호재/중립/악재 태그와 출처 검증 표시

키워드 기반의 단순 분류라서 참고용입니다(문장 전체의 맥락은 보지 못합니다).
출처 구분: 공시·거래소·Yahoo 데이터는 '검증', 언론 헤드라인은 '미검증'(원문 확인 필요).
커뮤니티·AI 요약은 이 프로그램이 수집하지 않으며, 사용자가 직접 넣는 이벤트는 verified 값을 따릅니다.
"""

from typing import Dict, Iterable, List

BULLISH, NEUTRAL, BEARISH = '호재', '중립', '악재'

POSITIVE_WORDS = (
    'beat', 'beats', 'surge', 'soar', 'jump', 'record', 'raises', 'raised', 'upgrade', 'upgraded',
    'wins', 'awarded', 'contract', 'expands', 'expansion', 'approval', 'approved', 'partnership',
    'guidance raise', 'outperform', 'backlog', 'order',
)
NEGATIVE_WORDS = (
    'miss', 'misses', 'plunge', 'slump', 'tumble', 'falls', 'drop', 'cut', 'cuts', 'downgrade',
    'downgraded', 'lawsuit', 'probe', 'investigation', 'delay', 'delays', 'delayed', 'recall',
    'offering', 'dilution', 'lockup', 'lock-up', 'short report', 'denied', 'ban', 'underperform',
    'warning', 'halt',
)

# 8-K 항목 라벨(scrapers.sec_filings.ITEM_LABELS)별 기본 태그. 나머지는 중립.
FILING_LABEL_TAGS = {
    '주요 계약 체결': BULLISH,
    '주요 계약 종료': BEARISH,
    '미등록 주식 발행': BEARISH,
}


def classify_text(text: str) -> str:
    """Tag a headline by counting positive and negative keywords (equal or none -> 중립)"""
    lowered = f" {(text or '').lower()} "
    pos = sum(1 for w in POSITIVE_WORDS if f" {w} " in lowered or f" {w}," in lowered)
    neg = sum(1 for w in NEGATIVE_WORDS if f" {w} " in lowered or f" {w}," in lowered)
    if pos > neg:
        return BULLISH
    if neg > pos:
        return BEARISH
    return NEUTRAL


def tag_news(articles: Iterable[Dict]) -> List[Dict]:
    """Copy of the articles with 'tag' and 'verified' (headlines are never verified facts)"""
    return [dict(a, tag=classify_text(a.get('title', '')), verified=False) for a in articles or []]


def tag_filings(filings: Iterable[Dict]) -> List[Dict]:
    """Copy of the filings with 'tag' and 'verified' (an SEC/Yahoo filing exists, so the fact is verified)"""
    return [
        dict(f, tag=FILING_LABEL_TAGS.get(f.get('label', ''), NEUTRAL), verified=True)
        for f in filings or []
    ]


def overall_tag(tags: Iterable[str]) -> str:
    """Whole-ticker tag: whichever of 호재/악재 is more frequent, 중립 on a tie or no tags"""
    tags = list(tags)
    pos, neg = tags.count(BULLISH), tags.count(BEARISH)
    return BULLISH if pos > neg else BEARISH if neg > pos else NEUTRAL
