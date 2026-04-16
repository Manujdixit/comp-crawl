import os
from datetime import datetime, timezone

from dotenv import load_dotenv
from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    create_engine,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Session, relationship, sessionmaker

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://user:password@localhost:5432/comp_crawl")

engine = create_engine(DATABASE_URL, echo=False)
SessionLocal = sessionmaker(bind=engine)


def utcnow():
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Competitor(Base):
    __tablename__ = "competitors"

    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False)
    website = Column(String(512), nullable=False)
    active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), default=utcnow)

    targets = relationship("CrawlTarget", back_populates="competitor")


class CrawlTarget(Base):
    __tablename__ = "crawl_targets"

    id = Column(Integer, primary_key=True)
    competitor_id = Column(Integer, ForeignKey("competitors.id"), nullable=False)
    url = Column(String(1024), nullable=False, unique=True)
    category = Column(String(100), nullable=True)  # NULL = LLM decides
    source = Column(String(50), default="discovered")  # seed / sitemap / discovered / pinned
    depth = Column(Integer, default=0)
    is_relevant = Column(Boolean, nullable=True)  # NULL = not yet checked, True/False after LLM filter
    active = Column(Boolean, default=True)

    competitor = relationship("Competitor", back_populates="targets")
    snapshots = relationship("PageSnapshot", back_populates="crawl_target")


class CrawlRun(Base):
    __tablename__ = "crawl_runs"

    id = Column(Integer, primary_key=True)
    started_at = Column(DateTime(timezone=True), default=utcnow)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    status = Column(String(50), default="running")
    pages_crawled = Column(Integer, default=0)
    changes_found = Column(Integer, default=0)

    snapshots = relationship("PageSnapshot", back_populates="crawl_run")
    changes = relationship("Change", back_populates="crawl_run")


class PageSnapshot(Base):
    __tablename__ = "page_snapshots"

    id = Column(Integer, primary_key=True)
    crawl_target_id = Column(Integer, ForeignKey("crawl_targets.id"), nullable=False)
    crawl_run_id = Column(Integer, ForeignKey("crawl_runs.id"), nullable=False)
    content_markdown = Column(Text, nullable=True)
    extracted_data = Column(JSONB, nullable=True)
    content_hash = Column(String(64), nullable=True)
    crawled_at = Column(DateTime(timezone=True), default=utcnow)

    crawl_target = relationship("CrawlTarget", back_populates="snapshots")
    crawl_run = relationship("CrawlRun", back_populates="snapshots")


class Change(Base):
    __tablename__ = "changes"

    id = Column(Integer, primary_key=True)
    crawl_target_id = Column(Integer, ForeignKey("crawl_targets.id"), nullable=False)
    crawl_run_id = Column(Integer, ForeignKey("crawl_runs.id"), nullable=False)
    change_type = Column(String(50), nullable=False)  # added / modified / removed
    category = Column(String(100), nullable=True)
    summary = Column(Text, nullable=True)
    diff_text = Column(Text, nullable=True)
    detected_at = Column(DateTime(timezone=True), default=utcnow)

    crawl_target = relationship("CrawlTarget")
    crawl_run = relationship("CrawlRun", back_populates="changes")


def init_db():
    """Create all tables."""
    Base.metadata.create_all(engine)
    print("Database tables created.")


def get_session() -> Session:
    return SessionLocal()


def get_latest_snapshot(session: Session, crawl_target_id: int) -> PageSnapshot | None:
    """Get the most recent snapshot for a crawl target."""
    return (
        session.query(PageSnapshot)
        .filter(PageSnapshot.crawl_target_id == crawl_target_id)
        .order_by(PageSnapshot.crawled_at.desc())
        .first()
    )


def sync_competitors_from_config(session: Session, competitors_config: list[dict]):
    """Upsert competitors and seed/pinned URLs from YAML config into the database."""
    for comp_cfg in competitors_config:
        competitor = (
            session.query(Competitor)
            .filter(Competitor.name == comp_cfg["name"])
            .first()
        )
        if not competitor:
            competitor = Competitor(
                name=comp_cfg["name"],
                website=comp_cfg["website"],
                active=comp_cfg.get("active", True),
            )
            session.add(competitor)
            session.flush()
        else:
            competitor.website = comp_cfg["website"]
            competitor.active = comp_cfg.get("active", True)

        existing_urls = {t.url for t in competitor.targets}

        # Add seed URLs
        for url in comp_cfg.get("seed_urls", []):
            if url not in existing_urls:
                session.add(CrawlTarget(
                    competitor_id=competitor.id,
                    url=url,
                    source="seed",
                    depth=0,
                    is_relevant=True,
                    active=True,
                ))

        # Add pinned URLs (always crawled)
        for url in comp_cfg.get("pinned_urls", []):
            if url not in existing_urls:
                session.add(CrawlTarget(
                    competitor_id=competitor.id,
                    url=url,
                    source="pinned",
                    depth=0,
                    is_relevant=True,
                    active=True,
                ))

    session.commit()


def get_or_create_target(session: Session, competitor_id: int, url: str,
                         source: str = "discovered", depth: int = 0) -> CrawlTarget:
    """Get existing crawl target or create a new one for a discovered URL."""
    target = session.query(CrawlTarget).filter(CrawlTarget.url == url).first()
    if not target:
        target = CrawlTarget(
            competitor_id=competitor_id,
            url=url,
            source=source,
            depth=depth,
            active=True,
        )
        session.add(target)
        session.flush()
    return target
