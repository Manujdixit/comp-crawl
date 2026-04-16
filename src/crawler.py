import asyncio
import hashlib
import logging
import xml.etree.ElementTree as ET
from urllib.parse import urljoin, urlparse

import yaml
from crawl4ai import AsyncWebCrawler, CrawlerRunConfig

from src.db import (
    Change,
    Competitor,
    CrawlRun,
    CrawlTarget,
    PageSnapshot,
    get_or_create_target,
    get_session,
    sync_competitors_from_config,
    utcnow,
)
from src.extractor import categorize_content, is_page_relevant
from src.change_detector import detect_changes_async

logger = logging.getLogger(__name__)


def load_config():
    with open("config/competitors.yaml") as f:
        competitors_cfg = yaml.safe_load(f)
    with open("config/settings.yaml") as f:
        settings = yaml.safe_load(f)
    return competitors_cfg, settings


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def is_same_domain(url: str, base_url: str) -> bool:
    """Check if URL belongs to the same domain as the base."""
    return urlparse(url).netloc == urlparse(base_url).netloc


def normalize_url(url: str) -> str:
    """Strip fragments and trailing slashes for deduplication."""
    parsed = urlparse(url)
    path = parsed.path.rstrip("/") or "/"
    return f"{parsed.scheme}://{parsed.netloc}{path}"


SKIP_EXTENSIONS = {
    ".pdf", ".jpg", ".jpeg", ".png", ".gif", ".svg", ".ico",
    ".css", ".js", ".zip", ".doc", ".docx", ".xls", ".xlsx",
    ".mp4", ".mp3", ".avi", ".mov",
}


def should_skip_url(url: str) -> bool:
    """Skip non-HTML resources."""
    path = urlparse(url).path.lower()
    return any(path.endswith(ext) for ext in SKIP_EXTENSIONS)


async def fetch_sitemap_urls(crawler, website: str) -> list[str]:
    """Try to fetch and parse sitemap.xml for a website."""
    sitemap_url = urljoin(website, "/sitemap.xml")
    urls = []
    try:
        result = await crawler.arun(
            url=sitemap_url,
            config=CrawlerRunConfig(page_timeout=15000),
        )
        if result.success and result.html:
            root = ET.fromstring(result.html)
            # Handle both sitemap index and regular sitemaps
            ns = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
            for loc in root.findall(".//sm:loc", ns):
                if loc.text:
                    urls.append(loc.text.strip())
            # Try without namespace too
            if not urls:
                for loc in root.findall(".//loc"):
                    if loc.text:
                        urls.append(loc.text.strip())
        logger.info(f"Sitemap for {website}: found {len(urls)} URLs")
    except Exception as e:
        logger.debug(f"No sitemap for {website}: {e}")
    return urls


def extract_internal_links(result, base_url: str) -> list[str]:
    """Extract same-domain links from a crawl result."""
    links = []
    if not result.links:
        return links
    # result.links is a dict with 'internal' and 'external' keys
    internal = result.links.get("internal", [])
    for link_info in internal:
        href = link_info.get("href", "") if isinstance(link_info, dict) else str(link_info)
        if href and is_same_domain(href, base_url) and not should_skip_url(href):
            links.append(normalize_url(href))
    return links


async def crawl_competitor(crawler, comp_cfg: dict, settings: dict, session, crawl_run):
    """Crawl a single competitor: discover pages via sitemap + links, then crawl and analyze."""
    crawler_settings = settings.get("crawler", {})
    llm_settings = settings.get("llm", {})
    auto_categorize = llm_settings.get("auto_categorize", True)
    filter_relevant = crawler_settings.get("filter_relevant", True)
    max_depth = comp_cfg.get("max_depth", crawler_settings.get("default_max_depth", 2))
    max_pages = crawler_settings.get("max_pages_per_competitor", 50)
    delay = crawler_settings.get("politeness_delay", 2)
    page_timeout = crawler_settings.get("page_timeout", 30) * 1000

    website = comp_cfg["website"]
    competitor = session.query(Competitor).filter(Competitor.name == comp_cfg["name"]).first()
    if not competitor:
        return 0, 0

    config = CrawlerRunConfig(
        word_count_threshold=10,
        page_timeout=page_timeout,
    )

    # Collect all URLs to visit: seeds + pinned + sitemap
    to_visit = []  # (url, depth)
    visited = set()

    # Seed URLs (depth 0)
    for url in comp_cfg.get("seed_urls", [website]):
        to_visit.append((normalize_url(url), 0))

    # Pinned URLs (depth 0)
    for url in comp_cfg.get("pinned_urls", []):
        to_visit.append((normalize_url(url), 0))

    # Sitemap URLs (depth 0, if enabled)
    if crawler_settings.get("use_sitemap", True):
        sitemap_urls = await fetch_sitemap_urls(crawler, website)
        for url in sitemap_urls:
            if is_same_domain(url, website) and not should_skip_url(url):
                to_visit.append((normalize_url(url), 0))

    pages_crawled = 0
    changes_found = 0

    while to_visit and pages_crawled < max_pages:
        url, depth = to_visit.pop(0)

        if url in visited:
            continue
        visited.add(url)

        try:
            logger.info(f"  [{comp_cfg['name']}] depth={depth} → {url}")
            result = await crawler.arun(url=url, config=config)

            if not result.success:
                logger.warning(f"  Failed: {url} — {result.error_message}")
                continue

            markdown = result.markdown or ""
            if not markdown.strip():
                continue

            # Check relevance (LLM filter)
            if filter_relevant:
                relevant = await is_page_relevant(url, markdown)
                if not relevant:
                    logger.info(f"  Filtered (not relevant): {url}")
                    continue

            # Get or create target in DB
            target = get_or_create_target(
                session, competitor.id, url,
                source="seed" if depth == 0 else "discovered",
                depth=depth,
            )
            target.is_relevant = True

            # Auto-categorize
            extracted = {}
            if auto_categorize:
                categories = await categorize_content(markdown)
                extracted["categories"] = categories
            elif target.category:
                extracted["categories"] = [target.category]

            # Store snapshot
            c_hash = content_hash(markdown)
            snapshot = PageSnapshot(
                crawl_target_id=target.id,
                crawl_run_id=crawl_run.id,
                content_markdown=markdown,
                extracted_data=extracted,
                content_hash=c_hash,
            )
            session.add(snapshot)
            session.commit()
            pages_crawled += 1

            # Detect changes
            new_changes = await detect_changes_async(session, target, snapshot, crawl_run)
            changes_found += len(new_changes)

            # Discover child links (if under max_depth)
            if depth < max_depth:
                child_links = extract_internal_links(result, website)
                for link in child_links:
                    if link not in visited:
                        to_visit.append((link, depth + 1))

            await asyncio.sleep(delay)

        except Exception as e:
            logger.error(f"  Error crawling {url}: {e}", exc_info=True)
            continue

    return pages_crawled, changes_found


async def crawl_all():
    """Main crawl pipeline: crawl all active competitors, detect changes."""
    competitors_cfg, settings = load_config()

    session = get_session()
    sync_competitors_from_config(session, competitors_cfg["competitors"])

    crawl_run = CrawlRun(status="running")
    session.add(crawl_run)
    session.commit()

    total_pages = 0
    total_changes = 0

    active_competitors = [c for c in competitors_cfg["competitors"] if c.get("active", True)]
    logger.info(f"Starting crawl run #{crawl_run.id} — {len(active_competitors)} competitors")

    async with AsyncWebCrawler() as crawler:
        for comp_cfg in active_competitors:
            logger.info(f"Crawling: {comp_cfg['name']}")
            pages, changes = await crawl_competitor(
                crawler, comp_cfg, settings, session, crawl_run
            )
            total_pages += pages
            total_changes += changes

    crawl_run.completed_at = utcnow()
    crawl_run.status = "completed"
    crawl_run.pages_crawled = total_pages
    crawl_run.changes_found = total_changes
    session.commit()

    logger.info(
        f"Crawl run #{crawl_run.id} completed: "
        f"{total_pages} pages, {total_changes} changes"
    )

    session.close()
    return crawl_run.id
