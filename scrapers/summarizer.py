"""
기사 요약·종목별 핵심 정리 (한국어)

AI 공급자 순서: Claude(ANTHROPIC_API_KEY) → GitHub Models(Actions의 GITHUB_TOKEN, 워크플로에 models: read 권한 필요).
둘 다 안 되면 기사 발췌문(영문일 수 있음)을 그대로 보여 주고, 발췌문도 없으면 요약 없이 제목만 나옵니다.
AI에는 수집한 제목·발췌문·수치만 주고 "그 밖의 지식·추측 금지"를 지시하지만, 기사 본문 전체를 읽지 않으므로
결과는 제목·발췌 범위를 넘지 않고, 언론 기사 기반이라 '미검증' 표시는 유지됩니다.
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
MAX_KEY_POINTS = 5
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


def clip(text: str, limit: int = MAX_SUMMARY_LENGTH) -> str:
    text = re.sub(r'\s+', ' ', text or '').strip()
    return text if len(text) <= limit else text[:limit - 1].rstrip() + '…'


# ---------- prompts and parsing ----------

def build_prompt(articles: List[Dict]) -> str:
    lines = [
        '아래 뉴스 각각을 한국어 1~2문장(최대 120자)으로 요약해 주세요. 영어 기사는 한국어로 옮겨 요약합니다.',
        '규칙: 제목과 발췌문에 있는 내용만 쓰고 추측·평가·투자 의견을 넣지 않습니다. 숫자·고유명사는 그대로 둡니다.',
        '발췌문이 없으면 제목이 말하는 내용만 옮기세요.',
        '출력은 JSON 문자열 배열 하나뿐이며 입력과 같은 순서·같은 개수여야 합니다.', '',
    ]
    for i, a in enumerate(articles, 1):
        lines.append(f"{i}. 제목: {a.get('title', '')}\n   발췌: {a.get('snippet') or '(없음)'}")
    return '\n'.join(lines)


def build_key_points_prompt(ticker: str, material: str) -> str:
    return (
        f'아래는 {ticker} 종목에 대해 오늘 수집한 자료(뉴스 제목·발췌, 애널리스트 의견 변경, 컨센서스, 공시)입니다.\n'
        f'투자자가 꼭 알아야 할 중요 내용을 한국어로 최대 {MAX_KEY_POINTS}개, 각 1문장(최대 100자)으로 정리해 주세요.\n'
        '규칙: 아래 자료에 있는 내용만 사용하고 자료에 없는 사실·전망·추측·투자 권유를 넣지 않습니다. '
        '숫자와 출처(증권사 이름 등)는 그대로 둡니다. 중복되는 내용은 합치고, 중요도 순으로 씁니다.\n'
        '출력은 JSON 문자열 배열 하나뿐입니다.\n\n' + material)


def parse_ai_summaries(text: str, expected: int) -> Optional[List[str]]:
    """The JSON array in the model's answer, or None if it is missing or has the wrong length"""
    items = parse_ai_list(text)
    if items is None or len(items) != expected:
        return None
    return items


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
    return [clip(x) for x in data]


# ---------- providers ----------

def _json_body(response) -> Dict:
    """response.json(), but a body that is not JSON is reported with its status and start (for the Actions log)"""
    try:
        return response.json()
    except ValueError:
        redirects = [r.status_code for r in getattr(response, 'history', [])]
        raise ProviderUnusable(
            f"not JSON: HTTP {response.status_code}, content-type {response.headers.get('Content-Type')}, "
            f"redirects {redirects}, body starts {response.text[:200]!r}")


def _post(url: str, headers: Dict, payload: Dict) -> Dict:
    response = requests.post(url, headers=headers, json=payload, timeout=API_TIMEOUT)
    if response.status_code in (401, 403, 404):
        raise ProviderUnusable(f"HTTP {response.status_code}: {response.text[:200]!r}")
    response.raise_for_status()
    return _json_body(response)


def _claude_text(prompt: str) -> Optional[str]:
    if not ANTHROPIC_API_KEY or 'claude' in _unusable:
        return None
    try:
        body = _post(API_URL, {'x-api-key': ANTHROPIC_API_KEY, 'anthropic-version': '2023-06-01',
                               'content-type': 'application/json'},
                     {'model': ANTHROPIC_MODEL, 'max_tokens': 1500,
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
                         {'model': model, 'max_tokens': 1500, 'temperature': 0.2,
                          'messages': [{'role': 'user', 'content': prompt}]})
            return body['choices'][0]['message']['content']
        except ProviderUnusable as e:
            _unusable.add(url)
            logger.error(f"GitHub Models endpoint {url} unusable, skipping it for this run: {e}")
        except Exception as e:
            logger.error(f"GitHub Models call to {url} failed: {e}")
            return None   # a temporary error (rate limit, 5xx): do not hammer the other endpoint
    return None


def ai_text(prompt: str) -> Optional[str]:
    """The model's answer from Claude, else GitHub Models; None if neither is configured/usable"""
    return _claude_text(prompt) or _github_models_text(prompt)


def ai_summaries(articles: List[Dict]) -> Optional[List[str]]:
    if not articles:
        return None
    return parse_ai_summaries(ai_text(build_prompt(articles)), len(articles))


def ai_key_points(ticker: str, material: str) -> Optional[List[str]]:
    points = parse_ai_list(ai_text(build_key_points_prompt(ticker, material)))
    return points[:MAX_KEY_POINTS] if points else None


# ---------- public API ----------

def add_summaries(groups: List[List[Dict]], fetch_pages: bool = True) -> None:
    """
    Add 'summary', 'summary_source' ('ai' | 'snippet' | None) and 'summary_basis' to every article, in place.
    An article that appears in several groups (same dict object) is summarized once.

    Args:
        groups: lists of articles; each list is summarized in one AI call (e.g. one per ticker)
        fetch_pages: also try the page's og:description when an article has no excerpt
    """
    seen = set()
    fresh_groups = []
    for group in groups:
        fresh = [a for a in group if id(a) not in seen and not seen.add(id(a))]
        if fresh:
            fresh_groups.append(fresh)

    if fetch_pages:
        missing = [a for group in fresh_groups for a in group if not a.get('snippet')]
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
            for article, text in zip(missing, pool.map(lambda a: fetch_page_description(a['url']), missing)):
                article['snippet'] = clip(text, 600)

    for group in fresh_groups:
        summaries = ai_summaries(group)
        for i, article in enumerate(group):
            if summaries:
                article['summary'], article['summary_source'] = summaries[i], 'ai'
                # 발췌문이 없으면 제목만 보고 쓴 요약이므로 화면에 그렇게 표시한다
                article['summary_basis'] = 'excerpt' if article.get('snippet') else 'title'
            elif article.get('snippet'):
                article['summary'], article['summary_source'] = clip(article['snippet']), 'snippet'
            else:
                article['summary'], article['summary_source'] = None, None


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
