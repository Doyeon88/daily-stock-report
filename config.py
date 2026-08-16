"""
Configuration file for Daily Stock Report
"""
import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# ============================================
# API Keys
# ============================================
ALPHA_VANTAGE_API_KEY = os.getenv('ALPHA_VANTAGE_API_KEY')
FMP_API_KEY = os.getenv('FMP_API_KEY')
FINNHUB_API_KEY = os.getenv('FINNHUB_API_KEY')
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
    'BE',      # Bloom Energy (예시)
    # 'TSLA',  # Tesla
    # 'AAPL',  # Apple
    # 추가 종목들을 여기에 입력하세요
]

# 경쟁사 매핑 (각 종목별 경쟁사)
COMPETITOR_MAP = {
    'BE': ['FCEL', 'PLUG'],  # Bloom Energy의 경쟁사
    # 'TSLA': ['NIO', 'LI'],
}

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