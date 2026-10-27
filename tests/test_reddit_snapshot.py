"""
Unit tests for reddit_snapshot.py (the daily snapshot-only entry point)
"""

from unittest.mock import MagicMock

import pytest

import reddit_snapshot
from processors import reddit_history


def test_a_recorded_snapshot_ends_normally(monkeypatch):
    record = MagicMock(return_value=True)
    monkeypatch.setattr(reddit_history, 'record_missing_snapshot', record)

    reddit_snapshot.main()

    record.assert_called_once()


def test_a_snapshot_that_could_not_be_recorded_fails_the_run(monkeypatch):
    monkeypatch.setattr(reddit_history, 'record_missing_snapshot', MagicMock(return_value=False))

    with pytest.raises(SystemExit) as exc_info:
        reddit_snapshot.main()

    assert exc_info.value.code == 1
