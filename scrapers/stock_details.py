"""
Extra per-ticker details from Yahoo Finance (no API key needed)

Volume vs average, 52-week range, moving averages, short interest, analyst targets,
after-hours move, next earnings date and technical indicators (RSI, period returns).
Each section is fetched on its own, so one failing section does not drop the others.
"""

import logging
from datetime import date, datetime
from typing import Dict, List, Optional

import pytz
import yfinance as yf

from config import TIMEZONE
from scrapers.retry import call_with_retry

logger = logging.getLogger(__name__)

RSI_PERIOD = 14


def _percent_change(value: Optional[float], base: Optional[float]) -> Optional[float]:
    if value is None or not base:
        return None
    return round((value / base - 1) * 100, 2)


def info_section(info: Dict, price: Optional[float], volume: Optional[int]) -> Dict:
    """
    Details that come from the Yahoo Finance `info` dictionary

    Args:
        info: yfinance Ticker.info
        price: Latest price from the price scraper (falls back to info's regular market price)
        volume: Latest volume from the price scraper

    Returns:
        dict: Details; values Yahoo does not provide are None
    """
    if price is None:
        price = info.get('regularMarketPrice')

    # The after-hours quote only counts if it is newer than the last regular session,
    # otherwise it is a leftover from the previous day
    post_price = info.get('postMarketPrice')
    post_time, regular_time = info.get('postMarketTime'), info.get('regularMarketTime')
    after_hours_valid = bool(post_price and post_time and regular_time and post_time > regular_time)

    year_high, year_low = info.get('fiftyTwoWeekHigh'), info.get('fiftyTwoWeekLow')
    range_position = None
    if price is not None and year_high is not None and year_low is not None and year_high > year_low:
        range_position = round((price - year_low) / (year_high - year_low) * 100, 1)

    average_volume = info.get('averageVolume10days')
    short_percent = info.get('shortPercentOfFloat')
    short_date = info.get('dateShortInterest')
    target = info.get('targetMeanPrice')
    ma50, ma200 = info.get('fiftyDayAverage'), info.get('twoHundredDayAverage')

    return {
        'market_cap': info.get('marketCap'),
        'volume_ratio': round(volume / average_volume, 2) if volume and average_volume else None,
        'year_high': year_high,
        'year_low': year_low,
        'range_position': range_position,
        'ma50': ma50,
        'ma200': ma200,
        'vs_ma50': _percent_change(price, ma50),
        'vs_ma200': _percent_change(price, ma200),
        'short_percent_float': round(short_percent * 100, 1) if short_percent is not None else None,
        'short_ratio': info.get('shortRatio'),
        'short_as_of': (
            datetime.fromtimestamp(short_date, tz=pytz.utc).date().isoformat() if short_date else None
        ),
        'target_mean': target,
        'upside': _percent_change(target, price),
        'analyst_count': info.get('numberOfAnalystOpinions'),
        'recommendation': info.get('recommendationKey'),
        'after_hours_price': post_price if after_hours_valid else None,
        'after_hours_change': _percent_change(post_price, price) if after_hours_valid else None,
    }


def technical_section(closes) -> Dict:
    """
    RSI (Wilder, 14 days) and 5/20-day returns from daily closing prices

    Args:
        closes: pandas Series of daily closes without NaN, oldest first

    Returns:
        dict: rsi14, return_5d, return_20d
    """
    if len(closes) < RSI_PERIOD + 1:
        raise ValueError(f"need at least {RSI_PERIOD + 1} daily closes, got {len(closes)}")

    delta = closes.diff()
    avg_gain = delta.clip(lower=0).ewm(alpha=1 / RSI_PERIOD, adjust=False).mean()
    avg_loss = (-delta.clip(upper=0)).ewm(alpha=1 / RSI_PERIOD, adjust=False).mean()
    last_gain, last_loss = float(avg_gain.iloc[-1]), float(avg_loss.iloc[-1])
    rsi = 100.0 if last_loss == 0 else 100 - 100 / (1 + last_gain / last_loss)

    def period_return(days: int) -> Optional[float]:
        if len(closes) <= days:
            return None
        return _percent_change(float(closes.iloc[-1]), float(closes.iloc[-1 - days]))

    return {'rsi14': round(rsi, 1), 'return_5d': period_return(5), 'return_20d': period_return(20)}


def earnings_section(calendar: Optional[Dict], today: date) -> Dict:
    """
    Next earnings date that is today or later (Yahoo sometimes still lists the last one)

    Args:
        calendar: yfinance Ticker.calendar
        today: Reference date

    Returns:
        dict: earnings_date (ISO) and days_to_earnings, both None if nothing is upcoming
    """
    dates = [d.date() if isinstance(d, datetime) else d for d in (calendar or {}).get('Earnings Date') or []]
    upcoming = sorted(d for d in dates if d >= today)
    if not upcoming:
        return {'earnings_date': None, 'days_to_earnings': None}
    return {'earnings_date': upcoming[0].isoformat(), 'days_to_earnings': (upcoming[0] - today).days}


def _daily_closes(stock):
    # The newest bar can be unfinished (NaN close), so drop NaN before computing anything
    return stock.history(period='6mo', interval='1d')['Close'].dropna()


def fetch_stock_details(
    tickers: List[str], stock_data: Dict[str, Dict], today: Optional[date] = None
) -> Dict[str, Dict]:
    """
    Fetch the extra details for each ticker

    Args:
        tickers: Stock ticker symbols
        stock_data: Result of yfinance_scraper.fetch_stock_data (price and volume are reused)
        today: Reference date for the earnings countdown (defaults to today in TIMEZONE)

    Returns:
        dict: ticker -> details (empty dict if every section failed)
    """
    today = today or datetime.now(pytz.timezone(TIMEZONE)).date()
    logger.info(f"Fetching stock details for {len(tickers)} ticker(s): {tickers}")

    results = {}
    for ticker in tickers:
        stock = yf.Ticker(ticker)
        quote = stock_data.get(ticker) or {}
        sections = (
            ('info', lambda: info_section(
                call_with_retry(lambda: stock.info, f"{ticker} info"), quote.get('price'), quote.get('volume'))),
            ('technicals', lambda: technical_section(
                call_with_retry(lambda: _daily_closes(stock), f"{ticker} price history"))),
            ('earnings', lambda: earnings_section(
                call_with_retry(lambda: stock.calendar, f"{ticker} calendar"), today)),
        )

        details = {}
        for name, build in sections:
            try:
                details.update(build())
            except Exception as e:
                logger.error(f"{ticker}: {name} details unavailable: {e}")
        results[ticker] = details

    return results
