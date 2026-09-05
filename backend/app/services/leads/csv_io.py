"""CSV import/export for the lead pipeline (pure parsing/formatting + a DB-aware importer)."""
from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ValidationError
from app.core.time import utcnow
from app.models import Lead
from app.services.leads.service import normalize_url
from app.services.leads.sources import host_of

MAX_CSV_BYTES = 2 * 1024 * 1024
MAX_ROWS_PER_IMPORT = 500

# Header aliases → Lead column (case-insensitive, spaces → underscores).
HEADER_ALIASES = {
    "company": "company", "name": "company", "business": "company",
    "website": "website_url", "url": "website_url", "site": "website_url",
    "phone": "phone", "mobile": "phone", "email": "email",
    "contact": "contact_name", "contact_name": "contact_name", "person": "contact_name",
    "category": "category", "type": "category", "industry": "category",
    "location": "location", "city": "location", "address": "address",
    "notes": "notes", "note": "notes",
}

EXPORT_COLUMNS = ["company", "website", "phone", "email", "contact", "category", "location", "address", "rating", "reviews", "status",
                  "opportunity_score", "website_score", "top_gaps", "pitch_angle", "source", "created_at"]


@dataclass
class ImportResult:
    created: list[Lead] = field(default_factory=list)
    skipped: int = 0


def parse_rows(raw: bytes) -> list[dict[str, str]]:
    """Decode a CSV upload into normalised dicts keyed by Lead column names (unknown headers dropped)."""
    if len(raw) > MAX_CSV_BYTES:
        raise ValidationError("CSV larger than 2 MB", status_code=413)
    reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig", errors="ignore")))
    if not reader.fieldnames:
        raise ValidationError("CSV has no header row")
    rows: list[dict[str, str]] = []
    for row in reader:
        data: dict[str, str] = {}
        for header, value in row.items():
            key = HEADER_ALIASES.get((header or "").strip().lower().replace(" ", "_"))
            if key and value:
                data[key] = str(value).strip()
        rows.append(data)
    return rows


async def import_leads(db: AsyncSession, website_id: int, raw: bytes, *, source_label: str = "CSV") -> ImportResult:
    """Create leads from a CSV upload, skipping rows without company/website and hosts already in the pipeline."""
    rows = parse_rows(raw)
    existing_hosts = {host_of(lead.website_url) for lead in (await db.execute(
        select(Lead.website_url).where(Lead.website_id == website_id)
    )).all() if lead.website_url}
    result = ImportResult()
    for data in rows:
        if not data.get("company") and not data.get("website_url"):
            result.skipped += 1
            continue
        url = normalize_url(data.get("website_url", ""))
        host = host_of(url)
        if host and host in existing_hosts:
            result.skipped += 1
            continue
        if host:
            existing_hosts.add(host)
        lead = Lead(website_id=website_id, company=data.get("company") or host, website_url=url, phone=data.get("phone", ""),
                    email=data.get("email", ""), contact_name=data.get("contact_name", ""), category=data.get("category", ""),
                    location=data.get("location", ""), address=data.get("address", ""), notes=data.get("notes", ""), source="csv",
                    status="new", score=0, audit={}, pitch={}, tags=[],
                    activity=[{"at": utcnow().isoformat(), "kind": "created", "note": f"Imported from {source_label}"}])
        db.add(lead)
        result.created.append(lead)
        if len(result.created) >= MAX_ROWS_PER_IMPORT:
            break
    await db.flush()
    return result


def export_rows(leads: list[Lead]) -> str:
    """Render leads as CSV text (header + one row per lead)."""
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(EXPORT_COLUMNS)
    for lead in leads:
        audit: dict[str, Any] = lead.audit or {}
        gaps = "; ".join(g.get("label", "") for g in audit.get("gaps", [])[:3])
        writer.writerow([lead.company, lead.website_url, lead.phone, lead.email, lead.contact_name, lead.category, lead.location, lead.address,
                         lead.rating, lead.reviews, lead.status, lead.score, lead.website_score, gaps, (lead.pitch or {}).get("angle", ""),
                         lead.source, lead.created_at.isoformat() if lead.created_at else ""])
    return buf.getvalue()
