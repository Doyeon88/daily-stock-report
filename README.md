# daily-stock-report

관심 종목의 전일 종가와 등락률, 오늘의 이상 신호를 매일 아침 모바일 푸시 알림(Firebase Cloud Messaging)으로 보내줍니다.
알림을 탭하면 시장 지수, 종목별 상세 지표, 뉴스, SEC 공시가 담긴 리포트 페이지가 열립니다.

- 추적 종목·실행 시각·이벤트: `watchlist.json` 한 곳에서 수정 (현재 BE, EROC, INNIO, CAT, FPS, NBIS, CRCL, BWXT, 매일 07:00 KST·화~토)
- 데이터: yfinance(가격·지표), Google News RSS와 Finnhub(뉴스), SEC EDGAR 또는 Yahoo Finance(공시)
- 알림: Firebase Cloud Messaging, 리포트 페이지: GitHub Pages(`docs/`)
- 실행: GitHub Actions 스케줄(권장), 또는 로컬 cron / 작업 스케줄러

## 빠른 시작

```bash
pip install -r requirements.txt
cp .env.example .env      # FIREBASE_CREDENTIALS, FCM_DEVICE_TOKEN 입력
python main.py
```

Firebase 설정, GitHub Actions Secret 등록, 자동화 방법은 [SETUP_GUIDE.md](SETUP_GUIDE.md)를 참고하세요.

## 설정 바꾸기

| 하고 싶은 것 | 방법 |
|---|---|
| 종목 추가·삭제, 경쟁사, 회사명 | `watchlist.json`의 `tickers` (티커가 비슷한 회사에 주의: EROC ≠ EROK ≠ ERO) |
| 실행 시각·요일 (KST) | `watchlist.json`의 `report_time`, `report_days` 수정 → `python scripts/sync_schedule.py` → 커밋·푸시 (워크플로 cron이 UTC로 자동 변환됨. GitHub cron은 몇 분 늦을 수 있음) |
| 시나리오 EPS 대비 밸류에이션 | 종목에 `scenario_eps`(`{"2027": 0.65, ...}`)와 최상위 `valuation_multiples` |
| 이벤트 캘린더(D-day), 종목별 체크리스트 | `events`, `checklist`. 출처가 불확실한 일정은 `"verified": false`로 두면 '?미검증'으로 표시 |
| 정책·규제 검색어 | `policy_queries` |
| 내 포트폴리오 | `portfolio.example.json`을 `portfolio.json`으로 복사해 수정 (git 제외). GitHub Actions에서는 `PORTFOLIO_JSON` Secret에 같은 JSON |

**포트폴리오 공개 범위:** 이 저장소는 공개라서 리포트 JSON(`report-data` 브랜치)도 공개됩니다. 기본값은 종목별 수익률(%)·비중(%)만 올리고 수량·평단·금액은 올리지 않습니다. 비중과 수익률만으로도 보유 사실은 드러나므로, 숨기고 싶으면 저장소를 비공개로 바꾸거나 `PORTFOLIO_JSON` Secret을 만들지 마세요.

## 리포트 페이지 사용법

맨 위 탭에서 **전체**(헤드라인·지수·신호·캘린더·포트폴리오·가격표·정책·관심 종목 리스크)와 **종목별**을 전환합니다. 종목 탭에는 현재가, 지표, **기사**(링크+요약),
**리포트·공시**(애널리스트 의견 변경과 공시, 링크+한 줄 설명·보도자료 요약), 실적 서프라이즈, 내부자 거래, 희석 점검, 옵션 기대 변동, 기술적 신호, 밸류에이션, 컨센서스, 13F, 체크리스트가 모여 있습니다.

- **기사 요약:** `ANTHROPIC_API_KEY` Secret이 있으면 Claude가, 없거나 실패하면 GitHub Models(Actions 자동 토큰, 별도 키 없음, 무료 한도 내, 모델은 `GITHUB_MODELS_MODEL`로 변경)가 한국어로 요약합니다(`AI 요약`). 본문을 읽은 기사는 5~7줄, 못 읽은 기사는 제목·발췌 범위의 1~2줄입니다. 둘 다 안 되면 기사 발췌문을 그대로 보여 주고(`기사 발췌`), 발췌문도 없으면 제목만 나옵니다. 언론 기사라 '?미검증' 표시는 그대로입니다. 모델은 `ANTHROPIC_MODEL`(기본 claude-haiku-5-5)로 바꿉니다.
- **AI 의견:** 헤드라인·정책·종목 기사·애널리스트 리포트·공시 보도자료, 그리고 새 항목(실적·내부자·공시·희석·옵션·기술적 신호·13F·관심 종목 리스크) 맨 끝에 주황색 `AI 의견` 줄이 붙습니다. 요약(사실)과 달리 앞으로의 진행·시기 전망과 관심 종목별 호재/악재·이유를 AI가 추정한 것이라 참고용입니다(예: "하원 표결과 대통령 서명이 남아 1월 시행이 유력해 보인다. 물을 쓰지 않고 NOx 배출이 거의 없는 연료전지의 BE에 호재"). AI가 동작하지 않으면 붙지 않습니다.
- **리포트:** 증권사 리포트 원문은 무료로 가져올 수 없어서, 목표가·투자의견을 다룬 기사와 Yahoo가 집계한 투자의견·목표가 변경을 보여 줍니다. 공시는 원문 링크와 양식 설명이고, 8-K는 공시 본문에서 읽은 항목(실적 발표·주요 계약 등), 보도자료(EX-99.1)가 있으면 그 AI 요약을 함께 보여 줍니다.

## 리포트 구성

시장 요약(지수) · 종목 카드(가격·지표, **호재/중립/악재** 태그, ✔검증/?미검증 표시) · 공시 감시(8-K·6-K 항목, 10-Q/10-K, S-1·S-3·424B 발행 서류, Form 4 건수, 13D/G) ·
애널리스트 투자의견·목표가 변경과 EPS 컨센서스 변화 · 13F 기관 보유(제출 기한 전후 시즌에만) · 정책·규제 뉴스 ·
이벤트 캘린더(D-day) · 시나리오 EPS 대비 밸류에이션 · 포트폴리오 · 다음 이벤트 체크리스트.

추가 항목(모두 무료 Yahoo Finance 데이터, 키 없음):

| 항목 | 내용 |
|---|---|
| 실적 서프라이즈·발표 후 반응 | 최근 8분기 EPS 예상/실제/서프라이즈와 발표를 소화한 첫 거래일 등락(장 마감 후 발표는 다음 날) |
| 내부자 장내 매매(Form 4) | 최근 90일 매수·매도 금액과 순매수, 30일 안에 2명 이상 매수하면 **클러스터 매수**. 주식보상·옵션 행사는 제외. 10b5-1 계획 여부는 Yahoo에 없음 |
| 희석·자금조달 점검 | 최근 180일 발행 서류(S-3·424B5 등), 발행주식 증가율, 현금 ÷ 분기 소진액 = 런웨이(추정). 위험 높음/주의/낮음 |
| 옵션 기대 변동 | 실적이 45일 안이면 발표 직후 만기의 ATM 스트래들로 "시장 기대 변동 ±x%", 풋/콜 비율, 이상 거래 |
| 기술적 신호·리스크 | MACD·볼린저·50일선·50/200일선 교차·ATR 라벨, 연 변동성·최대낙폭·QQQ 대비 베타. 전체 탭에 상관 0.6 이상 종목 쌍 |
| 데이터 부족 표시 | 종목 탭 가격 아래에 비어 있는 항목을 표시(AI 의견이 빈약한 자료에 기댄 것인지 확인용) |

오늘의 신호에는 골든·데드크로스, 희석 위험 높음, 임원 클러스터 매수, 7일 안 실적의 옵션 기대 변동이 추가로 올라옵니다.

- 기사 태그는 AI가 기사를 읽고 판정한 값(`AI 판정` 표시)을 쓰고, AI를 못 쓰면 키워드 자동 분류로 대신합니다(참고용). ✔검증은 공시·거래소(Yahoo) 데이터, ?미검증은 언론 헤드라인과 직접 입력한 일정입니다.
- 13F는 분기 말 기준의 지연 데이터이고 롱 포지션만 나오며 인덱스·패시브 자금이 섞입니다. 특정 기관의 신규 보유 여부는 SEC 원문(13F-HR, Schedule 13G/13D)으로 확인하세요.
- 옵션·분기 재무는 Yahoo 비공식 자료입니다. 소형주는 옵션 호가가 얇아 값이 튈 수 있고, 런웨이는 추정입니다.
- 커뮤니티 글은 수집하지 않습니다.

## 구조

| 경로 | 역할 |
|---|---|
| `main.py` | 수집 → 리포트 생성 → 알림 전송. 가격 수집 전부 실패나 알림 미전달 시 종료 코드 1 |
| `scrapers/` | 데이터 수집: `yfinance_scraper`(가격), `stock_details`(지표), `news_scraper`, `sec_filings`(8-K 항목·보도자료), `competitor_scraper`, `analyst_changes`, `institutional`(13F), `policy_tracker`, `earnings_history`, `insiders`(Form 4), `dilution`, `options_activity`, `price_history`, `summarizer`(요약·AI 의견) |
| `processors/` | 리포트 생성과 신호 계산(`report_generator`), 페이지용 데이터(`report_payload`), `tagging`, `valuation`, `portfolio`, `calendar_events`, `signals`(기술적 신호·리스크), `opinion_material`(AI 의견 재료), `data_quality` |
| `notifications/` | FCM 푸시 알림(`fcm_notifier`), 상세 리포트 저장(`report_publisher`) |
| `docs/` | GitHub Pages: 토큰 발급 페이지(`index.html`), 리포트 페이지(`report.html`) |
| `scheduler/` | 로컬 스케줄러 (`python scheduler/daily_task.py`) |
| `scripts/sync_schedule.py` | `watchlist.json`의 실행 시각을 GitHub Actions cron에 반영 |
| `watchlist.json` / `portfolio.example.json` | 종목·시각·이벤트 설정 / 포트폴리오 양식 |
| `tests/` | 단위 테스트 (`pip install -r requirements-dev.txt && pytest`) |

## 현재 상태

구현됨: 가격·등락률, 시간외 변동, 거래량·52주 범위·이동평균·RSI·공매도·애널리스트 목표가·실적일, 경쟁사와 시장 지수 비교,
뉴스 헤드라인, SEC 공시, 이상 신호 알림, 리포트 페이지. 소스 하나가 실패해도 나머지 리포트는 나갑니다.
미구현 (`main.py`의 TODO): CEO 활동 모니터링, 재무제표.

## 종목 탭의 핵심 5가지·애널리스트 리포트

- **핵심 5가지:** 종목별로 수집한 뉴스 제목·발췌, 애널리스트 의견 변경, 컨센서스, 공시를 AI가 한국어 최대 5문장으로 정리합니다(자료에 없는 내용은 쓰지 않도록 지시). AI를 못 쓰면 수치만으로 만든 요약이 나오고 `수치 요약(자동)`으로 표시됩니다.
- **애널리스트 리포트:** 증권사 리포트 원문은 가져올 수 없어서, 목표가·투자의견을 다룬 기사(링크+요약)와 Yahoo 집계 의견 변경(Yahoo 분석 페이지 링크)을 보여 줍니다.
- 요약은 모두 한국어로 만들지만 AI가 동작해야 합니다. AI가 안 되면 영문 발췌가 그대로 나옵니다. GitHub Models 주소는 두 개를 차례로 시도하고 로그에 사용 결과를 남깁니다.

## 오늘의 헤드라인 · 리포트 선별

- **헤드라인(전체 탭 맨 위)**: 최근 24시간 시황·경제·원자재·여론·정치 뉴스에서 주가에 영향을 줄 속보 3~5개. 소스는 Finnhub 일반뉴스(키가 있을 때), CNBC·MarketWatch RSS, 연준 보도자료, Google News 주제 검색입니다. 속보 단어·최신성 점수로 후보 40개를 추리고 AI가 중요도 순으로 고릅니다(한글 제목·핵심 이유·본문 요약). AI를 못 쓰면 점수 상위 기사를 영어 제목 그대로 보여 줍니다. 기사 기반이라 '미검증' 표시입니다.
- **뉴스**: 종목별 최근 3일 기사만.
- **리포트(애널리스트 기사)**: 종목별 최신 후보 16건(최근 30일) 중 본문을 읽을 수 있는 기사만 요약하고, 5줄 이상 요약되는 최신 3개만 남깁니다(미달이면 3개보다 적게 보임).

## 컨센서스 (종목 탭)
- 올해·내년의 매출·EPS(평균, 낮음~높음)와 PER, 애널리스트 목표주가(평균·중앙·높음·낮음)를 Yahoo 집계로 보여 줍니다.
- Yahoo는 내년까지만 제공해 2028년 등은 '자료 없음'입니다. 직접 알고 있는 값은 `watchlist.json`의 종목에 `"consensus_manual": {"2028": {"revenue_m": 3100, "eps": 5.2, "source": "출처"}}` 로 넣으면 '직접 입력'으로 표시됩니다(revenue_m은 백만 달러).
