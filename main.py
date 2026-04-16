#!/usr/bin/env python3
"""IILM Competitive Intelligence Tool

Usage:
    python main.py init       — Initialize database tables
    python main.py crawl      — Run a one-off crawl + change detection
    python main.py digest     — Send email digest of latest crawl
    python main.py run        — Start weekly scheduler (crawl + digest)
"""
import asyncio
import logging
import sys

from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("comp-crawl")


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    command = sys.argv[1].lower()

    if command == "init":
        from src.db import init_db
        init_db()

    elif command == "crawl":
        from src.crawler import crawl_all
        crawl_run_id = asyncio.run(crawl_all())
        print(f"Crawl complete. Run ID: {crawl_run_id}")

    elif command == "digest":
        from src.emailer import send_digest
        crawl_run_id = int(sys.argv[2]) if len(sys.argv) > 2 else None
        send_digest(crawl_run_id)
        print("Digest sent (or saved to latest_digest.html).")

    elif command == "run":
        from src.scheduler import start_scheduler
        start_scheduler()

    else:
        print(f"Unknown command: {command}")
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
