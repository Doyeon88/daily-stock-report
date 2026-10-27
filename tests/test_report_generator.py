"""
Unit tests for processors/report_generator.py
"""

from processors import report_generator


def test_generate_report_all_success():
    stock_data = {
        'AAPL': {
            'ticker': 'AAPL', 'price': 105.0, 'previous_close': 100.0,
            'change': 5.0, 'change_percent': 5.0, 'volume': 1000, 'error': None,
        },
        'MSFT': {
            'ticker': 'MSFT', 'price': 90.0, 'previous_close': 95.0,
            'change': -5.0, 'change_percent': -5.26, 'volume': 2000, 'error': None,
        },
    }

    report = report_generator.generate_report(stock_data)

    assert report['stocks_count'] == 2
    assert report['summary'] == '2/2 stocks updated successfully'
    assert any('AAPL' in insight for insight in report['insights'])
    assert any('MSFT' in insight for insight in report['insights'])
    assert 'timestamp' in report
    assert report['title'] == '📈 Daily Stock Report'


def test_generate_report_partial_failure():
    stock_data = {
        'AAPL': {
            'ticker': 'AAPL', 'price': 105.0, 'previous_close': 100.0,
            'change': 5.0, 'change_percent': 5.0, 'volume': 1000, 'error': None,
        },
        'BAD': {
            'ticker': 'BAD', 'price': None, 'previous_close': None,
            'change': None, 'change_percent': None, 'volume': None,
            'error': 'network error',
        },
    }

    report = report_generator.generate_report(stock_data)

    assert report['stocks_count'] == 2
    assert report['summary'] == '1/2 stocks updated successfully'
    assert any('BAD' in insight and 'unavailable' in insight for insight in report['insights'])


def test_generate_report_empty():
    report = report_generator.generate_report({})

    assert report['stocks_count'] == 0
    assert report['summary'] == 'No stocks tracked'
    assert report['insights'] == []


def test_generate_report_timestamp_is_in_configured_timezone():
    report = report_generator.generate_report({})

    assert report['timestamp'].endswith('+09:00')  # config.TIMEZONE is Asia/Seoul


def _quiet_details():
    return {'rsi14': 50.0, 'volume_ratio': 1.0, 'range_position': 50.0, 'after_hours_change': 0.5,
            'days_to_earnings': 30, 'earnings_date': '2026-11-26', 'short_percent_float': 5.0}


def test_build_flags_picks_out_unusual_values():
    from datetime import date
    stock_data = {'BE': {}, 'BWXT': {}, 'CRCL': {}, 'SECZ': {}}
    details = {
        'BE': {**_quiet_details(), 'rsi14': 23.4, 'volume_ratio': 1.8, 'after_hours_change': 7.7},
        'BWXT': {**_quiet_details(), 'rsi14': 74.0, 'range_position': 97.0,
                 'days_to_earnings': 7, 'earnings_date': '2026-11-03'},
        'CRCL': {**_quiet_details(), 'days_to_earnings': 0, 'earnings_date': '2026-10-27',
                 'short_percent_float': 16.2, 'range_position': 2.0},
        'SECZ': _quiet_details(),
    }
    filings = {'BWXT': {'filings': [{'form': '8-K', 'date': '2026-10-26', 'label': '실적 발표'}]}}

    flags = report_generator.build_flags(stock_data, details, filings, today=date(2026, 10, 27))

    assert flags == [
        'BE 시간외 +7.7%', 'BE 거래량 1.8배', 'BE RSI 23 과매도',
        'BWXT RSI 74 과열', 'BWXT 52주 고점 근처', 'BWXT 실적 발표 11-03 (D-7)', 'BWXT 8-K 10-26 실적 발표',
        'CRCL 52주 저점 근처', 'CRCL 실적 발표 10-27 (오늘)', 'CRCL 공매도 16%',
    ]


def test_build_flags_is_empty_on_a_quiet_day_and_without_data():
    from datetime import date
    today = date(2026, 10, 27)

    assert report_generator.build_flags({'A': {}}, {'A': _quiet_details()}, {}, today) == []
    assert report_generator.build_flags({'A': {}}, {}, {}, today) == []


def test_old_8k_and_other_forms_are_not_flagged():
    from datetime import date
    filings = {'A': {'filings': [
        {'form': '8-K', 'date': '2026-10-20', 'label': '실적 발표'},      # older than 3 days
        {'form': '10-Q', 'date': '2026-10-27', 'label': ''},              # not an 8-K
    ]}}

    assert report_generator.build_flags({'A': {}}, {}, filings, today=date(2026, 10, 27)) == []


def test_generate_report_carries_the_extra_data_and_flags():
    stock_data = {'A': {'ticker': 'A', 'price': 10.0, 'previous_close': 9.0, 'change': 1.0,
                        'change_percent': 11.11, 'volume': 1, 'error': None}}

    report = report_generator.generate_report(
        stock_data, details={'A': {'rsi14': 25.0}}, news={'A': [{'title': 'x'}]},
        filings={'A': {'filings': [], 'form4_count': 0}}, comparison={'market': []},
    )

    assert report['flags'] == ['A RSI 25 과매도']
    assert report['news'] == {'A': [{'title': 'x'}]}
    assert report['comparison'] == {'market': []}


def test_generate_report_without_extras_still_has_all_keys():
    report = report_generator.generate_report({})

    assert report['flags'] == [] and report['details'] == {} and report['news'] == {}
    assert report['filings'] == {} and report['comparison'] == {}


def _reddit(mentions, previous, rank=30):
    return {'rank': rank, 'mentions': mentions, 'upvotes': 50, 'rank_24h_ago': rank, 'mentions_24h_ago': previous}


def test_reddit_surge_is_flagged_only_when_big_and_not_just_noise():
    from datetime import date
    today = date(2026, 10, 27)
    stock_data = {'A': {}, 'B': {}, 'C': {}, 'D': {}, 'E': {}}
    reddit = {
        'A': _reddit(25, 10),     # 2.5x and plenty of mentions -> flagged
        'B': _reddit(16, 10),     # only 1.6x -> normal chatter
        'C': _reddit(5, 1),       # 5x but under 10 mentions -> noise
        'D': _reddit(12, 0),      # appeared from nothing with 12 mentions -> flagged
        'E': None,                # not ranked at all
    }

    flags = report_generator.build_flags(stock_data, {}, {}, today, reddit=reddit)

    assert flags == ['A 레딧 언급 급증 (25회, 24시간 전 10회)', 'D 레딧 언급 급증 (12회, 24시간 전 0회)']


def test_generate_report_carries_reddit_and_its_flag():
    stock_data = {'A': {'ticker': 'A', 'price': 10.0, 'previous_close': 9.0, 'change': 1.0,
                        'change_percent': 11.11, 'volume': 1, 'error': None}}
    reddit = {'A': _reddit(30, 10), 'B': None}

    report = report_generator.generate_report(stock_data, reddit=reddit)

    assert report['reddit'] == reddit
    assert report['flags'] == ['A 레딧 언급 급증 (30회, 24시간 전 10회)']
    assert report_generator.generate_report({})['reddit'] == {}
