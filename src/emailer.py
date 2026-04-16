import logging
import os
import smtplib
from collections import defaultdict
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import yaml
from dotenv import load_dotenv
from jinja2 import Environment, FileSystemLoader

from src.db import Change, Competitor, CrawlRun, CrawlTarget, get_session

load_dotenv()

logger = logging.getLogger(__name__)


def build_digest(crawl_run_id: int | None = None) -> tuple[str, str]:
    """Build HTML email digest for a crawl run.

    Returns (subject, html_body).
    If crawl_run_id is None, uses the latest completed run.
    """
    session = get_session()

    if crawl_run_id is None:
        crawl_run = (
            session.query(CrawlRun)
            .filter(CrawlRun.status == "completed")
            .order_by(CrawlRun.completed_at.desc())
            .first()
        )
    else:
        crawl_run = session.query(CrawlRun).get(crawl_run_id)

    if not crawl_run:
        session.close()
        return "No crawl data", "<p>No completed crawl runs found.</p>"

    # Get all changes for this run, joined with target and competitor
    changes = (
        session.query(Change, CrawlTarget, Competitor)
        .join(CrawlTarget, Change.crawl_target_id == CrawlTarget.id)
        .join(Competitor, CrawlTarget.competitor_id == Competitor.id)
        .filter(Change.crawl_run_id == crawl_run.id)
        .order_by(Competitor.name, Change.category)
        .all()
    )

    # Group: competitor -> category -> list of changes
    changes_by_competitor = defaultdict(lambda: defaultdict(list))
    competitors_with_changes = set()

    for change, target, competitor in changes:
        competitors_with_changes.add(competitor.name)
        categories = change.category or "uncategorized"
        for cat in categories.split(", "):
            changes_by_competitor[competitor.name][cat].append({
                "change_type": change.change_type,
                "summary": change.summary,
                "url": target.url,
            })

    # Find competitors with no changes
    all_competitors = session.query(Competitor).filter(Competitor.active == True).all()
    no_change_competitors = [c.name for c in all_competitors if c.name not in competitors_with_changes]

    # Load settings for subject prefix
    with open("config/settings.yaml") as f:
        settings = yaml.safe_load(f)
    prefix = settings.get("email", {}).get("subject_prefix", "IILM Competitive Intel")

    now = datetime.now(timezone.utc)
    subject = f"{prefix} — Week of {now.strftime('%b %d, %Y')}"

    # Render HTML template
    env = Environment(loader=FileSystemLoader("templates"))
    template = env.get_template("email_digest.html")
    html = template.render(
        subject=subject,
        total_pages=crawl_run.pages_crawled,
        total_competitors=len(all_competitors),
        total_changes=len(changes),
        changes_by_competitor=dict(changes_by_competitor),
        no_change_competitors=no_change_competitors,
        generated_at=now.strftime("%Y-%m-%d %H:%M UTC"),
    )

    session.close()
    return subject, html


def send_digest(crawl_run_id: int | None = None):
    """Build and send the email digest."""
    subject, html = build_digest(crawl_run_id)

    gmail_address = os.getenv("GMAIL_ADDRESS")
    gmail_password = os.getenv("GMAIL_APP_PASSWORD")
    recipients = os.getenv("DIGEST_RECIPIENTS", "").split(",")
    recipients = [r.strip() for r in recipients if r.strip()]

    if not gmail_address or not gmail_password:
        logger.error("Gmail credentials not set in .env — cannot send digest")
        # Save HTML locally as fallback
        with open("latest_digest.html", "w", encoding="utf-8") as f:
            f.write(html)
        logger.info("Digest saved to latest_digest.html")
        return

    if not recipients:
        logger.error("No DIGEST_RECIPIENTS set in .env")
        return

    with open("config/settings.yaml") as f:
        settings = yaml.safe_load(f)
    smtp_server = settings.get("email", {}).get("smtp_server", "smtp.gmail.com")
    smtp_port = settings.get("email", {}).get("smtp_port", 587)

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = gmail_address
    msg["To"] = ", ".join(recipients)
    msg.attach(MIMEText(html, "html"))

    try:
        with smtplib.SMTP(smtp_server, smtp_port) as server:
            server.starttls()
            server.login(gmail_address, gmail_password)
            server.send_message(msg)
        logger.info(f"Digest sent to {', '.join(recipients)}")
    except Exception as e:
        logger.error(f"Failed to send email: {e}")
        # Save locally as fallback
        with open("latest_digest.html", "w", encoding="utf-8") as f:
            f.write(html)
        logger.info("Digest saved to latest_digest.html as fallback")
