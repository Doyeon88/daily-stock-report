"""
호재/중립/악재 태그와 출처 검증 표시

기사 태그는 AI가 기사 본문·발췌를 읽고 판정한 값(ai_tag)을 우선 쓰고, AI를 못 쓰면 키워드로 단순 분류합니다(참고용).
출처 구분: 공시·거래소·Yahoo 데이터는 '검증', 언론 헤드라인은 '미검증'(원문 확인 필요).
사용자가 직접 넣는 이벤트는 verified 값을 따릅니다.
"""

from typing import Dict, Iterable, List

BULLISH, NEUTRAL, BEARISH = '호재', '중립', '악재'


def _describe(filing: Dict) -> str:
    # imported here: scrapers.sec_filings needs config/network libraries that tagging itself does not
    from scrapers.sec_filings import describe_form
    return describe_form(filing.get('form', ''), filing.get('label', ''))

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
    '상장 유지 요건 미달': BEARISH,
    '과거 재무제표 신뢰 불가': BEARISH,
    '자산 손상': BEARISH,
}
# 양식 자체가 주식 희석·매도 물량을 뜻하는 공시
FILING_FORM_TAGS = {form: BEARISH for form in ('S-3', 'S-3/A', 'S-3ASR', 'F-3', 'F-3/A', '424B5', '424B7')}
AI_TAGS = (BULLISH, NEUTRAL, BEARISH)


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


def _filing_tag(filing: Dict) -> str:
    """The first item label with a tag wins (an 8-K label can list two items), then the form itself"""
    for label in (filing.get('label') or '').split(', '):
        if label in FILING_LABEL_TAGS:
            return FILING_LABEL_TAGS[label]
    return FILING_FORM_TAGS.get(filing.get('form', ''), NEUTRAL)


def tag_news(articles: Iterable[Dict]) -> List[Dict]:
    """
    Copy of the articles with 'tag' and 'verified' (headlines are never verified facts).
    The AI's verdict from the summary step ('ai_tag', read with the article text) wins over the keyword count;
    such articles also get tag_source='ai'.
    """
    tagged = []
    for a in articles or []:
        if a.get('ai_tag') in AI_TAGS:
            tagged.append(dict(a, tag=a['ai_tag'], tag_source='ai', verified=False))
        else:
            tagged.append(dict(a, tag=classify_text(a.get('title', '')), verified=False))
    return tagged


def tag_filings(filings: Iterable[Dict]) -> List[Dict]:
    """Copy of the filings with 'tag' and 'verified' (an SEC/Yahoo filing exists, so the fact is verified)"""
    return [
        dict(f, tag=_filing_tag(f), verified=True, summary=f.get('summary') or _describe(f))
        for f in filings or []
    ]


def overall_tag(tags: Iterable[str]) -> str:
    """Whole-ticker tag: whichever of 호재/악재 is more frequent, 중립 on a tie or no tags"""
    tags = list(tags)
    pos, neg = tags.count(BULLISH), tags.count(BEARISH)
    return BULLISH if pos > neg else BEARISH if neg > pos else NEUTRAL
