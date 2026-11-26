// 푸시 알림을 탭하면 열리는 리포트 페이지의 로직.
//
// 데이터는 두 곳에서 옵니다 (notifications/fcm_notifier.py 의 _build_report_link):
//  - 주소의 # 뒤: 핵심 표와 신호만 담은 base64url JSON  {"v":1, "t", "s":[[ticker, price, prev, change, pct, volume, error]], "g":[신호...]}
//  - 주소의 ?d=<URL>: 상세 데이터(v2)를 저장해 둔 JSON 파일. 불러오지 못하면 # 뒤의 핵심 표로 대신합니다.
//    v2 = v1 + {"details", "news", "filings", "comparison", "tags", "analyst", "institutional",
//              "policy", "calendar", "valuation", "portfolio", "checklist", "earnings_history", "insiders",
//              "dilution", "options", "signals", "risk", "opinions", "data_quality"}
//    기사·헤드라인·정책·보도자료에는 "opinion"(AI 의견), opinions[ticker][항목]에는 항목별 AI 의견이 붙습니다.

// ?d= 로 받을 수 있는 주소는 이 저장소의 raw 파일로 제한합니다 (누가 만든 링크로 다른 곳의 데이터를 띄우지 못하게)
const DATA_URL_PREFIX = 'https://raw.githubusercontent.com/Doyeon88/daily-stock-report/';

const RECOMMENDATION_LABELS = {
  strong_buy: '적극 매수', buy: '매수', hold: '보유', underperform: '비중 축소', sell: '매도',
};

// ---------- 해석과 서식 (DOM 없이 시험할 수 있는 순수 함수) ----------

function decodeReportFragment(hash) {
  const encoded = String(hash || '').replace(/^#/, '');
  if (!encoded) return null;
  try {
    const b64 = encoded.replace(/-/g, '+').replace(/_/g, '/');
    const binary = atob(b64 + '='.repeat((4 - (b64.length % 4)) % 4));
    const bytes = Uint8Array.from(binary, (ch) => ch.charCodeAt(0));
    const data = JSON.parse(new TextDecoder('utf-8').decode(bytes));
    return data && (data.v === 1 || data.v === 2) && Array.isArray(data.s) ? data : null;
  } catch (e) {
    return null;
  }
}

async function loadReport(search, fragmentData, fetchFn) {
  const dataUrl = new URLSearchParams(search || '').get('d');
  if (!dataUrl) return { data: fragmentData, notice: '' };
  if (!dataUrl.startsWith(DATA_URL_PREFIX)) {
    return { data: fragmentData, notice: '상세 데이터 주소가 올바르지 않아 핵심 표만 보여 드립니다.' };
  }
  try {
    const response = await fetchFn(dataUrl);
    if (!response.ok) throw new Error('HTTP ' + response.status);
    const full = await response.json();
    if (!full || full.v !== 2 || !Array.isArray(full.s)) throw new Error('unexpected format');
    return { data: full, notice: '' };
  } catch (e) {
    return { data: fragmentData, notice: '상세 데이터를 불러오지 못해 핵심 표만 보여 드립니다.' };
  }
}

const has = (v) => v !== null && v !== undefined && v !== '' && !Number.isNaN(Number(v));
const toneOf = (n) => (n > 0 ? 'up' : n < 0 ? 'down' : '');   // 한국식: 빨강 상승, 파랑 하락
const signed = (n, digits = 1) => (Number(n) >= 0 ? '+' : '') + Number(n).toFixed(digits) + '%';
const money = (n) => '$' + Number(n).toFixed(2);
const safeUrl = (url) => (/^https?:\/\//i.test(String(url || '')) ? String(url) : null);

function formatRow(row) {
  const [ticker, price, , change, percent, volume, error] = row;
  if (error || price == null || change == null || percent == null) {
    return { ticker: String(ticker), unavailable: true, note: error ? String(error) : '데이터 없음' };
  }
  const up = Number(change) >= 0;
  return {
    ticker: String(ticker),
    unavailable: false,
    direction: up ? 'up' : 'down',
    price: '$' + Number(price).toFixed(2),
    change: (up ? '▲ ' : '▼ ') + Math.abs(Number(change)).toFixed(2),
    percent: (Number(percent) >= 0 ? '+' : '') + Number(percent).toFixed(2) + '%',
    volume: volume == null ? '-' : Number(volume).toLocaleString('en-US'),
  };
}

function formatTimestamp(iso) {
  const text = String(iso || '');
  if (text.length < 16) return '';
  const offset = text.match(/[+-]\d\d:\d\d$/);
  return text.slice(0, 16).replace('T', ' ') + (offset ? ' (UTC' + offset[0] + ')' : '');
}

function formatMarketCap(value) {
  const n = Number(value);
  return n >= 1e9 ? '$' + (n / 1e9).toFixed(1) + 'B' : '$' + (n / 1e6).toFixed(0) + 'M';
}

// 종목 카드의 "라벨: 값" 줄들. 값이 없는 항목은 건너뜁니다.
function formatDetailLines(details, peers) {
  const d = details || {};
  const lines = [];
  const add = (label, text, tone) => lines.push({ label, text, tone: tone || '' });

  if (has(d.after_hours_change)) {
    add('시간외', signed(d.after_hours_change) + (has(d.after_hours_price) ? ' (' + money(d.after_hours_price) + ')' : ''),
      toneOf(d.after_hours_change));
  }
  if (has(d.volume_ratio)) {
    add('거래량', Number(d.volume_ratio).toFixed(1) + '배 (10일 평균 대비)', d.volume_ratio >= 1.5 ? 'up' : '');
  }
  if (has(d.range_position) && has(d.year_low) && has(d.year_high)) {
    add('52주 범위', money(d.year_low) + ' ~ ' + money(d.year_high) + ' · 현재 위치 ' + Math.round(d.range_position) + '%');
  }
  if (has(d.vs_ma50) || has(d.vs_ma200)) {
    add('이동평균', [
      has(d.vs_ma50) ? '50일선 대비 ' + signed(d.vs_ma50) : null,
      has(d.vs_ma200) ? '200일선 대비 ' + signed(d.vs_ma200) : null,
    ].filter(Boolean).join(' · '));
  }
  if (has(d.rsi14)) {
    add('RSI(14)', Number(d.rsi14).toFixed(0) + (d.rsi14 <= 30 ? ' 과매도' : d.rsi14 >= 70 ? ' 과열' : ' 중립'));
  }
  if (has(d.return_5d) || has(d.return_20d)) {
    add('수익률', [
      has(d.return_5d) ? '5일 ' + signed(d.return_5d) : null,
      has(d.return_20d) ? '20일 ' + signed(d.return_20d) : null,
    ].filter(Boolean).join(' · '));
  }
  if (has(d.short_percent_float) || has(d.short_ratio)) {
    add('공매도', [
      has(d.short_percent_float) ? Number(d.short_percent_float).toFixed(1) + '% (유통주 대비)' : null,
      has(d.short_ratio) ? '청산 ' + Number(d.short_ratio).toFixed(1) + '일' : null,
      d.short_as_of ? '기준 ' + d.short_as_of : null,
    ].filter(Boolean).join(' · '));
  }
  if (has(d.target_mean)) {
    add('애널리스트', [
      '목표가 ' + money(d.target_mean) + (has(d.upside) ? ' (' + signed(d.upside) + ')' : ''),
      d.recommendation ? (RECOMMENDATION_LABELS[d.recommendation] || d.recommendation) : null,
      has(d.analyst_count) ? d.analyst_count + '명' : null,
    ].filter(Boolean).join(' · '), toneOf(d.upside));
  }
  if (d.earnings_date) {
    add('실적 발표', d.earnings_date + (has(d.days_to_earnings) ? (d.days_to_earnings === 0 ? ' (오늘)' : ' (D-' + d.days_to_earnings + ')') : ''));
  }
  if (has(d.market_cap)) add('시가총액', formatMarketCap(d.market_cap));
  if (peers && peers.length) {
    add('경쟁사', peers.map((p) => p.ticker + ' ' + signed(p.change_percent)).join(' · '));
  }
  return lines;
}

const TAGS = { '호재': 'up', '악재': 'down', '중립': '' };
const tagTone = (tag) => TAGS[tag] || '';
const verifiedMark = (verified) => (verified ? '✔검증' : '?미검증');

function formatFiling(filing) {
  return {
    text: filing.form + ' ' + String(filing.date).slice(5) + (filing.label ? ' · ' + filing.label : ''),
    url: safeUrl(filing.url),
    tag: filing.tag || '',
    verified: filing.verified === true,
  };
}

// 시나리오 EPS 밸류에이션 줄: "2027 EPS $0.65 · 현재가 기준 P/E 53.8배 · 20x $13 / 30x $19.5"
function formatValuation(valuation) {
  return ((valuation && valuation.rows) || []).map((r) => ({
    label: r.year + ' EPS',
    text: money(r.eps) + ' · 현재가 기준 P/E ' + Number(r.forward_pe).toFixed(1) + '배 · '
      + Object.keys(r.targets).map((m) => m + 'x ' + money(r.targets[m])).join(' / '),
  }));
}

function formatAnalyst(entry) {
  const lines = [];
  for (const r of (entry && entry.ratings) || []) {
    const grade = r.from_grade && r.to_grade ? r.from_grade + ' → ' + r.to_grade : r.to_grade || r.action;
    const target = has(r.target) ? ' · 목표가 ' + (has(r.prior_target) ? money(r.prior_target) + ' → ' : '') + money(r.target) : '';
    lines.push(String(r.date).slice(5) + ' ' + r.firm + ' ' + grade + target);
  }
  for (const e of (entry && entry.eps_trend) || []) {
    const parts = [has(e.change_7d_pct) ? '7일 ' + signed(e.change_7d_pct) : null,
      has(e.change_30d_pct) ? '30일 ' + signed(e.change_30d_pct) : null].filter(Boolean);
    lines.push('EPS 컨센 ' + e.label + ' ' + money(e.current) + (parts.length ? ' (' + parts.join(' · ') + ')' : ''));
  }
  return lines;
}

// 큰 금액을 $1.05B / $455.7M 형태로
function bigMoney(v) {
  if (!has(v)) return '-';
  const n = Number(v);
  if (Math.abs(n) >= 1e9) return '$' + (n / 1e9).toFixed(2) + 'B';
  return '$' + (n / 1e6).toFixed(1) + 'M';
}

// 연도별 컨센서스(매출·EPS·PER)와 목표주가. Yahoo는 올해·내년까지만 주므로 2028년은 직접 입력이 없으면 '자료 없음'
function formatConsensus(entry) {
  const lines = [];
  const rows = (entry && entry.years) || [];
  for (const r of rows) {
    const range = (lo, hi, fmt) => (has(lo) && has(hi) ? ' (' + fmt(lo) + ' ~ ' + fmt(hi) + ')' : '');
    const parts = [
      has(r.revenue) ? '매출 ' + bigMoney(r.revenue) + range(r.revenue_low, r.revenue_high, bigMoney)
        + (has(r.revenue_growth) ? ' ' + signed(r.revenue_growth * 100) : '') : null,
      has(r.eps) ? 'EPS ' + money(r.eps) + range(r.eps_low, r.eps_high, money) : null,
      has(r.per) ? 'PER ' + r.per + '배' : null,
      r.analysts ? r.analysts + '명' : null,
      r.note ? '출처: ' + r.note : null,
    ].filter(Boolean);
    lines.push(r.label + (r.fiscal_year && r.source !== 'manual' ? ' FY' + r.fiscal_year : '') + ' · ' + parts.join(' · '));
  }
  if (rows.length && !rows.some((r) => r.fiscal_year && r.fiscal_year >= 2028)) {
    lines.push('2028년 · 자료 없음 (Yahoo는 내년까지, 직접 입력하면 표시)');
  }
  const t = entry && entry.targets;
  if (t && (has(t.mean) || has(t.high))) {
    const upside = has(t.mean) && has(entry.price) && entry.price ? ' (현재가 대비 ' + signed((t.mean / entry.price - 1) * 100) + ')' : '';
    lines.push('목표주가 평균 ' + money(t.mean) + upside + ' · 중앙 ' + money(t.median)
      + ' · 높 ' + money(t.high) + ' · 낮 ' + money(t.low));
  }
  return lines;
}

function formatHolder(h) {
  return h.holder + ' ' + Number(h.shares).toLocaleString('en-US') + '주'
    + (has(h.pct_held) ? ' (' + Number(h.pct_held).toFixed(2) + '%)' : '')
    + (has(h.pct_change) ? ' · 직전 대비 ' + signed(h.pct_change) : '')
    + (h.reported ? ' · ' + h.reported : '');
}

// 매수/매도 동향용: 변화율을 앞세워 누가 얼마나 늘렸는지/줄였는지 바로 보이게 한다
function formatHolderMove(h) {
  return h.holder + ' ' + signed(h.pct_change)
    + (has(h.pct_held) ? ' · 보유 ' + Number(h.pct_held).toFixed(2) + '%' : '')
    + ' · ' + Number(h.shares).toLocaleString('en-US') + '주'
    + (h.reported ? ' · ' + h.reported : '');
}

// 금액: $1.20B / $455.7M / $12.5K / $900
function usd(v) {
  if (!has(v)) return '-';
  const n = Number(v);
  const sign = n < 0 ? '-' : '';
  const a = Math.abs(n);
  if (a >= 1e9) return sign + '$' + (a / 1e9).toFixed(2) + 'B';
  if (a >= 1e6) return sign + '$' + (a / 1e6).toFixed(1) + 'M';
  if (a >= 1e3) return sign + '$' + (a / 1e3).toFixed(1) + 'K';
  return sign + '$' + a.toFixed(0);
}

// 1번: 실적 서프라이즈와 발표 후 반응. 첫 줄은 요약, 나머지는 분기별(다음 거래일 등락으로 색 표시)
function formatEarningsHistory(entry) {
  if (!entry || !(entry.rows || []).length) return [];
  const lines = [{
    text: '최근 ' + entry.count + '회 · 예상 상회 ' + entry.beats + '회 · 하회 ' + entry.misses + '회'
      + (has(entry.avg_abs_reaction) ? ' · 발표 후 평균 변동 ±' + Number(entry.avg_abs_reaction).toFixed(1) + '%' : ''),
    tone: '',
  }];
  for (const r of entry.rows) {
    lines.push({
      text: String(r.date) + ' ' + r.timing + ' · EPS ' + (has(r.reported) ? money(r.reported) : '-')
        + ' (예상 ' + (has(r.estimate) ? money(r.estimate) : '-') + ')'
        + (has(r.surprise_pct) ? ' · 서프라이즈 ' + signed(r.surprise_pct) : '')
        + (has(r.reaction_pct) ? ' · 다음 거래 ' + signed(r.reaction_pct) : ''),
      tone: has(r.reaction_pct) ? toneOf(r.reaction_pct) : '',
    });
  }
  return lines;
}

// 2번: 내부자 장내 매매(Form 4). 순매수 요약, 클러스터 매수, 최근 거래
function formatInsiders(entry) {
  if (!entry) return [];
  const others = entry.other_count ? ' (주식보상·옵션 행사 등 ' + entry.other_count + '건 제외)' : '';
  if (!entry.buy_count && !entry.sell_count) {
    return [{ text: '최근 ' + entry.window_days + '일 장내 매수·매도 없음' + others, tone: '' }];
  }
  const lines = [{
    text: '최근 ' + entry.window_days + '일 순매수 ' + (entry.net_value > 0 ? '+' : '') + usd(entry.net_value)
      + ' · 매수 ' + entry.buy_count + '건 ' + usd(entry.buy_value) + ' · 매도 ' + entry.sell_count + '건 ' + usd(entry.sell_value) + others,
    tone: toneOf(entry.net_value),
  }];
  if (entry.cluster_buy) {
    lines.push({ text: '★ 클러스터 매수: 내부자 ' + (entry.buyers || []).length + '명이 30일 안에 장내 매수', tone: 'up' });
  }
  for (const t of entry.recent || []) {
    lines.push({
      text: (t.kind === 'buy' ? '▲ 매수 ' : '▼ 매도 ') + String(t.date).slice(5) + ' ' + t.insider
        + (t.position ? ' (' + t.position + ')' : '')
        + (has(t.shares) ? ' · ' + Number(t.shares).toLocaleString('en-US') + '주' : '')
        + (has(t.value) ? ' · ' + usd(t.value) : ''),
      tone: t.kind === 'buy' ? 'up' : 'down',
    });
  }
  return lines;
}

// 4번: 희석·자금조달. 위험 수준(높음=파랑 경고), 근거, 주식 수·현금·런웨이, 발행 서류(링크)
const DILUTION_TONES = { '높음': 'down', '주의': 'warn', '낮음': '' };
function formatDilution(entry) {
  if (!entry) return { level: '', lines: [] };
  const tone = DILUTION_TONES[entry.level] || '';
  const lines = (entry.reasons || []).map((text) => ({ text: '· ' + text, tone }));
  const parts = [
    has(entry.shares_qoq_pct) ? '발행주식 직전 분기 ' + signed(entry.shares_qoq_pct) : null,
    has(entry.shares_yoy_pct) ? '1년 ' + signed(entry.shares_yoy_pct) : null,
    has(entry.cash) ? '현금 ' + usd(entry.cash) : null,
    has(entry.quarterly_burn) ? '분기 소진 ' + usd(entry.quarterly_burn) : null,
    has(entry.runway_quarters) ? '런웨이 약 ' + entry.runway_quarters + '분기(추정)' : null,
  ].filter(Boolean);
  if (parts.length) lines.push({ text: parts.join(' · '), tone: '' });
  for (const o of entry.offerings || []) {
    lines.push({ text: o.form + ' ' + String(o.date).slice(5) + ' · ' + o.desc, url: safeUrl(o.url), tone: '' });
  }
  return { level: entry.level || '', tone, lines };
}

// 5번: 옵션 기대 변동폭과 풋/콜 비율
function formatOptions(entry) {
  if (!entry) return [];
  const which = entry.for_earnings ? '실적(' + String(entry.earnings_date).slice(5) + ') 직후 만기 ' : '만기 ';
  const lines = [{
    text: which + String(entry.expiry).slice(5) + ' · 기대 변동 ±' + entry.expected_move_pct + '%'
      + ' (ATM $' + entry.atm_strike + ' 스트래들 ' + money(entry.straddle) + ')',
    tone: '',
  }];
  const pc = entry.put_call_oi;
  const parts = [
    has(entry.iv_atm) ? 'ATM 내재변동성 ' + entry.iv_atm + '%' : null,
    has(pc) ? '풋/콜 미결제 ' + Number(pc).toFixed(2) + (pc >= 1.2 ? '(하락 대비 많음)' : pc <= 0.7 ? '(상승 베팅 많음)' : '') : null,
    has(entry.put_call_volume) ? '풋/콜 거래량 ' + Number(entry.put_call_volume).toFixed(2) : null,
  ].filter(Boolean);
  if (parts.length) lines.push({ text: parts.join(' · '), tone: has(pc) ? (pc >= 1.2 ? 'down' : pc <= 0.7 ? 'up' : '') : '' });
  for (const u of entry.unusual || []) {
    lines.push({
      text: '이상 거래 ' + u.side + ' $' + u.strike + ' · 거래량 ' + Number(u.volume).toLocaleString('en-US')
        + ' (미결제 ' + Number(u.oi).toLocaleString('en-US') + ')',
      tone: u.side === '콜' ? 'up' : 'down',
    });
  }
  return lines;
}

// 6번: 기술적 신호(라벨) + 종목 리스크(변동성·최대낙폭·베타)
function formatSignals(entry, riskRow, benchmark) {
  const lines = ((entry && entry.labels) || []).map((l) => ({ text: l.text, tone: l.tone || '' }));
  if (entry) {
    const parts = [
      has(entry.macd) ? 'MACD ' + entry.macd + ' / 시그널 ' + entry.macd_signal : null,
      has(entry.bb_pct) ? '볼린저 위치 ' + entry.bb_pct + '%' : null,
      has(entry.ma50) ? '50일선 ' + money(entry.ma50) : null,
      has(entry.ma200) ? '200일선 ' + money(entry.ma200) : null,
    ].filter(Boolean);
    if (parts.length) lines.push({ text: parts.join(' · '), tone: '' });
  }
  if (riskRow) {
    const parts = [
      has(riskRow.vol_annual) ? '연 변동성 ' + riskRow.vol_annual + '%' : null,
      has(riskRow.max_drawdown) ? '최대낙폭 ' + riskRow.max_drawdown + '%' : null,
      has(riskRow.beta) ? (benchmark || 'QQQ') + ' 대비 베타 ' + riskRow.beta : null,
    ].filter(Boolean);
    if (parts.length) lines.push({ text: parts.join(' · '), tone: '' });
  }
  return lines;
}

// 전체 탭: 관심 종목 리스크. 상관 높은 쌍(사실상 같은 베팅) 먼저, 그다음 종목별 베타·변동성·최대낙폭
function formatRisk(risk) {
  if (!risk || !risk.per_ticker) return [];
  const lines = [];
  const pairs = risk.high_corr_pairs || [];
  lines.push({
    text: pairs.length ? '함께 움직이는 쌍(상관 0.6 이상): ' + pairs.map((p) => p.a + '↔' + p.b + ' ' + p.corr).join(', ')
      : '상관 0.6 이상인 쌍 없음',
    tone: pairs.length ? 'warn' : '',
  });
  if (has(risk.avg_corr)) lines.push({ text: '종목 간 평균 상관 ' + risk.avg_corr, tone: '' });
  for (const ticker of Object.keys(risk.per_ticker)) {
    const r = risk.per_ticker[ticker];
    lines.push({
      text: ticker + ' · 베타 ' + (has(r.beta) ? r.beta : '-') + ' · 연 변동성 ' + (has(r.vol_annual) ? r.vol_annual + '%' : '-')
        + ' · 최대낙폭 ' + (has(r.max_drawdown) ? r.max_drawdown + '%' : '-')
        + ' · 기간 수익률 ' + (has(r.return_pct) ? signed(r.return_pct) : '-') + (r.days < 200 ? ' (상장 후 ' + r.days + '일)' : ''),
      tone: '',
    });
  }
  return lines;
}

// 7번: 비어 있는 자료 표시 ('' = 모두 수집됨)
function formatDataQuality(entry) {
  if (!entry || !(entry.missing || []).length) return '';
  return '데이터 부족: ' + entry.missing.join(', ') + ' (' + entry.collected + '/' + entry.total + ' 수집)';
}

function formatCalendarItem(item) {
  const dday = item.dday === 0 ? 'D-DAY' : 'D-' + item.dday;
  return {
    text: dday + ' ' + String(item.date).slice(5) + ' ' + item.label
      + (item.tickers && item.tickers.length ? ' [' + item.tickers.join(', ') + ']' : ''),
    verified: item.verified === true,
  };
}

// 포트폴리오: 금액이 있으면 금액도, 없으면 수익률·비중만
function formatPortfolio(p) {
  if (!p) return [];
  const lines = (p.positions || []).map((x) =>
    x.symbol + ' ' + (has(x.pnl_pct) ? signed(x.pnl_pct, 2) : '-') + (has(x.weight_pct) ? ' · 비중 ' + Number(x.weight_pct).toFixed(1) + '%' : '')
    + (has(x.pnl) ? ' · 평가손익 ' + (x.pnl >= 0 ? '+' : '') + '$' + Number(x.pnl).toFixed(0) : ''));
  const total = [has(p.total_pnl_pct) ? '누적 ' + signed(p.total_pnl_pct, 2) : null,
    has(p.day_pnl_pct) ? '오늘 ' + signed(p.day_pnl_pct, 2) : null].filter(Boolean).join(' · ');
  if (total) lines.unshift('합계 ' + total);
  return lines;
}

// 뉴스 시각은 브라우저 시간대와 무관하게 한국 시간(KST)으로 표시합니다.
function formatNewsTime(iso) {
  const ms = Date.parse(iso);
  return Number.isNaN(ms) ? '' : new Date(ms + 9 * 3600 * 1000).toISOString().slice(5, 16).replace('T', ' ') + ' KST';
}

function formatNews(article) {
  return {
    title: String(article.title),
    meta: [article.source, formatNewsTime(article.published)].filter(Boolean).join(' · '),
    url: safeUrl(article.url),
  };
}

// 오늘의 헤드라인 한 건: 분류·한글 제목·핵심 이유·출처/시각·본문 요약(있을 때)
function formatHeadline(h) {
  const original = h.title && h.title !== h.headline ? '원문: ' + String(h.title) : '';
  return {
    category: String(h.category || ''),
    text: String(h.headline || h.title || ''),
    why: h.why ? String(h.why) : '',
    url: safeUrl(h.url),
    meta: [h.source, formatNewsTime(h.published), '?미검증', original].filter(Boolean).join(' · '),
    summary: h.summary || '',
    label: summaryLabel(h),
    opinion: h.opinion || '',
  };
}

// 리포트 목록: 애널리스트 리포트 기사(링크+요약), 의견·목표가 변경(Yahoo 집계, 분석 페이지 링크), 공시를 날짜순으로 합칩니다.
// 증권사 리포트 원문은 가져올 수 없어 기사 제목·발췌 범위의 요약입니다. 8-K·6-K에 보도자료(EX-99.1)가 있으면 그 요약과
// AI 의견을, 없으면 양식 설명을 보여 줍니다.
function formatReportItems(analystEntry, filingInfo, ticker, analystArticles) {
  const items = [];
  for (const a of analystArticles || []) {
    items.push({
      kind: '리포트 기사', date: String(a.published || '').slice(0, 10), title: String(a.title),
      summary: a.summary || '', url: safeUrl(a.url), tag: a.tag || '', opinion: a.opinion || '',
      origin: [a.source, summaryLabel(a), a.tag_source === 'ai' ? 'AI 판정' : null, '?미검증'].filter(Boolean).join(' · '),
    });
  }
  const analysisUrl = ticker ? 'https://finance.yahoo.com/quote/' + encodeURIComponent(ticker) + '/analysis/' : null;
  for (const r of (analystEntry && analystEntry.ratings) || []) {
    const grade = r.from_grade && r.to_grade ? r.from_grade + ' → ' + r.to_grade : r.to_grade || r.action || '';
    const target = has(r.target) ? '목표가 ' + (has(r.prior_target) ? money(r.prior_target) + ' → ' : '') + money(r.target) : '';
    items.push({
      kind: '의견 변경', date: String(r.date), title: r.firm + (grade ? ' · ' + grade : ''),
      summary: [grade ? '투자의견 ' + grade : null, target || null].filter(Boolean).join(' · '),
      url: analysisUrl, tag: '', origin: 'Yahoo 집계',
    });
  }
  for (const f of (filingInfo && filingInfo.filings) || []) {
    const item = formatFiling(f);
    const press = f.press_release || null;
    items.push({
      kind: '공시', date: String(f.date), title: f.form + ' · ' + String(f.date).slice(5) + (f.label ? ' · ' + f.label : ''),
      summary: (press && press.summary) || f.summary || '', url: item.url, tag: item.tag,
      opinion: (press && press.opinion) || '', pressUrl: press ? safeUrl(press.url) : null,
      origin: '✔검증(SEC/Yahoo)' + (press && press.summary ? ' · ' + summaryLabel(press).replace('기사', '보도자료') : ''),
    });
  }
  return items.sort((x, y) => (x.date < y.date ? 1 : x.date > y.date ? -1 : 0));
}

// 종목별 핵심 5가지의 출처 표시
function keyPointsLabel(entry) {
  if (!entry || !entry.points || !entry.points.length) return '';
  return entry.source === 'ai'
    ? '핵심 ' + entry.points.length + '가지 · AI 정리(수집한 제목·발췌·수치만 근거, ?미검증)'
    : '핵심 ' + entry.points.length + '가지 · 수치 요약(자동)';
}

function summaryLabel(article) {
  if (!article.summary) return '';
  if (article.summary_source !== 'ai') return '기사 발췌';
  if (article.summary_basis === 'body') return 'AI 요약(기사 본문 기준)';
  return article.summary_basis === 'title' ? 'AI 요약(제목만 근거)' : 'AI 요약(제목·발췌 기준)';
}

// ---------- 화면 만들기 (값은 모두 textContent 로 넣어 HTML 이 끼어들 수 없게 합니다) ----------

function renderReport(doc, data) {
  const status = doc.getElementById('status');
  if (!data) {
    status.textContent = '리포트 데이터가 없습니다. 푸시 알림을 탭해서 열어 주세요.';
    return;
  }
  status.textContent = formatTimestamp(data.t);

  const element = (tag, className, text) => {
    const el = doc.createElement(tag);
    if (className) el.className = className;
    if (text !== undefined) el.textContent = text;
    return el;
  };
  const link = (text, url) => {
    if (!url) return element('span', '', text);
    const a = element('a', '', text);
    a.href = url;
    a.target = '_blank';
    a.rel = 'noopener noreferrer';
    return a;
  };
  // 항목 맨 끝의 AI 의견(전망·시기·관심 종목 영향). 사실이 아닌 AI 추정이라 따로 구분해 보여 준다.
  const addOpinion = (parent, text) => {
    if (!text) return;
    const box = element('div', 'opinion');
    box.appendChild(element('span', 'opinion-label', 'AI 의견'));
    box.appendChild(element('span', '', String(text)));
    parent.appendChild(box);
  };

  // 시장 맥락
  const market = (data.comparison && data.comparison.market) || [];
  const marketBox = doc.getElementById('market');
  for (const m of market) {
    marketBox.appendChild(element('span', 'chip ' + toneOf(m.change_percent), m.name + ' ' + signed(m.change_percent)));
  }

  // 오늘의 헤드라인(가장 먼저 읽는 속보 3~5개)
  const headlineBox = doc.getElementById('headlines');
  if (headlineBox && (data.headlines || []).length) {
    headlineBox.hidden = false;
    const ul = doc.getElementById('headline-list');
    for (const h of data.headlines) {
      const f = formatHeadline(h);
      const li = element('li', '');
      if (f.category) li.appendChild(element('span', 'cat', f.category));
      if (f.url) li.appendChild(link(f.text, f.url)); else li.appendChild(element('span', '', f.text));
      if (f.why) li.appendChild(element('div', 'why', f.why));
      li.appendChild(element('div', 'meta', f.meta));
      if (f.summary) {
        const details = element('details', 'more');
        details.appendChild(element('summary', '', '자세히 보기 · ' + f.label));
        details.appendChild(element('div', 'summary', f.summary));
        li.appendChild(details);
      }
      addOpinion(li, f.opinion);
      ul.appendChild(li);
    }
  }

  // 오늘의 신호
  const flags = data.g || [];
  if (flags.length) {
    doc.getElementById('flags').hidden = false;
    for (const flag of flags) doc.getElementById('flag-list').appendChild(element('li', '', String(flag)));
  }

  // 캘린더(D-day) · 포트폴리오 · 정책 (해당 영역이 페이지에 있을 때만)
  const fill = (id, listId, entries) => {
    const box = doc.getElementById(id);
    if (!box || !entries.length) return;
    box.hidden = false;
    const ul = doc.getElementById(listId);
    for (const e of entries) {
      const li = element('li', e.tone || '');
      if (e.url) li.appendChild(link(e.text, e.url)); else li.appendChild(element('span', '', e.text));
      if (e.summary) li.appendChild(element('div', 'summary', e.summary));
      if (e.meta) li.appendChild(element('div', 'meta', e.meta));
      addOpinion(li, e.opinion);
      ul.appendChild(li);
    }
    return box;
  };
  fill('calendar', 'calendar-list', (data.calendar || []).map((c) => {
    const f = formatCalendarItem(c);
    return { text: f.text, meta: verifiedMark(f.verified) };
  }));
  fill('portfolio', 'portfolio-list', formatPortfolio(data.portfolio).map((text) => ({ text })));
  const policyEntries = [];
  for (const group of data.policy || []) {
    for (const a of group.articles || []) {
      const n = formatNews(a);
      policyEntries.push({
        text: n.title, url: n.url, summary: a.summary || '', opinion: a.opinion || '',
        meta: [group.query, n.meta, summaryLabel(a), '?미검증'].filter(Boolean).join(' · '),
      });
    }
  }
  fill('policy', 'policy-list', policyEntries);
  const opinions = data.opinions || {};
  const riskBox = fill('risk', 'risk-list', formatRisk(data.risk));
  if (riskBox && !riskBox.hidden) addOpinion(riskBox, (opinions.__market__ || {}).risk);

  // 가격 표 (전체 탭)
  const body = doc.getElementById('rows');
  for (const row of data.s) {
    const item = formatRow(row);
    const tr = doc.createElement('tr');
    const cell = (text, className) => {
      const td = element('td', className, text);
      tr.appendChild(td);
      return td;
    };
    cell(item.ticker, 'ticker');
    if (item.unavailable) {
      const td = cell('데이터 없음 (' + item.note + ')', 'unavailable');
      td.colSpan = 4; // 좁은 화면에서 숨겨지는 '전일 대비' 열이 있어도 줄 전체를 차지한다
    } else {
      cell(item.price, 'num');
      cell(item.change, 'num chg ' + item.direction);
      cell(item.percent, 'num ' + item.direction);
      cell(item.volume, 'num');
    }
    body.appendChild(tr);
  }

  // 종목별 패널 (상세 데이터가 있을 때만) 과 최상단 탭
  const cards = doc.getElementById('cards');
  const tabs = doc.getElementById('tabs');
  const overview = doc.getElementById('panel-overview');
  const panels = [{ id: 'overview', button: null, panel: overview }];
  const details = data.details || {};
  const news = data.news || {};
  const filings = data.filings || {};
  const peers = (data.comparison && data.comparison.peers) || {};

  const select = (id) => {
    for (const p of panels) {
      const on = p.id === id;
      p.panel.hidden = !on;
      if (p.button) {
        p.button.className = p.button.className.replace(/\s*\bactive\b/, '') + (on ? ' active' : '');
        p.button.setAttribute('aria-selected', on ? 'true' : 'false');
      }
    }
  };
  const addTab = (id, label, tone, panel) => {
    const button = element('button', 'tab');
    button.setAttribute('role', 'tab');
    button.setAttribute('type', 'button');
    button.appendChild(element('span', 'tab-name', label));
    if (tone && tone.text) button.appendChild(element('span', 'tab-chg ' + tone.cls, tone.text));
    button.addEventListener('click', () => select(id));
    tabs.appendChild(button);
    panels.push({ id, button, panel });
    return button;
  };
  const overviewButton = element('button', 'tab');
  overviewButton.setAttribute('role', 'tab');
  overviewButton.setAttribute('type', 'button');
  overviewButton.appendChild(element('span', 'tab-name', '전체'));
  overviewButton.addEventListener('click', () => select('overview'));
  tabs.appendChild(overviewButton);
  panels[0].button = overviewButton;

  for (const row of data.s) {
    const ticker = String(row[0]);
    const lines = formatDetailLines(details[ticker], peers[ticker]);
    const valuationLines = formatValuation((data.valuation || {})[ticker]);
    const analystEntry = (data.analyst || {})[ticker];
    const analystLines = formatAnalyst(analystEntry);
    const inst = (data.institutional || {})[ticker] || {};
    const holders = inst.holders || [];
    const check = (data.checklist || {})[ticker];
    const filingInfo = filings[ticker] || { filings: [], form4_count: 0 };
    const articles = news[ticker] || [];
    const keyPoints = (data.key_points || {})[ticker];
    const reports = formatReportItems(analystEntry, filingInfo, ticker, (data.analyst_articles || {})[ticker]);
    const quote = formatRow(row);

    const card = element('section', 'card panel');
    card.hidden = true;

    const heading = element('h2', '', ticker);
    const overall = (data.tags || {})[ticker];
    if (overall) heading.appendChild(element('span', 'tag ' + tagTone(overall), overall));
    card.appendChild(heading);
    card.appendChild(element('div', 'quote ' + (quote.unavailable ? '' : quote.direction),
      quote.unavailable ? '데이터 없음 (' + quote.note + ')' : quote.price + ' ' + quote.change + ' (' + quote.percent + ')'));
    const gaps = formatDataQuality((data.data_quality || {})[ticker]);
    if (gaps) card.appendChild(element('div', 'meta dq', gaps));

    if (keyPoints && keyPoints.points && keyPoints.points.length) {
      const box = element('div', 'keypoints');
      box.appendChild(element('h3', '', keyPointsLabel(keyPoints)));
      const ol = element('ol', 'items');
      for (const point of keyPoints.points) ol.appendChild(element('li', '', String(point)));
      box.appendChild(ol);
      card.appendChild(box);
    }

    const list = element('dl', 'lines');
    for (const line of lines) {
      list.appendChild(element('dt', '', line.label));
      list.appendChild(element('dd', line.tone, line.text));
    }
    if (lines.length) card.appendChild(list);

    const addList = (title, entries) => {
      if (!entries.length) return;
      card.appendChild(element('h3', '', title));
      const ul = element('ul', 'items');
      for (const text of entries) ul.appendChild(element('li', '', text));
      card.appendChild(ul);
    };

    // 색으로 구분되는 매매 동향 목록 (매수=상승 톤/빨강, 매도=하락 톤/파랑)
    const addMoveList = (title, movers, tone) => {
      if (!movers.length) return;
      card.appendChild(element('h3', '', title));
      const ul = element('ul', 'items');
      const arrow = tone === 'up' ? '▲ ' : tone === 'down' ? '▼ ' : '';
      for (const h of movers) ul.appendChild(element('li', tone, arrow + formatHolderMove(h)));
      card.appendChild(ul);
    };

    // 새 항목(실적·내부자·희석·옵션·기술적 신호): 색이 있는 줄 목록 + 맨 끝 AI 의견
    const tickerOpinions = opinions[ticker] || {};
    const addSection = (title, entries, opinion) => {
      if (!entries.length) return;
      card.appendChild(element('h3', '', title));
      const ul = element('ul', 'items');
      for (const entry of entries) {
        const li = element('li', entry.tone || '');
        if (entry.url) li.appendChild(link(entry.text, entry.url)); else li.appendChild(element('span', '', entry.text));
        ul.appendChild(li);
      }
      card.appendChild(ul);
      addOpinion(card, opinion);
    };

    // 기사: 제목 링크 + 요약 + AI 의견
    if (articles.length) {
      card.appendChild(element('h3', '', '기사 (' + articles.length + ')'));
      const ul = element('ul', 'items');
      for (const article of articles) {
        const n = formatNews(article);
        const li = element('li');
        if (article.tag) li.appendChild(element('span', 'tag ' + tagTone(article.tag), article.tag));
        li.appendChild(link(n.title, n.url));
        if (article.summary) li.appendChild(element('div', 'summary', article.summary));
        const label = summaryLabel(article);
        li.appendChild(element('div', 'meta', [n.meta, label, article.tag_source === 'ai' ? 'AI 판정' : null,
          verifiedMark(article.verified === true)].filter(Boolean).join(' · ')));
        addOpinion(li, article.opinion);
        ul.appendChild(li);
      }
      card.appendChild(ul);
    }

    // 리포트: 애널리스트 의견 변경 + 공시(보도자료 요약) + 항목별 AI 의견
    if (reports.length || filingInfo.form4_count) {
      card.appendChild(element('h3', '', '애널리스트 리포트·공시 (' + reports.length + ')' + (filingInfo.source === 'yahoo' ? ' · 공시는 Yahoo Finance 제공' : '')));
      const ul = element('ul', 'items');
      for (const item of reports) {
        const li = element('li');
        li.appendChild(element('span', 'kind', item.kind));
        if (item.tag) li.appendChild(element('span', 'tag ' + tagTone(item.tag), item.tag));
        li.appendChild(link(item.title, item.url));
        if (item.pressUrl) {
          li.appendChild(element('span', '', ' · '));
          li.appendChild(link('보도자료', item.pressUrl));
        }
        if (item.summary) li.appendChild(element('div', 'summary', item.summary));
        li.appendChild(element('div', 'meta', item.date.slice(5) + ' · ' + item.origin));
        addOpinion(li, item.opinion);
        ul.appendChild(li);
      }
      if (filingInfo.form4_count) ul.appendChild(element('li', '', '임원·대주주 거래(Form 4) ' + filingInfo.form4_count + '건 (Yahoo 목록에는 없음)'));
      card.appendChild(ul);
      addOpinion(card, tickerOpinions.filings);
    }

    addSection('실적 서프라이즈·발표 후 주가 반응 (Yahoo 집계)',
      formatEarningsHistory((data.earnings_history || {})[ticker]), tickerOpinions.earnings);
    addSection('내부자 장내 매매 (Form 4 · Yahoo 집계, 10b5-1 계획 여부는 미제공)',
      formatInsiders((data.insiders || {})[ticker]), tickerOpinions.insiders);
    const dilution = formatDilution((data.dilution || {})[ticker]);
    addSection('희석·자금조달 점검' + (dilution.level ? ' · 위험 ' + dilution.level : '') + ' (분기 재무 기반 추정)',
      dilution.lines, tickerOpinions.dilution);
    addSection('옵션 기대 변동 (Yahoo 옵션 체인, 소형주는 호가가 얇아 참고용)',
      formatOptions((data.options || {})[ticker]), tickerOpinions.options);
    addSection('기술적 신호·리스크 (1년 일봉)',
      formatSignals((data.signals || {})[ticker], ((data.risk || {}).per_ticker || {})[ticker], (data.risk || {}).benchmark),
      tickerOpinions.technical);

    if (valuationLines.length) {
      const note = ((data.valuation || {})[ticker] || {}).note;
      addList('시나리오 EPS 밸류에이션 (제 추정' + (note ? ' · ' + note : '') + ')',
        valuationLines.map((v) => v.label + ' ' + v.text));
    }
    addList('컨센서스 (Yahoo 집계 · 매출/EPS/PER)', formatConsensus((data.consensus || {})[ticker]));
    addList('EPS 컨센서스 변화 (Yahoo 집계)', ((analystEntry && analystEntry.eps_trend) || []).length
      ? analystLines.filter((t) => t.startsWith('EPS 컨센')) : []);
    // 13F 기관 매매 동향: 누가 늘렸고(매수) 누가 줄였는지(매도)를 색으로 구분해 먼저 보여 준다
    if (holders.length) {
      const s = inst.summary || {};
      card.appendChild(element('h3', '', '13F 기관 매매 동향 (직전 신고 대비 · 지연·롱온리·패시브 포함, 원문 확인 필요)'));
      const counted = (s.increased || 0) + (s.decreased || 0) + (s.unchanged || 0);
      if ((s.increased || 0) + (s.decreased || 0) > 0) {
        const line = element('div', 'meta');
        line.appendChild(element('span', '', 'Yahoo 상위 ' + counted + '개 기관 중  '));
        line.appendChild(element('span', 'up', '▲ 매수 ' + (s.increased || 0) + '곳'));
        line.appendChild(element('span', '', '  ·  '));
        line.appendChild(element('span', 'down', '▼ 매도 ' + (s.decreased || 0) + '곳'));
        card.appendChild(line);
      }
      addMoveList('늘린 곳 (매수 상위)', inst.buyers || [], 'up');
      addMoveList('줄인 곳 (매도 상위)', inst.sellers || [], 'down');
      addList('보유량 순', holders.map(formatHolder));
      addOpinion(card, tickerOpinions.institutional);
    }
    if (check) {
      addList('다음 이벤트 체크리스트', [
        ...(check.next_event ? ['다음: ' + formatCalendarItem(check.next_event).text] : []),
        ...(check.items || []),
      ]);
    }

    cards.appendChild(card);
    addTab(ticker, ticker, quote.unavailable ? null : { text: quote.percent, cls: quote.direction }, card);
  }
  select('overview');
}

if (typeof document !== 'undefined') {
  loadReport(location.search, decodeReportFragment(location.hash), (url) => fetch(url)).then(({ data, notice }) => {
    renderReport(document, data);
    if (notice) document.getElementById('notice').textContent = notice;
  });
}
if (typeof module !== 'undefined') {
  module.exports = {
    decodeReportFragment, loadReport, formatRow, formatTimestamp, formatDetailLines,
    formatFiling, formatNews, formatNewsTime, formatHeadline, renderReport, DATA_URL_PREFIX,
    formatValuation, formatAnalyst, formatConsensus, formatHolder, formatHolderMove, formatCalendarItem, formatPortfolio, formatReportItems, keyPointsLabel,
    summaryLabel, classTag: tagTone, usd, formatEarningsHistory, formatInsiders, formatDilution, formatOptions, formatSignals,
    formatRisk, formatDataQuality,
  };
}
