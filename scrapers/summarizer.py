"""
기사 요약 붙이기

우선순위:
 1. ANTHROPIC_API_KEY가 있으면 Claude가 제목·발췌문만 근거로 한국어 1~2문장 요약 (summary_source='ai')
 1b. 키가 없거나 실패하면 GitHub Models(Actions의 GITHUB_TOKEN, 워크플로에 models: read 권한 필요)로 같은 요약
 2. 그것도 안 되면 기사 발췌문(Finnhub 요약, 페이지의 og:description)을 그대로 (summary_source='snippet')
 3. 둘 다 없으면 요약 없음 (제목만). 본문 전체를 읽지 못하므로 '요약'은 제목·발췌 범위를 넘지 않습니다.
요약은 언론 기사 기반이라 '미검증' 표시는 그대로 유지됩니다.
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
# GitHub Models: GitHub Actions의 자동 토큰으로 호출(별도 키 없음). 사용 가능한 모델·한도는 GitHub 계정 설정을 따릅니다.
GITHUB_MODELS_TOKEN = (os.getenv('GITHUB_TOKEN') or '').strip() or None
GITHUB_MODELS_MODEL = os.getenv('GITHUB_MODELS_MODEL') or 'openai/gpt-4.1-mini'
GITHUB_MODELS_URL = 'https://models.github.ai/inference/chat/completions'
PAGE_TIMEOUT = 6
API_TIMEOUT = 40
MAX_WORKERS = 8
MAX_SUMMARY_LENGTH = 220
USER_AGENT = 'Mozilla/5.0 (compatible; daily-stock-report)'

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


def build_prompt(articles: List[Dict]) -> str:
    lines = [
        '아래 뉴스 각각을 한국어 1~2문장(최대 120자)으로 요약해 주세요.',
        '규칙: 제목과 발췌문에 있는 내용만 쓰고 추측·평가·투자 의견을 넣지 않습니다. 숫자·고유명사는 그대로 둡니다.',
        '발췌문이 없으면 제목이 말하는 내용만 옮기세요.',
        '출력은 JSON 문자열 배열 하나뿐이며 입력과 같은 순서·같은 개수여야 합니다.', '',
    ]
    for i, a in enumerate(articles, 1):
        lines.append(f"{i}. 제목: {a.get('title', '')}\n   발췌: {a.get('snippet') or '(없음)'}")
    return '\n'.join(lines)


def parse_ai_summaries(text: str, expected: int) -> Optional[List[str]]:
    """The JSON array in the model's answer, or None if it is missing or has the wrong length"""
    match = re.search(r'\[.*\]', text or '', re.S)
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
    except ValueError:
        return None
    if not isinstance(data, list) or len(data) != expected or not all(isinstance(x, str) for x in data):
        return None
    return [clip(x) for x in data]


def _claude_summaries(articles: List[Dict]) -> Optional[List[str]]:
    if not ANTHROPIC_API_KEY:
        return None
    try:
        response = requests.post(
            API_URL,
            headers={'x-api-key': ANTHROPIC_API_KEY, 'anthropic-version': '2023-06-01',
                     'content-type': 'application/json'},
            json={'model': ANTHROPIC_MODEL, 'max_tokens': 1500,
                  'messages': [{'role': 'user', 'content': build_prompt(articles)}]},
            timeout=API_TIMEOUT,
        )
        response.raise_for_status()
        text = ''.join(b.get('text', '') for b in response.json().get('content', []))
        return parse_ai_summaries(text, len(articles))
    except Exception as e:
        logger.error(f"Claude summaries unavailable: {e}")
        return None


def _github_models_summaries(articles: List[Dict]) -> Optional[List[str]]:
    if not GITHUB_MODELS_TOKEN:
        return None
    try:
        response = requests.post(
            GITHUB_MODELS_URL,
            headers={'Authorization': f'Bearer {GITHUB_MODELS_TOKEN}', 'Accept': 'application/vnd.github+json',
                     'X-GitHub-Api-Version': '2022-11-28', 'Content-Type': 'application/json'},
            json={'model': GITHUB_MODELS_MODEL, 'max_tokens': 1500, 'temperature': 0.2,
                  'messages': [{'role': 'user', 'content': build_prompt(articles)}]},
            timeout=API_TIMEOUT,
        )
        response.raise_for_status()
        text = response.json()['choices'][0]['message']['content']
        return parse_ai_summaries(text, len(articles))
    except Exception as e:
        logger.error(f"GitHub Models summaries unavailable: {e}")
        return None


def ai_summaries(articles: List[Dict]) -> Optional[List[str]]:
    """Claude first, then GitHub Models; None if neither is configured or both fail"""
    if not articles:
        return None
    return _claude_summaries(articles) or _github_models_summaries(articles)


def add_summaries(groups: List[List[Dict]], fetch_pages: bool = True) -> None:
    """
    Add 'summary' and 'summary_source' ('ai' | 'snippet' | None) to every article, in place.

    Args:
        groups: lists of articles; each list is summarized in one AI call (e.g. one per ticker)
        fetch_pages: also try the page's og:description when an article has no excerpt
    """
    articles = [a for group in groups for a in group]
    if fetch_pages:
        missing = [a for a in articles if not a.get('snippet')]
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
            for article, text in zip(missing, pool.map(lambda a: fetch_page_description(a['url']), missing)):
                article['snippet'] = clip(text, 600)

    for group in groups:
        summaries = ai_summaries(group)
        for i, article in enumerate(group):
            if summaries:
                article['summary'], article['summary_source'] = summaries[i], 'ai'
            elif article.get('snippet'):
                article['summary'], article['summary_source'] = clip(article['snippet']), 'snippet'
            else:
                article['summary'], article['summary_source'] = None, None
