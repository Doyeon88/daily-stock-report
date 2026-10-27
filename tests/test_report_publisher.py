"""
Unit tests for notifications/report_publisher.py
"""

import base64
import json
from unittest.mock import MagicMock

import pytest

from notifications import report_publisher

REPORT = {
    'timestamp': '2026-10-28T09:00:03+09:00',
    'flags': ['BE RSI 23 과매도'],
    'stock_data': {'BE': {'price': 193.3, 'previous_close': 202.84, 'change': -9.54,
                          'change_percent': -4.7, 'volume': 100, 'error': None}},
    'news': {'BE': [{'title': '한글 headline', 'url': 'https://news.example/1'}]},
    'details': {'BE': {'rsi14': 23.0}},
    'filings': {}, 'comparison': {},
}


@pytest.fixture
def configured(monkeypatch):
    monkeypatch.setattr(report_publisher, 'GITHUB_TOKEN', 'ghs_token')
    monkeypatch.setattr(report_publisher, 'GITHUB_REPOSITORY', 'owner/repo')
    monkeypatch.setattr(report_publisher, 'REPORT_DATA_BRANCH', 'report-data')


def _ok_response(sha='abc1234def5678'):
    response = MagicMock()
    response.json.return_value = {'commit': {'sha': sha}, 'content': {}}
    return response


def test_report_is_committed_to_the_data_branch_and_the_url_is_pinned_to_the_commit(configured, monkeypatch):
    put = MagicMock(return_value=_ok_response('abc1234def5678'))
    monkeypatch.setattr(report_publisher.requests, 'put', put)

    url = report_publisher.publish_report(REPORT)

    api_url = put.call_args.args[0]
    body = put.call_args.kwargs['json']
    assert api_url.startswith('https://api.github.com/repos/owner/repo/contents/reports/')
    assert api_url.endswith('.json')
    assert put.call_args.kwargs['headers']['Authorization'] == 'Bearer ghs_token'
    assert body['branch'] == 'report-data'
    assert body['message'].endswith('[skip ci]')            # data commits must not start CI
    path = api_url.split('/contents/')[1]
    assert url == f'https://raw.githubusercontent.com/owner/repo/abc1234def5678/{path}'


def test_published_file_holds_the_full_report(configured, monkeypatch):
    put = MagicMock(return_value=_ok_response())
    monkeypatch.setattr(report_publisher.requests, 'put', put)

    report_publisher.publish_report(REPORT)

    payload = json.loads(base64.b64decode(put.call_args.kwargs['json']['content']).decode('utf-8'))
    assert payload['v'] == 2
    assert payload['s'][0][0] == 'BE'
    assert payload['g'] == ['BE RSI 23 과매도']
    assert payload['news']['BE'][0]['title'] == '한글 headline'   # non-ASCII survives
    assert payload['details'] == {'BE': {'rsi14': 23.0}}


def test_nothing_is_published_without_credentials(monkeypatch):
    monkeypatch.setattr(report_publisher, 'GITHUB_TOKEN', None)
    monkeypatch.setattr(report_publisher, 'GITHUB_REPOSITORY', None)
    put = MagicMock()
    monkeypatch.setattr(report_publisher.requests, 'put', put)

    assert report_publisher.publish_report(REPORT) is None
    put.assert_not_called()


@pytest.mark.parametrize('failure', ['http_error', 'network_error', 'unexpected_body'])
def test_failures_give_none_so_the_link_falls_back_to_the_core_table(configured, monkeypatch, failure):
    if failure == 'http_error':
        response = MagicMock()
        response.raise_for_status.side_effect = RuntimeError('404 Not Found (branch missing)')
        put = MagicMock(return_value=response)
    elif failure == 'network_error':
        put = MagicMock(side_effect=ConnectionError('down'))
    else:
        response = MagicMock()
        response.json.return_value = {'unexpected': True}
        put = MagicMock(return_value=response)
    monkeypatch.setattr(report_publisher.requests, 'put', put)

    assert report_publisher.publish_report(REPORT) is None
