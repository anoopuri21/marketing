"""Pydantic request/response schemas."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field, HttpUrl, field_serializer, field_validator


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    @field_serializer("*", when_used="json", check_fields=False)
    def _serialize_datetimes(self, value):
        # SQLite hands back naive datetimes; emit them as explicit UTC ISO strings.
        if isinstance(value, datetime):
            if value.tzinfo is None:
                value = value.replace(tzinfo=timezone.utc)
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
    workspaces: List[WorkspaceOut]


# --------------------------------------------------------------------------- #
# Websites
# --------------------------------------------------------------------------- #
class WebsiteCreate(BaseModel):
    url: str
    name: str = ""
    industry: str = ""
    target_location: str = ""
    description: str = ""
    workspace_id: Optional[int] = None

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
    name: Optional[str] = None
    industry: Optional[str] = None
    target_location: Optional[str] = None
    description: Optional[str] = None
    auto_audit_enabled: Optional[bool] = None


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
    verified_at: Optional[datetime]
    verification_method: str
    verification_token: str
    last_score: Optional[float]
    last_audit_at: Optional[datetime]
    auto_audit_enabled: bool
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
    status_code: Optional[int]
    response_ms: Optional[int]
    title: str
    meta_description: str
    h1: str
    word_count: int
    canonical: str
    data: Dict[str, Any]


class AuditSummaryOut(ORMModel):
    id: int
    website_id: int
    status: str
    trigger: str
    error: str
    started_at: Optional[datetime]
    finished_at: Optional[datetime]
    pages_crawled: int
    overall_score: Optional[float]
    seo_score: Optional[float]
    technical_score: Optional[float]
    content_score: Optional[float]
    aeo_score: Optional[float]
    ai_readiness_score: Optional[float]
    performance_score: Optional[float]
    social_score: Optional[float]
    created_at: datetime


class AuditDetailOut(AuditSummaryOut):
    summary: Dict[str, Any]
    ai_insights: Dict[str, Any]
    issues: List[AuditIssueOut]
    pages: List[AuditPageOut]


class AuditCreateResponse(BaseModel):
    audit: AuditSummaryOut
    message: str


# --------------------------------------------------------------------------- #
# Keywords
# --------------------------------------------------------------------------- #
class KeywordCreate(BaseModel):
    terms: List[str] = Field(min_length=1)
    location: str = ""
    language: str = "en"


class KeywordRankOut(ORMModel):
    id: int
    checked_at: datetime
    position: Optional[int]
    url: str
    engine: str
    provider: str
    features: Dict[str, Any]


class KeywordOut(ORMModel):
    id: int
    term: str
    location: str
    language: str
    intent: str
    source: str
    created_at: datetime
    latest_position: Optional[int] = None
    previous_position: Optional[int] = None
    latest_url: str = ""
    last_checked_at: Optional[datetime] = None


class KeywordDetailOut(KeywordOut):
    ranks: List[KeywordRankOut]


class KeywordSuggestion(BaseModel):
    term: str
    intent: str = ""
    reason: str = ""


class KeywordSuggestResponse(BaseModel):
    provider: str
    suggestions: List[KeywordSuggestion]


# --------------------------------------------------------------------------- #
# Tasks / planning
# --------------------------------------------------------------------------- #
class TaskCreate(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    description: str = ""
    category: str = "seo"
    priority: Literal["low", "medium", "high", "critical"] = "medium"
    due_date: Optional[datetime] = None
    page_url: str = ""


class TaskUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    category: Optional[str] = None
    priority: Optional[Literal["low", "medium", "high", "critical"]] = None
    status: Optional[Literal["todo", "in_progress", "done", "dismissed"]] = None
    due_date: Optional[datetime] = None


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
    due_date: Optional[datetime]
    completed_at: Optional[datetime]
    page_url: str
    created_at: datetime
    updated_at: datetime


class PlanRequest(BaseModel):
    horizon_weeks: int = Field(default=4, ge=1, le=12)
    focus: str = ""  # optional free-text goal e.g. "rank for 'dentist in delhi'"


class PlanWeek(BaseModel):
    week: int
    theme: str
    tasks: List[TaskCreate]


class PlanResponse(BaseModel):
    provider: str
    strategy_summary: str
    weeks: List[PlanWeek]
    created_tasks: int


# --------------------------------------------------------------------------- #
# Reports
# --------------------------------------------------------------------------- #
class ReportScheduleCreate(BaseModel):
    recipients: List[EmailStr] = Field(min_length=1)
    frequency: Literal["weekly", "monthly"] = "weekly"
    day_of_week: int = Field(default=0, ge=0, le=6)
    day_of_month: int = Field(default=1, ge=1, le=28)
    hour: int = Field(default=9, ge=0, le=23)
    minute: int = Field(default=0, ge=0, le=59)
    timezone: str = "Asia/Kolkata"
    enabled: bool = True
    run_fresh_audit: bool = True


class ReportScheduleUpdate(BaseModel):
    recipients: Optional[List[EmailStr]] = None
    frequency: Optional[Literal["weekly", "monthly"]] = None
    day_of_week: Optional[int] = Field(default=None, ge=0, le=6)
    day_of_month: Optional[int] = Field(default=None, ge=1, le=28)
    hour: Optional[int] = Field(default=None, ge=0, le=23)
    minute: Optional[int] = Field(default=None, ge=0, le=59)
    timezone: Optional[str] = None
    enabled: Optional[bool] = None
    run_fresh_audit: Optional[bool] = None


class ReportScheduleOut(ORMModel):
    id: int
    website_id: int
    recipients: List[str]
    frequency: str
    day_of_week: int
    day_of_month: int
    hour: int
    minute: int
    timezone: str
    enabled: bool
    run_fresh_audit: bool
    next_run_at: Optional[datetime]
    last_run_at: Optional[datetime]
    created_at: datetime


class ReportRunOut(ORMModel):
    id: int
    schedule_id: Optional[int]
    website_id: int
    period_label: str
    status: str
    recipients: List[str]
    subject: str
    delivery_info: str
    error: str
    created_at: datetime


class ReportSendNowRequest(BaseModel):
    recipients: Optional[List[EmailStr]] = None
    run_fresh_audit: bool = False
    period: Literal["weekly", "monthly"] = "weekly"


# --------------------------------------------------------------------------- #
# Integrations
# --------------------------------------------------------------------------- #
class IntegrationOut(ORMModel):
    id: int
    provider: str
    status: str
    connected_at: Optional[datetime]
    config: Dict[str, Any]
    last_synced_at: Optional[datetime] = None
    last_error: str = ""
    summary: Dict[str, Any] = Field(default_factory=dict)


class IntegrationUpsert(BaseModel):
    provider: str
    config: Dict[str, Any] = Field(default_factory=dict)


# --------------------------------------------------------------------------- #
# Dashboard / system
# --------------------------------------------------------------------------- #
class SystemStatus(BaseModel):
    app_name: str
    environment: str
    ai_provider: str
    serp_provider: str
    email_backend: str
    scheduler_enabled: bool
    version: str


class DashboardOut(BaseModel):
    websites: int
    verified_websites: int
    audits_completed: int
    open_tasks: int
    tracked_keywords: int
    avg_score: Optional[float]
    reports_sent: int
    recent_audits: List[AuditSummaryOut]
    upcoming_reports: List[ReportScheduleOut]
    open_issue_counts: Dict[str, int]
