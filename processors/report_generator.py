"""
Report generator
Builds a human-readable report from collected stock data
"""

import logging
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional

import pytz

from config import TIMEZONE

logger = logging.getLogger(__name__)

# Thresholds that turn a detail into a short "signal" line in the notification
AFTER_HOURS_MOVE = 3.0       # % move after the close
VOLUME_SURGE = 1.5           # x the 10-day average volume
RSI_OVERSOLD = 30
RSI_OVERBOUGHT = 70
NEAR_RANGE_EDGE = 5          # % of the 52-week range counted as "near the high/low"
EARNINGS_SOON_DAYS = 7
SHORT_INTEREST_HIGH = 15.0   # % of float
FILING_RECENT_DAYS = 3       # 8-K filings newer than this are flagged
REDDIT_MIN_MENTIONS = 10     # fewer Reddit mentions than this is noise, never a surge
REDDIT_SURGE_RATIO = 2.0     # x the mentions 24 hours earlier


def build_flags(
    stock_data: Dict[str, Dict],
    details: Dict[str, Dict],
    filings: Dict[str, Dict],
    today: Optional[date] = None,
    reddit: Optional[Dict[str, Optional[Dict]]] = None,
) -> List[str]:
    """
    Pick out what is unusual today, as short one-line signals

    Args:
        stock_data: ticker -> price data (order decides the order of the signals)
        details: ticker -> details from scrapers.stock_details
        filings: ticker -> filings from scrapers.sec_filings
        today: Reference date (defaults to today in TIMEZONE)
        reddit: ticker -> Reddit mentions from scrapers.reddit_mentions (None for unranked tickers)

    Returns:
        list: Signal lines such as "BE RSI 23 과매도"
    """
    today = today or datetime.now(pytz.timezone(TIMEZONE)).date()
    filing_cutoff = (today - timedelta(days=FILING_RECENT_DAYS)).isoformat()

    flags = []
    for ticker in stock_data:
        d = details.get(ticker) or {}

        after_hours = d.get('after_hours_change')
        if after_hours is not None and abs(after_hours) >= AFTER_HOURS_MOVE:
            flags.append(f"{ticker} 시간외 {after_hours:+.1f}%")

        volume_ratio = d.get('volume_ratio')
        if volume_ratio is not None and volume_ratio >= VOLUME_SURGE:
            flags.append(f"{ticker} 거래량 {volume_ratio:.1f}배")

        rsi = d.get('rsi14')
        if rsi is not None and rsi <= RSI_OVERSOLD:
            flags.append(f"{ticker} RSI {rsi:.0f} 과매도")
        elif rsi is not None and rsi >= RSI_OVERBOUGHT:
            flags.append(f"{ticker} RSI {rsi:.0f} 과열")

        position = d.get('range_position')
        if position is not None and position >= 100 - NEAR_RANGE_EDGE:
            flags.append(f"{ticker} 52주 고점 근처")
        elif position is not None and position <= NEAR_RANGE_EDGE:
            flags.append(f"{ticker} 52주 저점 근처")

        days_to_earnings = d.get('days_to_earnings')
        if days_to_earnings is not None and 0 <= days_to_earnings <= EARNINGS_SOON_DAYS:
            countdown = '오늘' if days_to_earnings == 0 else f"D-{days_to_earnings}"
            flags.append(f"{ticker} 실적 발표 {d['earnings_date'][5:]} ({countdown})")

        short_interest = d.get('short_percent_float')
        if short_interest is not None and short_interest >= SHORT_INTEREST_HIGH:
            flags.append(f"{ticker} 공매도 {short_interest:.0f}%")

        recent_8k = [
            f for f in (filings.get(ticker) or {}).get('filings', [])
            if f['form'] == '8-K' and f['date'] >= filing_cutoff
        ]
        if recent_8k:
            flags.append(f"{ticker} 8-K {recent_8k[0]['date'][5:]} {recent_8k[0]['label']}".rstrip())

        mentions = (reddit or {}).get(ticker)
        if mentions and mentions['mentions'] >= max(REDDIT_MIN_MENTIONS, REDDIT_SURGE_RATIO * mentions['mentions_24h_ago']):
            flags.append(
                f"{ticker} 레딧 언급 급증 ({mentions['mentions']}회, 24시간 전 {mentions['mentions_24h_ago']}회)"
            )

    return flags


def generate_report(
    stock_data: Dict[str, Dict],
    details: Optional[Dict[str, Dict]] = None,
    news: Optional[Dict[str, List[Dict]]] = None,
    filings: Optional[Dict[str, Dict]] = None,
    comparison: Optional[Dict] = None,
    reddit: Optional[Dict[str, Optional[Dict]]] = None,
) -> Dict:
    """
    Generate a report dictionary from collected stock data

    Args:
        stock_data: Mapping of ticker -> stock data (from yfinance_scraper.fetch_stock_data)
        details: ticker -> extra details (scrapers.stock_details), optional
        news: ticker -> headlines (scrapers.news_scraper), optional
        filings: ticker -> SEC filings (scrapers.sec_filings), optional
        comparison: competitor and market changes (scrapers.competitor_scraper), optional
        reddit: ticker -> Reddit mentions (scrapers.reddit_mentions), optional

    Returns:
        dict: Report data compatible with notifications.fcm_notifier.send_report
              (and the underlying send_report_notification), containing 'title',
              'summary', 'insights', 'flags', 'timestamp' and 'stocks_count', plus the
              optional data passed in ('details', 'news', 'filings', 'comparison', 'reddit')
    """
    # Timezone-aware: the GitHub Actions runner clock is UTC, not the configured TIMEZONE
    timestamp = datetime.now(pytz.timezone(TIMEZONE)).isoformat()
    details, news, filings, reddit = details or {}, news or {}, filings or {}, reddit or {}
    tickers = list(stock_data.keys())

    valid_entries = {
        ticker: data for ticker, data in stock_data.items() if data.get('error') is None
    }
    failed_tickers = [ticker for ticker in tickers if ticker not in valid_entries]

    insights = []
    for ticker, data in valid_entries.items():
        arrow = '▲' if data['change'] >= 0 else '▼'
        insights.append(
            f"{ticker}: ${data['price']:.2f} {arrow} {data['change_percent']:+.2f}%"
        )

    for ticker in failed_tickers:
        insights.append(f"{ticker}: data unavailable ({stock_data[ticker].get('error')})")

    summary = (
        f"{len(valid_entries)}/{len(tickers)} stocks updated successfully"
        if tickers
        else "No stocks tracked"
    )

    report = {
        'title': '📈 Daily Stock Report',
        'summary': summary,
        'insights': insights,
        'flags': build_flags(stock_data, details, filings, reddit=reddit),
        'timestamp': timestamp,
        'stocks_count': len(tickers),
        'stock_data': stock_data,
        'details': details,
        'news': news,
        'filings': filings,
        'comparison': comparison or {},
        'reddit': reddit,
    }

    logger.info(f"Generated report: {summary}")
    return report
