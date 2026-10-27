"""
Unit tests for notifications/fcm_notifier.py
"""

import base64
import json
from unittest.mock import MagicMock

import pytest

from notifications import fcm_notifier

REPORT_PAGE = 'https://example.github.io/app/report.html'


def _decode_fragment(link):
    fragment = link.split('#', 1)[1]
    return json.loads(base64.urlsafe_b64decode(fragment + '=' * (-len(fragment) % 4)))


@pytest.fixture
def notifier(monkeypatch):
    """An initialized FCMNotifier with Firebase itself mocked out"""
    monkeypatch.setattr(fcm_notifier, 'ENABLE_FCM_NOTIFICATION', True)
    monkeypatch.setattr(fcm_notifier, 'FCM_DEVICE_TOKEN', 'device-token')
    monkeypatch.setattr(fcm_notifier, '_load_credentials', MagicMock())
    monkeypatch.setattr(fcm_notifier.firebase_admin, 'initialize_app', MagicMock())
    monkeypatch.setattr(fcm_notifier.firebase_admin, '_apps', {})
    return fcm_notifier.FCMNotifier()


def _batch_response(success_count, failure_count):
    response = MagicMock()
    response.success_count = success_count
    response.failure_count = failure_count
    response.responses = []
    return response


def test_load_credentials_from_json_content(monkeypatch):
    certificate = MagicMock()
    monkeypatch.setattr(fcm_notifier.credentials, 'Certificate', certificate)

    fcm_notifier._load_credentials('  {"type": "service_account", "project_id": "p"}')

    certificate.assert_called_once_with({'type': 'service_account', 'project_id': 'p'})


def test_load_credentials_from_file_path(monkeypatch):
    certificate = MagicMock()
    monkeypatch.setattr(fcm_notifier.credentials, 'Certificate', certificate)

    fcm_notifier._load_credentials('serviceAccountKey.json')

    certificate.assert_called_once_with('serviceAccountKey.json')


def test_send_uses_send_each_for_multicast(notifier, monkeypatch):
    send_each = MagicMock(return_value=_batch_response(1, 0))
    monkeypatch.setattr(fcm_notifier.messaging, 'send_each_for_multicast', send_each)

    assert notifier.send_notification('title', 'body') is True
    send_each.assert_called_once()


def test_send_returns_false_when_every_delivery_fails(notifier, monkeypatch):
    send_each = MagicMock(return_value=_batch_response(0, 1))
    monkeypatch.setattr(fcm_notifier.messaging, 'send_each_for_multicast', send_each)

    assert notifier.send_notification('title', 'body') is False


def test_send_returns_false_when_not_initialized(monkeypatch):
    monkeypatch.setattr(fcm_notifier, 'ENABLE_FCM_NOTIFICATION', True)
    monkeypatch.setattr(fcm_notifier, 'FCM_DEVICE_TOKEN', None)
    send_each = MagicMock()
    monkeypatch.setattr(fcm_notifier.messaging, 'send_each_for_multicast', send_each)

    assert fcm_notifier.FCMNotifier().send_notification('title', 'body') is False
    send_each.assert_not_called()


def test_report_notification_includes_every_insight(notifier, monkeypatch):
    send_each = MagicMock(return_value=_batch_response(1, 0))
    monkeypatch.setattr(fcm_notifier.messaging, 'send_each_for_multicast', send_each)
    report = {
        'title': 'Daily Stock Report',
        'summary': '4/4 stocks updated successfully',
        'insights': ['BE: $1', 'BWXT: $2', 'CRCL: $3', 'SECZ: $4'],
        'timestamp': '2026-10-26T09:00:00',
        'stocks_count': 4,
    }

    assert notifier.send_report_notification(report) is True

    message = send_each.call_args[0][0]
    for ticker in ('BE', 'BWXT', 'CRCL', 'SECZ'):
        assert ticker in message.notification.body
    assert message.data == {'report_timestamp': '2026-10-26T09:00:00', 'stocks_count': '4'}


def _report_with_stock_data():
    return {
        'title': 'Daily Stock Report',
        'summary': '1/2 stocks updated successfully',
        'insights': ['BE: $10.00', 'BAD: data unavailable'],
        'timestamp': '2026-10-28T09:00:03+09:00',
        'stocks_count': 2,
        'stock_data': {
            'BE': {'price': 10.0, 'previous_close': 9.0, 'change': 1.0,
                   'change_percent': 11.11, 'volume': 1234, 'error': None},
            'BAD': {'price': None, 'previous_close': None, 'change': None,
                    'change_percent': None, 'volume': None, 'error': 'network ' * 30},
        },
    }


def test_report_notification_opens_report_page_on_tap(notifier, monkeypatch):
    monkeypatch.setattr(fcm_notifier, 'REPORT_PAGE_URL', REPORT_PAGE)
    send_each = MagicMock(return_value=_batch_response(1, 0))
    monkeypatch.setattr(fcm_notifier.messaging, 'send_each_for_multicast', send_each)

    assert notifier.send_report_notification(_report_with_stock_data()) is True

    link = send_each.call_args[0][0].webpush.fcm_options.link
    assert link.startswith(REPORT_PAGE + '#')
    payload = _decode_fragment(link)
    assert payload['v'] == 1
    assert payload['t'] == '2026-10-28T09:00:03+09:00'
    assert payload['s'][0] == ['BE', 10.0, 9.0, 1.0, 11.11, 1234, None]
    assert payload['s'][1][0] == 'BAD'
    assert 0 < len(payload['s'][1][6]) <= 80  # long error text is truncated


def test_report_notification_has_no_link_when_page_not_configured(notifier, monkeypatch):
    monkeypatch.setattr(fcm_notifier, 'REPORT_PAGE_URL', '')
    send_each = MagicMock(return_value=_batch_response(1, 0))
    monkeypatch.setattr(fcm_notifier.messaging, 'send_each_for_multicast', send_each)

    assert notifier.send_report_notification(_report_with_stock_data()) is True

    assert send_each.call_args[0][0].webpush is None


def test_link_carries_the_data_url_and_still_the_core_table(notifier, monkeypatch):
    from urllib.parse import parse_qs, urlsplit
    monkeypatch.setattr(fcm_notifier, 'REPORT_PAGE_URL', REPORT_PAGE)
    send_each = MagicMock(return_value=_batch_response(1, 0))
    monkeypatch.setattr(fcm_notifier.messaging, 'send_each_for_multicast', send_each)
    report = _report_with_stock_data()
    report['flags'] = ['BE RSI 23 과매도']
    report['data_url'] = 'https://raw.githubusercontent.com/owner/repo/abc123/reports/x.json'

    assert notifier.send_report_notification(report) is True

    link = send_each.call_args[0][0].webpush.fcm_options.link
    parts = urlsplit(link)
    assert parse_qs(parts.query)['d'] == [report['data_url']]      # the page loads the details from here
    payload = _decode_fragment(link)                               # and still has the fallback table + signals
    assert payload['s'][0][0] == 'BE'
    assert payload['g'] == ['BE RSI 23 과매도']


def test_link_has_no_query_without_published_data(notifier, monkeypatch):
    monkeypatch.setattr(fcm_notifier, 'REPORT_PAGE_URL', REPORT_PAGE)
    send_each = MagicMock(return_value=_batch_response(1, 0))
    monkeypatch.setattr(fcm_notifier.messaging, 'send_each_for_multicast', send_each)

    notifier.send_report_notification(_report_with_stock_data())

    assert '?' not in send_each.call_args[0][0].webpush.fcm_options.link


def test_body_lists_the_signals_and_caps_them(notifier, monkeypatch):
    send_each = MagicMock(return_value=_batch_response(1, 0))
    monkeypatch.setattr(fcm_notifier.messaging, 'send_each_for_multicast', send_each)
    report = _report_with_stock_data()
    report['flags'] = [f'T{i} 거래량 2.0배' for i in range(10)]

    notifier.send_report_notification(report)

    body = send_each.call_args[0][0].notification.body
    assert '▸ T0 거래량 2.0배' in body and '▸ T7 거래량 2.0배' in body
    assert 'T8 거래량' not in body                                  # beyond the cap of 8
    assert '▸ 외 2건' in body


def test_body_without_signals_is_unchanged(notifier, monkeypatch):
    send_each = MagicMock(return_value=_batch_response(1, 0))
    monkeypatch.setattr(fcm_notifier.messaging, 'send_each_for_multicast', send_each)

    notifier.send_report_notification(_report_with_stock_data())

    assert '▸' not in send_each.call_args[0][0].notification.body
