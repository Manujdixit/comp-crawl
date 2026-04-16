import asyncio
import difflib
import logging

from src.db import Change, CrawlRun, CrawlTarget, PageSnapshot, get_latest_snapshot
from src.extractor import summarize_changes

logger = logging.getLogger(__name__)


def detect_changes(session, target: CrawlTarget, new_snapshot: PageSnapshot,
                   crawl_run: CrawlRun) -> list[Change]:
    """Compare new snapshot against the previous one for the same target.

    Returns list of Change records created.
    """
    # Get the previous snapshot (exclude the one we just inserted)
    prev_snapshot = (
        session.query(PageSnapshot)
        .filter(
            PageSnapshot.crawl_target_id == target.id,
            PageSnapshot.id != new_snapshot.id,
        )
        .order_by(PageSnapshot.crawled_at.desc())
        .first()
    )

    changes = []

    if prev_snapshot is None:
        # First time seeing this page — record as "added"
        categories = (new_snapshot.extracted_data or {}).get("categories", ["uncategorized"])
        change = Change(
            crawl_target_id=target.id,
            crawl_run_id=crawl_run.id,
            change_type="added",
            category=", ".join(categories),
            summary=f"New page discovered: {target.url}",
            diff_text=None,
        )
        session.add(change)
        session.commit()
        changes.append(change)
        return changes

    # Quick check: has anything changed?
    if prev_snapshot.content_hash == new_snapshot.content_hash:
        return []  # No changes

    # Generate diff
    old_lines = (prev_snapshot.content_markdown or "").splitlines(keepends=True)
    new_lines = (new_snapshot.content_markdown or "").splitlines(keepends=True)
    diff = list(difflib.unified_diff(old_lines, new_lines, lineterm="",
                                      fromfile="previous", tofile="current"))
    diff_text = "\n".join(diff)

    if not diff_text.strip():
        return []  # Whitespace-only changes

    # Get LLM summary (run async from sync context)
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # We're already in an async context — create a task
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                summary = loop.run_in_executor(pool, lambda: "Content modified (summary pending)")
                summary = "Content modified on this page"
        else:
            summary = loop.run_until_complete(summarize_changes(diff_text, target.url))
    except RuntimeError:
        summary = "Content modified on this page"

    categories = (new_snapshot.extracted_data or {}).get("categories", ["uncategorized"])

    change = Change(
        crawl_target_id=target.id,
        crawl_run_id=crawl_run.id,
        change_type="modified",
        category=", ".join(categories),
        summary=summary,
        diff_text=diff_text[:10000],  # Cap diff size
    )
    session.add(change)
    session.commit()
    changes.append(change)

    logger.info(f"  Change detected: {target.url} — {summary[:80]}")
    return changes


async def detect_changes_async(session, target: CrawlTarget, new_snapshot: PageSnapshot,
                               crawl_run: CrawlRun) -> list[Change]:
    """Async version of detect_changes with proper LLM summarization."""
    prev_snapshot = (
        session.query(PageSnapshot)
        .filter(
            PageSnapshot.crawl_target_id == target.id,
            PageSnapshot.id != new_snapshot.id,
        )
        .order_by(PageSnapshot.crawled_at.desc())
        .first()
    )

    changes = []

    if prev_snapshot is None:
        categories = (new_snapshot.extracted_data or {}).get("categories", ["uncategorized"])
        change = Change(
            crawl_target_id=target.id,
            crawl_run_id=crawl_run.id,
            change_type="added",
            category=", ".join(categories),
            summary=f"New page discovered: {target.url}",
            diff_text=None,
        )
        session.add(change)
        session.commit()
        changes.append(change)
        return changes

    if prev_snapshot.content_hash == new_snapshot.content_hash:
        return []

    old_lines = (prev_snapshot.content_markdown or "").splitlines(keepends=True)
    new_lines = (new_snapshot.content_markdown or "").splitlines(keepends=True)
    diff = list(difflib.unified_diff(old_lines, new_lines, lineterm="",
                                      fromfile="previous", tofile="current"))
    diff_text = "\n".join(diff)

    if not diff_text.strip():
        return []

    summary = await summarize_changes(diff_text, target.url)
    categories = (new_snapshot.extracted_data or {}).get("categories", ["uncategorized"])

    change = Change(
        crawl_target_id=target.id,
        crawl_run_id=crawl_run.id,
        change_type="modified",
        category=", ".join(categories),
        summary=summary,
        diff_text=diff_text[:10000],
    )
    session.add(change)
    session.commit()
    changes.append(change)

    logger.info(f"  Change detected: {target.url} — {summary[:80]}")
    return changes
