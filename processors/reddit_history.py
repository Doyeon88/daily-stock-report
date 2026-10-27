"""
Reddit mention history: one snapshot per day, kept for a year, and the two series the report page plots

ApeWisdom cannot give the past (its ticker page only holds about 17 hours), so the history starts with the
first run that records it. Each run adds that day's rank, mentions and upvotes per ticker; the report page
draws two views per ticker: the last 3 months day by day and the last 52 weeks week by week.
"""

import logging
from datetime import date, datetime, timedelta
from statistics import mean
from typing import Dict, List, Optional

import pytz

from config import TIMEZONE
from notifications import history_store

logger = logging.getLogger(__name__)

KEEP_DAYS = 400            # a little over a year of snapshots
DAILY_WINDOW_DAYS = 92     # "3 months"
WEEKLY_WINDOW_WEEKS = 52   # "1 year"

# ticker -> {'YYYY-MM-DD': [rank or None, mentions, upvotes]}
History = Dict[str, Dict[str, List]]


def record_snapshot(history: Optional[History], reddit: Optional[Dict], day: date) -> History:
    """
    Add one day's snapshot (replacing an earlier snapshot of the same day) and drop what is too old

    Args:
        history: Stored history (not modified)
        reddit: ticker -> mentions from scrapers.reddit_mentions; None means "not ranked" (stored as no rank,
                0 mentions, 0 upvotes), a ticker that is missing means "unknown today" and is skipped
        day: The date of the snapshot

    Returns:
        dict: The new history
    """
    merged = {ticker: dict(days) for ticker, days in (history or {}).items()}
    for ticker, info in (reddit or {}).items():
        merged.setdefault(ticker, {})[day.isoformat()] = (
            [None, 0, 0] if info is None else [info['rank'], info['mentions'], info['upvotes']]
        )

    cutoff = (day - timedelta(days=KEEP_DAYS)).isoformat()
    for days in merged.values():
        for key in [key for key in days if key < cutoff]:
            del days[key]
    return merged


def daily_series(days: Dict[str, List], today: date) -> List[List]:
    """The recorded days of the last DAILY_WINDOW_DAYS days: [date, rank, mentions, upvotes], oldest first"""
    start = (today - timedelta(days=DAILY_WINDOW_DAYS - 1)).isoformat()
    return [[key, *days[key]] for key in sorted(days) if key >= start]


def weekly_series(days: Dict[str, List], today: date) -> List[List]:
    """
    Week by week (weeks start on Monday) for the last WEEKLY_WINDOW_WEEKS weeks

    Returns:
        list: [week start, average rank or None, average mentions, average upvotes, recorded days], oldest first.
              Averages are over the days that were recorded, since the daily run skips Sunday and Monday.
    """
    this_week = today - timedelta(days=today.weekday())
    start = (this_week - timedelta(weeks=WEEKLY_WINDOW_WEEKS - 1)).isoformat()

    weeks: Dict[str, List[List]] = {}
    for key, values in days.items():
        day = date.fromisoformat(key)
        week_start = (day - timedelta(days=day.weekday())).isoformat()
        if week_start >= start:
            weeks.setdefault(week_start, []).append(values)

    rows = []
    for week_start in sorted(weeks):
        entries = weeks[week_start]
        ranks = [entry[0] for entry in entries if entry[0] is not None]
        rows.append([
            week_start,
            round(mean(ranks), 1) if ranks else None,
            round(mean(entry[1] for entry in entries), 1),
            round(mean(entry[2] for entry in entries), 1),
            len(entries),
        ])
    return rows


def build_report_history(history: History, today: date) -> Dict[str, Dict]:
    """ticker -> {'daily': [...], 'weekly': [...], 'first_date': first recorded day, 'days': recorded days}"""
    report = {}
    for ticker, days in history.items():
        if days:
            report[ticker] = {
                'daily': daily_series(days, today),
                'weekly': weekly_series(days, today),
                'first_date': min(days),
                'days': len(days),
            }
    return report


def update_history(reddit: Dict, today: Optional[date] = None) -> Dict[str, Dict]:
    """
    Record today's snapshot in the stored history and return the series for the report

    The stored file is only written back when it was read successfully (or does not exist yet): after a failed
    read, writing would replace a year of history with a single day. Without GitHub credentials (a local run)
    nothing is read or written and the series hold only today.

    Args:
        reddit: ticker -> mentions from scrapers.reddit_mentions
        today: Reference date (defaults to today in TIMEZONE)

    Returns:
        dict: See build_report_history
    """
    today = today or datetime.now(pytz.timezone(TIMEZONE)).date()

    merged: History = {}
    for attempt in (1, 2):   # a second try covers another run writing the file in between
        stored, sha, readable = history_store.load_history()
        merged = record_snapshot(stored, reddit, today)
        if not readable or merged == stored:   # nothing to write: unreadable, or the same values again
            break
        if history_store.save_history(merged, sha, today) != history_store.CONFLICT:
            break
        logger.warning("Reddit history was changed by another run, reading it again")

    return build_report_history(merged, today)


def record_missing_snapshot(tickers: List[str], today: Optional[date] = None) -> bool:
    """
    Record today's snapshot for the tickers that do not have one yet (used by the daily snapshot-only run)

    The report run (Tuesday to Saturday) records its own snapshot first, so on those days this does nothing,
    not even a request to ApeWisdom; on Sunday and Monday it fills the gap. An existing snapshot is never
    replaced here.

    Args:
        tickers: Stock ticker symbols
        today: Reference date (defaults to today in TIMEZONE)

    Returns:
        bool: True if today has a snapshot for every ticker afterwards (recorded now or already there)
    """
    from scrapers import reddit_mentions   # only this entry point needs the scraper

    today = today or datetime.now(pytz.timezone(TIMEZONE)).date()
    key = today.isoformat()

    for attempt in (1, 2):
        stored, sha, readable = history_store.load_history()
        if not readable:
            logger.error("Reddit snapshot not recorded: the stored history could not be read")
            return False

        missing = [ticker for ticker in tickers if key not in stored.get(ticker, {})]
        if not missing:
            logger.info("Today's Reddit snapshot is already recorded")
            return True

        fetched = {t: v for t, v in reddit_mentions.fetch_reddit_mentions(missing).items() if t in missing}
        if not fetched:
            logger.error("Reddit snapshot not recorded: the ranking could not be read")
            return False

        result = history_store.save_history(record_snapshot(stored, fetched, today), sha, today)
        if result == history_store.SAVED:
            logger.info(f"Recorded today's Reddit snapshot for {sorted(fetched)}")
            return True
        if result != history_store.CONFLICT:
            return False
        logger.warning("Reddit history was changed by another run, reading it again")

    return False
