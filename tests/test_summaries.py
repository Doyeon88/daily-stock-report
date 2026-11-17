"""
Tests for article summaries (scrapers/summarizer.py), RSS excerpts and filing descriptions
"""

from unittest.mock import MagicMock

import pytest

from processors import tagging
from scrapers import news_scraper, sec_filings, summarizer


def test_parse_page_description_prefers_og_and_unescapes():
    page = '<head><meta property="og:description" content="Bloom &amp; Co wins a $1B deal"><meta name="description" content="other"></head>'
    assert summarizer.parse_page_description(page) == 'Bloom & Co wins a $1B deal'
    assert summarizer.parse_page_description('<html></html>') == ''
    assert summarizer.parse_page_description(None) == ''


def test_rss_snippet_drops_text_that_only_repeats_the_headline():
    assert news_scraper._rss_snippet('<a href="x">Bloom wins deal</a>&nbsp;<font>Reuters</font>', 'Bloom wins deal') == ''
    assert news_scraper._rss_snippet('<p>Company said <b>orders</b> doubled.</p>', 'Bloom wins deal') == 'Company said orders doubled.'
    assert news_scraper._rss_snippet(None, 't') == ''


def test_merge_keeps_the_snippet_capped():
    from datetime import datetime, timezone
    now = datetime(2026, 11, 17, tzinfo=timezone.utc)
    merged = news_scraper._merge(
        [{'title': 'a', 'source': 's', 'url': 'u', 'published': now, 'snippet': 'x' * 1000}], now)
    assert len(merged[0]['snippet']) == news_scraper.MAX_SNIPPET_LENGTH


def test_parse_ai_summaries_requires_matching_length_and_strings():
    assert summarizer.parse_ai_summaries('결과: ["가", "나"]', 2) == ['가', '나']
    assert summarizer.parse_ai_summaries('["가"]', 2) is None
    assert summarizer.parse_ai_summaries('[1, 2]', 2) is None
    assert summarizer.parse_ai_summaries('no json', 1) is None
    assert summarizer.parse_ai_summaries('[not json]', 1) is None


def test_clip():
    assert summarizer.clip('  a   b ') == 'a b'
    assert summarizer.clip('x' * 300, 10) == 'x' * 9 + '…'


def test_prompt_contains_every_headline_and_forbids_speculation():
    prompt = summarizer.build_prompt([{'title': 'T1', 'snippet': 'S1'}, {'title': 'T2'}])
    assert 'T1' in prompt and 'S1' in prompt and 'T2' in prompt and '(없음)' in prompt
    assert '추측' in prompt


def test_without_any_key_summaries_fall_back_to_the_excerpt(monkeypatch):
    monkeypatch.setattr(summarizer, 'ANTHROPIC_API_KEY', None)
    monkeypatch.setattr(summarizer, 'GITHUB_MODELS_TOKEN', None)
    group = [{'title': 'a', 'url': 'u1', 'snippet': 'Orders doubled this quarter.'},
             {'title': 'b', 'url': 'u2', 'snippet': ''}]
    summarizer.add_summaries([group], fetch_pages=False)
    assert (group[0]['summary'], group[0]['summary_source']) == ('Orders doubled this quarter.', 'snippet')
    assert (group[1]['summary'], group[1]['summary_source']) == (None, None)


def test_missing_excerpt_is_fetched_from_the_page(monkeypatch):
    monkeypatch.setattr(summarizer, 'ANTHROPIC_API_KEY', None)
    monkeypatch.setattr(summarizer, 'GITHUB_MODELS_TOKEN', None)
    monkeypatch.setattr(summarizer, 'fetch_page_description', lambda url: 'Page says X')
    group = [{'title': 'a', 'url': 'u1', 'snippet': ''}]
    summarizer.add_summaries([group])
    assert group[0]['summary'] == 'Page says X'


def test_ai_summary_is_used_and_marked(monkeypatch):
    monkeypatch.setattr(summarizer, 'ANTHROPIC_API_KEY', 'k')
    response = MagicMock()
    response.json.return_value = {'content': [{'type': 'text', 'text': '["요약 1", "요약 2"]'}]}
    post = MagicMock(return_value=response)
    monkeypatch.setattr(summarizer.requests, 'post', post)
    group = [{'title': 'a', 'url': 'u', 'snippet': 's'}, {'title': 'b', 'url': 'u2', 'snippet': ''}]
    summarizer.add_summaries([group], fetch_pages=False)
    assert [a['summary'] for a in group] == ['요약 1', '요약 2']
    assert {a['summary_source'] for a in group} == {'ai'}
    assert post.call_args[1]['headers']['x-api-key'] == 'k'


def test_failed_ai_call_falls_back_to_excerpts(monkeypatch):
    monkeypatch.setattr(summarizer, 'ANTHROPIC_API_KEY', 'k')
    monkeypatch.setattr(summarizer, 'GITHUB_MODELS_TOKEN', None)
    monkeypatch.setattr(summarizer.requests, 'post', MagicMock(side_effect=RuntimeError('down')))
    group = [{'title': 'a', 'url': 'u', 'snippet': 'excerpt'}]
    summarizer.add_summaries([group], fetch_pages=False)
    assert (group[0]['summary'], group[0]['summary_source']) == ('excerpt', 'snippet')


@pytest.mark.parametrize('form,label,expected', [
    ('10-Q', '', '분기보고서(재무제표·MD&A)'),
    ('8-K', '실적 발표', '수시 공시(주요 사건 보고) · 실적 발표'),
    ('SCHEDULE 13G', '', '5% 이상 보유 신고(수동적 투자)'),
    ('ZZZ', '', 'ZZZ'),
])
def test_describe_form(form, label, expected):
    assert sec_filings.describe_form(form, label) == expected


def test_tagged_filings_carry_a_summary():
    tagged = tagging.tag_filings([{'form': 'S-1', 'label': ''}, {'form': '8-K', 'label': '주요 계약 체결'}])
    assert tagged[0]['summary'].startswith('증권 신고서')
    assert tagged[1]['summary'].endswith('주요 계약 체결')


def test_github_models_is_used_when_there_is_no_claude_key(monkeypatch):
    monkeypatch.setattr(summarizer, 'ANTHROPIC_API_KEY', None)
    monkeypatch.setattr(summarizer, 'GITHUB_MODELS_TOKEN', 'ghs_token')
    response = MagicMock()
    response.json.return_value = {'choices': [{'message': {'content': '["요약 A"]'}}]}
    post = MagicMock(return_value=response)
    monkeypatch.setattr(summarizer.requests, 'post', post)
    group = [{'title': 'a', 'url': 'u', 'snippet': 's'}]
    summarizer.add_summaries([group], fetch_pages=False)
    assert (group[0]['summary'], group[0]['summary_source']) == ('요약 A', 'ai')
    assert post.call_args[0][0] == summarizer.GITHUB_MODELS_URL
    assert post.call_args[1]['headers']['Authorization'] == 'Bearer ghs_token'


def test_github_models_takes_over_when_claude_fails(monkeypatch):
    monkeypatch.setattr(summarizer, 'ANTHROPIC_API_KEY', 'k')
    monkeypatch.setattr(summarizer, 'GITHUB_MODELS_TOKEN', 'ghs_token')
    ok = MagicMock()
    ok.json.return_value = {'choices': [{'message': {'content': '["대체 요약"]'}}]}

    def post(url, **kwargs):
        if url == summarizer.API_URL:
            raise RuntimeError('no credit')
        return ok

    monkeypatch.setattr(summarizer.requests, 'post', post)
    group = [{'title': 'a', 'url': 'u', 'snippet': 's'}]
    summarizer.add_summaries([group], fetch_pages=False)
    assert group[0]['summary'] == '대체 요약'


def test_both_providers_failing_gives_the_excerpt(monkeypatch):
    monkeypatch.setattr(summarizer, 'ANTHROPIC_API_KEY', 'k')
    monkeypatch.setattr(summarizer, 'GITHUB_MODELS_TOKEN', 'ghs_token')
    monkeypatch.setattr(summarizer.requests, 'post', MagicMock(side_effect=RuntimeError('down')))
    group = [{'title': 'a', 'url': 'u', 'snippet': 'excerpt'}]
    summarizer.add_summaries([group], fetch_pages=False)
    assert (group[0]['summary'], group[0]['summary_source']) == ('excerpt', 'snippet')


def test_summary_basis_tells_title_only_from_excerpt(monkeypatch):
    monkeypatch.setattr(summarizer, 'ANTHROPIC_API_KEY', 'k')
    response = MagicMock()
    response.json.return_value = {'content': [{'type': 'text', 'text': '["가", "나"]'}]}
    monkeypatch.setattr(summarizer.requests, 'post', MagicMock(return_value=response))
    group = [{'title': 'a', 'url': 'u', 'snippet': 'has excerpt'}, {'title': 'b', 'url': 'u2', 'snippet': ''}]
    summarizer.add_summaries([group], fetch_pages=False)
    assert [a['summary_basis'] for a in group] == ['excerpt', 'title']


def test_non_json_body_is_reported_with_status_and_start(monkeypatch):
    monkeypatch.setattr(summarizer, 'ANTHROPIC_API_KEY', None)
    monkeypatch.setattr(summarizer, 'GITHUB_MODELS_TOKEN', 'ghs')
    response = MagicMock(status_code=200, text='<html>login</html>', history=[])
    response.headers = {'Content-Type': 'text/html'}
    response.json.side_effect = ValueError('Expecting value')
    monkeypatch.setattr(summarizer.requests, 'post', MagicMock(return_value=response))
    messages = []
    monkeypatch.setattr(summarizer.logger, 'error', lambda m: messages.append(m))
    assert summarizer._github_models_summaries([{'title': 'a'}]) is None
    assert 'HTTP 200' in messages[0] and 'text/html' in messages[0] and '<html>login' in messages[0]
