"""
오늘의 헤드라인: 시황·경제·원자재·여론·정치 뉴스 중 주가에 영향을 줄 만한 속보를 3~5개 고른다.

소스(모두 공개 RSS/API, 하나가 막혀도 나머지로 진행):
  Finnhub 일반 시장 뉴스(키가 있을 때) · CNBC(톱·경제·에너지·정치) · MarketWatch(톱·Market Pulse 속보) ·
  연준 보도자료 · Google News 주제 검색(시황·경제·원자재·여론·정치)
최근 24시간 기사만 쓰고, 속보성 단어·최신성으로 점수를 매겨 후보를 줄인 뒤 AI가 중요도 순으로 고른다.
AI를 못 쓰면 점수 상위 기사를 영어 제목 그대로 보여 준다.
"""

import logging
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Dict, List, Optional

import requests

from config import FINNHUB_API_KEY, HEADLINE_LOOKBACK_HOURS, HEADLINE_MAX
from scrapers.news_scraper import _rss_snippet, google_news_query
from scrapers.retry import call_with_retry

logger = logging.getLogger(__name__)

CATEGORIES = ('시황', '경제', '원자재', '여론', '정치')
REQUEST_TIMEOUT = 15
MAX_CANDIDATES = 40
USER_AGENT = 'Mozilla/5.0 (compatible; daily-stock-report)'

# (이름, 주소, 분류 힌트)
RSS_FEEDS = [
    ('CNBC', 'https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=100003114', '시황'),
    ('CNBC', 'https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=20910258', '경제'),
    ('CNBC', 'https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=19836768', '원자재'),
    ('CNBC', 'https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=10000113', '정치'),
    ('MarketWatch', 'https://feeds.content.dowjones.io/public/rss/mw_topstories', '시황'),
    ('MarketWatch', 'https://feeds.content.dowjones.io/public/rss/mw_marketpulse', '시황'),
    ('Federal Reserve', 'https://www.federalreserve.gov/feeds/press_all.xml', '경제'),
]
# (검색어, 분류 힌트)
GOOGLE_QUERIES = [
    ('stock market futures Wall Street today', '시황'),
    ('Federal Reserve inflation jobs report Treasury yields', '경제'),
    ('oil prices OPEC gold copper', '원자재'),
    ('investor sentiment survey consumer confidence poll', '여론'),
    ('White House Congress tariffs sanctions trade deal', '정치'),
]

# 속보·시장 영향이 큰 단어(소문자). 점수는 후보를 줄이는 데만 쓰고, 최종 선택은 AI가 한다.
BREAKING_WORDS = (
    'breaking', 'just in', 'alert', 'urgent', 'emergency', 'halt', 'crash', 'plunge', 'plunges', 'tumble', 'soar',
    'surge', 'slump', 'rout', 'record high', 'record low', 'selloff', 'sell-off', 'rally',
    'fed ', 'federal reserve', 'rate cut', 'rate hike', 'powell', 'cpi', 'inflation', 'jobs report', 'payrolls',
    'treasury yield', 'gdp', 'recession', 'opec', 'oil', 'crude', 'gold', 'tariff', 'sanction', 'export control',
    'shutdown', 'default', 'ceasefire', 'war', 'attack', 'trump', 'congress', 'senate', 'bill', 'ban',
    'nvidia', 'earnings', 'ipo', 'bitcoin', 'stablecoin',
)


def _parse_time(text: Optional[str]) -> Optional[datetime]:
    if not text:
        return None
    try:
        parsed = parsedate_to_datetime(text.strip())
    except (TypeError, ValueError):
        try:
            parsed = datetime.fromisoformat(text.strip().replace('Z', '+00:00'))
        except ValueError:
            return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def parse_rss(xml_bytes: bytes, source: str, category: str) -> List[Dict]:
    """Items of an RSS 2.0 feed ('item') or Atom feed ('entry') as article dicts"""
    articles = []
    root = ET.fromstring(xml_bytes)
    for item in list(root.iter('item')) + list(root.iter('{http://www.w3.org/2005/Atom}entry')):
        title = (item.findtext('title') or item.findtext('{http://www.w3.org/2005/Atom}title') or '').strip()
        link = item.findtext('link')
        if not link:
            atom = item.find('{http://www.w3.org/2005/Atom}link')
            link = atom.get('href') if atom is not None else None
        published = _parse_time(item.findtext('pubDate') or item.findtext('{http://www.w3.org/2005/Atom}updated')
                                or item.findtext('{http://purl.org/dc/elements/1.1/}date'))
        if title and link and published:
            articles.append({
                'title': title, 'source': source, 'url': link.strip(), 'published': published, 'category': category,
                'snippet': _rss_snippet(item.findtext('description')
                                        or item.findtext('{http://www.w3.org/2005/Atom}summary'), title),
            })
    return articles


def _fetch_rss(name: str, url: str, category: str) -> List[Dict]:
    response = requests.get(url, headers={'User-Agent': USER_AGENT}, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()
    return parse_rss(response.content, name, category)


def _fetch_finnhub_general() -> List[Dict]:
    response = requests.get('https://finnhub.io/api/v1/news', params={'category': 'general'},
                            headers={'X-Finnhub-Token': FINNHUB_API_KEY}, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()
    return [{'title': a['headline'], 'source': a.get('source'), 'url': a['url'], 'category': '시황',
             'published': datetime.fromtimestamp(a['datetime'], tz=timezone.utc),
             'snippet': (a.get('summary') or '').strip()}
            for a in response.json() if a.get('headline') and a.get('url') and a.get('datetime')]


def _fetch_google(query: str, category: str, now: datetime) -> List[Dict]:
    return [dict(a, category=category) for a in google_news_query(query, now, lookback_days=1)]


def score(article: Dict, now: datetime) -> float:
    """Higher = more likely a breaking, market-moving story (used to cut the candidate list, not to decide)"""
    text = f"{article['title']} {article.get('snippet') or ''}".lower()
    hits = sum(1 for word in BREAKING_WORDS if word in text)
    age_hours = max(0.0, (now - article['published']).total_seconds() / 3600)
    freshness = max(0.0, 1 - age_hours / HEADLINE_LOOKBACK_HOURS) * 3
    return hits * 1.5 + freshness + (1 if article.get('snippet') else 0)


def fetch_candidates(now: Optional[datetime] = None) -> List[Dict]:
    """
    Last 24 hours of market-wide articles from all sources, de-duplicated, best scores first,
    spread over the categories (at most MAX_CANDIDATES). Each: title, source, url, published (datetime),
    snippet, category (hint), score.
    """
    now = now or datetime.now(timezone.utc)
    jobs = [(f'{name} {category}', lambda n=name, u=url, c=category: _fetch_rss(n, u, c))
            for name, url, category in RSS_FEEDS]
    jobs += [(f'Google News "{query}"', lambda q=query, c=category: _fetch_google(q, c, now))
             for query, category in GOOGLE_QUERIES]
    if FINNHUB_API_KEY:
        jobs.insert(0, ('Finnhub market news', _fetch_finnhub_general))

    articles: List[Dict] = []
    ok = 0
    for description, fetch in jobs:
        try:
            articles += call_with_retry(fetch, description)
            ok += 1
        except Exception as e:
            logger.error(f"Headline source unavailable ({description}): {e}")
    logger.info(f"Headline sources: {ok}/{len(jobs)} answered, {len(articles)} article(s)")

    cutoff = now - timedelta(hours=HEADLINE_LOOKBACK_HOURS)
    seen, fresh = set(), []
    for article in sorted(articles, key=lambda a: a['published'], reverse=True):
        key = re.sub(r'[^a-z0-9]+', '', article['title'].lower())[:80]
        if article['published'] < cutoff or article['published'] > now + timedelta(minutes=5) or key in seen:
            continue
        seen.add(key)
        article['score'] = score(article, now)
        fresh.append(article)

    # 분류별로 번갈아 가며 점수 순으로 채워 한 분야로 쏠리지 않게 한다
    by_category = {c: sorted((a for a in fresh if a['category'] == c), key=lambda a: -a['score']) for c in CATEGORIES}
    picked: List[Dict] = []
    while len(picked) < MAX_CANDIDATES and any(by_category.values()):
        for category in CATEGORIES:
            if by_category[category] and len(picked) < MAX_CANDIDATES:
                picked.append(by_category[category].pop(0))
    return sorted(picked, key=lambda a: -a['score'])


def to_entry(article: Dict, category: Optional[str] = None, headline: Optional[str] = None,
             why: Optional[str] = None) -> Dict:
    """JSON-ready headline entry; the same dict is also given to the summarizer"""
    return {
        'category': category if category in CATEGORIES else article.get('category', '시황'),
        'headline': headline or article['title'],
        'why': why or '',
        'title': article['title'], 'source': article.get('source'), 'url': article['url'],
        'published': article['published'].astimezone(timezone.utc).isoformat(timespec='minutes'),
        'snippet': article.get('snippet') or '',
    }


def fallback_headlines(candidates: List[Dict], count: int = HEADLINE_MAX) -> List[Dict]:
    """Without AI: the best-scored articles, one per category first, English titles as they are"""
    chosen, used = [], set()
    for article in candidates:
        if article['category'] not in used and len(chosen) < count:
            used.add(article['category'])
            chosen.append(article)
    for article in candidates:
        if article not in chosen and len(chosen) < count:
            chosen.append(article)
    return [to_entry(a) for a in sorted(chosen, key=lambda a: -a['score'])]


# ---------- AI selection ----------

def build_pick_prompt(candidates: List[Dict], now: datetime, minimum: int, maximum: int) -> str:
    lines = [
        '아래는 최근 24시간 시장 뉴스 후보입니다. 오늘 아침 가장 먼저 읽을 "주가에 영향을 줄 속보·중요 뉴스"를 '
        f'{minimum}~{maximum}개 고르세요. 독자는 미국 증시, 특히 AI 전력·데이터센터·연료전지·원자력·스테이블코인·AI 인프라 종목에 투자합니다.',
        '선택 기준: 시장 전체나 이들 업종을 움직일 만한 큰 사건(금리·물가·고용, 유가·원자재, 관세·제재·법안·정치, 시장 심리·여론, 지수 급변동)을 '
        '우선하고, 속보일수록·최신일수록 앞에 둡니다. 같은 사건은 하나만 고르고, 단순 시황 나열·광고성·개별 상품 리뷰·오래된 내용은 제외합니다. '
        '분야(시황·경제·원자재·여론·정치)가 다양하면 좋지만 중요도가 우선입니다.',
        '각 항목: n(후보 번호), category(시황/경제/원자재/여론/정치 중 하나), headline(한국어 제목 60자 이내, 영어 기사는 번역), '
        'why(기사에 나온 사실만으로 시장·주가와 어떻게 연결되는지 한 문장, 추측·투자 권유 금지).',
        '출력은 JSON 배열 하나뿐이며 중요도 순입니다. 문장 안에 큰따옴표(")를 쓰지 마세요. '
        '예: [{"n": 3, "category": "경제", "headline": "...", "why": "..."}]', '',
    ]
    for i, a in enumerate(candidates, 1):
        age = max(0, int((now - a['published']).total_seconds() // 3600))
        snippet = (a.get('snippet') or '')[:250]
        lines.append(f"{i}. [{a['category']}] {age}시간 전 · {a.get('source') or '?'} · {a['title']}"
                     + (f"\n   발췌: {snippet}" if snippet else ''))
    return '\n'.join(lines)


def parse_picks(text: Optional[str], candidate_count: int, maximum: int) -> Optional[List[Dict]]:
    """The model's picks: [{'n', 'category', 'headline', 'why'}] with valid, unique numbers; None if unusable"""
    import json
    match = re.search(r'\[.*\]', text or '', re.S)
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
    except ValueError:
        return None
    picks, used = [], set()
    for item in data if isinstance(data, list) else []:
        if not isinstance(item, dict) or not isinstance(item.get('n'), int):
            continue
        n = item['n']
        if not 1 <= n <= candidate_count or n in used or not str(item.get('headline') or '').strip():
            continue
        used.add(n)
        picks.append({'n': n, 'category': item.get('category'),
                      'headline': ' '.join(str(item['headline']).split())[:120],
                      'why': ' '.join(str(item.get('why') or '').split())[:220]})
    return picks[:maximum] or None


def select_headlines(candidates: List[Dict], now: Optional[datetime] = None,
                     minimum: int = 3, maximum: int = HEADLINE_MAX) -> List[Dict]:
    """
    3~5 headline entries (see to_entry) with Korean headline, reason and article summary; [] with no candidates.
    Entries carry summary / summary_source / summary_basis like other articles.
    """
    from scrapers import summarizer
    if not candidates:
        return []
    now = now or datetime.now(timezone.utc)
    prompt = build_pick_prompt(candidates, now, minimum, maximum)
    picks = None
    for attempt in (1, 2):
        text = summarizer.ai_text(prompt)
        if text is None:
            break
        picks = parse_picks(text, len(candidates), maximum)
        if picks:
            break
        logger.warning(f"AI headline pick unusable (attempt {attempt}/2): {text[:200]!r}")

    if picks:
        entries = [to_entry(candidates[p['n'] - 1], p['category'], p['headline'], p['why']) for p in picks]
    else:
        entries = fallback_headlines(candidates, maximum)
    summarizer.add_summaries([entries])
    return entries
