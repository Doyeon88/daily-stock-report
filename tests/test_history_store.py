"""
Unit tests for notifications/history_store.py
"""

import base64
import json
from datetime import date
from unittest.mock import MagicMock

import pytest

from notifications import history_store

STORED = {'BE': {'2026-10-26': [32, 16, 51]}, 'BWXT': {'2026-10-26': [None, 0, 0]}}


@pytest.fixture
def configured(monkeypatch):
    monkeypatch.setattr(history_store, 'GITHUB_TOKEN', 'ghs_token')
    monkeypatch.setattr(history_store, 'GITHUB_REPOSITORY', 'owner/repo')
    monkeypatch.setattr(history_store, 'REPORT_DATA_BRANCH', 'report-data')


def _file_response(payload=None, sha='sha1'):
    raw = json.dumps(payload if payload is not None else {'v': 1, 'tickers': STORED}).encode('utf-8')
    response = MagicMock(status_code=200)
    # encodebytes wraps the text in lines, like the GitHub contents API does
    response.json.return_value = {'content': base64.encodebytes(raw).decode(), 'sha': sha}
    return response


def test_history_is_read_from_the_data_branch(configured, monkeypatch):
    get = MagicMock(return_value=_file_response())
    monkeypatch.setattr(history_store.requests, 'get', get)

    history, sha, readable = history_store.load_history()

    assert (history, sha, readable) == (STORED, 'sha1', True)
    assert get.call_args.args[0] == 'https://api.github.com/repos/owner/repo/contents/history/reddit.json'
    assert get.call_args.kwargs['params'] == {'ref': 'report-data'}
    assert get.call_args.kwargs['headers']['Authorization'] == 'Bearer ghs_token'


def test_a_missing_file_counts_as_readable_and_empty(configured, monkeypatch):
    monkeypatch.setattr(history_store.requests, 'get', MagicMock(return_value=MagicMock(status_code=404)))

    assert history_store.load_history() == ({}, None, True)


def _failing_get(kind):
    if kind == 'http_error':
        response = MagicMock(status_code=500)
        response.raise_for_status.side_effect = RuntimeError('500 Server Error')
        return MagicMock(return_value=response)
    if kind == 'network':
        return MagicMock(side_effect=ConnectionError('down'))
    if kind == 'wrong_version':
        return MagicMock(return_value=_file_response({'v': 2, 'tickers': {}}))
    if kind == 'wrong_shape':
        return MagicMock(return_value=_file_response({'v': 1, 'tickers': ['not', 'a', 'dict']}))
    response = MagicMock(status_code=200)
    response.json.return_value = {'content': base64.b64encode(b'not json').decode(), 'sha': 's'}
    return MagicMock(return_value=response)


@pytest.mark.parametrize('kind', ['http_error', 'network', 'wrong_version', 'wrong_shape', 'not_json'])
def test_a_history_that_cannot_be_read_is_reported_as_unreadable(configured, monkeypatch, kind):
    monkeypatch.setattr(history_store.requests, 'get', _failing_get(kind))

    history, sha, readable = history_store.load_history()

    assert readable is False                     # the caller must not write: it would replace the stored history
    assert history == {} and sha is None


def test_nothing_is_requested_without_credentials(monkeypatch):
    monkeypatch.setattr(history_store, 'GITHUB_TOKEN', None)
    monkeypatch.setattr(history_store, 'GITHUB_REPOSITORY', None)
    get = MagicMock()
    monkeypatch.setattr(history_store.requests, 'get', get)

    assert history_store.load_history() == ({}, None, False)
    get.assert_not_called()


def test_save_writes_one_commit_with_the_file_sha_and_skip_ci(configured, monkeypatch):
    put = MagicMock(return_value=MagicMock(status_code=200))
    monkeypatch.setattr(history_store.requests, 'put', put)

    result = history_store.save_history(STORED, 'sha1', date(2026, 10, 27))

    body = put.call_args.kwargs['json']
    assert result == history_store.SAVED
    assert body['sha'] == 'sha1'                 # a newer version is refused instead of overwritten
    assert body['branch'] == 'report-data'
    assert body['message'] == 'Reddit history 2026-10-27 [skip ci]'
    assert json.loads(base64.b64decode(body['content'])) == {'v': 1, 'tickers': STORED}


def test_creating_the_file_sends_no_sha(configured, monkeypatch):
    put = MagicMock(return_value=MagicMock(status_code=201))
    monkeypatch.setattr(history_store.requests, 'put', put)

    history_store.save_history(STORED, None, date(2026, 10, 27))

    assert 'sha' not in put.call_args.kwargs['json']


@pytest.mark.parametrize('status', [409, 422])
def test_a_refused_overwrite_is_a_conflict(configured, monkeypatch, status):
    monkeypatch.setattr(history_store.requests, 'put', MagicMock(return_value=MagicMock(status_code=status)))

    assert history_store.save_history(STORED, 'old', date(2026, 10, 27)) == history_store.CONFLICT


def test_other_failures_are_reported_as_failed(configured, monkeypatch):
    response = MagicMock(status_code=500)
    response.raise_for_status.side_effect = RuntimeError('500 Server Error')
    monkeypatch.setattr(history_store.requests, 'put', MagicMock(return_value=response))
    assert history_store.save_history(STORED, 'sha1', date(2026, 10, 27)) == history_store.FAILED

    monkeypatch.setattr(history_store.requests, 'put', MagicMock(side_effect=ConnectionError('down')))
    assert history_store.save_history(STORED, 'sha1', date(2026, 10, 27)) == history_store.FAILED
