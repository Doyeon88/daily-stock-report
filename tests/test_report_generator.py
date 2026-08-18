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
