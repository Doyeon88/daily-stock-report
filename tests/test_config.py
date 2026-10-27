"""
Unit tests for config.py
"""

import importlib

import pytest

import config


@pytest.fixture
def reload_config(monkeypatch):
    """Re-evaluate config.py after the environment was changed, and restore it afterwards"""
    yield lambda: importlib.reload(config)
    monkeypatch.undo()
    importlib.reload(config)


@pytest.mark.parametrize('name', ['SEC_USER_AGENT', 'FINNHUB_API_KEY', 'GITHUB_TOKEN'])
def test_secrets_sent_in_headers_lose_surrounding_whitespace(monkeypatch, reload_config, name):
    # A secret pasted into GitHub often ends with a newline, which an HTTP header rejects
    monkeypatch.setenv(name, '  my-value x@y.com\n')

    reload_config()

    assert getattr(config, name) == 'my-value x@y.com'


@pytest.mark.parametrize('raw', ['', '   ', '\n'])
def test_blank_secret_counts_as_not_set(monkeypatch, reload_config, raw):
    monkeypatch.setenv('SEC_USER_AGENT', raw)

    reload_config()

    assert config.SEC_USER_AGENT is None


def test_unset_secret_is_none(monkeypatch, reload_config):
    monkeypatch.delenv('SEC_USER_AGENT', raising=False)

    reload_config()

    assert config.SEC_USER_AGENT is None
