"""
Tests for today's headlines (scrapers/headlines.py)
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest

from scrapers import headlines, summarizer

NOW = datetime(2026, 11, 17, 21, 0, tzinfo=timezone.utc)

RSS = b"""<?xml version="1.0"?><rss><channel>
<item><title>Oil jumps 4% as OPEC signals deeper cuts</title><link>https://x.test/oil</link>
<pubDate>Tue, 17 Nov 2026 20:30:00 GMT</pubDate><description>&lt;p&gt;Crude futures surged.&lt;/p&gt;</description></item>
<item><title>No date item</title><link>https://x.test/none</link></item>
</channel></rss>"""

ATOM = b"""<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom"><entry><title>Fed statement</title>
<link href="https://fed.test/a"/><updated>2026-11-17T19:00:00Z</updated><summary>Policy update</summary></entry></feed>"""


def article(title, hours_ago, category='시황', snippet='', source='S'):
    return {'title': title, 'source': source, 'url': f'https://x.test/{title.replace(" ", "-")}',
            'published': NOW - timedelta(hours=hours_ago), 'category': category, 'snippet': snippet}


def test_parse_rss_and_atom():
    items = headlines.parse_rss(RSS, 'CNBC', '원자재')
    assert len(items) == 1 and items[0]['title'].startswith('Oil jumps') and items[0]['category'] == '원자재'
    assert items[0]['snippet'] == 'Crude futures surged.'
    atom = headlines.parse_rss(ATOM, 'Federal Reserve', '경제')
    assert atom[0]['url'] == 'https://fed.test/a' and atom[0]['published'].tzinfo is not None


def test_breaking_fresh_stories_score_higher():
    breaking = article('Breaking: Fed cuts rates, stocks surge', 1)
    dull = article('Ten tips for your garden', 20)
    assert headlines.score(breaking, NOW) > headlines.score(dull, NOW)


def test_candidates_are_recent_unique_and_spread_over_categories(monkeypatch):
    monkeypatch.setattr(headlines, 'FINNHUB_API_KEY', None)
    monkeypatch.setattr(headlines, 'call_with_retry', lambda fetch, description: fetch())
    old = article('Old story', 30)
    dup = article('Oil jumps again', 2, '원자재')
    pool = {
        '시황': [article('Stocks slide on Fed worries', 1), old],
        '원자재': [article('Oil jumps again', 3, '원자재'), dup],
        '정치': [article('Senate vote on tariff bill', 2, '정치')],
    }
    monkeypatch.setattr(headlines, '_fetch_rss', lambda name, url, category: pool.get(category, []))
    monkeypatch.setattr(headlines, '_fetch_google', lambda query, category, now: [])
    result = headlines.fetch_candidates(NOW)
    titles = [a['title'] for a in result]
    assert 'Old story' not in titles and titles.count('Oil jumps again') == 1
    assert {'시황', '원자재', '정치'} <= {a['category'] for a in result}


def test_a_failing_source_does_not_stop_the_others(monkeypatch):
    monkeypatch.setattr(headlines, 'FINNHUB_API_KEY', None)
    monkeypatch.setattr(headlines, 'call_with_retry', lambda fetch, description: fetch())

    def rss(name, url, category):
        if category == '경제':
            raise RuntimeError('blocked')
        return [article(f'{category} news', 1, category)]

    monkeypatch.setattr(headlines, '_fetch_rss', rss)
    monkeypatch.setattr(headlines, '_fetch_google', lambda query, category, now: [])
    assert headlines.fetch_candidates(NOW)


def test_parse_picks_validates_numbers_and_caps():
    text = ('결과 [{"n": 2, "category": "경제", "headline": "연준 동결", "why": "금리 동결"},'
            '{"n": 2, "headline": "중복"}, {"n": 9, "headline": "범위 밖"}, {"n": 1, "headline": ""},'
            '{"n": 3, "category": "정치", "headline": "관세 법안", "why": ""}]')
    picks = headlines.parse_picks(text, 3, 5)
    assert [p['n'] for p in picks] == [2, 3]
    assert headlines.parse_picks(text, 3, 1)[0]['headline'] == '연준 동결'
    assert headlines.parse_picks('no json', 3, 5) is None
    assert headlines.parse_picks('[1, 2]', 3, 5) is None


def test_prompt_lists_every_candidate_with_age_and_rules():
    prompt = headlines.build_pick_prompt([article('A news', 2, snippet='snip'), article('B news', 5, '정치')], NOW, 3, 5)
    assert '1. [시황] 2시간 전' in prompt and '2. [정치] 5시간 전' in prompt and 'snip' in prompt
    assert '3~5개' in prompt and '추측' in prompt


def test_ai_picks_become_headlines_with_summaries(monkeypatch):
    candidates = [article('Oil jumps', 1, '원자재'), article('Fed holds', 2, '경제'), article('Tariff vote', 3, '정치')]
    answers = iter(['[{"n": 2, "category": "경제", "headline": "연준 금리 동결", "why": "금리 동결 소식"},'
                    '{"n": 1, "category": "원자재", "headline": "유가 4% 급등", "why": "OPEC 감산"}]'])
    monkeypatch.setattr(summarizer, 'ai_text', lambda prompt: next(answers))
    seen = {}
    monkeypatch.setattr(summarizer, 'add_summaries', lambda groups, **kw: seen.setdefault('groups', groups))
    result = headlines.select_headlines(candidates, NOW)
    assert [(h['category'], h['headline']) for h in result] == [('경제', '연준 금리 동결'), ('원자재', '유가 4% 급등')]
    assert result[0]['title'] == 'Fed holds' and result[0]['why'] == '금리 동결 소식'
    assert seen['groups'] == [result]


def test_without_ai_the_best_stories_are_used_one_per_category(monkeypatch):
    monkeypatch.setattr(summarizer, 'ai_text', lambda prompt: None)
    monkeypatch.setattr(summarizer, 'add_summaries', MagicMock())
    candidates = [dict(article(f'N{i}', 1, c), score=10 - i) for i, c in
                  enumerate(['시황', '시황', '경제', '원자재', '정치', '여론', '시황'])]
    result = headlines.select_headlines(candidates, NOW)
    assert len(result) == 5 and {h['category'] for h in result} == {'시황', '경제', '원자재', '정치', '여론'}
    assert headlines.select_headlines([], NOW) == []


def test_unusable_ai_answer_is_retried_once_then_falls_back(monkeypatch):
    calls = []
    monkeypatch.setattr(summarizer, 'ai_text', lambda prompt: calls.append(1) or 'sorry')
    monkeypatch.setattr(summarizer, 'add_summaries', MagicMock())
    result = headlines.select_headlines([dict(article('Only', 1), score=1)], NOW)
    assert len(calls) == 2 and result[0]['headline'] == 'Only'
