"""SQLAlchemy ORM models for the whole platform.

Modules covered (foundation milestone): users/workspaces, websites (+ verification),
SEO/AEO audits, keyword rank tracking, planning tasks, report schedules/runs,
integrations, and placeholder tables for social posts & leads (phase 2).
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def aware(dt: Optional[datetime]) -> Optional[datetime]:
    """SQLite returns naive datetimes; treat them as UTC so comparisons are safe."""
    if dt is None:
        return None
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )


# --------------------------------------------------------------------------- #
# Accounts
# --------------------------------------------------------------------------- #
class User(TimestampMixin, Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    full_name: Mapped[str] = mapped_column(String(255), default="")
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    workspaces: Mapped[List["Workspace"]] = relationship(back_populates="owner", cascade="all, delete-orphan")


class Workspace(TimestampMixin, Base):
    """A workspace = one client / agency account. Holds many websites."""

    __tablename__ = "workspaces"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)

    owner: Mapped[User] = relationship(back_populates="workspaces")
    websites: Mapped[List["Website"]] = relationship(back_populates="workspace", cascade="all, delete-orphan")


# --------------------------------------------------------------------------- #
# Websites
# --------------------------------------------------------------------------- #
class Website(TimestampMixin, Base):
    __tablename__ = "websites"

    id: Mapped[int] = mapped_column(primary_key=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    url: Mapped[str] = mapped_column(String(2048), nullable=False)
    domain: Mapped[str] = mapped_column(String(255), index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), default="")
    industry: Mapped[str] = mapped_column(String(255), default="")
    target_location: Mapped[str] = mapped_column(String(255), default="")
    description: Mapped[str] = mapped_column(Text, default="")

    # Ownership verification (meta tag / DNS TXT / HTML file)
    verification_token: Mapped[str] = mapped_column(String(64), nullable=False)
    verified: Mapped[bool] = mapped_column(Boolean, default=False)
    verified_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    verification_method: Mapped[str] = mapped_column(String(32), default="")

    # Denormalised health snapshot (from last audit)
    last_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    last_audit_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    auto_audit_enabled: Mapped[bool] = mapped_column(Boolean, default=True)

    workspace: Mapped[Workspace] = relationship(back_populates="websites")
    audits: Mapped[List["Audit"]] = relationship(
        back_populates="website", cascade="all, delete-orphan", order_by="Audit.created_at.desc()"
    )
    keywords: Mapped[List["Keyword"]] = relationship(back_populates="website", cascade="all, delete-orphan")
    tasks: Mapped[List["Task"]] = relationship(back_populates="website", cascade="all, delete-orphan")
    report_schedules: Mapped[List["ReportSchedule"]] = relationship(
        back_populates="website", cascade="all, delete-orphan"
    )
    integrations: Mapped[List["Integration"]] = relationship(back_populates="website", cascade="all, delete-orphan")
    social_posts: Mapped[List["SocialPost"]] = relationship(back_populates="website", cascade="all, delete-orphan")
    leads: Mapped[List["Lead"]] = relationship(back_populates="website", cascade="all, delete-orphan")


# --------------------------------------------------------------------------- #
# Audits (SEO + AEO + technical + AI readiness)
# --------------------------------------------------------------------------- #
class Audit(TimestampMixin, Base):
    __tablename__ = "audits"

    id: Mapped[int] = mapped_column(primary_key=True)
    website_id: Mapped[int] = mapped_column(ForeignKey("websites.id", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(String(16), default="queued")  # queued|running|completed|failed
    trigger: Mapped[str] = mapped_column(String(16), default="manual")  # manual|scheduled|report
    error: Mapped[str] = mapped_column(Text, default="")

    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    pages_crawled: Mapped[int] = mapped_column(Integer, default=0)

    # Scores 0-100
    overall_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    seo_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    technical_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    content_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    aeo_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)  # answer-engine optimisation
    ai_readiness_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)  # LLM/AI search readiness
    performance_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    social_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    summary: Mapped[dict] = mapped_column(JSON, default=dict)  # site-level facts (robots, sitemap, https ...)
    ai_insights: Mapped[dict] = mapped_column(JSON, default=dict)  # LLM generated recommendations

    website: Mapped[Website] = relationship(back_populates="audits")
    pages: Mapped[List["AuditPage"]] = relationship(back_populates="audit", cascade="all, delete-orphan")
    issues: Mapped[List["AuditIssue"]] = relationship(back_populates="audit", cascade="all, delete-orphan")


class AuditPage(Base):
    __tablename__ = "audit_pages"

    id: Mapped[int] = mapped_column(primary_key=True)
    audit_id: Mapped[int] = mapped_column(ForeignKey("audits.id", ondelete="CASCADE"), index=True)
    url: Mapped[str] = mapped_column(String(2048), nullable=False)
    status_code: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    response_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    title: Mapped[str] = mapped_column(Text, default="")
    meta_description: Mapped[str] = mapped_column(Text, default="")
    h1: Mapped[str] = mapped_column(Text, default="")
    word_count: Mapped[int] = mapped_column(Integer, default=0)
    canonical: Mapped[str] = mapped_column(Text, default="")
    data: Mapped[dict] = mapped_column(JSON, default=dict)  # everything else extracted

    audit: Mapped[Audit] = relationship(back_populates="pages")


class AuditIssue(Base):
    __tablename__ = "audit_issues"

    id: Mapped[int] = mapped_column(primary_key=True)
    audit_id: Mapped[int] = mapped_column(ForeignKey("audits.id", ondelete="CASCADE"), index=True)
    code: Mapped[str] = mapped_column(String(64), index=True)
    category: Mapped[str] = mapped_column(String(32))  # seo|technical|content|aeo|ai|performance|social
    severity: Mapped[str] = mapped_column(String(16))  # critical|high|medium|low|info
    title: Mapped[str] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(Text, default="")
    recommendation: Mapped[str] = mapped_column(Text, default="")
    page_url: Mapped[str] = mapped_column(Text, default="")
    impact: Mapped[int] = mapped_column(Integer, default=1)  # 1-10 weight used in scoring

    audit: Mapped[Audit] = relationship(back_populates="issues")


# --------------------------------------------------------------------------- #
# Keywords & rank tracking
# --------------------------------------------------------------------------- #
class Keyword(TimestampMixin, Base):
    __tablename__ = "keywords"
    __table_args__ = (UniqueConstraint("website_id", "term", "location", name="uq_keyword_site_term_loc"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    website_id: Mapped[int] = mapped_column(ForeignKey("websites.id", ondelete="CASCADE"), index=True)
    term: Mapped[str] = mapped_column(String(255), nullable=False)
    location: Mapped[str] = mapped_column(String(128), default="")
    language: Mapped[str] = mapped_column(String(8), default="en")
    intent: Mapped[str] = mapped_column(String(32), default="")  # informational|commercial|transactional|navigational
    source: Mapped[str] = mapped_column(String(32), default="manual")  # manual|discovered|ai

    website: Mapped[Website] = relationship(back_populates="keywords")
    ranks: Mapped[List["KeywordRank"]] = relationship(
        back_populates="keyword", cascade="all, delete-orphan", order_by="KeywordRank.checked_at.desc()"
    )


class KeywordRank(Base):
    __tablename__ = "keyword_ranks"

    id: Mapped[int] = mapped_column(primary_key=True)
    keyword_id: Mapped[int] = mapped_column(ForeignKey("keywords.id", ondelete="CASCADE"), index=True)
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    position: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)  # None = not in top 100
    url: Mapped[str] = mapped_column(Text, default="")
    engine: Mapped[str] = mapped_column(String(16), default="google")
    provider: Mapped[str] = mapped_column(String(32), default="")
    features: Mapped[dict] = mapped_column(JSON, default=dict)  # SERP features (ai_overview, snippet, ...)

    keyword: Mapped[Keyword] = relationship(back_populates="ranks")


# --------------------------------------------------------------------------- #
# Planning / tasks
# --------------------------------------------------------------------------- #
class Task(TimestampMixin, Base):
    __tablename__ = "tasks"

    id: Mapped[int] = mapped_column(primary_key=True)
    website_id: Mapped[int] = mapped_column(ForeignKey("websites.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    category: Mapped[str] = mapped_column(String(32), default="seo")
    priority: Mapped[str] = mapped_column(String(16), default="medium")  # low|medium|high|critical
    status: Mapped[str] = mapped_column(String(16), default="todo")  # todo|in_progress|done|dismissed
    source: Mapped[str] = mapped_column(String(32), default="manual")  # manual|audit|ai
    source_issue_code: Mapped[str] = mapped_column(String(64), default="")
    due_date: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    page_url: Mapped[str] = mapped_column(Text, default="")

    website: Mapped[Website] = relationship(back_populates="tasks")


# --------------------------------------------------------------------------- #
# Reports
# --------------------------------------------------------------------------- #
class ReportSchedule(TimestampMixin, Base):
    __tablename__ = "report_schedules"

    id: Mapped[int] = mapped_column(primary_key=True)
    website_id: Mapped[int] = mapped_column(ForeignKey("websites.id", ondelete="CASCADE"), index=True)
    recipients: Mapped[list] = mapped_column(JSON, default=list)  # list[str]
    frequency: Mapped[str] = mapped_column(String(16), default="weekly")  # weekly|monthly
    day_of_week: Mapped[int] = mapped_column(Integer, default=0)  # 0=Monday (weekly)
    day_of_month: Mapped[int] = mapped_column(Integer, default=1)  # 1-28 (monthly)
    hour: Mapped[int] = mapped_column(Integer, default=9)
    minute: Mapped[int] = mapped_column(Integer, default=0)
    timezone: Mapped[str] = mapped_column(String(64), default="Asia/Kolkata")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    run_fresh_audit: Mapped[bool] = mapped_column(Boolean, default=True)
    next_run_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    last_run_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    website: Mapped[Website] = relationship(back_populates="report_schedules")
    runs: Mapped[List["ReportRun"]] = relationship(
        back_populates="schedule", cascade="all, delete-orphan", order_by="ReportRun.created_at.desc()"
    )


class ReportRun(TimestampMixin, Base):
    __tablename__ = "report_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    schedule_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("report_schedules.id", ondelete="SET NULL"), nullable=True, index=True
    )
    website_id: Mapped[int] = mapped_column(ForeignKey("websites.id", ondelete="CASCADE"), index=True)
    period_label: Mapped[str] = mapped_column(String(64), default="")
    status: Mapped[str] = mapped_column(String(16), default="pending")  # pending|sent|failed
    recipients: Mapped[list] = mapped_column(JSON, default=list)
    subject: Mapped[str] = mapped_column(String(255), default="")
    html: Mapped[str] = mapped_column(Text, default="")
    delivery_info: Mapped[str] = mapped_column(Text, default="")
    error: Mapped[str] = mapped_column(Text, default="")

    schedule: Mapped[Optional[ReportSchedule]] = relationship(back_populates="runs")


# --------------------------------------------------------------------------- #
# Integrations (Search Console, GA4, social accounts...) - credentials stored as JSON
# --------------------------------------------------------------------------- #
class Integration(TimestampMixin, Base):
    __tablename__ = "integrations"
    __table_args__ = (UniqueConstraint("website_id", "provider", name="uq_integration_site_provider"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    website_id: Mapped[int] = mapped_column(ForeignKey("websites.id", ondelete="CASCADE"), index=True)
    provider: Mapped[str] = mapped_column(String(32))  # google_search_console|ga4|facebook|instagram|linkedin|x
    status: Mapped[str] = mapped_column(String(16), default="disconnected")  # connected|disconnected|error
    config: Mapped[dict] = mapped_column(JSON, default=dict)
    connected_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    website: Mapped[Website] = relationship(back_populates="integrations")


# --------------------------------------------------------------------------- #
# Phase-2 tables (social publishing & lead finder) - schema ready, UI later
# --------------------------------------------------------------------------- #
class SocialPost(TimestampMixin, Base):
    __tablename__ = "social_posts"

    id: Mapped[int] = mapped_column(primary_key=True)
    website_id: Mapped[int] = mapped_column(ForeignKey("websites.id", ondelete="CASCADE"), index=True)
    platform: Mapped[str] = mapped_column(String(32))  # facebook|instagram|linkedin|x|gbp
    content: Mapped[str] = mapped_column(Text, default="")
    media_urls: Mapped[list] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(16), default="draft")  # draft|scheduled|published|failed
    scheduled_for: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    published_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    external_id: Mapped[str] = mapped_column(String(255), default="")
    generated_by_ai: Mapped[bool] = mapped_column(Boolean, default=False)

    website: Mapped[Website] = relationship(back_populates="social_posts")


class Lead(TimestampMixin, Base):
    __tablename__ = "leads"

    id: Mapped[int] = mapped_column(primary_key=True)
    website_id: Mapped[int] = mapped_column(ForeignKey("websites.id", ondelete="CASCADE"), index=True)
    company: Mapped[str] = mapped_column(String(255), default="")
    contact_name: Mapped[str] = mapped_column(String(255), default="")
    email: Mapped[str] = mapped_column(String(255), default="")
    phone: Mapped[str] = mapped_column(String(64), default="")
    website_url: Mapped[str] = mapped_column(String(2048), default="")
    source: Mapped[str] = mapped_column(String(64), default="manual")
    score: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(16), default="new")  # new|contacted|qualified|won|lost
    notes: Mapped[str] = mapped_column(Text, default="")

    website: Mapped[Website] = relationship(back_populates="leads")
