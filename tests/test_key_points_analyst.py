"""
Tests for the key-points material, analyst-report articles and the payload fields
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest

from processors import key_points
from processors.report_payload import build_full_payload
from scrapers import news_scraper

NOW = datetime(2026, 11, 17, 12, 0, tzinfo=timezone.utc)


@pytest.mark.parametrize('title,expected', [
    ('UBS raises Bloom Energy price target to $350', True),
    ('Analyst upgrades EROC to Buy', True),
    ('Morgan Stanley initiates coverage of Caterpillar', True),
    ('Bloom Energy signs supply agreement', False),
])
def test_is_analyst_article(title, expected):
    assert news_scraper.is_analyst_article(title) is expected


def test_bundle_picks_analyst_articles_before_the_news_cap(monkeypatch):
    def article(i, title, hours):
        return {'title': title, 'source': 's', 'url': f'https://x/{i}', 'snippet': '',
                'published': datetime(2026, 11, 17, 12 - hours, tzinfo=timezone.utc)}
    plain = [article(i, f'Plain news {i}', 1 + i * 0.1 if False else 1) for i in range(8)]
    # eight newer plain stories push the analyst story out of the five-item news list
    analyst = article(99, 'HSBC raises price target on BE', 9)
    monkeypatch.setattr(news_scraper, '_primary_sources', lambda: [('src', lambda t, n: plain + [analyst])])
    monkeypatch.setattr(news_scraper, '_google_news', lambda t, n: [])
    monkeypatch.setattr(news_scraper, '_google_analyst_news', lambda t, n: [])
    monkeypatch.setattr('scrapers.retry.time.sleep', lambda _: None)

    bundle = news_scraper.fetch_news_bundle(['BE'], NOW)

    assert len(bundle['news']['BE']) == 5
    assert all('price target' not in a['title'] for a in bundle['news']['BE'])
    assert [a['title'] for a in bundle['analyst']['BE']] == ['HSBC raises price target on BE']


def test_analyst_list_reuses_the_news_dict_when_the_article_is_in_both(monkeypatch):
    item = {'title': 'UBS lifts BE target price', 'source': 's', 'url': 'https://x/1', 'snippet': '',
            'published': datetime(2026, 11, 17, 11, tzinfo=timezone.utc)}
    monkeypatch.setattr(news_scraper, '_primary_sources', lambda: [('src', lambda t, n: [item])])
    monkeypatch.setattr(news_scraper, '_google_news', lambda t, n: [])
    monkeypatch.setattr(news_scraper, '_google_analyst_news', lambda t, n: [])
    bundle = news_scraper.fetch_news_bundle(['BE'], NOW)
    assert bundle['analyst']['BE'][0] is bundle['news']['BE'][0]


def test_material_contains_only_collected_facts():
    material = key_points.build_material(
        'BE',
        {'target_mean': 120.0, 'upside': 10.5, 'recommendation': 'buy', 'analyst_count': 20,
         'earnings_date': '2026-11-20', 'days_to_earnings': 3, 'rsi14': 55.0, 'return_5d': 1.0, 'return_20d': 2.0},
        [{'title': 'BE wins deal', 'published': '2026-11-16T00:00', 'source': 'AP', 'snippet': 'excerpt', 'tag': '호재'}],
        [{'title': 'UBS raises BE target', 'published': '2026-11-15T00:00', 'source': 'Reuters'}],
        {'ratings': [{'date': '2026-11-13', 'firm': 'UBS', 'from_grade': 'Neutral', 'to_grade': 'Buy',
                      'target': 350.0, 'prior_target': 300.0}],
         'eps_trend': [{'label': '내년', 'current': 1.1, 'change_7d_pct': 10.0, 'change_30d_pct': None}]},
        {'filings': [{'form': '8-K', 'date': '2026-11-10', 'summary': '수시 공시'}]},
    )
    text = material['text']
    for needle in ('평균 목표가 $120.00', 'UBS: Neutral → Buy, 목표가 $300.00 → $350.00', 'EPS 컨센서스 내년', 'UBS raises BE target',
                   'BE wins deal', '2026-11-10 8-K'):
        assert needle in text
    assert any('목표가' in f for f in material['fallback']) and any('공시' in f for f in material['fallback'])
    assert any('호재 1' in f for f in material['fallback'])


def test_material_is_empty_without_any_data():
    assert key_points.build_material('X', {}, [], [], {}, {}) == {'text': '', 'fallback': []}


def test_payload_carries_key_points_and_analyst_articles():
    report = {'key_points': {'BE': {'points': ['a'], 'source': 'ai'}},
              'analyst_articles': {'BE': [{'title': 't', 'summary': '요약'}]}}
    payload = build_full_payload(report)
    assert payload['key_points']['BE']['points'] == ['a']
    assert payload['analyst_articles']['BE'][0]['summary'] == '요약'


# ---------- excerpt-first sourcing ----------

def _art(i, title, hours, snippet=''):
    return {'title': title, 'source': 's', 'url': f'https://x/{i}', 'snippet': snippet,
            'published': NOW - timedelta(hours=hours)}


def test_merge_prefers_articles_with_an_excerpt_and_keeps_newest_first():
    articles = [_art(1, 'new google', 1), _art(2, 'mid google', 2), _art(3, 'old yahoo', 8, 'has excerpt'),
                _art(4, 'older finnhub', 9, 'has excerpt')]
    merged = news_scraper._merge(articles, NOW, limit=3)
    assert [a['title'] for a in merged] == ['new google', 'old yahoo', 'older finnhub']


def test_google_is_not_asked_when_the_primary_sources_are_enough(monkeypatch):
    primary = [_art(i, f'story {i}', 1 + i * 0.01, 'excerpt') for i in range(5)]
    google = MagicMock(return_value=[_art(99, 'google story', 1)])
    monkeypatch.setattr(news_scraper, '_primary_sources', lambda: [('Yahoo', lambda t, n: primary)])
    monkeypatch.setattr(news_scraper, '_google_news', google)
    monkeypatch.setattr(news_scraper, '_google_analyst_news', MagicMock(return_value=[]))

    news_scraper.fetch_news(['BE'], NOW)

    google.assert_not_called()


def test_google_fills_up_when_the_primary_sources_give_too_few(monkeypatch):
    primary = [_art(1, 'only yahoo', 1, 'excerpt')]
    google = MagicMock(return_value=[_art(2, 'google story', 2)])
    monkeypatch.setattr(news_scraper, '_primary_sources', lambda: [('Yahoo', lambda t, n: primary)])
    monkeypatch.setattr(news_scraper, '_google_news', google)

    result = news_scraper.fetch_news(['BE'], NOW)

    google.assert_called_once()
    assert [a['title'] for a in result['BE']] == ['only yahoo', 'google story']


def test_google_analyst_search_is_skipped_when_excerpt_articles_suffice(monkeypatch):
    analysts = [_art(i, f'Bank {i} raises price target', 1 + i * 0.01, 'excerpt') for i in range(5)]
    analyst_google = MagicMock(return_value=[])
    monkeypatch.setattr(news_scraper, '_primary_sources', lambda: [('Yahoo', lambda t, n: analysts)])
    monkeypatch.setattr(news_scraper, '_google_news', MagicMock(return_value=[]))
    monkeypatch.setattr(news_scraper, '_google_analyst_news', analyst_google)

    bundle = news_scraper.fetch_news_bundle(['BE'], NOW)

    analyst_google.assert_not_called()
    assert len(bundle['analyst']['BE']) == 5
