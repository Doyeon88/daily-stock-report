"""
Main entry point for Daily Stock Report
Orchestrates the data collection, processing, and notification workflow
"""

import os
import sys
import logging
from datetime import datetime

import pytz

# Add current directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Import configuration
from config import (
    LOG_LEVEL, LOG_FILE, LOG_FORMAT, DATA_DIR,
    STOCKS_TO_TRACK, DAILY_REPORT_TIME, TIMEZONE,
    ENABLE_FCM_NOTIFICATION, SCENARIO_EPS, SCENARIO_NOTES, VALUATION_MULTIPLES, USER_EVENTS, CHECKLIST,
    PORTFOLIO, PORTFOLIO_PUBLISH_AMOUNTS, HEADLINE_MIN, HEADLINE_MAX, ANALYST_REPORTS_PER_TICKER
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
            analyst_changes, competitor_scraper, consensus, headlines, institutional, news_scraper, policy_tracker,
            sec_filings, stock_details, summarizer, yfinance_scraper
        )
        from processors import calendar_events, key_points, portfolio, report_generator, tagging, valuation
        from notifications import fcm_notifier, report_publisher

        logger.info("Step 1: Collecting stock data...")
        stock_data = yfinance_scraper.fetch_stock_data(STOCKS_TO_TRACK)
        logger.info("[OK] Stock data collected")

        # Steps 2-5 are extras: a failure in one of them only drops that part of the report

        logger.info("Step 2: Collecting stock details (volume, 52-week range, short interest, analysts, earnings, RSI)...")
        details = _collect_optional(
            "Stock details",
            lambda: stock_details.fetch_stock_details(STOCKS_TO_TRACK, stock_data), {}
        )
        logger.info(f"- Details for {sum(1 for d in details.values() if d)}/{len(STOCKS_TO_TRACK)} ticker(s)")

        logger.info("Step 3: Collecting news...")
        bundle = _collect_optional(
            "News", lambda: news_scraper.fetch_news_bundle(STOCKS_TO_TRACK), {'news': {}, 'analyst': {}})
        news, analyst_articles = bundle.get('news', {}), bundle.get('analyst', {})
        logger.info(f"- {sum(len(items) for items in news.values())} headline(s)")
        # 리포트(애널리스트 기사): 본문을 읽을 수 있는 최신 후보만 요약하고, 5줄 이상 요약되는 최신 3개만 남긴다
        def prepare_reports():
            spare = ANALYST_REPORTS_PER_TICKER + 2
            for ticker in list(analyst_articles):
                analyst_articles[ticker] = summarizer.keep_readable(analyst_articles[ticker], spare)
        _collect_optional("Readable analyst reports", prepare_reports, None)
        _collect_optional(
            "News summaries",
            lambda: summarizer.add_summaries(list(news.values()) + list(analyst_articles.values())), None)

        def trim_reports():
            for ticker in list(analyst_articles):
                analyst_articles[ticker] = summarizer.top_with_full_summary(
                    analyst_articles[ticker], ANALYST_REPORTS_PER_TICKER)
        _collect_optional("Analyst report selection", trim_reports, None)

        logger.info("Step 4: Collecting SEC filings...")
        filings = _collect_optional(
            "SEC filings", lambda: sec_filings.fetch_sec_filings(STOCKS_TO_TRACK), {}
        )
        logger.info(f"- Filings for {len(filings)}/{len(STOCKS_TO_TRACK)} ticker(s)")

        logger.info("Step 5: Comparing with competitors and the market...")
        comparison = _collect_optional(
            "Competitor comparison", lambda: competitor_scraper.compare_stocks(STOCKS_TO_TRACK), {}
        )
        logger.info(f"- {len(comparison.get('market', []))} market index(es)")

        logger.info("Step 5b: Analyst and consensus changes, 13F holders (13F season only), policy news...")
        consensus_data = _collect_optional("Consensus", lambda: consensus.fetch_consensus(STOCKS_TO_TRACK), {})
        analyst = _collect_optional("Analyst changes", lambda: analyst_changes.fetch_analyst_changes(STOCKS_TO_TRACK), {})
        holders = _collect_optional("13F holders", lambda: institutional.fetch_institutional(STOCKS_TO_TRACK), {})
        policy = _collect_optional("Policy news", policy_tracker.fetch_policy_news, [])
        _collect_optional(
            "Policy summaries", lambda: summarizer.add_summaries([g['articles'] for g in policy]), None)

        logger.info("Step 5c: Today's headlines (market, economy, commodities, sentiment, politics)...")
        headline_list = _collect_optional(
            "Headlines", lambda: headlines.select_headlines(headlines.fetch_candidates(), minimum=HEADLINE_MIN,
                                                            maximum=HEADLINE_MAX), [])
        logger.info(f"- {len(headline_list)} headline(s)")

        # Local calculations (no network): calendar, valuation vs. scenario EPS, portfolio, checklist
        today = datetime.now(pytz.timezone(TIMEZONE)).date()
        calendar = calendar_events.build_calendar(today, details, USER_EVENTS)
        valuations = {}
        for ticker, eps in SCENARIO_EPS.items():
            result = valuation.scenario_valuation(
                (stock_data.get(ticker) or {}).get('price'), eps, VALUATION_MULTIPLES)
            if result:
                result['note'] = SCENARIO_NOTES.get(ticker, '')
                valuations[ticker] = result
        portfolio_result = portfolio.compute_portfolio(PORTFOLIO, stock_data)
        # 종목별 핵심 5가지: 수집한 자료만 근거로 AI가 정리(안 되면 수치 요약)
        def collect_key_points():
            materials = {
                t: key_points.build_material(
                    t, details.get(t), tagging.tag_news(news.get(t, [])), analyst_articles.get(t, []),
                    analyst.get(t), {'filings': tagging.tag_filings((filings.get(t) or {}).get('filings', []))})
                for t in STOCKS_TO_TRACK
            }
            return summarizer.add_key_points(materials)
        points = _collect_optional("Key points", collect_key_points, {})

        extras = {
            'analyst_articles': {t: tagging.tag_news(items) for t, items in analyst_articles.items()},
            'key_points': points,
            'headlines': headline_list,
            'analyst': analyst, 'consensus': consensus_data, 'institutional': holders, 'policy': policy, 'calendar': calendar,
            'valuation': valuations,
            'portfolio': portfolio_result,   # 금액 포함: 로컬 출력용, 저장소에는 올리지 않는다
            'portfolio_public': portfolio.public_view(portfolio_result, PORTFOLIO_PUBLISH_AMOUNTS),
            'checklist': calendar_events.build_checklists(STOCKS_TO_TRACK, calendar, CHECKLIST),
        }

        # CEO social media monitoring is not implemented

        logger.info("Step 6: Generating report...")
        report = report_generator.generate_report(stock_data, details, news, filings, comparison, extras)
        logger.info(f"[OK] Report generated ({len(report['flags'])} signal(s))")

        logger.info("Step 7: Sending push notification...")
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
