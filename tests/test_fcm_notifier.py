"""
Unit tests for notifications/fcm_notifier.py
"""

from unittest.mock import MagicMock

import pytest

from notifications import fcm_notifier


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
