"""
Unit tests for scrapers/news_scraper.py
"""

from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from scrapers import news_scraper

NOW = datetime(2026, 10, 27, 12, 0, tzinfo=timezone.utc)

RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
  <item><title>Bloom wins big deal - Reuters</title><link>https://news.example/1</link>
        <pubDate>Tue, 27 Oct 2026 03:15:00 GMT</pubDate><source url="https://reuters.com">Reuters</source></item>
  <item><title>Bloom wins big deal - Other Outlet</title><link>https://news.example/2</link>
        <pubDate>Tue, 27 Oct 2026 04:00:00 GMT</pubDate><source url="https://other.example">Other Outlet</source></item>
  <item><title>Older story - CNBC</title><link>https://news.example/3</link>
        <pubDate>Mon, 26 Oct 2026 09:00:00 GMT</pubDate><source url="https://cnbc.com">CNBC</source></item>
  <item><title>Way too old - Blog</title><link>https://news.example/4</link>
        <pubDate>Fri, 16 Oct 2026 09:00:00 GMT</pubDate><source url="https://blog.example">Blog</source></item>
</channel></rss>"""

FINNHUB = [
    {'headline': 'Bloom Wins Big Deal!', 'source': 'Finnhub Wire', 'url': 'https://finn.example/a',
     'datetime': int(datetime(2026, 10, 27, 5, 0, tzinfo=timezone.utc).timestamp())},
    {'headline': 'Analyst raises target', 'source': 'Finnhub Wire', 'url': 'https://finn.example/b',
     'datetime': int(datetime(2026, 10, 27, 1, 0, tzinfo=timezone.utc).timestamp())},
]


def _response(content=b'', payload=None):
    response = MagicMock()
    response.content = content
    response.json.return_value = payload
    return response


def _fake_get(calls, google=RSS, finnhub=FINNHUB):
    def get(url, **kwargs):
        calls.append((url, kwargs))
        if 'finnhub' in url:
            return _response(payload=finnhub)
        return _response(content=google.encode('utf-8'))
    return get


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    monkeypatch.setattr('scrapers.retry.time.sleep', lambda _: None)


def test_google_news_is_cleaned_deduplicated_and_sorted(monkeypatch):
    calls = []
    monkeypatch.setattr(news_scraper, 'FINNHUB_API_KEY', None)
    monkeypatch.setattr(news_scraper.requests, 'get', _fake_get(calls))

    result = news_scraper.fetch_news(['BE'], now=NOW)

    titles = [article['title'] for article in result['BE']]
    # source suffix removed, same-title duplicate dropped (the first seen = newest kept), >3 day old dropped
    assert titles == ['Bloom wins big deal', 'Older story']
    assert result['BE'][0]['url'] == 'https://news.example/2'
    assert result['BE'][0]['published'] == '2026-10-27T04:00+00:00'
    assert len(calls) == 1 and 'news.google.com' in calls[0][0]
    assert '"Bloom Energy" stock' in calls[0][1]['params']['q']


def test_finnhub_is_used_with_a_header_and_merged_with_google(monkeypatch):
    calls = []
    monkeypatch.setattr(news_scraper, 'FINNHUB_API_KEY', 'secret-key')
    monkeypatch.setattr(news_scraper.requests, 'get', _fake_get(calls))

    result = news_scraper.fetch_news(['BE'], now=NOW)

    finnhub_call = next(kwargs for url, kwargs in calls if 'finnhub' in url)
    assert finnhub_call['headers'] == {'X-Finnhub-Token': 'secret-key'}
    assert 'secret-key' not in str(finnhub_call['params'])   # the key must not end up in URLs or error messages
    titles = [article['title'] for article in result['BE']]
    # "Bloom Wins Big Deal!" (Finnhub) and "Bloom wins big deal" (Google) are the same headline
    assert len([t for t in titles if t.lower().startswith('bloom wins')]) == 1
    assert 'Analyst raises target' in titles


def test_result_is_capped_to_the_news_limit(monkeypatch):
    monkeypatch.setattr(news_scraper, 'FINNHUB_API_KEY', 'k')
    monkeypatch.setattr(news_scraper, 'NEWS_LIMIT', 2)
    monkeypatch.setattr(news_scraper.requests, 'get', _fake_get([]))

    assert len(news_scraper.fetch_news(['BE'], now=NOW)['BE']) == 2


def test_one_failing_source_does_not_hide_the_other(monkeypatch):
    monkeypatch.setattr(news_scraper, 'FINNHUB_API_KEY', 'k')

    def get(url, **kwargs):
        if 'news.google.com' in url:
            raise ConnectionError('google down')
        return _response(payload=FINNHUB)

    monkeypatch.setattr(news_scraper.requests, 'get', get)

    result = news_scraper.fetch_news(['BE'], now=NOW)

    assert [a['title'] for a in result['BE']] == ['Bloom Wins Big Deal!', 'Analyst raises target']


def test_every_source_failing_gives_an_empty_list_not_an_exception(monkeypatch):
    monkeypatch.setattr(news_scraper, 'FINNHUB_API_KEY', None)
    monkeypatch.setattr(news_scraper.requests, 'get', MagicMock(side_effect=ConnectionError('down')))

    assert news_scraper.fetch_news(['BE', 'CRCL'], now=NOW) == {'BE': [], 'CRCL': []}
