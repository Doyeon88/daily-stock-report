"""
사용자 시나리오 EPS 대비 밸류에이션 (모든 값은 사용자가 넣은 가정에서 계산한 '제 추정'입니다)
"""

from typing import Dict, List, Optional


def scenario_valuation(
    price: Optional[float], scenario_eps: Dict[str, float], multiples: List[float]
) -> Optional[Dict]:
    """
    Args:
        price: Current price
        scenario_eps: {'2027': 0.65, ...} user EPS scenario
        multiples: P/E multiples to price the scenario at, e.g. [20, 30, 40]

    Returns:
        {'rows': [{'year', 'eps', 'forward_pe', 'targets': {'20': price, ...}}]} or None without inputs
    """
    if not price or not scenario_eps:
        return None
    rows = []
    for year in sorted(scenario_eps):
        eps = scenario_eps[year]
        if not eps or eps <= 0:
            continue
        rows.append({
            'year': str(year),
            'eps': eps,
            'forward_pe': round(price / eps, 1),
            'targets': {str(m): round(eps * m, 2) for m in multiples},
        })
    return {'rows': rows} if rows else None
