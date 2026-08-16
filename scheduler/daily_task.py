"""
Scheduler for running daily stock report at specified time
Supports both development (local scheduling) and production (cron/systemd) modes
"""

import schedule
import time
import logging
import subprocess
import sys
from datetime import datetime
import pytz

from config import DAILY_REPORT_TIME, TIMEZONE

logger = logging.getLogger(__name__)


def run_daily_report():
    """
    Execute the daily stock report
    """
    logger.info(f"Running daily report at {datetime.now()}")
    
    try:
        # Run main.py as subprocess
        result = subprocess.run(
            [sys.executable, 'main.py'],
            capture_output=True,
            text=True,
            timeout=300  # 5 minute timeout
        )
        
        if result.returncode == 0:
            logger.info("Daily report completed successfully")
            return True
        else:
            logger.error(f"Daily report failed with return code {result.returncode}")
            logger.error(f"STDERR: {result.stderr}")
            return False
            
    except subprocess.TimeoutExpired:
        logger.error("Daily report timed out after 5 minutes")
        return False
    except Exception as e:
        logger.error(f"Error running daily report: {str(e)}")
        return False


def start_scheduler():
    """
    Start the scheduler in foreground
    This is for development/testing purposes
    For production, use cron or systemd
    """
    logger.info(f"Scheduler started. Running daily report at {DAILY_REPORT_TIME} {TIMEZONE}")
    
    # Schedule the job
    schedule.every().day.at(DAILY_REPORT_TIME).do(run_daily_report)
    
    # Keep scheduler running
    while True:
        schedule.run_pending()
        time.sleep(60)  # Check every minute


if __name__ == "__main__":
    # Configure logging for scheduler
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    start_scheduler()