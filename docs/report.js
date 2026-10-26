// 푸시 알림을 탭하면 열리는 리포트 페이지의 로직.
// 리포트는 URL의 # 뒤에 base64url JSON으로 들어 있습니다 (notifications/fcm_notifier.py 의 _build_report_link):
//   {"v":1, "t":"<ISO 시각>", "s":[[ticker, price, previous_close, change, change_percent, volume, error], ...]}

function decodeReportFragment(hash) {
  const encoded = String(hash || '').replace(/^#/, '');
  if (!encoded) return null;
  try {
    const b64 = encoded.replace(/-/g, '+').replace(/_/g, '/');
    const binary = atob(b64 + '='.repeat((4 - (b64.length % 4)) % 4));
    const bytes = Uint8Array.from(binary, (ch) => ch.charCodeAt(0));
    const data = JSON.parse(new TextDecoder('utf-8').decode(bytes));
    return data && data.v === 1 && Array.isArray(data.s) ? data : null;
  } catch (e) {
    return null;
  }
}

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

function renderReport(doc, data) {
  const status = doc.getElementById('status');
  const body = doc.getElementById('rows');
  if (!data) {
    status.textContent = '리포트 데이터가 없습니다. 푸시 알림을 탭해서 열어 주세요.';
    return;
  }
  status.textContent = formatTimestamp(data.t);

  for (const row of data.s) {
    const item = formatRow(row);
    const tr = doc.createElement('tr');
    const cell = (text, className) => {
      const td = doc.createElement('td');
      td.textContent = text;
      if (className) td.className = className;
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
}

if (typeof document !== 'undefined') {
  renderReport(document, decodeReportFragment(location.hash));
}
if (typeof module !== 'undefined') {
  module.exports = { decodeReportFragment, formatRow, formatTimestamp, renderReport };
}
