"""
Tests for article summaries (scrapers/summarizer.py), RSS excerpts and filing descriptions
"""

from unittest.mock import MagicMock

import pytest

from processors import tagging
from scrapers import news_scraper, sec_filings, summarizer


@pytest.fixture(autouse=True)
def fresh_provider_state(monkeypatch):
    monkeypatch.setattr(summarizer, '_unusable', set())


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
    assert summarizer._github_models_text('prompt') is None
    assert 'HTTP 200' in messages[0] and 'text/html' in messages[0] and '<html>login' in messages[0]


def test_unusable_endpoint_is_skipped_and_the_next_one_is_tried(monkeypatch):
    monkeypatch.setattr(summarizer, 'ANTHROPIC_API_KEY', None)
    monkeypatch.setattr(summarizer, 'GITHUB_MODELS_TOKEN', 'ghs')
    first, second = summarizer.GITHUB_MODELS_ENDPOINTS[0][0], summarizer.GITHUB_MODELS_ENDPOINTS[1][0]
    calls = []
    ok_response = MagicMock(status_code=200)
    ok_response.json.return_value = {'choices': [{'message': {'content': '["요약"]'}}]}
    bad_response = MagicMock(status_code=200, text='OK\r\n', history=[])
    bad_response.headers = {'Content-Type': 'text/plain'}
    bad_response.json.side_effect = ValueError('Expecting value')

    def post(url, **kwargs):
        calls.append(url)
        return bad_response if url == first else ok_response

    monkeypatch.setattr(summarizer.requests, 'post', post)
    assert summarizer._github_models_text('p') == '["요약"]'
    assert summarizer._github_models_text('p') == '["요약"]'
    assert calls == [first, second, second]   # the broken endpoint is not asked a second time


def test_auth_failure_disables_claude_for_the_run(monkeypatch):
    monkeypatch.setattr(summarizer, 'ANTHROPIC_API_KEY', 'bad')
    monkeypatch.setattr(summarizer, 'GITHUB_MODELS_TOKEN', None)
    post = MagicMock(return_value=MagicMock(status_code=401, text='unauthorized'))
    monkeypatch.setattr(summarizer.requests, 'post', post)
    assert summarizer.ai_text('p') is None and summarizer.ai_text('p') is None
    assert post.call_count == 1


def test_temporary_error_does_not_try_the_other_endpoint(monkeypatch):
    monkeypatch.setattr(summarizer, 'ANTHROPIC_API_KEY', None)
    monkeypatch.setattr(summarizer, 'GITHUB_MODELS_TOKEN', 'ghs')
    post = MagicMock(side_effect=RuntimeError('429'))
    monkeypatch.setattr(summarizer.requests, 'post', post)
    assert summarizer._github_models_text('p') is None
    assert post.call_count == 1


def test_article_in_two_groups_is_summarized_once(monkeypatch):
    monkeypatch.setattr(summarizer, 'ANTHROPIC_API_KEY', None)
    monkeypatch.setattr(summarizer, 'GITHUB_MODELS_TOKEN', None)
    shared = {'title': 'a', 'url': 'u', 'snippet': 'x'}
    calls = []
    monkeypatch.setattr(summarizer, 'ai_summaries', lambda group, bodies=None: calls.append(len(group)))
    summarizer.add_summaries([[shared], [shared, {'title': 'b', 'url': 'u2', 'snippet': 'y'}]], fetch_pages=False)
    assert calls == [1, 1]   # the shared article is not part of the second call


def test_parse_ai_list_accepts_any_length():
    assert summarizer.parse_ai_list('앞말 ["가", "나", "다"]') == ['가', '나', '다']
    assert summarizer.parse_ai_list('[]') is None
    assert summarizer.parse_ai_list('[1]') is None


def test_key_points_use_ai_and_cap_at_seven(monkeypatch):
    monkeypatch.setattr(summarizer, 'ai_text', lambda prompt: '["1","2","3","4","5","6","7"]')
    result = summarizer.add_key_points({'BE': {'text': '자료', 'fallback': ['수치']}})
    assert result['BE'] == {'points': ['1', '2', '3', '4', '5', '6', '7'], 'source': 'ai'}


def test_key_points_fall_back_to_the_numbers(monkeypatch):
    monkeypatch.setattr(summarizer, 'ai_text', lambda prompt: None)
    result = summarizer.add_key_points({
        'BE': {'text': '자료', 'fallback': ['a', 'b']}, 'X': {'text': '', 'fallback': []}})
    assert result == {'BE': {'points': ['a', 'b'], 'source': 'data'}}


def test_key_points_prompt_only_allows_the_given_material():
    prompt = summarizer.build_key_points_prompt('BE', '[뉴스]\n- x')
    assert '자료에 없는' in prompt and '[뉴스]' in prompt and '5개' in prompt


def test_unresolvable_endpoint_is_marked_unusable(monkeypatch):
    monkeypatch.setattr(summarizer, 'ANTHROPIC_API_KEY', None)
    monkeypatch.setattr(summarizer, 'GITHUB_MODELS_TOKEN', 'ghs')
    post = MagicMock(side_effect=summarizer.requests.ConnectionError('Failed to resolve'))
    monkeypatch.setattr(summarizer.requests, 'post', post)
    assert summarizer._github_models_text('p') is None
    assert summarizer._github_models_text('p') is None
    assert post.call_count == len(summarizer.GITHUB_MODELS_ENDPOINTS)   # each endpoint is tried once per run


def test_extract_article_text_keeps_paragraphs_and_skips_menus():
    long1 = 'Bloom Energy said orders doubled in the quarter, driven by data center demand across the country. '
    long2 = 'The company also raised its full year revenue guidance and expects margins to expand next year as well.'
    page = ('<nav><p>' + 'menu ' * 30 + '</p></nav><script>var x;</script>'
            f'<article><p>{long1}</p><p>short</p><p>{long2}</p><p>{long2 * 2}</p><p>{long1}</p></article><footer><p>{long1}</p></footer>')
    text = summarizer.extract_article_text(page, limit=1000)
    assert text.count('orders doubled') == 1 and 'menu' not in text and 'guidance' in text
    assert summarizer.extract_article_text('<p>too short to be an article</p>') == ''


def test_prompt_asks_for_five_lines_when_the_body_is_known():
    prompt = summarizer.build_prompt([{'title': 'T1', 'snippet': ''}, {'title': 'T2', 'snippet': 'S2'}], {0: 'BODY TEXT'})
    assert '본문: BODY TEXT' in prompt and '5~7줄' in prompt
    assert prompt.count('본문:') == 1


def test_parse_summaries_turns_line_lists_into_bullets():
    parsed = summarizer.parse_ai_summaries('[["가", "나", "다"], "한 줄"]', 2)
    assert parsed == ['• 가\n• 나\n• 다', '한 줄']
    assert summarizer.parse_ai_summaries('[["가"], 3]', 2) is None
    assert summarizer.parse_ai_summaries('[["가"]]', 1) == ['가']


def test_body_based_summary_is_marked_and_not_published(monkeypatch):
    monkeypatch.setattr(summarizer, 'ANTHROPIC_API_KEY', 'k')
    monkeypatch.setattr(summarizer, 'fetch_article_text', lambda url: 'FULL TEXT' if url == 'u1' else '')
    monkeypatch.setattr(summarizer, 'fetch_page_description', lambda url: '')
    seen = {}
    monkeypatch.setattr(summarizer, 'ai_text', lambda prompt: seen.setdefault('p', prompt) and '[["가", "나", "다", "라", "마"], ["제목 요약"]]')
    group = [{'title': 'a', 'url': 'u1', 'snippet': ''}, {'title': 'b', 'url': 'u2', 'snippet': ''}]
    summarizer.add_summaries([group])
    assert [a['summary_basis'] for a in group] == ['body', 'title']
    assert group[0]['summary'].count('•') == 5
    assert 'body' not in group[0] and 'FULL TEXT' in seen['p']


def test_long_groups_are_split_into_batches(monkeypatch):
    sizes = []
    monkeypatch.setattr(summarizer, 'ai_summaries', lambda group, bodies=None: sizes.append(len(group)))
    group = [{'title': str(i), 'url': f'u{i}', 'snippet': 's'} for i in range(summarizer.BATCH_SIZE + 2)]
    summarizer.add_summaries([group], fetch_pages=False)
    assert sizes == [summarizer.BATCH_SIZE, 2]


def test_unresolvable_google_link_gives_no_text(monkeypatch):
    monkeypatch.setattr(summarizer.requests, 'get', MagicMock(side_effect=RuntimeError('429')))
    assert summarizer.resolve_google_news_url('https://news.google.com/rss/articles/AbC?oc=5') == ''
    assert summarizer.fetch_article_text('https://news.google.com/rss/articles/AbC?oc=5') == ''
