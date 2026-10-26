"""
Unit tests for main.py: the exit code must reflect failures so a scheduled run fails visibly
"""

from unittest.mock import MagicMock

import pytest

import main
from notifications import fcm_notifier
from scrapers import yfinance_scraper


def _ok(ticker):
    return {
        'ticker': ticker, 'price': 10.0, 'previous_close': 9.0, 'change': 1.0,
        'change_percent': 11.11, 'volume': 100, 'error': None,
    }


def _failed(ticker):
    return {
        'ticker': ticker, 'price': None, 'previous_close': None, 'change': None,
        'change_percent': None, 'volume': None, 'error': 'network error',
    }


def _run_main(monkeypatch, stock_data, notified, fcm_enabled=True):
    monkeypatch.setattr(yfinance_scraper, 'fetch_stock_data', MagicMock(return_value=stock_data))
    monkeypatch.setattr(fcm_notifier, 'send_report', MagicMock(return_value=notified))
    monkeypatch.setattr(main, 'ENABLE_FCM_NOTIFICATION', fcm_enabled)
    main.main()


def _assert_exits_with_failure(monkeypatch, **kwargs):
    with pytest.raises(SystemExit) as exc_info:
        _run_main(monkeypatch, **kwargs)
    assert exc_info.value.code == 1


def test_success_does_not_exit(monkeypatch):
    _run_main(monkeypatch, {'A': _ok('A'), 'B': _ok('B')}, notified=True)


def test_partial_data_failure_still_succeeds(monkeypatch):
    _run_main(monkeypatch, {'A': _ok('A'), 'B': _failed('B')}, notified=True)


def test_all_stock_data_failed_exits_with_error(monkeypatch):
    _assert_exits_with_failure(
        monkeypatch, stock_data={'A': _failed('A'), 'B': _failed('B')}, notified=True
    )


def test_undelivered_notification_exits_with_error(monkeypatch):
    _assert_exits_with_failure(monkeypatch, stock_data={'A': _ok('A')}, notified=False)


def test_disabled_fcm_is_not_a_failure(monkeypatch):
    _run_main(monkeypatch, {'A': _ok('A')}, notified=False, fcm_enabled=False)


def test_unexpected_exception_exits_with_error(monkeypatch):
    monkeypatch.setattr(
        yfinance_scraper, 'fetch_stock_data', MagicMock(side_effect=RuntimeError('boom'))
    )
    with pytest.raises(SystemExit) as exc_info:
        main.main()
    assert exc_info.value.code == 1
