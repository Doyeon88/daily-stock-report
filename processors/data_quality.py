"""
종목별 데이터 수집 상태: 어떤 항목이 비었는지 표시해, AI 의견·요약이 빈약한 자료에 기대고 있는지 알 수 있게 합니다.
"""

from typing import Dict, List

# (리포트 키, 화면 이름). 공시와 내부자 거래는 '최근에 없음'도 정상 결과라서 키가 있으면 수집된 것으로 본다.
SECTIONS = (
    ('details', '가격 지표'), ('news', '기사'), ('filings', '공시'), ('analyst', '애널리스트'),
    ('earnings_history', '실적 이력'), ('insiders', '내부자 거래'), ('dilution', '희석 점검'),
    ('options', '옵션'), ('signals', '기술적 신호'),
)
PRESENCE_ONLY = {'filings', 'insiders'}


def build_data_quality(tickers: List[str], sources: Dict[str, Dict]) -> Dict[str, Dict]:
    """
    Args:
        tickers: watchlist symbols
        sources: report key -> {ticker: data} (keys missing from sources count as not collected)

    Returns:
        ticker -> {'missing': [screen names], 'collected': int, 'total': int}
    """
    results = {}
    for ticker in tickers:
        missing = []
        for key, label in SECTIONS:
            source = sources.get(key) or {}
            present = ticker in source and (key in PRESENCE_ONLY or bool(source[ticker]))
            if not present:
                missing.append(label)
        results[ticker] = {'missing': missing, 'collected': len(SECTIONS) - len(missing), 'total': len(SECTIONS)}
    return results
