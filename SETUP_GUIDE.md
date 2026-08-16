# Daily Stock Report - 설정 가이드 📋

이 가이드를 따라 Daily Stock Report를 설정하고 실행하세요.

## 📋 목차

1. [환경 준비](#환경-준비)
2. [저장소 클론](#저장소-클론)
3. [Python 환경 설정](#python-환경-설정)
4. [API 키 발급](#api-키-발급)
5. [Firebase 설정](#firebase-설정)
6. [프로젝트 설정](#프로젝트-설정)
7. [테스트](#테스트)
8. [자동화 설정](#자동화-설정)

---

## 🔧 환경 준비

### 필수 요구사항
- Python 3.8 이상
- Git
- Firebase 계정
- 여러 API 키 (아래 참조)

### 설치 확인
```bash
python --version
git --version
```

---

## 📥 저���소 클론

```bash
git clone https://github.com/songdoyeon88-creator/daily-stock-report.git
cd daily-stock-report
```

---

## 🐍 Python 환경 설정

### 1. 가상환경 생성
```bash
# Windows
python -m venv venv
venv\Scripts\activate

# Mac/Linux
python3 -m venv venv
source venv/bin/activate
```

### 2. 라이브러리 설치
```bash
pip install -r requirements.txt
```

---

## 🔑 API 키 발급

### 1. Alpha Vantage (기술지표, 재무)
1. https://www.alphavantage.co/api 접속
2. 이메일로 가입
3. API 키 받기
4. **무료 사용량: 월 500회**

### 2. Financial Modeling Prep (재무제표)
1. https://financialmodelingprep.com 접속
2. 가입
3. Dashboard → API Keys
4. **무료 사용량: 월 250회**

### 3. Finnhub (뉴스, 기업정보)
1. https://finnhub.io 접속
2. Sign Up
3. Dashboard에서 API 키 복사
4. **무료 사용량: 월 60회 + 리얼타임**

### 4. NewsAPI (뉴스 수집)
1. https://newsapi.org 접속
2. Get API Key (무료)
3. 이메일 인증
4. **무료 사용량: 월 100회**

### 5. Twitter/X API (CEO 트윗)
1. https://developer.twitter.com 접속
2. Developer Portal 로그인
3. Create New App
4. Keys and Tokens 탭에서:
   - API Key
   - API Key Secret
   - Access Token
   - Access Token Secret 복사

### 6. SEC EDGAR (공시 정보)
- **API 불필요** - 공개 웹사이트
- `sec-edgar-downloader` 라이브러리 사용

---

## 🔥 Firebase 설정

### 1. Firebase 프로젝트 생성
1. https://firebase.google.com 접속
2. "시작하기" 클릭
3. 프로젝트 이름: `daily-stock-report`
4. Google Analytics 활성화 (선택)
5. 프로젝트 생성

### 2. Cloud Messaging 활성화
1. Firebase 프로젝트 대시보드
2. 좌측 메뉴 → "Cloud Messaging"
3. "시작하기" 클릭

### 3. 서비스 계정 키 생성
1. ⚙️ 설정 → "프로젝트 설정"
2. "서비스 계정" 탭
3. "새 비공개 키 생성" 클릭
4. `serviceAccountKey.json` 다운로드
5. 프로젝트 루트에 저장 (`.gitignore`에 이미 추가됨)

### 4. 디바이스 토큰 생성 (폰에서)
- Firebase 공식 앱 또는 웹 앱에서:
  - Cloud Messaging 토큰 생성
  - 이 토큰을 `.env` 파일의 `FCM_DEVICE_TOKEN`에 저장

---

## ⚙️ 프로젝트 설정

### 1. .env 파일 생성
```bash
cp .env.example .env
```

### 2. .env 파일 편집
```
# API Keys
ALPHA_VANTAGE_API_KEY=your_key_here
FMP_API_KEY=your_key_here
FINNHUB_API_KEY=your_key_here
NEWSAPI_KEY=your_key_here

# Twitter
TWITTER_API_KEY=your_key
TWITTER_API_SECRET=your_secret
TWITTER_ACCESS_TOKEN=your_token
TWITTER_ACCESS_TOKEN_SECRET=your_secret

# Firebase
FIREBASE_CREDENTIALS=serviceAccountKey.json
FCM_DEVICE_TOKEN=your_device_token_here
```

### 3. 추적할 종목 설정
`config.py` 편집:
```python
STOCKS_TO_TRACK = [
    'BE',      # Bloom Energy
    'TSLA',    # Tesla
    'AAPL',    # Apple
    # 추가...
]
```

### 4. 실행 시간 설정
`config.py`에서:
```python
DAILY_REPORT_TIME = '09:00'  # 오전 9시
TIMEZONE = 'Asia/Seoul'      # 한국 표준시
```

---

## 🧪 테스트

### 1. 환경 변수 확인
```bash
python -c "from config import *; print('Config loaded successfully')"
```

### 2. 의존성 확인
```bash
pip check
```

### 3. 테스트 실행
```bash
python main.py
```

출력:
```
============================================================
Daily Stock Report - Starting
...
Daily Stock Report - Completed successfully!
============================================================
```

### 4. 푸시 알림 테스트
```python
from notifications.fcm_notifier import send_notification

send_notification(
    title="테스트",
    body="Daily Stock Report 테스트 알림입니다"
)
```

---

## ⏰ 자동화 설정

### 옵션 1: Linux/Mac (Cron)

```bash
# 크론 작업 편집
crontab -e

# 오전 9시에 매일 실행하도록 추가
0 9 * * * cd /home/user/daily-stock-report && /usr/bin/python3 main.py >> logs/cron.log 2>&1
```

### 옵션 2: Windows (Task Scheduler)

1. "작업 스케줄러" 열기
2. "기본 작업 만들기"
3. 이름: `daily-stock-report`
4. 트리거: 매일 09:00
5. 작업: 프로그램 시작
   - 프로그램: `C:\Users\YourName\daily-stock-report\venv\Scripts\python.exe`
   - 인수: `main.py`
   - 시작 위치: `C:\Users\YourName\daily-stock-report`

### 옵션 3: Python Scheduler

```bash
# 백그라운드에서 스케줄러 실행
python scheduler/daily_task.py &

# 또는 systemd 서비스로 등록
sudo vi /etc/systemd/system/daily-stock-report.service
```

서비스 파일 내용:
```ini
[Unit]
Description=Daily Stock Report
After=network.target

[Service]
Type=simple
User=your_username
WorkingDirectory=/home/your_username/daily-stock-report
ExecStart=/home/your_username/daily-stock-report/venv/bin/python scheduler/daily_task.py
Restart=always

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable daily-stock-report
sudo systemctl start daily-stock-report
```

---

## 📝 로그 확인

```bash
# 최신 로그 보기
tail -f logs/daily_stock_report.log

# 특정 날짜의 로그
grep "2026-08-16" logs/daily_stock_report.log
```

---

## 🐛 문제 해결

### API 오류
```
Error: Invalid API key
```
→ `.env` 파일의 API 키 확인

### Firebase 오류
```
Error: Failed to initialize FCM
```
→ `serviceAccountKey.json` 위치 확인
→ `.gitignore`에 이미 추가되었으므로 안전함

### 푸시 알림 받지 못함
→ `FCM_DEVICE_TOKEN` 확인
→ Firebase 앱에서 토큰 재생성
→ 폰의 알림 권한 확인

### 종목 데이터 없음
→ 티커 심볼 정확한지 확인 (BE, TSLA 등)
→ 미국 거래소 종목만 지원
→ API 월 사용량 확인

---

## 📚 추가 리소스

- [yfinance 문서](https://pypi.org/project/yfinance/)
- [Firebase 문서](https://firebase.google.com/docs)
- [Alpha Vantage API](https://www.alphavantage.co/documentation/)
- [Finnhub API](https://finnhub.io/docs/api)

---

**설정이 완료되었습니다! 🎉**

다음 단계:
1. `main.py` 실행하여 테스트
2. 자동화 설정
3. 매일 9시에 푸시 알림 받기!