"""
Unit tests for scrapers/retry.py
"""

from unittest.mock import MagicMock

import pytest

from scrapers import retry


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    monkeypatch.setattr('scrapers.retry.time.sleep', lambda _: None)


class Refused(Exception):
    pass


def test_retries_until_it_works():
    func = MagicMock(side_effect=[ConnectionError('1'), ConnectionError('2'), 'ok'])

    assert retry.call_with_retry(func, 'thing') == 'ok'
    assert func.call_count == 3


def test_raises_the_last_error_when_every_attempt_fails():
    func = MagicMock(side_effect=ConnectionError('down'))

    with pytest.raises(ConnectionError):
        retry.call_with_retry(func, 'thing')
    assert func.call_count == retry.MAX_RETRIES


def test_give_up_on_is_raised_at_once():
    func = MagicMock(side_effect=Refused('no'))

    with pytest.raises(Refused):
        retry.call_with_retry(func, 'thing', give_up_on=(Refused,))
    assert func.call_count == 1


def test_give_up_on_does_not_stop_retrying_other_errors():
    func = MagicMock(side_effect=[ConnectionError('hiccup'), 'ok'])

    assert retry.call_with_retry(func, 'thing', give_up_on=(Refused,)) == 'ok'
