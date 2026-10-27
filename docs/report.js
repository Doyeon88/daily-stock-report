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
  for (const row of data.s) {
    const ticker = String(row[0]);
    const lines = formatDetailLines(details[ticker], peers[ticker]);
    const filingInfo = filings[ticker] || { filings: [], form4_count: 0 };
    const articles = news[ticker] || [];
    if (!lines.length && !filingInfo.filings.length && !filingInfo.form4_count && !articles.length) continue;

    const card = element('section', 'card');
    card.appendChild(element('h2', '', ticker));

    const list = element('dl', 'lines');
    for (const line of lines) {
      list.appendChild(element('dt', '', line.label));
      list.appendChild(element('dd', line.tone, line.text));
    }
    if (lines.length) card.appendChild(list);

    if (filingInfo.filings.length || filingInfo.form4_count) {
      card.appendChild(element('h3', '', 'SEC 공시 (최근 7일)'));
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
  };
}
