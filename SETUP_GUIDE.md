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
- Python 3.10 또는 3.11 (GitHub Actions는 3.11 사용). 3.12 이상은 `pandas==2.0.3`/`numpy==1.24.3`
  핀 버전의 설치 파일이 없어 `pip install`이 실패합니다.
- Git
- Firebase 계정
- 여러 API 키 (아래 참조)

### 설치 확인
```bash
python --version
git --version
```

---

## 📥 저장소 클론

```bash
git clone https://github.com/Doyeon88/daily-stock-report.git
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

> 현재 리포트는 아래 API 키 없이도 실행됩니다. 가격·상세 지표·경쟁사 비교는 yfinance(키 불필요),
> 뉴스는 Google News RSS(키 불필요)를 씁니다. 키가 있으면 더 좋아지는 선택 항목은 Finnhub(뉴스)와
> `SEC_USER_AGENT`(SEC 공시)이고, 나머지 키(Alpha Vantage, FMP, NewsAPI, Twitter)는 아직 쓰이지 않습니다.
> 필수는 아래 Firebase 설정입니다.

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

`FIREBASE_CREDENTIALS`에는 키 파일 경로(로컬 실행) 또는 키 JSON 내용 자체(GitHub Actions Secret)를 넣을 수 있습니다.

### 3. 추적할 종목 설정
`config.py` 편집:
```python
STOCKS_TO_TRACK = [
    'BE',      # Bloom Energy
    'BWXT',    # BWX Technologies
    'CRCL',    # Circle Internet Group
    'SECZ',    # Securitize
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

### 5. 단위 테스트
```bash
pip install -r requirements-dev.txt
pytest
```

---

## ⏰ 자동화 설정

### 옵션 1: GitHub Actions (서버·PC 불필요, 권장)

`.github/workflows/daily_report.yml`이 화~토 오전 9시(KST)에 자동 실행됩니다.
미국장은 KST 새벽에 마감하므로, 월~금 장 마감 결과가 다음날 아침(금요일 장은 토요일 아침)에 도착합니다.

1. 저장소 → Settings → Secrets and variables → Actions → New repository secret
2. 아래 2개를 등록
   - `FCM_DEVICE_TOKEN`: 폰의 FCM 토큰
   - `FIREBASE_CREDENTIALS`: 서비스 계정 키 `serviceAccountKey.json` 파일의 **내용 전체** (파일 경로가 아님)
3. Actions 탭 → Daily Stock Report → Run workflow 로 수동 실행해서 알림이 오는지 확인

참고:
- 종목 데이터를 하나도 못 가져왔거나 푸시 알림이 전달되지 않으면 실행이 실패(빨간 X)로 표시되고 GitHub이 실패 메일을 보냅니다. 로그의 `[FAIL]` 줄을 확인하세요.
- 알림을 탭하면 `docs/report.html`(GitHub Pages)이 열립니다.
  Pages가 켜져 있어야 하고, 푸시를 받는 페이지(토큰 발급 페이지)와 같은 주소(`REPORT_PAGE_URL`, 기본값은 이 저장소의 Pages 주소)여야 합니다.
- 공개 저장소는 60일간 활동이 없으면 스케줄 실행이 자동으로 꺼집니다. Actions 탭에서 다시 켜세요.

#### 리포트에 들어가는 내용

| 위치 | 내용 | 출처 |
|---|---|---|
| 알림 본문 | 종목별 현재가·등락률 + **오늘의 신호**(이상 항목만, 최대 8줄) | yfinance |
| 리포트 페이지 | 시장 지수(S&P 500, Nasdaq, Bitcoin), 가격 표 | yfinance |
| 종목 카드 | 시간외 변동, 거래량 배수, 52주 위치, 이동평균 대비, RSI, 5·20일 수익률, 공매도, 애널리스트 목표가, 실적 발표일, 경쟁사 등락 | yfinance |
| 종목 카드 | 최근 뉴스 헤드라인 | Finnhub(키가 있을 때) + Google News RSS |
| 종목 카드 | 최근 7일 SEC 공시(8-K, 10-Q, 10-K)와 임원 거래(Form 4) 건수 | SEC EDGAR |

신호 기준(거래량 1.5배, RSI 30/70, 시간외 ±3%, 실적 7일 이내, 공매도 15%, 52주 고저점 5%, 8-K 3일 이내)은
`processors/report_generator.py` 위쪽의 상수로 바꿀 수 있습니다. 항목 하나가 실패해도 나머지 리포트는 그대로 나갑니다.

#### 선택 설정 (GitHub Secret)

- `SEC_USER_AGENT`: SEC 공시를 보려면 필요합니다. SEC는 연락처가 없는 요청을 403으로 거절합니다.
  `daily-stock-report 내이름 me@example.com` 형태로 **일반 이메일**을 넣으세요.
  `github`가 들어간 문자열(저장소 주소, GitHub noreply 주소)도 거절됩니다. 설정하지 않으면 공시는 건너뜁니다.
- `FINNHUB_API_KEY`: https://finnhub.io 무료 키. 없으면 Google News RSS만 쓰며, 이쪽은 키워드 검색이라
  종목과 관련 없는 기사가 섞일 수 있습니다.

#### 상세 데이터 저장 (`report-data` 브랜치)

알림에는 4KB밖에 못 담아서, 뉴스와 상세 지표는 JSON 파일로 `report-data` 브랜치에 커밋해 두고 알림 링크에 그 주소를 싣습니다.
브랜치가 없거나 커밋에 실패하면 가격 표와 신호만 담은 링크로 대신하므로 알림 탭은 계속 동작합니다.
이 커밋을 위해 워크플로에 `contents: write` 권한이 있습니다. `[skip ci]`로 커밋해서 테스트나 Pages 배포를 일으키지 않습니다.

### 옵션 2: Linux/Mac (Cron)

```bash
# 크론 작업 편집
crontab -e

# 오전 9시에 매일 실행하도록 추가
0 9 * * * cd /home/user/daily-stock-report && /usr/bin/python3 main.py >> logs/cron.log 2>&1
```

### 옵션 3: Windows (Task Scheduler)

1. "작업 스케줄러" 열기
2. "기본 작업 만들기"
3. 이름: `daily-stock-report`
4. 트리거: 매일 09:00
5. 작업: 프로그램 시작
   - 프로그램: `C:\Users\YourName\daily-stock-report\venv\Scripts\python.exe`
   - 인수: `main.py`
   - 시작 위치: `C:\Users\YourName\daily-stock-report`

### 옵션 4: Python Scheduler

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

### 실행이 실패(exit code 1)로 끝남
→ 로그의 `[FAIL]` 줄 확인: 알림이 전달되지 않았거나 종목 데이터를 하나도 못 가져온 경우입니다.
→ yfinance는 Yahoo 응답 변경에 자주 깨지므로, 전부 실패하면 `pip install -U yfinance`로 최신 버전을 먼저 시도하세요.

### 알림은 오는데 탭하면 아무것도 열리지 않음
→ 알림에 링크가 없던 옛 버전으로 보낸 알림이거나, `REPORT_PAGE_URL`이 비어 있는 경우입니다.
→ 링크는 푸시를 받는 페이지(`github.io`)와 같은 호스트여야만 열립니다. 다른 주소는 Firebase SDK가 무시합니다.
→ 열렸는데 "리포트 데이터가 없습니다"가 나오면 주소 뒤의 `#...` 부분이 잘린 것입니다.
→ "상세 데이터를 불러오지 못해 핵심 표만 보여 드립니다"가 나오면 `report-data` 브랜치가 없거나 저장에 실패한 것입니다(Actions 로그의 `Failed to publish report data` 확인).

### 리포트에 뉴스나 공시가 안 보임
→ 공시: `SEC_USER_AGENT` Secret이 없거나 SEC가 거절한 경우입니다(로그의 `SEC filings skipped` / `403` 확인).
→ 뉴스: 로그의 `news unavailable` 확인. Google News RSS는 비공식이라 가끔 실패합니다. Finnhub 키를 넣으면 보완됩니다.

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