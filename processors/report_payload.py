"""
Serialize a report for the report page (docs/report.js)

Two sizes: the core payload always fits in the notification link (FCM allows ~4KB per message),
the full payload carries everything and is stored as JSON (notifications.report_publisher).
"""

from typing import Dict, List

MAX_ERROR_LENGTH = 80
MAX_CORE_FLAGS = 12


def build_rows(report: Dict) -> List[List]:
    """One row per ticker: [ticker, price, previous_close, change, change_percent, volume, error]"""
    rows = []
    for ticker, data in (report.get('stock_data') or {}).items():
        error = str(data['error'])[:MAX_ERROR_LENGTH] if data.get('error') else None
        rows.append([
            ticker, data.get('price'), data.get('previous_close'), data.get('change'),
            data.get('change_percent'), data.get('volume'), error,
        ])
    return rows


def build_core_payload(report: Dict) -> Dict:
    """Price table and signals only (v1)"""
    return {
        'v': 1,
        't': report.get('timestamp', ''),
        's': build_rows(report),
        'g': (report.get('flags') or [])[:MAX_CORE_FLAGS],
    }


def build_full_payload(report: Dict) -> Dict:
    """Everything the page can show (v2)"""
    return {
        'v': 2,
        't': report.get('timestamp', ''),
        's': build_rows(report),
        'g': report.get('flags') or [],
        'details': report.get('details') or {},
        'news': report.get('news') or {},
        'filings': report.get('filings') or {},
        'comparison': report.get('comparison') or {},
        'reddit': report.get('reddit') or {},
    }
