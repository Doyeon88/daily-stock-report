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
# Stock Configuration
# ============================================
# 추적할 종목 리스트 (티커 심볼)
STOCKS_TO_TRACK = [
    'BE',     # Bloom Energy - 고체산화물 연료전지(온사이트 발전)
    'BWXT',   # BWX Technologies - 원자력 부품(해군 원자로 등), 방위산업
    'CRCL',   # Circle Internet Group - 스테이블코인(USDC)·블록체인 인프라
    'SECZ',   # Securitize - 디지털 자산 토큰화 플랫폼
]

# 경쟁사 매핑 (각 종목별 경쟁사)
COMPETITOR_MAP = {
    'BE': ['FCEL', 'PLUG', 'HYLN'],           # Bloom Energy의 경쟁사 (연료전지·분산발전)
    'BWXT': ['RTX', 'LMT', 'NOC'],            # BWX Technologies의 경쟁사 (방위산업)
    'CRCL': ['COIN', 'PYPL'],                 # Circle의 경쟁사 (크립토·결제)
    'SECZ': ['COIN', 'GLXY', 'BKKT'],         # Securitize의 경쟁사 (디지털 자산 인프라)
}

# 뉴스 검색(Google News)에 쓰는 회사명
STOCK_NAMES = {
    'BE': 'Bloom Energy',
    'BWXT': 'BWX Technologies',
    'CRCL': 'Circle Internet Group',
    'SECZ': 'Securitize',
}

# 시장 맥락으로 함께 보여 줄 지수 (티커, 표시 이름)
MARKET_CONTEXT = [
    ('^GSPC', 'S&P 500'),
    ('^IXIC', 'Nasdaq'),
    ('BTC-USD', 'Bitcoin'),
]

# ============================================
# Schedule Configuration
# ============================================
# 매일 실행할 시간 (24시간 형식)
DAILY_REPORT_TIME = '09:00'  # 오전 9시

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
