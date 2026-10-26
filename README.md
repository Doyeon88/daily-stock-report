# daily-stock-report

관심 종목의 전일 종가와 등락률을 매일 아침 모바일 푸시 알림(Firebase Cloud Messaging)으로 보내줍니다.

- 추적 종목: `config.py`의 `STOCKS_TO_TRACK` (현재 BE, BWXT, CRCL, SECZ)
- 데이터: yfinance (API 키 불필요)
- 알림: Firebase Cloud Messaging
- 실행: GitHub Actions 스케줄(권장), 또는 로컬 cron / 작업 스케줄러

## 빠른 시작

```bash
pip install -r requirements.txt
cp .env.example .env      # FIREBASE_CREDENTIALS, FCM_DEVICE_TOKEN 입력
python main.py
```

Firebase 설정, GitHub Actions Secret 등록, 자동화 방법은 [SETUP_GUIDE.md](SETUP_GUIDE.md)를 참고하세요.

## 구조

| 경로 | 역할 |
|---|---|
| `main.py` | 수집 → 리포트 생성 → 알림 전송. 실패 시 종료 코드 1 |
| `scrapers/` | 데이터 수집 (현재 `yfinance_scraper`만 구현) |
| `processors/` | 리포트 생성 |
| `notifications/` | FCM 푸시 알림 |
| `scheduler/` | 로컬 스케줄러 (`python scheduler/daily_task.py`) |
| `tests/` | 단위 테스트 (`pip install -r requirements-dev.txt && pytest`) |

## 현재 상태

구현됨: 주가·등락률 수집, 리포트 생성, 푸시 알림.
미구현 (`main.py`의 TODO): 재무제표, 뉴스, 공매도 잔고, CEO 활동, 기술적 지표, 경쟁사 비교.
