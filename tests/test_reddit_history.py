"""
Unit tests for processors/reddit_history.py
"""

from datetime import date, timedelta
from unittest.mock import MagicMock

import pytest

from notifications import history_store
from processors import reddit_history

TODAY = date(2026, 10, 27)   # a Tuesday


def _mention(rank, mentions=10, upvotes=40):
    return {'rank': rank, 'mentions': mentions, 'upvotes': upvotes, 'rank_24h_ago': rank, 'mentions_24h_ago': mentions}


# ---------- record_snapshot ----------

def test_snapshot_is_added_and_an_unranked_ticker_is_stored_as_no_rank_and_zero():
    result = reddit_history.record_snapshot({}, {'BE': _mention(32, 16, 51), 'BWXT': None}, TODAY)

    assert result == {'BE': {'2026-10-27': [32, 16, 51]}, 'BWXT': {'2026-10-27': [None, 0, 0]}}


def test_a_second_snapshot_of_the_same_day_replaces_the_first():
    first = reddit_history.record_snapshot({}, {'BE': _mention(32, 16, 51)}, TODAY)

    result = reddit_history.record_snapshot(first, {'BE': _mention(30, 20, 60)}, TODAY)

    assert result['BE'] == {'2026-10-27': [30, 20, 60]}


def test_a_ticker_that_is_missing_today_is_skipped_not_recorded_as_unranked():
    history = {'BE': {'2026-10-26': [32, 16, 51]}}

    result = reddit_history.record_snapshot(history, {}, TODAY)

    assert result == history


def test_the_stored_history_is_not_modified():
    history = {'BE': {'2026-10-26': [32, 16, 51]}}

    reddit_history.record_snapshot(history, {'BE': _mention(30)}, TODAY)

    assert history == {'BE': {'2026-10-26': [32, 16, 51]}}


def test_snapshots_older_than_a_little_over_a_year_are_dropped():
    keep = (TODAY - timedelta(days=reddit_history.KEEP_DAYS)).isoformat()
    drop = (TODAY - timedelta(days=reddit_history.KEEP_DAYS + 1)).isoformat()
    history = {'BE': {keep: [10, 1, 1], drop: [10, 1, 1]}}

    result = reddit_history.record_snapshot(history, {'BE': _mention(30)}, TODAY)

    assert keep in result['BE'] and drop not in result['BE']


# ---------- daily_series ----------

def test_daily_series_covers_the_last_92_days_oldest_first():
    first = (TODAY - timedelta(days=91)).isoformat()      # the 92nd day back: still inside
    outside = (TODAY - timedelta(days=92)).isoformat()
    days = {TODAY.isoformat(): [32, 16, 51], first: [40, 5, 9], outside: [50, 1, 1]}

    rows = reddit_history.daily_series(days, TODAY)

    assert rows == [[first, 40, 5, 9], [TODAY.isoformat(), 32, 16, 51]]


# ---------- weekly_series ----------

def test_weekly_series_averages_the_recorded_days_of_a_week_starting_on_monday():
    days = {
        '2026-10-20': [30, 10, 40],      # Tue \
        '2026-10-24': [None, 0, 0],      # Sat  } the week that starts Monday 2026-10-19
        '2026-10-25': [34, 14, 44],      # Sun /   (Sunday belongs to the week before the coming Monday)
        '2026-10-26': [32, 16, 51],      # Mon: the next week
    }

    rows = reddit_history.weekly_series(days, TODAY)

    assert rows == [
        ['2026-10-19', 32.0, 8.0, 28.0, 3],   # ranks 30 and 34 (the unranked day has no rank), mentions (10+0+14)/3
        ['2026-10-26', 32.0, 16.0, 51.0, 1],
    ]


def test_a_week_in_which_the_ticker_was_never_ranked_has_no_average_rank():
    days = {'2026-10-20': [None, 0, 0], '2026-10-21': [None, 0, 0]}

    assert reddit_history.weekly_series(days, TODAY) == [['2026-10-19', None, 0.0, 0.0, 2]]


def test_weekly_series_covers_the_last_52_weeks():
    this_monday = TODAY - timedelta(days=TODAY.weekday())
    oldest_inside = (this_monday - timedelta(weeks=51)).isoformat()
    just_outside = (this_monday - timedelta(weeks=52)).isoformat()
    days = {oldest_inside: [10, 1, 1], just_outside: [10, 1, 1]}

    rows = reddit_history.weekly_series(days, TODAY)

    assert [row[0] for row in rows] == [oldest_inside]


# ---------- build_report_history ----------

def test_report_history_has_both_series_and_the_collection_start():
    history = {'BE': {'2026-10-20': [30, 10, 40], '2026-10-27': [32, 16, 51]}, 'EMPTY': {}}

    report = reddit_history.build_report_history(history, TODAY)

    assert list(report) == ['BE']                       # a ticker without any record is left out
    assert report['BE']['first_date'] == '2026-10-20' and report['BE']['days'] == 2
    assert [row[0] for row in report['BE']['daily']] == ['2026-10-20', '2026-10-27']
    assert [row[0] for row in report['BE']['weekly']] == ['2026-10-19', '2026-10-26']


# ---------- update_history ----------

@pytest.fixture
def store(monkeypatch):
    """A fake history store: store.stored / store.sha / store.readable, and the calls it received"""
    state = MagicMock()
    state.stored, state.sha, state.readable = {'BE': {'2026-10-26': [32, 16, 51]}}, 'sha1', True
    state.save_results = [history_store.SAVED]
    state.saved = []
    state.loads = 0

    def load():
        state.loads += 1
        return state.stored, state.sha, state.readable

    def save(history, sha, day):
        state.saved.append((history, sha, day))
        return state.save_results.pop(0) if state.save_results else history_store.SAVED

    monkeypatch.setattr(history_store, 'load_history', load)
    monkeypatch.setattr(history_store, 'save_history', save)
    return state


def test_update_records_today_saves_it_and_returns_the_series(store):
    series = reddit_history.update_history({'BE': _mention(30, 20, 60)}, TODAY)

    history, sha, day = store.saved[0]
    assert history['BE'] == {'2026-10-26': [32, 16, 51], '2026-10-27': [30, 20, 60]}
    assert sha == 'sha1' and day == TODAY
    assert [row[0] for row in series['BE']['daily']] == ['2026-10-26', '2026-10-27']


def test_update_does_not_write_when_nothing_changed(store):
    store.stored = {'BE': {'2026-10-27': [30, 20, 60]}}

    reddit_history.update_history({'BE': _mention(30, 20, 60)}, TODAY)

    assert store.saved == []


def test_update_never_writes_when_the_history_could_not_be_read(store):
    store.stored, store.sha, store.readable = {}, None, False

    series = reddit_history.update_history({'BE': _mention(30, 20, 60)}, TODAY)

    assert store.saved == []                            # writing would replace a year of history with one day
    assert series['BE']['days'] == 1                    # the report still gets today's point


def test_update_reads_again_and_retries_once_after_a_conflict(store):
    store.save_results = [history_store.CONFLICT, history_store.SAVED]

    reddit_history.update_history({'BE': _mention(30, 20, 60)}, TODAY)

    assert store.loads == 2 and len(store.saved) == 2


def test_update_gives_up_quietly_after_two_conflicts(store):
    store.save_results = [history_store.CONFLICT, history_store.CONFLICT]

    series = reddit_history.update_history({'BE': _mention(30, 20, 60)}, TODAY)

    assert len(store.saved) == 2 and 'BE' in series


# ---------- record_missing_snapshot ----------

@pytest.fixture
def fetch(monkeypatch):
    from scrapers import reddit_mentions
    mock = MagicMock(return_value={'BWXT': None})
    monkeypatch.setattr(reddit_mentions, 'fetch_reddit_mentions', mock)
    return mock


def test_nothing_is_fetched_or_written_when_every_ticker_already_has_today(store, fetch):
    store.stored = {'BE': {'2026-10-27': [30, 20, 60]}, 'BWXT': {'2026-10-27': [None, 0, 0]}}

    assert reddit_history.record_missing_snapshot(['BE', 'BWXT'], TODAY) is True
    fetch.assert_not_called()
    assert store.saved == []


def test_only_the_missing_tickers_are_fetched_and_existing_snapshots_are_kept(store, fetch):
    store.stored = {'BE': {'2026-10-27': [30, 20, 60]}}
    fetch.return_value = {'BWXT': None, 'BE': _mention(1, 99, 99)}   # BE was not asked for: must be ignored

    assert reddit_history.record_missing_snapshot(['BE', 'BWXT'], TODAY) is True

    fetch.assert_called_once_with(['BWXT'])
    history = store.saved[0][0]
    assert history['BE']['2026-10-27'] == [30, 20, 60]            # not replaced
    assert history['BWXT']['2026-10-27'] == [None, 0, 0]


def test_not_recorded_when_the_ranking_could_not_be_read(store, fetch):
    fetch.return_value = {}

    assert reddit_history.record_missing_snapshot(['BWXT'], TODAY) is False
    assert store.saved == []


def test_not_recorded_when_the_stored_history_could_not_be_read(store, fetch):
    store.readable = False

    assert reddit_history.record_missing_snapshot(['BWXT'], TODAY) is False
    fetch.assert_not_called()
    assert store.saved == []


def test_not_recorded_when_saving_fails(store, fetch):
    store.save_results = [history_store.FAILED]

    assert reddit_history.record_missing_snapshot(['BWXT'], TODAY) is False


def test_a_conflict_is_retried_once(store, fetch):
    store.save_results = [history_store.CONFLICT, history_store.SAVED]

    assert reddit_history.record_missing_snapshot(['BWXT'], TODAY) is True
    assert store.loads == 2
