"""
Storage of the Reddit history: one JSON file on the report-data branch, read and written through the GitHub
contents API (same branch and credentials as notifications.report_publisher)

The file is {"v": 1, "tickers": {ticker: {"YYYY-MM-DD": [rank or null, mentions, upvotes]}}}.
"""

import base64
import json
import logging
from datetime import date
from typing import Dict, Optional, Tuple

import requests

from config import GITHUB_REPOSITORY, GITHUB_TOKEN, REPORT_DATA_BRANCH

logger = logging.getLogger(__name__)

HISTORY_PATH = 'history/reddit.json'
REQUEST_TIMEOUT = 20

SAVED, CONFLICT, FAILED = 'saved', 'conflict', 'failed'


def _url() -> str:
    return f"https://api.github.com/repos/{GITHUB_REPOSITORY}/contents/{HISTORY_PATH}"


def _headers() -> Dict[str, str]:
    return {
        'Authorization': f"Bearer {GITHUB_TOKEN}",
        'Accept': 'application/vnd.github+json',
        'X-GitHub-Api-Version': '2022-11-28',
    }


def load_history() -> Tuple[Dict, Optional[str], bool]:
    """
    Read the stored history

    Returns:
        tuple: (history, sha of the file, readable). `readable` is False when the history could not be read
               (no credentials, network or API error, a file that is not in the expected format); the caller
               must then not write, or it would replace the stored history with a fresh one. A file that does
               not exist yet counts as readable and empty.
    """
    if not (GITHUB_TOKEN and GITHUB_REPOSITORY):
        logger.info("Reddit history not read (no GITHUB_TOKEN / GITHUB_REPOSITORY)")
        return {}, None, False

    try:
        response = requests.get(
            _url(), headers=_headers(), params={'ref': REPORT_DATA_BRANCH}, timeout=REQUEST_TIMEOUT
        )
        if response.status_code == 404:
            return {}, None, True
        response.raise_for_status()
        body = response.json()
        data = json.loads(base64.b64decode(body['content']).decode('utf-8'))
        if data.get('v') != 1 or not isinstance(data.get('tickers'), dict):
            raise ValueError("unexpected format of the history file")
        return data['tickers'], body['sha'], True
    except Exception as e:
        logger.error(f"Failed to read the Reddit history from branch '{REPORT_DATA_BRANCH}': {e}")
        return {}, None, False


def save_history(history: Dict, sha: Optional[str], day: date) -> str:
    """
    Write the history back as one commit

    Args:
        history: The complete history to store
        sha: sha of the file as it was read (None when the file did not exist), so a write that would
             overwrite a newer version is refused instead
        day: Date used in the commit message

    Returns:
        str: SAVED, CONFLICT (someone else wrote the file in between: read it again) or FAILED
    """
    content = json.dumps(
        {'v': 1, 'tickers': history}, ensure_ascii=False, separators=(',', ':'), sort_keys=True
    ).encode('utf-8')
    body = {
        'message': f"Reddit history {day.isoformat()} [skip ci]",
        'content': base64.b64encode(content).decode('ascii'),
        'branch': REPORT_DATA_BRANCH,
    }
    if sha:
        body['sha'] = sha

    try:
        response = requests.put(_url(), headers=_headers(), json=body, timeout=REQUEST_TIMEOUT)
        if response.status_code in (409, 422):
            return CONFLICT
        response.raise_for_status()
        return SAVED
    except Exception as e:
        logger.error(f"Failed to save the Reddit history to branch '{REPORT_DATA_BRANCH}': {e}")
        return FAILED
