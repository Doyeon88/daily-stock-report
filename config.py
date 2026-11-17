"""
Configuration file for Daily Stock Report
"""
import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()


def _header_secret(name):
    """
    Environment value for something that is sent in an HTTP header, or None if unset/empty

    Surrounding whitespace is removed: a secret pasted into GitHub often ends with a newline,
    which HTTP headers reject ("Invalid header value").
    """
    return (os.getenv(name) or '').strip() or None


# ============================================
# API Keys
# ============================================
ALPHA_VANTAGE_API_KEY = os.getenv('ALPHA_VANTAGE_API_KEY')
FMP_API_KEY = os.getenv('FMP_API_KEY')
FINNHUB_API_KEY = _header_secret('FINNHUB_API_KEY')
NEWSAPI_KEY = os.getenv('NEWSAPI_KEY')
TWITTER_API_KEY = os.getenv('TWITTER_API_KEY')
TWITTER_API_SECRET = os.getenv('TWITTER_API_SECRET')
TWITTER_ACCESS_TOKEN = os.getenv('TWITTER_ACCESS_TOKEN')
TWITTER_ACCESS_TOKEN_SECRET = os.getenv('TWITTER_ACCESS_TOKEN_SECRET')
FIREBASE_CREDENTIALS_PATH = os.getenv('FIREBASE_CREDENTIALS', 'serviceAccountKey.json')
FCM_DEVICE_TOKEN = os.getenv('FCM_DEVICE_TOKEN')

# ============================================
# Stock Configuration (watchlist.json에서 읽음)
# ============================================
import json

WATCHLIST_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'watchlist.json')
PORTFOLIO_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'portfolio.json')

_DEFAULT_WATCHLIST = {
    'tickers': [
        {'symbol': 'BE', 'name': 'Bloom Energy', 'competitors': ['FCEL', 'PLUG', 'HYLN']},
        {'symbol': 'BWXT', 'name': 'BWX Technologies', 'competitors': ['RTX', 'LMT', 'NOC']},
        {'symbol': 'CRCL', 'name': 'Circle Internet Group', 'competitors': ['COIN', 'PYPL']},
    ],
    'market_context': [
        {'symbol': '^GSPC', 'name': 'S&P 500'},
        {'symbol': '^IXIC', 'name': 'Nasdaq'},
        {'symbol': 'BTC-USD', 'name': 'Bitcoin'},
    ],
}


def _load_json(path):
    """JSON file content, or None if the file is missing or not valid JSON"""
    try:
        with open(path, encoding='utf-8') as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def load_watchlist(path=None):
    """watchlist.json, or the built-in default when it is missing/broken/has no tickers"""
    data = _load_json(path or WATCHLIST_FILE)
    if not isinstance(data, dict) or not data.get('tickers'):
        return dict(_DEFAULT_WATCHLIST)
    return data


def load_portfolio(path=None):
    """
    Personal holdings: PORTFOLIO_JSON env (GitHub Secret) first, then portfolio.json; {} if neither.
    The report repo is public, so the numbers live in a secret or a git-ignored file, never in git.
    """
    raw = os.getenv('PORTFOLIO_JSON')
    if raw:
        try:
            data = json.loads(raw)
        except ValueError:
            data = None
    else:
        data = _load_json(path or PORTFOLIO_FILE)
    return data if isinstance(data, dict) else {}


WATCHLIST = load_watchlist()
_ENTRIES = [t for t in WATCHLIST['tickers'] if isinstance(t, dict) and t.get('symbol')]

# 추적할 종목 리스트 (티커 심볼)
STOCKS_TO_TRACK = [t['symbol'] for t in _ENTRIES]
# 경쟁사 매핑 (각 종목별 경쟁사)
COMPETITOR_MAP = {t['symbol']: list(t.get('competitors') or []) for t in _ENTRIES}
# 뉴스 검색(Google News)에 쓰는 회사명
STOCK_NAMES = {t['symbol']: t.get('name') or t['symbol'] for t in _ENTRIES}
# 사용자 시나리오 EPS: {ticker: {'2027': 0.65, ...}}
SCENARIO_EPS = {t['symbol']: t['scenario_eps'] for t in _ENTRIES if t.get('scenario_eps')}
SCENARIO_NOTES = {t['symbol']: t.get('scenario_note', '') for t in _ENTRIES if t.get('scenario_eps')}
# 시장 맥락으로 함께 보여 줄 지수 (티커, 표시 이름)
MARKET_CONTEXT = [
    (m['symbol'], m.get('name') or m['symbol']) for m in WATCHLIST.get('market_context', [])
]
VALUATION_MULTIPLES = WATCHLIST.get('valuation_multiples') or [20, 30, 40]
POLICY_QUERIES = WATCHLIST.get('policy_queries') or []
USER_EVENTS = WATCHLIST.get('events') or []
CHECKLIST = WATCHLIST.get('checklist') or {}
PORTFOLIO = load_portfolio()
# 공개 저장소에 올라가는 리포트에 금액까지 넣을지 (기본: 수익률·비중(%)만)
PORTFOLIO_PUBLISH_AMOUNTS = os.getenv('PORTFOLIO_PUBLISH_AMOUNTS') == '1'

# ============================================
# Schedule Configuration
# ============================================
# 매일 실행할 시간 (24시간 형식, KST). watchlist.json의 report_time으로 바꾸세요.
DAILY_REPORT_TIME = WATCHLIST.get('report_time') or '07:00'
# GitHub Actions 요일 (KST 기준). scripts/sync_schedule.py가 워크플로 cron으로 바꿔 줍니다.
DAILY_REPORT_DAYS = WATCHLIST.get('report_days') or 'tue-sat'

# ============================================
# Data Storage
# ============================================
DATA_DIR = 'data'
STOCK_DATA_FILE = os.path.join(DATA_DIR, 'stock_data.json')
FINANCIALS_FILE = os.path.join(DATA_DIR, 'financials.json')
NEWS_FILE = os.path.join(DATA_DIR, 'news.json')
SHORT_INTEREST_FILE = os.path.join(DATA_DIR, 'short_interest.json')
CEO_UPDATES_FILE = os.path.join(DATA_DIR, 'ceo_updates.json')
COMPETITORS_FILE = os.path.join(DATA_DIR, 'competitors.json')
TECHNICALS_FILE = os.path.join(DATA_DIR, 'technicals.json')
METRICS_FILE = os.path.join(DATA_DIR, 'metrics.json')

# ============================================
# Notification Settings
# ============================================
# Firebase FCM 푸시 알림 활성화 여부
ENABLE_FCM_NOTIFICATION = True

# 알림을 탭하면 열리는 리포트 페이지 (docs/report.html, GitHub Pages)
# 푸시를 받는 서비스 워커와 같은 호스트여야 합니다. 비워 두면 탭해도 아무것도 열리지 않습니다.
REPORT_PAGE_URL = os.getenv(
    'REPORT_PAGE_URL', 'https://doyeon88.github.io/daily-stock-report/report.html'
)

# 리포트 상세 데이터(JSON) 저장소. 알림 한도(4KB)에 다 담을 수 없어서 별도 브랜치에 커밋하고,
# 알림 링크에는 그 파일의 주소를 싣습니다. 토큰이 없으면(로컬 실행) 건너뛰고 핵심 표만 링크에 담습니다.
GITHUB_TOKEN = _header_secret('GITHUB_TOKEN')
GITHUB_REPOSITORY = os.getenv('GITHUB_REPOSITORY')  # "owner/repo", GitHub Actions가 자동으로 채움
REPORT_DATA_BRANCH = os.getenv('REPORT_DATA_BRANCH') or 'report-data'

# 이메일 설정 (선택사항)
ENABLE_EMAIL_NOTIFICATION = False
EMAIL_FROM = os.getenv('EMAIL_FROM')
EMAIL_PASSWORD = os.getenv('EMAIL_PASSWORD')

# ============================================
# Data Collection Settings
# ============================================
# 각 API별 재시도 횟수
MAX_RETRIES = 3
RETRY_DELAY = 2  # seconds

# 뉴스 수집 설정
NEWS_SOURCES = ['reuters', 'marketwatch', 'cnbc', 'bloomberg']
NEWS_LANGUAGE = 'en'
NEWS_LIMIT = 5  # 각 종목당 상위 5개 뉴스
NEWS_LOOKBACK_DAYS = 3  # 최근 3일 이내 뉴스만

# SEC EDGAR 공시 설정. SEC는 User-Agent에 연락처(이메일)를 요구하고, 없으면 403으로 거절합니다.
# 'github'가 들어간 문자열(저장소 주소, GitHub noreply 주소)도 403이므로 일반 이메일을 쓰세요.
# 영문(ASCII) 한 줄이어야 합니다(한글·줄바꿈은 HTTP 헤더에 못 담습니다. 앞뒤 공백·줄바꿈은 자동으로 지웁니다).
# 예: SEC_USER_AGENT="daily-stock-report YourName me@example.com"
# 기본값을 두지 않습니다(가짜 연락처를 보낼 수 없고, 이메일을 저장소에 올리지 않으려고).
# 설정하지 않으면 SEC 직접 조회는 건너뛰고 Yahoo Finance의 공시 목록으로 대신합니다(SEC가 클라우드 IP를
# 거절하는 GitHub Actions에서도 마찬가지). GitHub에서는 Actions Secret으로 넣으세요.
SEC_USER_AGENT = _header_secret('SEC_USER_AGENT')
SEC_LOOKBACK_DAYS = 7  # 최근 7일 이내 공시만

# CEO 모니터링 설정
CEO_TWEETS_LIMIT = 5

# ============================================
# Report Settings
# ============================================
# 리포트에 포함할 섹션
REPORT_SECTIONS = [
    'stock_price',
    'basic_metrics',
    'financials',
    'short_interest',
    'news',
    'ceo_updates',
    'technical_analysis',
    'competitor_comparison',
]

# ============================================
# Logging
# ============================================
LOG_LEVEL = 'INFO'
LOG_FILE = 'logs/daily_stock_report.log'
LOG_FORMAT = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'

# ============================================
# API Rate Limits (requests per minute)
# ============================================
ALPHA_VANTAGE_RATE_LIMIT = 5
FINNHUB_RATE_LIMIT = 60
FMP_RATE_LIMIT = 250
NEWSAPI_RATE_LIMIT = 100

# ============================================
# Timezone
# ============================================
TIMEZONE = 'Asia/Seoul'  # 한국 표준시

# 오늘의 헤드라인(전체 탭 맨 위): 시황·경제·원자재·여론·정치 중 주가에 영향을 줄 속보
HEADLINE_MIN = 3
HEADLINE_MAX = 5
HEADLINE_LOOKBACK_HOURS = 24
# 리포트(애널리스트 기사): 5줄 이상 요약되는 최신 N개만 남김
ANALYST_REPORTS_PER_TICKER = 3
