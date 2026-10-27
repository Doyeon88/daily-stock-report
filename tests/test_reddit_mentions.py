"""
Unit tests for scrapers/reddit_mentions.py (the data shape follows ApeWisdom's ranking API)
"""

from unittest.mock import MagicMock

import pytest

from scrapers import reddit_mentions


def _row(rank, ticker, mentions=5, upvotes=20, rank_24h_ago=None, mentions_24h_ago=None):
    return {
        'rank': rank, 'ticker': ticker, 'name': f'{ticker} &amp; Co', 'mentions': mentions, 'upvotes': upvotes,
        'rank_24h_ago': rank_24h_ago if rank_24h_ago is not None else rank,
        'mentions_24h_ago': mentions_24h_ago if mentions_24h_ago is not None else mentions,
    }


PAGES = {
    1: {'count': 5, 'pages': 2, 'current_page': 1, 'results': [
        _row(1, 'SPY', 97), _row(32, 'BE', 16, 51, 23, 10),
    ]},
    2: {'count': 5, 'pages': 2, 'current_page': 2, 'results': [
        _row(662, 'CRCL', 1, 1, 583, 1), _row(688, 'XLAB'),
    ]},
}


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    monkeypatch.setattr('scrapers.retry.time.sleep', lambda _: None)


def _serve(monkeypatch, pages=PAGES, failing_pages=()):
    requested = []

    def get(url, **kwargs):
        page = int(url.rsplit('/', 1)[1])
        requested.append(page)
        if page in failing_pages:
            raise ConnectionError(f'page {page} down')
        response = MagicMock()
        response.json.return_value = pages[page]
        return response

    monkeypatch.setattr(reddit_mentions.requests, 'get', get)
    return requested


def test_tickers_are_found_across_pages_and_unranked_ones_are_none(monkeypatch):
    requested = _serve(monkeypatch)

    result = reddit_mentions.fetch_reddit_mentions(['BE', 'BWXT', 'CRCL'])

    assert result['BE'] == {'rank': 32, 'mentions': 16, 'upvotes': 51, 'rank_24h_ago': 23, 'mentions_24h_ago': 10}
    assert result['CRCL']['rank'] == 662
    assert result['BWXT'] is None                 # read the whole ranking, nobody mentioned it
    assert requested == [1, 2]


def test_reading_stops_once_every_ticker_is_found(monkeypatch):
    requested = _serve(monkeypatch)

    result = reddit_mentions.fetch_reddit_mentions(['BE'])

    assert result['BE']['rank'] == 32
    assert requested == [1]                       # page 2 is not needed


def test_ticker_match_ignores_case(monkeypatch):
    _serve(monkeypatch)

    assert reddit_mentions.fetch_reddit_mentions(['be'])['be']['rank'] == 32


def test_unreachable_ranking_gives_an_empty_result_not_an_exception(monkeypatch):
    _serve(monkeypatch, failing_pages=(1,))

    assert reddit_mentions.fetch_reddit_mentions(['BE', 'CRCL']) == {}


def test_tickers_not_found_in_an_incomplete_read_are_left_out_not_marked_unranked(monkeypatch):
    _serve(monkeypatch, failing_pages=(2,))

    result = reddit_mentions.fetch_reddit_mentions(['BE', 'CRCL'])

    assert result['BE']['rank'] == 32             # found before the failure
    assert 'CRCL' not in result                   # it might be on the page that could not be read, so no claim


def test_the_number_of_pages_read_is_capped(monkeypatch):
    pages = {n: {'pages': 50, 'results': [_row(n, f'T{n}')]} for n in range(1, 51)}
    requested = _serve(monkeypatch, pages=pages)
    monkeypatch.setattr(reddit_mentions, 'MAX_PAGES', 3)

    result = reddit_mentions.fetch_reddit_mentions(['NOPE'])

    assert requested == [1, 2, 3]
    assert result == {'NOPE': None}
