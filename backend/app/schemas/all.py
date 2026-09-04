"""Pydantic request/response schemas."""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, HttpUrl, field_serializer, field_validator


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    @field_serializer("*", when_used="json", check_fields=False)
    def _serialize_datetimes(self, value):
        # SQLite hands back naive datetimes; emit them as explicit UTC ISO strings.
        if isinstance(value, datetime):
            if value.tzinfo is None:
                value = value.replace(tzinfo=UTC)
            return value.isoformat().replace("+00:00", "Z")
        return value


# --------------------------------------------------------------------------- #
# Auth
# --------------------------------------------------------------------------- #
class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=6, max_length=128)
    full_name: str = ""
    workspace_name: str = ""


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserOut(ORMModel):
    id: int
    email: str
    full_name: str
    created_at: datetime


class WorkspaceOut(ORMModel):
    id: int
    name: str
    created_at: datetime


class MeResponse(BaseModel):
    user: UserOut
    workspaces: list[WorkspaceOut]


# --------------------------------------------------------------------------- #
# Websites
# --------------------------------------------------------------------------- #
class WebsiteCreate(BaseModel):
    url: str
    name: str = ""
    industry: str = ""
    target_location: str = ""
    description: str = ""
    workspace_id: int | None = None

    @field_validator("url")
    @classmethod
    def _normalise_url(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("URL is required")
        if not v.startswith(("http://", "https://")):
            v = "https://" + v
        # validate
        HttpUrl(v)
        return v.rstrip("/")


class WebsiteUpdate(BaseModel):
    name: str | None = None
    industry: str | None = None
    target_location: str | None = None
    description: str | None = None
    auto_audit_enabled: bool | None = None
    brand: dict[str, Any] | None = None


class WebsiteOut(ORMModel):
    id: int
    workspace_id: int
    url: str
    domain: str
    name: str
    industry: str
    target_location: str
    description: str
    verified: bool
    verified_at: datetime | None
    verification_method: str
    verification_token: str
    last_score: float | None
    last_audit_at: datetime | None
    auto_audit_enabled: bool
    brand: dict[str, Any] | None = None
    created_at: datetime


class VerificationInstructions(BaseModel):
    token: str
    meta_tag: str
    dns_record: str
    html_file_name: str
    html_file_content: str
    html_file_url: str


class VerifyRequest(BaseModel):
    method: Literal["auto", "meta", "dns", "file"] = "auto"


class VerifyResponse(BaseModel):
    verified: bool
    method: str = ""
    detail: str = ""


# --------------------------------------------------------------------------- #
# Audits
# --------------------------------------------------------------------------- #
class AuditIssueOut(ORMModel):
    id: int
    code: str
    category: str
    severity: str
    title: str
    description: str
    recommendation: str
    page_url: str
    impact: int


class AuditPageOut(ORMModel):
    id: int
    url: str
    status_code: int | None
    response_ms: int | None
    title: str
    meta_description: str
    h1: str
    word_count: int
    canonical: str
    data: dict[str, Any]


class AuditSummaryOut(ORMModel):
    id: int
    website_id: int
    status: str
    trigger: str
    error: str
    started_at: datetime | None
    finished_at: datetime | None
    pages_crawled: int
    overall_score: float | None
    seo_score: float | None
    technical_score: float | None
    content_score: float | None
    aeo_score: float | None
    ai_readiness_score: float | None
    performance_score: float | None
    social_score: float | None
    created_at: datetime


class AuditDetailOut(AuditSummaryOut):
    summary: dict[str, Any]
    ai_insights: dict[str, Any]
    issues: list[AuditIssueOut]
    pages: list[AuditPageOut]


class AuditCreateResponse(BaseModel):
    audit: AuditSummaryOut
    message: str


# --------------------------------------------------------------------------- #
# Keywords
# --------------------------------------------------------------------------- #
class KeywordCreate(BaseModel):
    terms: list[str] = Field(min_length=1)
    location: str = ""
    language: str = "en"


class KeywordRankOut(ORMModel):
    id: int
    checked_at: datetime
    position: int | None
    url: str
    engine: str
    provider: str
    features: dict[str, Any]


class KeywordOut(ORMModel):
    id: int
    term: str
    location: str
    language: str
    intent: str
    source: str
    created_at: datetime
    latest_position: int | None = None
    previous_position: int | None = None
    latest_url: str = ""
    last_checked_at: datetime | None = None


class KeywordDetailOut(KeywordOut):
    ranks: list[KeywordRankOut]


class KeywordSuggestion(BaseModel):
    term: str
    intent: str = ""
    reason: str = ""


class KeywordSuggestResponse(BaseModel):
    provider: str
    suggestions: list[KeywordSuggestion]


# --------------------------------------------------------------------------- #
# Tasks / planning
# --------------------------------------------------------------------------- #
class TaskCreate(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    description: str = ""
    category: str = "seo"
    priority: Literal["low", "medium", "high", "critical"] = "medium"
    due_date: datetime | None = None
    page_url: str = ""


class TaskUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    category: str | None = None
    priority: Literal["low", "medium", "high", "critical"] | None = None
    status: Literal["todo", "in_progress", "done", "dismissed"] | None = None
    due_date: datetime | None = None


class TaskOut(ORMModel):
    id: int
    website_id: int
    title: str
    description: str
    category: str
    priority: str
    status: str
    source: str
    source_issue_code: str
    due_date: datetime | None
    completed_at: datetime | None
    page_url: str
    created_at: datetime
    updated_at: datetime


class PlanRequest(BaseModel):
    horizon_weeks: int = Field(default=4, ge=1, le=12)
    focus: str = ""  # optional free-text goal e.g. "rank for 'dentist in delhi'"


class PlanWeek(BaseModel):
    week: int
    theme: str
    tasks: list[TaskCreate]


class PlanResponse(BaseModel):
    provider: str
    strategy_summary: str
    weeks: list[PlanWeek]
    created_tasks: int


# --------------------------------------------------------------------------- #
# Reports
# --------------------------------------------------------------------------- #
class ReportScheduleCreate(BaseModel):
    recipients: list[EmailStr] = Field(min_length=1)
    frequency: Literal["weekly", "monthly"] = "weekly"
    day_of_week: int = Field(default=0, ge=0, le=6)
    day_of_month: int = Field(default=1, ge=1, le=28)
    hour: int = Field(default=9, ge=0, le=23)
    minute: int = Field(default=0, ge=0, le=59)
    timezone: str = "Asia/Kolkata"
    enabled: bool = True
    run_fresh_audit: bool = True


class ReportScheduleUpdate(BaseModel):
    recipients: list[EmailStr] | None = None
    frequency: Literal["weekly", "monthly"] | None = None
    day_of_week: int | None = Field(default=None, ge=0, le=6)
    day_of_month: int | None = Field(default=None, ge=1, le=28)
    hour: int | None = Field(default=None, ge=0, le=23)
    minute: int | None = Field(default=None, ge=0, le=59)
    timezone: str | None = None
    enabled: bool | None = None
    run_fresh_audit: bool | None = None


class ReportScheduleOut(ORMModel):
    id: int
    website_id: int
    recipients: list[str]
    frequency: str
    day_of_week: int
    day_of_month: int
    hour: int
    minute: int
    timezone: str
    enabled: bool
    run_fresh_audit: bool
    next_run_at: datetime | None
    last_run_at: datetime | None
    created_at: datetime


class ReportRunOut(ORMModel):
    id: int
    schedule_id: int | None
    website_id: int
    period_label: str
    status: str
    recipients: list[str]
    subject: str
    delivery_info: str
    error: str
    created_at: datetime


class ReportSendNowRequest(BaseModel):
    recipients: list[EmailStr] | None = None
    run_fresh_audit: bool = False
    period: Literal["weekly", "monthly"] = "weekly"


# --------------------------------------------------------------------------- #
# Integrations
# --------------------------------------------------------------------------- #
class IntegrationOut(ORMModel):
    id: int
    provider: str
    status: str
    connected_at: datetime | None
    config: dict[str, Any]
    last_synced_at: datetime | None = None
    last_error: str = ""
    summary: dict[str, Any] = Field(default_factory=dict)


class IntegrationUpsert(BaseModel):
    provider: str
    config: dict[str, Any] = Field(default_factory=dict)


# --------------------------------------------------------------------------- #
# Dashboard / system
# --------------------------------------------------------------------------- #
class SystemStatus(BaseModel):
    app_name: str
    environment: str
    ai_provider: str
    serp_provider: str
    email_backend: str
    image_provider: str = "none"
    lead_provider: str = "demo"
    scheduler_enabled: bool
    version: str


class DashboardOut(BaseModel):
    websites: int
    verified_websites: int
    audits_completed: int
    open_tasks: int
    tracked_keywords: int
    avg_score: float | None
    reports_sent: int
    leads_total: int = 0
    leads_active: int = 0  # contacted + replied + qualified
    leads_won: int = 0
    follow_ups_due: int = 0
    recent_audits: list[AuditSummaryOut]
    upcoming_reports: list[ReportScheduleOut]
    open_issue_counts: dict[str, int]
