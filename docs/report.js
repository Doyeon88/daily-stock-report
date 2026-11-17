// 푸시 알림을 탭하면 열리는 리포트 페이지의 로직.
//
// 데이터는 두 곳에서 옵니다 (notifications/fcm_notifier.py 의 _build_report_link):
//  - 주소의 # 뒤: 핵심 표와 신호만 담은 base64url JSON  {"v":1, "t", "s":[[ticker, price, prev, change, pct, volume, error]], "g":[신호...]}
//  - 주소의 ?d=<URL>: 상세 데이터(v2)를 저장해 둔 JSON 파일. 불러오지 못하면 # 뒤의 핵심 표로 대신합니다.
//    v2 = v1 + {"details", "news", "filings", "comparison", "tags", "analyst", "institutional",
//              "policy", "calendar", "valuation", "portfolio", "checklist"}

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

function formatHolder(h) {
  return h.holder + ' ' + Number(h.shares).toLocaleString('en-US') + '주'
    + (has(h.pct_held) ? ' (' + Number(h.pct_held).toFixed(2) + '%)' : '')
    + (has(h.pct_change) ? ' · 직전 대비 ' + signed(h.pct_change) : '')
    + (h.reported ? ' · ' + h.reported : '');
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

// 리포트 목록: 애널리스트 리포트 기사(링크+요약), 의견·목표가 변경(Yahoo 집계, 분석 페이지 링크), 공시를 날짜순으로 합칩니다.
// 증권사 리포트 원문은 가져올 수 없어 기사 제목·발췌 범위의 요약입니다. 공시 본문은 읽지 않아 공시 요약은 양식 설명입니다.
function formatReportItems(analystEntry, filingInfo, ticker, analystArticles) {
  const items = [];
  for (const a of analystArticles || []) {
    items.push({
      kind: '리포트 기사', date: String(a.published || '').slice(0, 10), title: String(a.title),
      summary: a.summary || '', url: safeUrl(a.url), tag: a.tag || '',
      origin: [a.source, summaryLabel(a), '?미검증'].filter(Boolean).join(' · '),
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
    items.push({
      kind: '공시', date: String(f.date), title: f.form + ' · ' + String(f.date).slice(5),
      summary: f.summary || '', url: item.url, tag: item.tag, origin: '✔검증(SEC/Yahoo)',
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

  // 시장 맥락
  const market = (data.comparison && data.comparison.market) || [];
  const marketBox = doc.getElementById('market');
  for (const m of market) {
    marketBox.appendChild(element('span', 'chip ' + toneOf(m.change_percent), m.name + ' ' + signed(m.change_percent)));
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
      ul.appendChild(li);
    }
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
        text: n.title, url: n.url, summary: a.summary || '',
        meta: [group.query, n.meta, summaryLabel(a), '?미검증'].filter(Boolean).join(' · '),
      });
    }
  }
  fill('policy', 'policy-list', policyEntries);

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
    const holders = ((data.institutional || {})[ticker] || {}).holders || [];
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

    // 기사: 제목 링크 + 요약
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
        li.appendChild(element('div', 'meta', [n.meta, label, verifiedMark(article.verified === true)].filter(Boolean).join(' · ')));
        ul.appendChild(li);
      }
      card.appendChild(ul);
    }

    // 리포트: 애널리스트 의견 변경 + 공시
    if (reports.length || filingInfo.form4_count) {
      card.appendChild(element('h3', '', '애널리스트 리포트·공시 (' + reports.length + ')' + (filingInfo.source === 'yahoo' ? ' · 공시는 Yahoo Finance 제공' : '')));
      const ul = element('ul', 'items');
      for (const item of reports) {
        const li = element('li');
        li.appendChild(element('span', 'kind', item.kind));
        if (item.tag) li.appendChild(element('span', 'tag ' + tagTone(item.tag), item.tag));
        li.appendChild(link(item.title, item.url));
        if (item.summary) li.appendChild(element('div', 'summary', item.summary));
        li.appendChild(element('div', 'meta', item.date.slice(5) + ' · ' + item.origin));
        ul.appendChild(li);
      }
      if (filingInfo.form4_count) ul.appendChild(element('li', '', '임원·대주주 거래(Form 4) ' + filingInfo.form4_count + '건 (Yahoo 목록에는 없음)'));
      card.appendChild(ul);
    }

    if (valuationLines.length) {
      const note = ((data.valuation || {})[ticker] || {}).note;
      addList('시나리오 EPS 밸류에이션 (제 추정' + (note ? ' · ' + note : '') + ')',
        valuationLines.map((v) => v.label + ' ' + v.text));
    }
    addList('EPS 컨센서스 변화 (Yahoo 집계)', ((analystEntry && analystEntry.eps_trend) || []).length
      ? analystLines.filter((t) => t.startsWith('EPS 컨센')) : []);
    addList('13F 기관 보유 (지연·롱온리·패시브 포함, 원문 확인 필요)', holders.map(formatHolder));
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
    formatFiling, formatNews, formatNewsTime, renderReport, DATA_URL_PREFIX,
    formatValuation, formatAnalyst, formatHolder, formatCalendarItem, formatPortfolio, formatReportItems, keyPointsLabel,
    summaryLabel, classTag: tagTone,
  };
}
