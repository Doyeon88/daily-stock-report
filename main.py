"""
Main entry point for Daily Stock Report
Orchestrates the data collection, processing, and notification workflow
"""

import os
import sys
import logging
from datetime import datetime

# Add current directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Import configuration
from config import (
    LOG_LEVEL, LOG_FILE, LOG_FORMAT, DATA_DIR,
    STOCKS_TO_TRACK, DAILY_REPORT_TIME, TIMEZONE,
    ENABLE_FCM_NOTIFICATION
)

logger = logging.getLogger(__name__)


def configure_logging():
    """
    Create output directories and configure logging
    Called at run time (not on import) so importing main has no side effects
    """
    os.makedirs(DATA_DIR, exist_ok=True)
    os.makedirs('logs', exist_ok=True)

    logging.basicConfig(
        level=getattr(logging, LOG_LEVEL),
        format=LOG_FORMAT,
        handlers=[
            logging.FileHandler(LOG_FILE, encoding='utf-8'),
            logging.StreamHandler()
        ]
    )


def _collect_optional(name, collect, default):
    """
    Run an optional data collector; the report is still sent without it if it fails
    """
    try:
        return collect()
    except Exception as e:
        logger.error(f"[WARN] {name} unavailable, continuing without it: {e}")
        return default


def main():
    """
    Main function to run daily stock report
    """
    logger.info("=" * 60)
    logger.info("Daily Stock Report - Starting")
    logger.info(f"Timestamp: {datetime.now()}")
    logger.info(f"Stocks to track: {STOCKS_TO_TRACK}")
    logger.info("=" * 60)

    try:
        # Import data collectors, processors and notifications
        from scrapers import (
            competitor_scraper, news_scraper, reddit_mentions, sec_filings, stock_details,
            yfinance_scraper
        )
        from processors import reddit_history, report_generator
        from notifications import fcm_notifier, report_publisher

        logger.info("Step 1: Collecting stock data...")
        stock_data = yfinance_scraper.fetch_stock_data(STOCKS_TO_TRACK)
        logger.info("[OK] Stock data collected")

        # Steps 2-6 are extras: a failure in one of them only drops that part of the report

        logger.info("Step 2: Collecting stock details (volume, 52-week range, short interest, analysts, earnings, RSI)...")
        details = _collect_optional(
            "Stock details",
            lambda: stock_details.fetch_stock_details(STOCKS_TO_TRACK, stock_data), {}
        )
        logger.info(f"- Details for {sum(1 for d in details.values() if d)}/{len(STOCKS_TO_TRACK)} ticker(s)")

        logger.info("Step 3: Collecting news...")
        news = _collect_optional("News", lambda: news_scraper.fetch_news(STOCKS_TO_TRACK), {})
        logger.info(f"- {sum(len(items) for items in news.values())} headline(s)")

        logger.info("Step 4: Collecting SEC filings...")
        filings = _collect_optional(
            "SEC filings", lambda: sec_filings.fetch_sec_filings(STOCKS_TO_TRACK), {}
        )
        logger.info(f"- Filings for {len(filings)}/{len(STOCKS_TO_TRACK)} ticker(s)")

        logger.info("Step 5: Collecting Reddit mentions...")
        reddit = _collect_optional(
            "Reddit mentions", lambda: reddit_mentions.fetch_reddit_mentions(STOCKS_TO_TRACK), {}
        )
        logger.info(f"- {sum(1 for mentions in reddit.values() if mentions)}/{len(STOCKS_TO_TRACK)} ticker(s) ranked")
        # Today's snapshot goes into the stored history; the report plots the daily and weekly series from it
        reddit_trend = _collect_optional(
            "Reddit history", lambda: reddit_history.update_history(reddit), {}
        )
        logger.info(f"- History for {len(reddit_trend)} ticker(s)")

        logger.info("Step 6: Comparing with competitors and the market...")
        comparison = _collect_optional(
            "Competitor comparison", lambda: competitor_scraper.compare_stocks(STOCKS_TO_TRACK), {}
        )
        logger.info(f"- {len(comparison.get('market', []))} market index(es)")

        # CEO social media monitoring is not implemented

        logger.info("Step 7: Generating report...")
        report = report_generator.generate_report(
            stock_data, details, news, filings, comparison, reddit, reddit_trend
        )
        logger.info(f"[OK] Report generated ({len(report['flags'])} signal(s))")

        logger.info("Step 8: Sending push notification...")
        # The notification carries only the summary; the report page loads the full report from this file
        report['data_url'] = report_publisher.publish_report(report)
        notified = fcm_notifier.send_report(report)
        if notified:
            logger.info("[OK] Notification sent")
        elif ENABLE_FCM_NOTIFICATION:
            logger.error("[FAIL] Notification was not delivered")
        else:
            logger.info("- Skipped (FCM notifications are disabled)")

        # Report problems through the exit code so the scheduler / GitHub Actions run fails visibly
        failures = []
        if stock_data and all(data.get('error') is not None for data in stock_data.values()):
            failures.append("no stock data could be collected")
        if ENABLE_FCM_NOTIFICATION and not notified:
            failures.append("push notification was not delivered")

        if failures:
            logger.error(f"Daily Stock Report - Failed: {'; '.join(failures)}")
            sys.exit(1)

        logger.info("=" * 60)
        logger.info("Daily Stock Report - Completed successfully!")
        logger.info("=" * 60)

    except Exception as e:
        logger.error(f"Error during report generation: {str(e)}", exc_info=True)
        # TODO: Send error notification
        sys.exit(1)


if __name__ == "__main__":
    configure_logging()
    main()
