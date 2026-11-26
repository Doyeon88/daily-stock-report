"""
기사 요약·종목별 핵심 정리·AI 의견 (한국어)

AI 공급자 순서: Claude(ANTHROPIC_API_KEY) → GitHub Models(Actions의 GITHUB_TOKEN, 워크플로에 models: read 권한 필요).
둘 다 안 되면 기사 발췌문(영문일 수 있음)을 그대로 보여 주고, 발췌문도 없으면 요약 없이 제목만 나옵니다.
요약은 수집한 본문·제목·발췌문만 근거로 쓰게 하고(추측 금지), 언론 기사 기반이라 '미검증' 표시는 유지됩니다.
요약과 따로 붙는 'AI 의견'은 앞으로의 진행·시기 전망과 관심 종목별 호재/악재 판단으로, 일반 지식과 추정이 들어가므로
화면에 'AI 의견(추정, 투자 권유 아님)'으로 구분해 보여 줍니다.
"""

import json
import logging
import os
import re
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, List, Optional

import requests

logger = logging.getLogger(__name__)

ANTHROPIC_API_KEY = (os.getenv('ANTHROPIC_API_KEY') or '').strip() or None
ANTHROPIC_MODEL = os.getenv('ANTHROPIC_MODEL') or 'claude-haiku-5-5'
API_URL = 'https://api.anthropic.com/v1/messages'
# GitHub Models: Actions의 자동 토큰으로 호출(별도 키 없음). 주소는 위에서부터 차례로 시도하고, 응답이 JSON이 아니거나
# 401/403/404를 주는 주소는 이번 실행에서 다시 부르지 않습니다.
GITHUB_MODELS_TOKEN = (os.getenv('GITHUB_TOKEN') or '').strip() or None
GITHUB_MODELS_ENDPOINTS = [
    (os.getenv('GITHUB_MODELS_URL') or 'https://models.github.ai/inference/chat/completions',
     os.getenv('GITHUB_MODELS_MODEL') or 'openai/gpt-4.1-mini'),
    ('https://models.inference.ai.azure.com/chat/completions', 'gpt-4o-mini'),
]
GITHUB_MODELS_URL = GITHUB_MODELS_ENDPOINTS[0][0]   # (테스트와 문서용)
PAGE_TIMEOUT = 6
API_TIMEOUT = 40
MAX_WORKERS = 8
MAX_SUMMARY_LENGTH = 220
MAX_LINE_LENGTH = 140          # 본문 요약 한 줄 최대 길이
MAX_KEY_POINTS = 7
MIN_KEY_POINTS = 5
MAX_OPINION_LENGTH = 360       # AI 의견 최대 길이
TONES = ('호재', '중립', '악재')
BODY_TIMEOUT = 10
MAX_BODY_CHARS = 3500          # 기사 하나당 AI에 주는 본문 길이
MIN_BODY_CHARS = 300           # 이보다 짧으면 본문을 못 읽은 것으로 본다(로그인·동의 창 등)
BATCH_SIZE = 3                 # 한 번의 AI 호출에 넣는 기사 수(답이 길어 잘리지 않도록 작게)
AI_WORKERS = 4                 # AI 호출 동시 실행 수
BROWSER_UA = ('Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) '
              'Chrome/124.0 Safari/537.36')
USER_AGENT = 'Mozilla/5.0 (compatible; daily-stock-report)'

_unusable = set()   # providers/endpoints that answered with a hard failure in this run


class ProviderUnusable(Exception):
    """The provider refuses us (401/403/404) or does not answer with JSON: asking again cannot help"""


_META = re.compile(
    r'<meta[^>]+(?:property|name)=["\'](?:og:description|description|twitter:description)["\'][^>]*>', re.I)
_CONTENT = re.compile(r'content=["\']([^"\']*)["\']', re.I)


def parse_page_description(page_html: str) -> str:
    """og:description / meta description of an HTML page, '' if none"""
    import html as html_module
    for tag in _META.findall(page_html or ''):
        match = _CONTENT.search(tag)
        if match and match.group(1).strip():
            return re.sub(r'\s+', ' ', html_module.unescape(match.group(1))).strip()
    return ''


def fetch_page_description(url: str) -> str:
    """Best effort: some sites (and Google News redirect links) give nothing, that is fine"""
    try:
        response = requests.get(url, headers={'User-Agent': USER_AGENT}, timeout=PAGE_TIMEOUT)
        response.raise_for_status()
        if 'html' not in response.headers.get('Content-Type', 'html'):
            return ''
        return parse_page_description(response.text[:200000])
    except Exception as e:
        logger.debug(f"No page description for {url}: {e}")
        return ''


class _ParagraphParser(__import__('html.parser', fromlist=['HTMLParser']).HTMLParser):
    """Collects the text of <p> tags, ignoring scripts, menus and footers"""
    SKIP = {'script', 'style', 'noscript', 'nav', 'footer', 'header', 'aside', 'form', 'figure'}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.paragraphs, self._skip, self._in_p, self._buf = [], 0, False, []

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self._skip += 1
        elif tag == 'p' and not self._skip:
            self._in_p, self._buf = True, []

    def handle_endtag(self, tag):
        if tag in self.SKIP and self._skip:
            self._skip -= 1
        elif tag == 'p' and self._in_p:
            text = re.sub(r'\s+', ' ', ''.join(self._buf)).strip()
            if len(text) >= 60:
                self.paragraphs.append(text)
            self._in_p = False

    def handle_data(self, data):
        if self._in_p and not self._skip:
            self._buf.append(data)


def extract_article_text(page_html: str, limit: int = MAX_BODY_CHARS) -> str:
    """The article's paragraph text (up to limit characters); '' if the page has too little text"""
    parser = _ParagraphParser()
    try:
        parser.feed(page_html or '')
    except Exception:
        pass
    seen, parts = set(), []
    for paragraph in parser.paragraphs:
        if paragraph not in seen:
            seen.add(paragraph)
            parts.append(paragraph)
    text = ' '.join(parts)
    return text[:limit] if len(text) >= MIN_BODY_CHARS else ''


def resolve_google_news_url(url: str) -> str:
    """
    Google News RSS links ('news.google.com/rss/articles/...') only redirect in a browser. This asks Google's own
    page for the real address (the same request the page makes). Returns '' if it does not work.
    """
    match = re.search(r'/articles/([^/?]+)', url or '')
    if not match:
        return ''
    article_id = match.group(1)
    try:
        page = requests.get(f'https://news.google.com/rss/articles/{article_id}',
                            headers={'User-Agent': BROWSER_UA}, timeout=PAGE_TIMEOUT)
        signature = re.search(r'data-n-a-sg="([^"]+)"', page.text)
        timestamp = re.search(r'data-n-a-ts="([^"]+)"', page.text)
        if not signature or not timestamp:
            return ''
        inner = ('["garturlreq",[["X","X",["X","X"],null,null,1,1,"US:en",null,1,null,null,null,null,null,0,1],'
                 '"X","X",1,[1,1,1],1,1,null,0,0,null,0],'
                 f'"{article_id}",{timestamp.group(1)},"{signature.group(1)}"]')
        body = 'f.req=' + requests.utils.quote(json.dumps([[['Fbv4je', inner, None, 'generic']]]))
        response = requests.post('https://news.google.com/_/DotsSplashUi/data/batchexecute',
                                 headers={'Content-Type': 'application/x-www-form-urlencoded;charset=UTF-8',
                                          'User-Agent': BROWSER_UA},
                                 data=body, timeout=PAGE_TIMEOUT)
        parsed = json.loads(response.text.split('\n\n')[1])[:-2]
        resolved = json.loads(parsed[0][2])[1]
        return resolved if isinstance(resolved, str) and resolved.startswith('http') else ''
    except Exception as e:
        logger.debug(f"Could not resolve Google News link: {e}")
        return ''


_text_cache: Dict[str, str] = {}   # url -> article text: a page is read once per run


def remember_text(url: str, text: str) -> None:
    """Use this text for the url instead of reading the page (e.g. a filing exhibit read by sec_filings)"""
    if url and text:
        _text_cache[url] = text


def fetch_article_text(url: str) -> str:
    """Best effort: the article's text, '' when the site blocks us, is paywalled or has no readable text"""
    if url not in _text_cache:
        _text_cache[url] = _read_article_text(url)
    return _text_cache[url]


def _read_article_text(url: str) -> str:
    try:
        if 'news.google.com' in (url or ''):
            url = resolve_google_news_url(url)
            if not url:
                return ''
        response = requests.get(url, headers={'User-Agent': BROWSER_UA, 'Accept-Language': 'en-US,en;q=0.9'},
                                timeout=BODY_TIMEOUT)
        response.raise_for_status()
        if 'html' not in response.headers.get('Content-Type', 'html'):
            return ''
        return extract_article_text(response.text[:600000])
    except Exception as e:
        logger.debug(f"No article text for {url}: {e}")
        return ''


def clip(text: str, limit: int = MAX_SUMMARY_LENGTH) -> str:
    text = re.sub(r'\s+', ' ', text or '').strip()
    return text if len(text) <= limit else text[:limit - 1].rstrip() + '…'


# ---------- prompts and parsing ----------

OPINION_GUIDE = (
    'AI 의견(opinion)은 1~3문장, 최대 300자입니다. ① 이 일이 앞으로 어떻게 진행될지와 대략의 시기, 그렇게 보는 이유 '
    '(예: 법안이면 남은 절차와 예상 시점) ② 관심 종목 중 영향을 받을 종목과 호재·악재 여부, 그 이유(사업 구조·경쟁 관계 등)를 씁니다. '
    '여기서는 일반 지식을 써도 되지만 확실하지 않은 것은 "~로 보인다"처럼 추정임을 드러내고, 매수·매도 권유는 하지 않습니다. '
    '관련된 관심 종목이 없으면 그렇다고 씁니다. 예: 상원을 통과해 하원 표결과 대통령 서명이 남았다. 연말 회기 일정상 12월 시행은 '
    '어렵고 1월쯤 시작될 것으로 보인다. 데이터센터 자가발전(BTM) 기업, 그중 물을 쓰지 않고 NOx 배출이 거의 없는 연료전지의 BE에 호재다.'
)


def watchlist_text() -> str:
    """'BE(Bloom Energy), ...' for the prompts, '' if the watchlist cannot be read"""
    try:
        from config import STOCK_NAMES
    except Exception:
        return ''
    return ', '.join(f'{t}({name})' if name and name != t else t for t, name in STOCK_NAMES.items())


def build_prompt(articles: List[Dict], bodies: Optional[Dict[int, str]] = None, context: Optional[str] = None) -> str:
    """
    bodies: position (0-based) -> article text, for the articles whose page could be read
    context: what the articles were collected for (a ticker or a policy search); None for market-wide news
    """
    bodies = bodies or {}
    watch = watchlist_text()
    lines = [
        '아래 뉴스 각각을 한국어로 요약하고, 호재/악재 판정과 AI 의견을 붙여 주세요. 영어 기사는 한국어로 옮겨 요약합니다.',
        f'이 기사들은 {context} 관련으로 모았습니다.' if context else '이 기사들은 시장 전체·정책 뉴스입니다.',
        f'독자의 관심 종목: {watch}.' if watch else None,
        '요약(lines): "본문"이 있는 기사는 중요한 내용을 5~7줄로 요약합니다. 한 줄은 한 문장(최대 120자)이고, '
        '무슨 일인지·누가·얼마(숫자)·언제·배경·시장/종목에 미치는 쟁점 순으로 씁니다. '
        '본문이 없는 기사는 제목과 발췌문이 말하는 내용만 1~2줄로 씁니다(줄 수를 채우려고 지어내지 않습니다).',
        '요약 규칙: 주어진 본문·제목·발췌문에 있는 내용만 쓰고 추측·평가·투자 의견을 넣지 않습니다. 숫자·고유명사는 그대로 둡니다.',
        'tone: 이 기사가 모은 대상 종목(없으면 관심 종목 전반)에 호재·중립·악재 중 하나입니다.',
        OPINION_GUIDE,
        '출력은 JSON 하나뿐입니다: 입력과 같은 순서·같은 개수의 배열이고, 각 원소는 '
        '{"lines": ["첫 줄", "둘째 줄"], "tone": "호재", "opinion": "..."} 입니다. '
        '문장 안에는 큰따옴표(")와 줄바꿈을 쓰지 말고 작은따옴표를 쓰세요.', '',
    ]
    lines = [line for line in lines if line is not None]
    for i, a in enumerate(articles, 1):
        entry = f"{i}. 제목: {a.get('title', '')}\n   발췌: {a.get('snippet') or '(없음)'}"
        if bodies.get(i - 1):
            entry += f"\n   본문: {bodies[i - 1]}"
        lines.append(entry)
    return '\n'.join(lines)


def build_key_points_prompt(ticker: str, material: str) -> str:
    return (
        f'아래는 {ticker} 종목에 대해 오늘 수집한 자료(뉴스 제목·발췌, 애널리스트 의견 변경, 컨센서스, 공시)입니다.\n'
        f'투자자가 꼭 알아야 할 중요 내용을 한국어로 {MIN_KEY_POINTS}~{MAX_KEY_POINTS}개, 각 1문장(최대 140자)으로 정리해 주세요. '
        f'자료가 충분하면 {MIN_KEY_POINTS}개 이상 쓰고, 기사 요약에 나온 구체적인 내용(원인·숫자·일정)을 포함하세요.\n'
        '규칙: 아래 자료에 있는 내용만 사용하고 자료에 없는 사실·전망·추측·투자 권유를 넣지 않습니다. '
        '숫자와 출처(증권사 이름 등)는 그대로 둡니다. 중복되는 내용은 합치고, 중요도 순으로 씁니다.\n'
        '출력은 JSON 문자열 배열 하나뿐입니다.\n\n' + material)


def build_section_opinion_prompt(subject: str, material: str, sections: Dict[str, str]) -> str:
    """sections: key -> what the section is, e.g. {'insiders': '내부자 거래(Form 4)'}"""
    watch = watchlist_text()
    keys = ', '.join(f'"{key}"({label})' for key, label in sections.items())
    return (
        f'아래는 {subject}에 대해 오늘 수집한 항목별 자료입니다.' + (f' 독자의 관심 종목: {watch}.' if watch else '') + '\n'
        '항목마다 한국어 AI 의견을 1~3문장(최대 300자)으로 써 주세요: 이 수치·사실이 무엇을 뜻하는지, 앞으로 무엇을 언제 '
        '지켜봐야 하는지, 이 종목(또는 관심 종목)에 호재인지 악재인지와 그 이유. 자료의 숫자는 그대로 인용합니다. '
        '일반 지식은 써도 되지만 추정은 추정이라고 밝히고, 매수·매도 권유는 하지 않습니다.\n'
        f'출력은 JSON 객체 하나뿐입니다. 키는 {keys} 이고 값은 의견 문자열입니다. '
        '자료가 없는 항목은 빼고, 문장 안에 큰따옴표(")를 쓰지 마세요.\n\n' + material)


def parse_ai_object(text: Optional[str], keys) -> Optional[Dict[str, str]]:
    """{key: opinion} for the expected keys found in the model's JSON object; None if there is none"""
    match = re.search(r'\{.*\}', text or '', re.S)
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
    except ValueError:
        return None
    if not isinstance(data, dict):
        return None
    opinions = {key: clip(value, MAX_OPINION_LENGTH) for key, value in data.items()
                if key in keys and isinstance(value, str) and value.strip()}
    return opinions or None


def _lines_to_summary(item) -> Optional[str]:
    """A string stays one line; a list of strings becomes bullet lines separated by newlines"""
    if isinstance(item, str):
        return clip(item, MAX_SUMMARY_LENGTH)
    if isinstance(item, list) and item and all(isinstance(x, str) for x in item):
        lines = [clip(x, MAX_LINE_LENGTH) for x in item if x.strip()]
        if len(lines) == 1:
            return lines[0]
        return '\n'.join('• ' + line for line in lines) if lines else None
    return None


def parse_ai_items(text: str, expected: int) -> Optional[List[Dict]]:
    """
    One {'summary', 'tone', 'opinion'} per article from the model's JSON answer; None if it is missing or has the
    wrong length. Each element may be {'lines': [...], 'tone', 'opinion'} or, as before, a string / list of lines.
    """
    match = re.search(r'\[.*\]', text or '', re.S)
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
    except ValueError:
        return None
    if not isinstance(data, list) or len(data) != expected:
        return None
    items = []
    for element in data:
        if isinstance(element, dict):
            summary = _lines_to_summary(element.get('lines', element.get('summary')))
            tone = element.get('tone') if element.get('tone') in TONES else None
            opinion = element.get('opinion')
            opinion = clip(opinion, MAX_OPINION_LENGTH) if isinstance(opinion, str) and opinion.strip() else None
        else:
            summary, tone, opinion = _lines_to_summary(element), None, None
        if not summary:
            return None
        items.append({'summary': summary, 'tone': tone, 'opinion': opinion})
    return items


def parse_ai_summaries(text: str, expected: int) -> Optional[List[str]]:
    """One summary per article from the model's JSON answer, None if it is missing or has the wrong length"""
    items = parse_ai_items(text, expected)
    return [item['summary'] for item in items] if items else None


def parse_ai_list(text: str) -> Optional[List[str]]:
    """Any JSON array of strings in the answer (clipped), None if missing/invalid"""
    match = re.search(r'\[.*\]', text or '', re.S)
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
    except ValueError:
        return None
    if not isinstance(data, list) or not data or not all(isinstance(x, str) for x in data):
        return None
    return [clip(x, 160) for x in data]


# ---------- providers ----------

def _json_body(response) -> Dict:
    """response.json(), but a body that is not JSON is reported with its status and start (for the Actions log)"""
    try:
        return response.json()
    except ValueError:
        redirects = [r.status_code for r in getattr(response, 'history', [])]
        raise ProviderUnusable(
            f"not JSON: HTTP {response.status_code}, content-type {response.headers.get('Content-Type')}, "
            f"redirects {redirects}, body starts {response.text[:300]!r}")


def _post(url: str, headers: Dict, payload: Dict) -> Dict:
    response = requests.post(url, headers=headers, json=payload, timeout=API_TIMEOUT)
    if response.status_code in (400, 401, 403, 404):
        raise ProviderUnusable(f"HTTP {response.status_code}: {response.text[:300]!r}")
    response.raise_for_status()
    return _json_body(response)


def _claude_text(prompt: str) -> Optional[str]:
    if not ANTHROPIC_API_KEY or 'claude' in _unusable:
        return None
    try:
        body = _post(API_URL, {'x-api-key': ANTHROPIC_API_KEY, 'anthropic-version': '2023-06-01',
                               'content-type': 'application/json'},
                     {'model': ANTHROPIC_MODEL, 'max_tokens': 8000,
                      'messages': [{'role': 'user', 'content': prompt}]})
        return ''.join(b.get('text', '') for b in body.get('content', []))
    except ProviderUnusable as e:
        _unusable.add('claude')
        logger.error(f"Claude unusable, skipping it for this run: {e}")
    except Exception as e:
        logger.error(f"Claude call failed: {e}")
    return None


def _github_models_text(prompt: str) -> Optional[str]:
    if not GITHUB_MODELS_TOKEN:
        return None
    for url, model in GITHUB_MODELS_ENDPOINTS:
        if url in _unusable:
            continue
        try:
            body = _post(url, {'Authorization': f'Bearer {GITHUB_MODELS_TOKEN}', 'Accept': 'application/json',
                               'Content-Type': 'application/json'},
                         {'model': model, 'max_tokens': 8000, 'temperature': 0.2,
                          'messages': [{'role': 'user', 'content': prompt}]})
            return body['choices'][0]['message']['content']
        except (ProviderUnusable, requests.ConnectionError) as e:
            # 주소가 풀리지 않거나(DNS) 연결이 안 되는 경우도 다시 부르지 않는다
            _unusable.add(url)
            logger.error(f"GitHub Models endpoint {url} unusable, skipping it for this run: {e}")
        except Exception as e:
            logger.error(f"GitHub Models call to {url} failed: {e}")
            return None   # a temporary error (rate limit, 5xx): do not hammer the other endpoint
    return None


def ai_text(prompt: str) -> Optional[str]:
    """The model's answer from Claude, else GitHub Models; None if neither is configured/usable"""
    return _claude_text(prompt) or _github_models_text(prompt)


def ai_summaries(articles: List[Dict], bodies: Optional[Dict[int, str]] = None,
                 context: Optional[str] = None) -> Optional[List[Dict]]:
    """[{'summary', 'tone', 'opinion'}] per article, or None"""
    if not articles:
        return None
    prompt = build_prompt(articles, bodies, context)
    for attempt in (1, 2):
        text = ai_text(prompt)
        items = parse_ai_items(text, len(articles))
        if items or text is None:
            return items
        logger.warning(f"AI summary answer unusable (attempt {attempt}/2, {len(articles)} articles): "
                       f"{(text or '')[:200]!r} ... {(text or '')[-120:]!r}")
    return None


def ai_key_points(ticker: str, material: str) -> Optional[List[str]]:
    points = parse_ai_list(ai_text(build_key_points_prompt(ticker, material)))
    return points[:MAX_KEY_POINTS] if points else None


# ---------- public API ----------

def add_summaries(groups: List[List[Dict]], fetch_pages: bool = True, contexts: Optional[List[str]] = None) -> None:
    """
    Add 'summary', 'summary_source' ('ai' | 'snippet' | None) and 'summary_basis' to every article, in place.
    With an AI answer the article also gets 'opinion' (AI 의견: outlook and which watchlist tickers it helps or
    hurts) and 'ai_tag' (호재/중립/악재). An article that appears in several groups (same dict object) is
    summarized once.

    Args:
        groups: lists of articles; each list is summarized in one AI call (e.g. one per ticker)
        fetch_pages: read each article's text (Google News links are resolved first); an article without text or excerpt
            falls back to the page's og:description
        contexts: per group, what the articles were collected for (a ticker, a policy search); None = market-wide
    """
    seen = set()
    fresh_groups = []
    for index, group in enumerate(groups):
        fresh = [a for a in group if id(a) not in seen and not seen.add(id(a))]
        if fresh:
            context = contexts[index] if contexts and index < len(contexts) else None
            fresh_groups.append((fresh, context))

    bodies: Dict[int, str] = {}      # id(article) -> article text (kept out of the published article)
    if fetch_pages:
        everyone = [a for group, _ in fresh_groups for a in group]
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
            for article, text in zip(everyone, pool.map(lambda a: fetch_article_text(a.get('url') or ''), everyone)):
                if text:
                    bodies[id(article)] = text
        missing = [a for a in everyone if not a.get('snippet') and id(a) not in bodies]
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
            for article, text in zip(missing, pool.map(lambda a: fetch_page_description(a['url']), missing)):
                article['snippet'] = clip(text, 600)
        google = [a for a in everyone if 'news.google.com' in (a.get('url') or '')]
        logger.info(f"Article text read for {len(bodies)}/{len(everyone)} articles "
                    f"(Google News links: {sum(1 for a in google if id(a) in bodies)}/{len(google)})")

    chunks = [(group[start:start + BATCH_SIZE], context)
              for group, context in fresh_groups for start in range(0, len(group), BATCH_SIZE)]

    def summarize(job):
        chunk, context = job
        chunk_bodies = {i: bodies[id(a)] for i, a in enumerate(chunk) if id(a) in bodies}
        return chunk_bodies, ai_summaries(chunk, chunk_bodies, context)

    with ThreadPoolExecutor(max_workers=AI_WORKERS) as pool:
        results = list(pool.map(summarize, chunks))

    for (chunk, _), (chunk_bodies, items) in zip(chunks, results):
        for i, article in enumerate(chunk):
            if items:
                item = items[i]
                article['summary'], article['summary_source'] = item['summary'], 'ai'
                # 근거를 화면에 표시한다: 기사 본문 / 제목·발췌 / 제목만
                article['summary_basis'] = ('body' if i in chunk_bodies
                                            else 'excerpt' if article.get('snippet') else 'title')
                if item.get('opinion'):
                    article['opinion'] = item['opinion']
                if item.get('tone'):
                    article['ai_tag'] = item['tone']
            elif article.get('snippet'):
                article['summary'], article['summary_source'] = clip(article['snippet']), 'snippet'
            else:
                article['summary'], article['summary_source'] = None, None


def keep_readable(articles: List[Dict], keep: int) -> List[Dict]:
    """The first `keep` articles (newest first, as given) whose page text can be read"""
    if not articles:
        return []
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        texts = list(pool.map(lambda a: fetch_article_text(a.get('url') or ''), articles))
    return [a for a, text in zip(articles, texts) if text][:keep]


def summary_lines(article: Dict) -> int:
    """Number of lines in an article's summary (bullet lines separated by newlines)"""
    summary = article.get('summary') or ''
    return len([line for line in summary.split('\n') if line.strip()])


def top_with_full_summary(articles: List[Dict], keep: int, min_lines: int = MIN_KEY_POINTS) -> List[Dict]:
    """The first `keep` articles with an AI summary of the article text that has at least `min_lines` lines"""
    good = [a for a in articles
            if a.get('summary_source') == 'ai' and a.get('summary_basis') == 'body' and summary_lines(a) >= min_lines]
    return good[:keep]


def add_key_points(materials: Dict[str, Dict]) -> Dict[str, Dict]:
    """
    ticker -> {'points': [...up to 5], 'source': 'ai' | 'data'}

    Args:
        materials: ticker -> {'text': material for the AI, 'fallback': bullets built from the numbers}
                   (processors.key_points). Without a working AI the number-based bullets are used.
    """
    results = {}
    for ticker, material in materials.items():
        points = ai_key_points(ticker, material['text']) if material.get('text') else None
        if points:
            results[ticker] = {'points': points, 'source': 'ai'}
        elif material.get('fallback'):
            results[ticker] = {'points': material['fallback'][:MAX_KEY_POINTS], 'source': 'data'}
    return results


def section_opinions(subject: str, material: str, sections: Dict[str, str]) -> Optional[Dict[str, str]]:
    """{section key: AI 의견} for one subject; None without a usable AI answer"""
    prompt = build_section_opinion_prompt(subject, material, sections)
    for attempt in (1, 2):
        text = ai_text(prompt)
        opinions = parse_ai_object(text, sections)
        if opinions or text is None:
            return opinions
        logger.warning(f"AI section opinions unusable for {subject} (attempt {attempt}/2): {(text or '')[:200]!r}")
    return None


def add_section_opinions(materials: Dict[str, Dict]) -> Dict[str, Dict[str, str]]:
    """
    key -> {section: AI 의견}

    Args:
        materials: key (a ticker, or e.g. '__market__') -> {'subject', 'text', 'sections': {section: label}}
                   (processors.opinion_material); entries without text are skipped
    """
    jobs = [(key, m) for key, m in materials.items() if m.get('text') and m.get('sections')]

    def run(job):
        key, m = job
        return key, section_opinions(m.get('subject') or key, m['text'], m['sections'])

    with ThreadPoolExecutor(max_workers=AI_WORKERS) as pool:
        return {key: opinions for key, opinions in pool.map(run, jobs) if opinions}
