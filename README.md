# daily-stock-report

관심 종목의 전일 종가와 등락률, 오늘의 이상 신호를 매일 아침 모바일 푸시 알림(Firebase Cloud Messaging)으로 보내줍니다.
알림을 탭하면 시장 지수, 종목별 상세 지표, 뉴스, SEC 공시가 담긴 리포트 페이지가 열립니다.

- 추적 종목: `config.py`의 `STOCKS_TO_TRACK` (현재 BE, BWXT, CRCL, SECZ)
- 데이터: yfinance(가격·지표), Google News RSS와 Finnhub(뉴스), SEC EDGAR 또는 Yahoo Finance(공시), ApeWisdom(레딧 언급량)
- 알림: Firebase Cloud Messaging, 리포트 페이지: GitHub Pages(`docs/`)
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
| `main.py` | 수집 → 리포트 생성 → 알림 전송. 가격 수집 전부 실패나 알림 미전달 시 종료 코드 1 |
| `reddit_snapshot.py` | 레딧 언급 기록만 남기는 매일 실행용(알림 없음), `Reddit Snapshot` 워크플로가 호출 |
| `scrapers/` | 데이터 수집: `yfinance_scraper`(가격), `stock_details`(지표), `news_scraper`, `sec_filings`, `reddit_mentions`, `competitor_scraper` |
| `processors/` | 리포트 생성과 신호 계산(`report_generator`), 페이지용 데이터(`report_payload`), 레딧 기록과 일별·주별 계열(`reddit_history`) |
| `notifications/` | FCM 푸시 알림(`fcm_notifier`), 상세 리포트 저장(`report_publisher`), 레딧 기록 파일(`history_store`) |
| `docs/` | GitHub Pages: 토큰 발급 페이지(`index.html`), 리포트 페이지(`report.html`) |
| `scheduler/` | 로컬 스케줄러 (`python scheduler/daily_task.py`) |
| `tests/` | 단위 테스트 (`pip install -r requirements-dev.txt && pytest`) |

## 현재 상태

구현됨: 가격·등락률, 시간외 변동, 거래량·52주 범위·이동평균·RSI·공매도·애널리스트 목표가·실적일, 경쟁사와 시장 지수 비교,
뉴스 헤드라인, SEC 공시, 레딧 언급량과 추세 그래프(일별 3개월·주별 52주, 기록은 켜진 날부터 쌓임), 이상 신호 알림, 리포트 페이지.
소스 하나가 실패해도 나머지 리포트는 나갑니다.
미구현 (`main.py`의 TODO): CEO 활동 모니터링, 재무제표.
