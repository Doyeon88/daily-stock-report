"""
포트폴리오 연동: 보유 수량·평단과 현재가로 손익과 비중을 계산합니다.
"""

from typing import Dict, Optional


def compute_portfolio(portfolio: Dict, stock_data: Dict[str, Dict], quotes: Optional[Dict] = None) -> Optional[Dict]:
    """
    Args:
        portfolio: {'holdings': [{'symbol', 'shares', 'avg_cost'}], 'cash': 0}
        stock_data: price data per tracked ticker (scrapers.yfinance_scraper)

    Returns:
        {'positions': [...], 'total_value', 'total_cost', 'total_pnl', 'total_pnl_pct', 'day_pnl'} or None
        Holdings without a price are listed with price None and left out of the totals.
    """
    holdings = (portfolio or {}).get('holdings') or []
    if not holdings:
        return None

    positions, value_sum, cost_sum, day_sum = [], 0.0, 0.0, 0.0
    for h in holdings:
        symbol, shares, cost = h.get('symbol'), h.get('shares'), h.get('avg_cost')
        if not symbol or not shares:
            continue
        quote = stock_data.get(symbol) or {}
        price, prev = quote.get('price'), quote.get('previous_close')
        pos = {'symbol': symbol, 'shares': shares, 'avg_cost': cost, 'price': price,
               'value': None, 'pnl': None, 'pnl_pct': None, 'day_pnl': None, 'weight_pct': None}
        if price is not None and quote.get('error') is None:
            pos['value'] = round(price * shares, 2)
            value_sum += pos['value']
            if cost:
                pos['pnl'] = round((price - cost) * shares, 2)
                pos['pnl_pct'] = round((price / cost - 1) * 100, 2)
                cost_sum += cost * shares
            if prev is not None:
                pos['day_pnl'] = round((price - prev) * shares, 2)
                day_sum += pos['day_pnl']
        positions.append(pos)

    if not positions:
        return None
    for pos in positions:
        if pos['value'] is not None and value_sum:
            pos['weight_pct'] = round(pos['value'] / value_sum * 100, 1)

    priced_cost = sum(p['avg_cost'] * p['shares'] for p in positions if p['pnl'] is not None)
    total_pnl = round(sum(p['pnl'] for p in positions if p['pnl'] is not None), 2)
    return {
        'positions': positions,
        'total_value': round(value_sum, 2),
        'total_cost': round(priced_cost, 2),
        'total_pnl': total_pnl,
        'total_pnl_pct': round(total_pnl / priced_cost * 100, 2) if priced_cost else None,
        'day_pnl': round(day_sum, 2),
        'day_pnl_pct': round(day_sum / (value_sum - day_sum) * 100, 2) if value_sum - day_sum else None,
    }


def public_view(result: Optional[Dict], include_amounts: bool = False) -> Optional[Dict]:
    """
    Version safe to publish in the (public) report repo: %s and weights only, unless amounts are allowed.
    """
    if not result:
        return None
    keep = ('symbol', 'pnl_pct', 'weight_pct')
    if include_amounts:
        return result
    return {
        'positions': [{k: p[k] for k in keep} for p in result['positions']],
        'total_pnl_pct': result['total_pnl_pct'],
        'day_pnl_pct': result['day_pnl_pct'],
    }
