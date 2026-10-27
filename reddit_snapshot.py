"""
Record today's Reddit mention snapshot, nothing else (no report, no notification)

Run every day by .github/workflows/reddit_snapshot.yml so the history has no gaps on the days the report
does not run. Exits with 1 if the snapshot could not be recorded, so the run shows up as failed.
"""

import os
import sys
import logging

# Add current directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import STOCKS_TO_TRACK

logger = logging.getLogger(__name__)


def main():
    from processors import reddit_history

    logger.info(f"Reddit snapshot - Starting for {STOCKS_TO_TRACK}")
    if not reddit_history.record_missing_snapshot(STOCKS_TO_TRACK):
        logger.error("Reddit snapshot - Failed")
        sys.exit(1)
    logger.info("Reddit snapshot - Done")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    main()
