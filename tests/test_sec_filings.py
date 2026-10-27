"""
Unit tests for scrapers/sec_filings.py (the data shapes follow the EDGAR submissions API and yfinance's sec_filings)
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

YAHOO_FILINGS = [
    {'date': date(2026, 10, 22), 'type': '10-Q', 'title': 'Periodic Financial Reports',
     'edgarUrl': 'https://finance.yahoo.com/sec-filing/BE/0001628280-26-066931_1664703'},
    {'date': '2026-10-26', 'type': '8-K', 'title': 'Corporate Changes & Voting Matters',
     'edgarUrl': 'https://finance.yahoo.com/sec-filing/BE/0001628280-26-066890_1664703'},
    {'date': date(2026, 10, 10), 'type': '8-K', 'title': 'Corporate Changes & Voting Matters',
     'edgarUrl': 'https://finance.yahoo.com/sec-filing/BE/old'},                    # too old
    {'date': date(2026, 10, 25), 'type': 'SC 13G/A', 'title': 'Ownership',
     'edgarUrl': 'https://finance.yahoo.com/sec-filing/BE/13g'},                    # not a tracked form
    {'date': date(2026, 10, 24), 'type': '10-K', 'title': 'Annual', 'edgarUrl': None},  # nothing to link to
]


@pytest.fixture(autouse=True)
def configured(monkeypatch):
    monkeypatch.setattr('scrapers.retry.time.sleep', lambda _: None)
    monkeypatch.setattr(sec_filings, 'SEC_USER_AGENT', 'test-agent admin@example.com')


@pytest.fixture
def yahoo(monkeypatch):
    """Fake yfinance: yahoo['BE'] = list of filings (or an Exception to raise); unknown tickers give Yahoo's empty {}"""
    data, requested = {}, []

    class FakeTicker:
        def __init__(self, ticker):
            self.ticker = ticker

        @property
        def sec_filings(self):
            requested.append(self.ticker)
            value = data.get(self.ticker, {})
            if isinstance(value, Exception):
                raise value
            return value

    monkeypatch.setattr(sec_filings.yf, 'Ticker', FakeTicker)
    data['requested'] = requested   # lets a test see which tickers fell back to Yahoo
    return data


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
    assert result['source'] == 'sec'
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


def test_parse_yahoo_filings_filters_sorts_and_accepts_date_objects_and_strings():
    result = sec_filings.parse_yahoo_filings(YAHOO_FILINGS, since='2026-10-20')

    assert [(f['form'], f['date']) for f in result['filings']] == [
        ('8-K', '2026-10-26'),           # newest first, a string date works...
        ('10-Q', '2026-10-22'),          # ...and so does a date object
    ]
    assert all(f['label'] == '' for f in result['filings'])    # Yahoo's 8-K category is the same for every 8-K
    assert result['filings'][1]['url'].startswith('https://finance.yahoo.com/sec-filing/BE/')
    assert result['form4_count'] == 0 and result['source'] == 'yahoo'


@pytest.mark.parametrize('empty', [{}, [], None])
def test_parse_yahoo_filings_handles_what_yahoo_returns_when_it_has_nothing(empty):
    assert sec_filings.parse_yahoo_filings(empty, since='2026-10-20')['filings'] == []


@pytest.mark.parametrize('missing_date', [None, ''])
def test_parse_yahoo_filings_ignores_an_entry_without_a_date(missing_date):
    # the string 'None' would compare as newer than any '2026-...' date and slip through the filter
    filings = [{'date': missing_date, 'type': '8-K', 'edgarUrl': 'https://finance.yahoo.com/sec-filing/BE/x'}]

    assert sec_filings.parse_yahoo_filings(filings, since='2026-10-20')['filings'] == []


def _fake_get_json(failing_url_part=None):
    def get_json(url):
        if failing_url_part and failing_url_part in url:
            raise ConnectionError('sec down')
        if url.endswith('company_tickers.json'):
            return TICKER_LIST
        return SUBMISSIONS
    return get_json


def test_sec_answers_are_used_and_yahoo_is_not_asked_for_them(monkeypatch, yahoo):
    monkeypatch.setattr(sec_filings, '_get_json', MagicMock(side_effect=_fake_get_json()))

    result = sec_filings.fetch_sec_filings(['BE', 'BWXT'], today=date(2026, 10, 27))

    assert {t: r['source'] for t, r in result.items()} == {'BE': 'sec', 'BWXT': 'sec'}
    assert yahoo['requested'] == []


def test_ticker_unknown_to_sec_falls_back_to_yahoo(monkeypatch, yahoo):
    get_json = MagicMock(side_effect=_fake_get_json())
    monkeypatch.setattr(sec_filings, '_get_json', get_json)
    yahoo['NOPE'] = YAHOO_FILINGS

    result = sec_filings.fetch_sec_filings(['BE', 'NOPE'], today=date(2026, 10, 27))

    requested = [call.args[0] for call in get_json.call_args_list]
    assert 'https://data.sec.gov/submissions/CIK0001519583.json' in requested   # CIK zero-padded to 10 digits
    assert result['BE']['source'] == 'sec' and result['BE']['form4_count'] == 2
    assert result['NOPE']['source'] == 'yahoo' and len(result['NOPE']['filings']) == 2


def test_one_failing_company_falls_back_to_yahoo_without_touching_the_others(monkeypatch, yahoo):
    monkeypatch.setattr(sec_filings, '_get_json', _fake_get_json(failing_url_part='CIK0001486957'))
    yahoo['BWXT'] = YAHOO_FILINGS

    result = sec_filings.fetch_sec_filings(['BE', 'BWXT'], today=date(2026, 10, 27))

    assert result['BE']['source'] == 'sec'
    assert result['BWXT']['source'] == 'yahoo'
    assert yahoo['requested'] == ['BWXT']


def test_unreachable_sec_falls_back_to_yahoo_for_every_ticker(monkeypatch, yahoo):
    # e.g. SEC refusing a GitHub Actions runner's IP with 403
    monkeypatch.setattr(sec_filings, '_get_json', MagicMock(side_effect=ConnectionError('403 Forbidden')))
    yahoo['BE'] = YAHOO_FILINGS

    result = sec_filings.fetch_sec_filings(['BE', 'CRCL'], today=date(2026, 10, 27))

    assert {t: r['source'] for t, r in result.items()} == {'BE': 'yahoo', 'CRCL': 'yahoo'}
    assert [f['form'] for f in result['BE']['filings']] == ['8-K', '10-Q']


def test_a_ticker_neither_source_can_answer_is_left_out(monkeypatch, yahoo):
    monkeypatch.setattr(sec_filings, '_get_json', MagicMock(side_effect=ConnectionError('down')))
    yahoo['BE'] = RuntimeError('yahoo down')
    yahoo['CRCL'] = YAHOO_FILINGS

    result = sec_filings.fetch_sec_filings(['BE', 'CRCL'], today=date(2026, 10, 27))

    assert list(result) == ['CRCL']


def test_without_a_user_agent_sec_is_not_requested_but_yahoo_still_works(monkeypatch, yahoo):
    monkeypatch.setattr(sec_filings, 'SEC_USER_AGENT', None)
    get_json = MagicMock()
    monkeypatch.setattr(sec_filings, '_get_json', get_json)
    yahoo['BE'] = YAHOO_FILINGS

    result = sec_filings.fetch_sec_filings(['BE'], today=date(2026, 10, 27))

    get_json.assert_not_called()
    assert result['BE']['source'] == 'yahoo' and len(result['BE']['filings']) == 2


@pytest.mark.parametrize('user_agent', [
    'daily-stock-report 송도연 me@example.com',     # Korean cannot be sent in an HTTP header
    'daily-stock-report\nme@example.com',           # neither can a line break
])
def test_user_agent_that_cannot_be_an_http_header_skips_sec_but_not_yahoo(monkeypatch, yahoo, user_agent):
    monkeypatch.setattr(sec_filings, 'SEC_USER_AGENT', user_agent)
    get_json = MagicMock()
    monkeypatch.setattr(sec_filings, '_get_json', get_json)
    yahoo['BE'] = YAHOO_FILINGS

    result = sec_filings.fetch_sec_filings(['BE'], today=date(2026, 10, 27))

    get_json.assert_not_called()
    assert result['BE']['source'] == 'yahoo'


def test_requests_carry_the_declared_user_agent(monkeypatch):
    response = MagicMock()
    response.json.return_value = {}
    get = MagicMock(return_value=response)
    monkeypatch.setattr(sec_filings.requests, 'get', get)
    monkeypatch.setattr(sec_filings, 'SEC_USER_AGENT', 'my-app (me@example.com)')

    sec_filings._get_json('https://data.sec.gov/x')

    assert get.call_args.kwargs['headers'] == {'User-Agent': 'my-app (me@example.com)'}


REFUSAL_PAGE = (
    '<html><head><title>SEC.gov | Request Rate Threshold Exceeded</title><style>p{color:red}</style></head>'
    '<body><h1>Request Rate Threshold Exceeded</h1><p>Automated access must comply with the Fair Access policy.</p>'
    '<script>var x = 1;</script></body></html>'
)


def _refusing_get(calls):
    def get(url, **kwargs):
        calls.append(url)
        response = MagicMock()
        response.status_code = 403
        response.text = REFUSAL_PAGE
        return response
    return get


def test_a_403_carries_the_reason_sec_gives_and_is_not_retried(monkeypatch, yahoo, caplog):
    calls = []
    monkeypatch.setattr(sec_filings.requests, 'get', _refusing_get(calls))
    yahoo['BE'] = YAHOO_FILINGS

    with caplog.at_level('ERROR'):
        result = sec_filings.fetch_sec_filings(['BE'], today=date(2026, 10, 27))

    assert len(calls) == 1                                  # asking again cannot help, so no retries
    assert result['BE']['source'] == 'yahoo'                # Yahoo took over
    assert 'Request Rate Threshold Exceeded' in caplog.text  # SEC's own words end up in the log...
    assert 'var x' not in caplog.text and '<h1>' not in caplog.text   # ...without markup or scripts


def test_refusal_for_one_company_stops_asking_sec_for_the_others(monkeypatch, yahoo):
    calls = []

    def get(url, **kwargs):
        calls.append(url)
        if url.endswith('company_tickers.json'):
            response = MagicMock(status_code=200)
            response.json.return_value = TICKER_LIST
            return response
        return _refusing_get([])(url)

    monkeypatch.setattr(sec_filings.requests, 'get', get)
    yahoo['BE'], yahoo['BWXT'] = YAHOO_FILINGS, YAHOO_FILINGS

    result = sec_filings.fetch_sec_filings(['BE', 'BWXT'], today=date(2026, 10, 27))

    assert len(calls) == 2                                  # the ticker list and the first company only
    assert {t: r['source'] for t, r in result.items()} == {'BE': 'yahoo', 'BWXT': 'yahoo'}


def test_other_errors_are_still_retried(monkeypatch, yahoo):
    get = MagicMock(side_effect=ConnectionError('reset'))
    monkeypatch.setattr(sec_filings.requests, 'get', get)

    sec_filings.fetch_sec_filings(['BE'], today=date(2026, 10, 27))

    assert get.call_count == 3                              # MAX_RETRIES: a network hiccup is worth another try
