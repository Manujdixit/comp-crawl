import asyncio
import logging

import yaml
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

from src.crawler import crawl_all
from src.emailer import send_digest

logger = logging.getLogger(__name__)


def run_crawl_and_digest():
    """Run a full crawl cycle then send the email digest."""
    logger.info("Scheduled crawl starting...")
    crawl_run_id = asyncio.run(crawl_all())
    logger.info(f"Crawl complete (run #{crawl_run_id}). Sending digest...")
    send_digest(crawl_run_id)
    logger.info("Digest sent. Cycle complete.")


def start_scheduler():
    """Start the APScheduler with cron trigger from settings."""
    with open("config/settings.yaml") as f:
        settings = yaml.safe_load(f)

    schedule = settings.get("schedule", {})
    trigger = CronTrigger(
        day_of_week=schedule.get("day_of_week", "sun"),
        hour=schedule.get("hour", 20),
        minute=schedule.get("minute", 0),
    )

    scheduler = BlockingScheduler()
    scheduler.add_job(run_crawl_and_digest, trigger, id="weekly_crawl")

    logger.info(
        f"Scheduler started — running every {schedule.get('day_of_week', 'sun')} "
        f"at {schedule.get('hour', 20)}:{schedule.get('minute', 0):02d}"
    )

    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Scheduler stopped.")
