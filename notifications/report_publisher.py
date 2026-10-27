"""
Publish the full report as a JSON file on a data branch

A push notification only carries ~4KB, too little for news and details. The report page loads
the full report from this file instead. The file lives on its own branch (REPORT_DATA_BRANCH),
so it does not touch main, does not trigger a Pages rebuild and does not trigger CI ([skip ci]).
"""

import base64
import json
import logging
from datetime import datetime, timezone
from typing import Dict, Optional

import requests

from config import GITHUB_REPOSITORY, GITHUB_TOKEN, REPORT_DATA_BRANCH
from processors.report_payload import build_full_payload

logger = logging.getLogger(__name__)

REQUEST_TIMEOUT = 20


def publish_report(report: Dict) -> Optional[str]:
    """
    Commit the full report to the data branch through the GitHub contents API

    Args:
        report: Report dictionary from report_generator.generate_report

    Returns:
        str: URL of the committed file, pinned to the commit (available immediately and never
             changes, so older notification links keep showing their own day's report);
             None if publishing is not possible or failed, in which case the notification link
             falls back to the core table
    """
    if not GITHUB_TOKEN or not GITHUB_REPOSITORY:
        logger.info("Report data not published (no GITHUB_TOKEN / GITHUB_REPOSITORY), link carries the core table only")
        return None

    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    path = f"reports/{stamp}.json"
    content = json.dumps(build_full_payload(report), ensure_ascii=False, separators=(',', ':')).encode('utf-8')

    try:
        response = requests.put(
            f"https://api.github.com/repos/{GITHUB_REPOSITORY}/contents/{path}",
            headers={
                'Authorization': f"Bearer {GITHUB_TOKEN}",
                'Accept': 'application/vnd.github+json',
                'X-GitHub-Api-Version': '2022-11-28',
            },
            json={
                'message': f"Report {stamp} [skip ci]",
                'content': base64.b64encode(content).decode('ascii'),
                'branch': REPORT_DATA_BRANCH,
            },
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        commit_sha = response.json()['commit']['sha']
    except Exception as e:
        logger.error(f"Failed to publish report data to branch '{REPORT_DATA_BRANCH}': {e}")
        return None

    logger.info(f"Report data published: {path} @ {commit_sha[:7]}")
    return f"https://raw.githubusercontent.com/{GITHUB_REPOSITORY}/{commit_sha}/{path}"
