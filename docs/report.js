// 푸시 알림을 탭하면 열리는 리포트 페이지의 로직.
//
// 데이터는 두 곳에서 옵니다 (notifications/fcm_notifier.py 의 _build_report_link):
//  - 주소의 # 뒤: 핵심 표와 신호만 담은 base64url JSON  {"v":1, "t", "s":[[ticker, price, prev, change, pct, volume, error]], "g":[신호...]}
//  - 주소의 ?d=<URL>: 상세 데이터(v2)를 저장해 둔 JSON 파일. 불러오지 못하면 # 뒤의 핵심 표로 대신합니다.
//    v2 = v1 + {"details", "news", "filings", "comparison"}

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

// 레딧 언급 줄 (ApeWisdom). null 은 "집계 순위에 없음", undefined 는 "조회 못 함"이라 줄을 만들지 않습니다.
function formatRedditText(info) {
  if (info === null) return '언급 없음 (ApeWisdom 집계)';
  const parts = [info.rank + '위' + (has(info.rank_24h_ago) ? ' (24시간 전 ' + info.rank_24h_ago + '위)' : '')];
  parts.push('언급 ' + info.mentions + '회' + (has(info.mentions_24h_ago) ? ' (24시간 전 ' + info.mentions_24h_ago + '회)' : ''));
  if (has(info.upvotes)) parts.push('업보트 ' + info.upvotes);
  return parts.join(' · ') + ' · ApeWisdom 집계';
}

// 종목 카드의 "라벨: 값" 줄들. 값이 없는 항목은 건너뜁니다.
function formatDetailLines(details, peers, reddit) {
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
  if (reddit !== undefined) {
    add('레딧 언급', formatRedditText(reddit));
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

function formatFiling(filing) {
  return {
    text: filing.form + ' ' + String(filing.date).slice(5) + (filing.label ? ' · ' + filing.label : ''),
    url: safeUrl(filing.url),
  };
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

// ---------- 레딧 추세 그래프 (외부 라이브러리 없이 그리는 SVG) ----------
// 그래프에 들어가는 것은 숫자와 'YYYY-MM-DD' 날짜뿐이라, 만든 문자열을 innerHTML 로 넣어도 HTML 이 끼어들 수 없습니다.

const CHART = { width: 300, height: 84, left: 4, right: 4, top: 10, bottom: 16 };
const DAY_MS = 86400000;

function dayNumber(iso) {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(String(iso));
  return m ? Date.UTC(Number(m[1]), Number(m[2]) - 1, Number(m[3])) / DAY_MS : null;
}

const finiteOrNull = (v) => (v === null || v === undefined || v === '' || !Number.isFinite(Number(v)) ? null : Number(v));
const oneDecimal = (v) => String(Math.round(v * 10) / 10);

// points: [{ day: 'YYYY-MM-DD', value: 숫자 또는 null }] (오래된 것부터). null 인 날은 선이 끊깁니다.
// options: invert(순위처럼 작을수록 좋은 값은 위로), zeroBase(개수는 0부터), format(축 숫자 서식), label(접근성 설명)
function buildChartSvg(points, options) {
  const o = options || {};
  const valid = points.map((p) => ({ x: dayNumber(p.day), y: finiteOrNull(p.value), day: String(p.day) })).filter((p) => p.x !== null);
  const known = valid.filter((p) => p.y !== null);
  if (!known.length) return '';

  const { width, height, left, right, top, bottom } = CHART;
  const plotW = width - left - right;
  const plotH = height - top - bottom;
  const minX = Math.min(...valid.map((p) => p.x));
  const maxX = Math.max(...valid.map((p) => p.x));
  const dataMin = Math.min(...known.map((p) => p.y));
  const dataMax = Math.max(...known.map((p) => p.y));
  let minY = o.zeroBase ? 0 : dataMin;
  let maxY = dataMax;
  if (maxY === minY) {          // 값이 하나뿐이거나 계속 같으면 선이 가운데에 오게 여백을 준다
    if (o.zeroBase) maxY = minY + 1; else { minY -= 1; maxY += 1; }
  }

  const px = (x) => left + (maxX === minX ? plotW / 2 : ((x - minX) / (maxX - minX)) * plotW);
  const py = (y) => top + plotH * (o.invert ? (y - minY) / (maxY - minY) : 1 - (y - minY) / (maxY - minY));
  const f1 = (n) => n.toFixed(1);
  const format = o.format || oneDecimal;

  const segments = [];
  let current = [];
  for (const p of valid) {
    if (p.y === null) { if (current.length) segments.push(current); current = []; } else current.push(p);
  }
  if (current.length) segments.push(current);

  const paths = segments.filter((s) => s.length > 1)
    .map((s) => '<path d="M' + s.map((p) => f1(px(p.x)) + ' ' + f1(py(p.y))).join(' L') + '" />').join('');
  const isolated = segments.filter((s) => s.length === 1).map((s) => s[0]);
  const dotted = known.length <= 45 ? known : isolated;       // 점이 많으면 선만 그리고, 끊긴 외톨이 점만 찍는다
  const dots = dotted.map((p) => '<circle cx="' + f1(px(p.x)) + '" cy="' + f1(py(p.y)) + '" r="1.8" />').join('');
  const last = known[known.length - 1];
  const lastDot = '<circle cx="' + f1(px(last.x)) + '" cy="' + f1(py(last.y)) + '" r="3" />';

  const topValue = o.invert ? dataMin : dataMax;
  const bottomValue = o.zeroBase ? 0 : (o.invert ? dataMax : dataMin);
  const first = valid[0];
  const lastDay = valid[valid.length - 1];
  const dateText = (p) => (o.withYear ? p.day.slice(2) : p.day.slice(5));
  const text = (x, y, anchor, value) => '<text x="' + x + '" y="' + y + '" text-anchor="' + anchor + '">' + value + '</text>';

  return '<svg class="chart" viewBox="0 0 ' + width + ' ' + height + '" role="img" aria-label="' + (o.label || '추세 그래프') + '">'
    + '<line class="grid" x1="' + left + '" x2="' + (width - right) + '" y1="' + top + '" y2="' + top + '" />'
    + '<line class="grid" x1="' + left + '" x2="' + (width - right) + '" y1="' + (height - bottom) + '" y2="' + (height - bottom) + '" />'
    + paths + dots + lastDot
    + text(left + 2, top - 2, 'start', format(topValue))
    + text(left + 2, height - bottom - 3, 'start', format(bottomValue))
    + text(left, height - 3, 'start', dateText(first))
    + text(width - right, height - 3, 'end', dateText(lastDay))
    + '</svg>';
}

// mode: 'daily'(최근 3개월 일별) 또는 'weekly'(최근 52주 주별 평균). history: {daily, weekly, first_date, days}
function trendHtml(history, mode) {
  const weekly = mode === 'weekly';
  const rows = (weekly ? history.weekly : history.daily) || [];
  if (!rows.length) return '<p class="empty">이 기간의 기록이 없습니다.</p>';

  const started = dayNumber(history.first_date) === null ? '' : ' · ' + history.first_date + '부터';
  const note = '기록 ' + (finiteOrNull(history.days) || rows.length) + '일' + started;
  const neverRanked = rows.every((r) => finiteOrNull(r[1]) === null && !finiteOrNull(r[2]) && !finiteOrNull(r[3]));
  if (neverRanked) return '<p class="empty">이 기간 레딧 언급 없음 (' + note + ')</p>';

  const average = weekly ? ' (주 평균)' : '';
  const charts = [
    { title: '순위', index: 1, invert: true, format: (v) => Math.round(v) + '위', label: '레딧 언급 순위 추세',
      latest: (v) => (v === null ? '순위 없음' : Math.round(v) + '위'), none: '이 기간 순위 없음' },
    { title: '언급 수' + average, index: 2, zeroBase: true, label: '레딧 언급 수 추세', latest: oneDecimal },
    { title: '업보트' + average, index: 3, zeroBase: true, label: '레딧 업보트 추세', latest: oneDecimal },
  ];

  let html = '<div class="trend-note">' + note + (rows.length < 2 ? ' · 기록이 2개 이상 쌓이면 선이 그려집니다' : '') + '</div>';
  for (const chart of charts) {
    const points = rows.map((r) => ({ day: r[0], value: r[chart.index] }));
    const values = points.map((p) => finiteOrNull(p.value));
    const lastKnown = values.filter((v) => v !== null).pop();
    const svg = buildChartSvg(points, { invert: chart.invert, zeroBase: chart.zeroBase, format: chart.format, label: chart.label, withYear: weekly });
    html += '<div class="chart-title"><span>' + chart.title + '</span><b>' + chart.latest(lastKnown === undefined ? null : lastKnown) + '</b></div>'
      + (svg || '<p class="empty">' + chart.none + '</p>');
  }
  return html;
}

function renderTrend(doc, history) {
  const box = doc.createElement('div');
  box.className = 'trend';
  const heading = doc.createElement('h3');
  heading.textContent = '레딧 추세 (ApeWisdom)';
  box.appendChild(heading);

  const tabs = doc.createElement('div');
  tabs.className = 'tabs';
  const area = doc.createElement('div');
  area.className = 'trend-area';
  const buttons = {};
  const show = (mode) => {
    area.innerHTML = trendHtml(history, mode);
    for (const key of Object.keys(buttons)) buttons[key].className = key === mode ? 'on' : '';
  };
  for (const [mode, label] of [['daily', '일별 3개월'], ['weekly', '주별 52주']]) {
    const button = doc.createElement('button');
    button.type = 'button';
    button.textContent = label;
    button.addEventListener('click', () => show(mode));
    buttons[mode] = button;
    tabs.appendChild(button);
  }
  box.appendChild(tabs);
  box.appendChild(area);
  show('daily');
  return box;
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

  // 가격 표
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

  // 종목별 카드 (상세 데이터가 있을 때만)
  const cards = doc.getElementById('cards');
  const details = data.details || {};
  const news = data.news || {};
  const filings = data.filings || {};
  const peers = (data.comparison && data.comparison.peers) || {};
  const reddit = data.reddit || {};
  const redditHistory = data.reddit_history || {};
  for (const row of data.s) {
    const ticker = String(row[0]);
    const lines = formatDetailLines(details[ticker], peers[ticker], reddit[ticker]);
    const filingInfo = filings[ticker] || { filings: [], form4_count: 0 };
    const articles = news[ticker] || [];
    const trend = redditHistory[ticker];
    if (!lines.length && !filingInfo.filings.length && !filingInfo.form4_count && !articles.length && !trend) continue;

    const card = element('section', 'card');
    card.appendChild(element('h2', '', ticker));

    const list = element('dl', 'lines');
    for (const line of lines) {
      list.appendChild(element('dt', '', line.label));
      list.appendChild(element('dd', line.tone, line.text));
    }
    if (lines.length) card.appendChild(list);

    if (trend) card.appendChild(renderTrend(doc, trend));

    if (filingInfo.filings.length || filingInfo.form4_count) {
      // Yahoo가 대신 준 목록은 임원 거래(Form 4)가 없고 8-K 항목 설명도 없다
      card.appendChild(element('h3', '', 'SEC 공시 (최근 7일)' + (filingInfo.source === 'yahoo' ? ' · Yahoo Finance 제공' : '')));
      const ul = element('ul', 'items');
      for (const filing of filingInfo.filings) {
        const f = formatFiling(filing);
        const li = element('li');
        li.appendChild(link(f.text, f.url));
        ul.appendChild(li);
      }
      if (filingInfo.form4_count) ul.appendChild(element('li', '', '임원·대주주 거래(Form 4) ' + filingInfo.form4_count + '건'));
      card.appendChild(ul);
    }

    if (articles.length) {
      card.appendChild(element('h3', '', '뉴스'));
      const ul = element('ul', 'items');
      for (const article of articles) {
        const n = formatNews(article);
        const li = element('li');
        li.appendChild(link(n.title, n.url));
        if (n.meta) li.appendChild(element('div', 'meta', n.meta));
        ul.appendChild(li);
      }
      card.appendChild(ul);
    }
    cards.appendChild(card);
  }
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
    buildChartSvg, trendHtml, renderTrend,
  };
}
