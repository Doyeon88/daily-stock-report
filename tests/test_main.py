"""
Unit tests for main.py: the exit code must reflect failures so a scheduled run fails visibly,
and a failing optional collector (details, news, filings, comparison) must not stop the report
"""

from unittest.mock import MagicMock

import pytest

import main
from notifications import fcm_notifier, report_publisher
from processors import reddit_history
from scrapers import (
    competitor_scraper, news_scraper, reddit_mentions, sec_filings, stock_details, yfinance_scraper
)

OPTIONAL_COLLECTORS = (
    (stock_details, 'fetch_stock_details', {}),
    (news_scraper, 'fetch_news', {}),
    (sec_filings, 'fetch_sec_filings', {}),
    (reddit_mentions, 'fetch_reddit_mentions', {}),
    (reddit_history, 'update_history', {}),
    (competitor_scraper, 'compare_stocks', {'peers': {}, 'market': []}),
)


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


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    """No test in this file may touch the network: replace every collector and the publisher"""
    for module, name, empty in OPTIONAL_COLLECTORS:
        monkeypatch.setattr(module, name, MagicMock(return_value=empty))
    monkeypatch.setattr(report_publisher, 'publish_report', MagicMock(return_value=None))


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


@pytest.mark.parametrize('module, name', [(m, n) for m, n, _ in OPTIONAL_COLLECTORS])
def test_failing_optional_collector_does_not_stop_the_report(monkeypatch, module, name):
    monkeypatch.setattr(module, name, MagicMock(side_effect=RuntimeError('source down')))
    send_report = MagicMock(return_value=True)
    monkeypatch.setattr(yfinance_scraper, 'fetch_stock_data', MagicMock(return_value={'A': _ok('A')}))
    monkeypatch.setattr(fcm_notifier, 'send_report', send_report)

    main.main()  # must not raise SystemExit

    report = send_report.call_args[0][0]
    assert report['stock_data']['A']['price'] == 10.0


def test_collected_extras_reach_the_report_and_the_published_link(monkeypatch):
    monkeypatch.setattr(stock_details, 'fetch_stock_details', MagicMock(return_value={'A': {'rsi14': 25.0}}))
    monkeypatch.setattr(news_scraper, 'fetch_news', MagicMock(return_value={'A': [{'title': 'Headline'}]}))
    monkeypatch.setattr(reddit_mentions, 'fetch_reddit_mentions', MagicMock(return_value={'A': None}))
    monkeypatch.setattr(reddit_history, 'update_history', MagicMock(return_value={'A': {'daily': [], 'weekly': []}}))
    monkeypatch.setattr(
        report_publisher, 'publish_report', MagicMock(return_value='https://raw.example/report.json')
    )
    send_report = MagicMock(return_value=True)
    monkeypatch.setattr(yfinance_scraper, 'fetch_stock_data', MagicMock(return_value={'A': _ok('A')}))
    monkeypatch.setattr(fcm_notifier, 'send_report', send_report)

    main.main()

    report = send_report.call_args[0][0]
    assert report['news'] == {'A': [{'title': 'Headline'}]}
    assert report['reddit'] == {'A': None}
    assert report['reddit_history'] == {'A': {'daily': [], 'weekly': []}}
    assert 'A RSI 25 과매도' in report['flags']
    assert report['data_url'] == 'https://raw.example/report.json'
