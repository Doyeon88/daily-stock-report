"""
Unit tests for scrapers/sec_filings.py (the data shapes follow the EDGAR submissions API)
"""

from datetime import date
from unittest.mock import MagicMock

import pytest

from scrapers import sec_filings

SUBMISSIONS = {
    'filings': {'recent': {
        'form':            ['8-K',           '4',          '10-Q',       '8-K',        '4/A',        'S-1'],
        'filingDate':      ['2026-10-26',    '2026-10-26', '2026-10-20', '2026-10-10', '2026-10-25', '2026-10-25'],
        'accessionNumber': ['0001-26-000001', '0001-26-000002', '0001-26-000003', '0001-26-000004',
                            '0001-26-000005', '0001-26-000006'],
        'primaryDocument': ['earnings.htm',  'form4.xml',  'q3.htm',     'old8k.htm',  'f4a.xml',    's1.htm'],
        'items':           ['2.02,9.01',     '',           '',           '5.02',       '',           ''],
    }},
}

TICKER_LIST = {
    '0': {'cik_str': 1519583, 'ticker': 'BE', 'title': 'Bloom Energy Corp'},
    '1': {'cik_str': 1486957, 'ticker': 'BWXT', 'title': 'BWX Technologies'},
}


@pytest.fixture(autouse=True)
def configured(monkeypatch):
    monkeypatch.setattr('scrapers.retry.time.sleep', lambda _: None)
    monkeypatch.setattr(sec_filings, 'SEC_USER_AGENT', 'test-agent admin@example.com')


def test_describe_items_uses_labels_skips_exhibits_and_caps_at_two():
    assert sec_filings.describe_items('2.02,9.01') == '실적 발표'
    assert sec_filings.describe_items('1.01,2.03,5.02') == '주요 계약 체결, 채무 발생'
    assert sec_filings.describe_items('9.99') == 'Item 9.99'
    assert sec_filings.describe_items('') == ''
    assert sec_filings.describe_items(None) == ''


def test_parse_recent_filings_filters_by_form_and_date():
    result = sec_filings.parse_recent_filings(SUBMISSIONS, cik=1519583, since='2026-10-20')

    assert [(f['form'], f['date'], f['label']) for f in result['filings']] == [
        ('8-K', '2026-10-26', '실적 발표'),
        ('10-Q', '2026-10-20', ''),
    ]                                    # the 8-K from 10-10 is too old, the S-1 is not a tracked form
    assert result['form4_count'] == 2    # '4' and '4/A'
    assert result['filings'][0]['url'] == (
        'https://www.sec.gov/Archives/edgar/data/1519583/000126000001/earnings.htm'
    )


def test_parse_recent_filings_works_without_an_items_column():
    submissions = {'filings': {'recent': {
        'form': ['8-K'], 'filingDate': ['2026-10-26'], 'accessionNumber': ['0001-26-000001'],
        'primaryDocument': ['a.htm'],
    }}}

    result = sec_filings.parse_recent_filings(submissions, cik=1, since='2026-10-20')

    assert result['filings'][0]['label'] == ''


def _fake_get_json(failing_url_part=None):
    def get_json(url):
        if failing_url_part and failing_url_part in url:
            raise ConnectionError('sec down')
        if url.endswith('company_tickers.json'):
            return TICKER_LIST
        return SUBMISSIONS
    return get_json


def test_fetch_sec_filings_maps_tickers_to_ciks_and_skips_unknown_ones(monkeypatch):
    get_json = MagicMock(side_effect=_fake_get_json())
    monkeypatch.setattr(sec_filings, '_get_json', get_json)

    result = sec_filings.fetch_sec_filings(['BE', 'NOPE'], today=date(2026, 10, 27))

    assert list(result) == ['BE']
    requested = [call.args[0] for call in get_json.call_args_list]
    assert 'https://data.sec.gov/submissions/CIK0001519583.json' in requested   # CIK zero-padded to 10 digits
    assert result['BE']['form4_count'] == 2


def test_one_failing_company_does_not_drop_the_others(monkeypatch):
    monkeypatch.setattr(sec_filings, '_get_json', _fake_get_json(failing_url_part='CIK0001486957'))

    result = sec_filings.fetch_sec_filings(['BE', 'BWXT'], today=date(2026, 10, 27))

    assert list(result) == ['BE']


def test_unreachable_sec_gives_an_empty_result_not_an_exception(monkeypatch):
    monkeypatch.setattr(sec_filings, '_get_json', MagicMock(side_effect=ConnectionError('blocked')))

    assert sec_filings.fetch_sec_filings(['BE'], today=date(2026, 10, 27)) == {}


def test_requests_carry_the_declared_user_agent(monkeypatch):
    response = MagicMock()
    response.json.return_value = {}
    get = MagicMock(return_value=response)
    monkeypatch.setattr(sec_filings.requests, 'get', get)
    monkeypatch.setattr(sec_filings, 'SEC_USER_AGENT', 'my-app (me@example.com)')

    sec_filings._get_json('https://data.sec.gov/x')

    assert get.call_args.kwargs['headers'] == {'User-Agent': 'my-app (me@example.com)'}


def test_without_a_user_agent_nothing_is_requested(monkeypatch):
    # SEC answers 403 to requests without a contact address, so the step is skipped instead of failing
    monkeypatch.setattr(sec_filings, 'SEC_USER_AGENT', None)
    get_json = MagicMock()
    monkeypatch.setattr(sec_filings, '_get_json', get_json)

    assert sec_filings.fetch_sec_filings(['BE'], today=date(2026, 10, 27)) == {}
    get_json.assert_not_called()
