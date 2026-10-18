"""Exports.

Two products:

* A sequencer CSV (``CSV_COLUMNS``) for people who send cold email.
* A lead-list CSV (``LEAD_COLUMNS``) for people who only want the list:
  one row per company, with the best owner or buyer Harvey found.
"""

import csv
import io
import logging

from harvey.state import StateManager

logger = logging.getLogger("harvey.export")

# Column order chosen so the file imports cleanly into cold-email tools
# without remapping; extra columns are simply available as custom variables.
CSV_COLUMNS = [
    "email", "first_name", "last_name", "company_name", "title",
    "website", "linkedin_url", "industry", "personalization",
    "email_status", "score", "seniority", "source", "status", "created_at",
]

DEFAULT_EMAIL_STATUSES = ["verified", "risky"]

# One row per company. A business with no email is still a lead.
LEAD_COLUMNS = [
    "company_name", "segment", "city", "address", "phone", "website",
    "icp_score", "icp_reason",
    "contact_name", "contact_title", "contact_email", "email_confidence",
]


async def collect_prospects(
    state: StateManager,
    email_statuses: list[str] | None = None,
    min_score: int = 0,
    statuses: list[str] | None = None,
    include_all: bool = False,
) -> list[dict]:
    """Fetch prospects matching the filters as export-ready dicts.

    Default view is the *deliverable* list (verified + risky emails).
    ``include_all`` disables every filter for a full dump.
    """
    import aiosqlite

    where = []
    params: list = []
    if not include_all:
        wanted = email_statuses if email_statuses is not None else DEFAULT_EMAIL_STATUSES
        if wanted:
            placeholders = ",".join("?" for _ in wanted)
            where.append(f"email != '' AND email_status IN ({placeholders})")
            params.extend(wanted)
        if min_score > 0:
            where.append("score >= ?")
            params.append(min_score)
        if statuses:
            placeholders = ",".join("?" for _ in statuses)
            where.append(f"status IN ({placeholders})")
            params.extend(statuses)

    sql = "SELECT * FROM prospects"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY score DESC, created_at DESC"

    async with aiosqlite.connect(state.db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(sql, params) as cursor:
            rows = [dict(r) for r in await cursor.fetchall()]

    out = []
    for r in rows:
        out.append({
            "email": r.get("email", ""),
            "first_name": r.get("first_name", ""),
            "last_name": r.get("last_name", ""),
            "company_name": r.get("company", ""),
            "title": r.get("title", ""),
            "website": r.get("source_url", ""),
            "linkedin_url": r.get("linkedin_url", ""),
            "industry": r.get("industry", ""),
            "personalization": r.get("personalization_notes", ""),
            "email_status": r.get("email_status", ""),
            "score": r.get("score", 0),
            "seniority": r.get("seniority", ""),
            "source": r.get("source", ""),
            "status": r.get("status", ""),
            "created_at": r.get("created_at", ""),
        })
    return out


def to_csv(rows: list[dict]) -> str:
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=CSV_COLUMNS, extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        writer.writerow(row)
    return buf.getvalue()


async def export_prospects_csv(
    state: StateManager,
    out_path: str | None = None,
    email_statuses: list[str] | None = None,
    min_score: int = 0,
    statuses: list[str] | None = None,
    include_all: bool = False,
) -> tuple[int, str]:
    """Export prospects to CSV. Returns (row_count, csv_text).

    Writes to ``out_path`` when given; caller handles printing/serving.
    """
    rows = await collect_prospects(
        state,
        email_statuses=email_statuses,
        min_score=min_score,
        statuses=statuses,
        include_all=include_all,
    )
    text = to_csv(rows)
    if out_path:
        with open(out_path, "w", newline="") as f:
            f.write(text)
        logger.info(f"Exported {len(rows)} prospects to {out_path}")
    return len(rows), text


def _website(company) -> str:
    site = (getattr(company, "website", "") or "").strip()
    if site:
        return site
    domain = (getattr(company, "domain", "") or "").strip()
    return f"https://{domain}" if domain else ""


def _city(company) -> str:
    city = (getattr(company, "city", "") or "").strip()
    if city:
        return city
    location = (getattr(company, "location", "") or "").strip()
    return location.split(",")[0].strip() if location else ""


def _lead_score(company, config):
    """Stored score when scout already wrote one, otherwise compute it."""
    stored = int(getattr(company, "icp_score", 0) or 0)
    reason = (getattr(company, "icp_reason", "") or "").strip()
    if stored > 0 or config is None:
        return stored, reason
    from harvey.scoring import score_company
    return score_company(company, config)


async def collect_leads(
    state: StateManager,
    config=None,
    min_score: int = 0,
) -> list[dict]:
    """One row per company, best owner or buyer attached when one exists.

    Companies with no contact and no email are included. A published
    inbox (contato@) is labeled ``published`` so it is not mistaken for
    a verified personal mailbox.
    """
    from harvey.scoring import pick_best_contact

    companies = await state.list_companies()
    prospects = await state.list_prospects()
    by_company: dict[str, list] = {}
    for prospect in prospects:
        if prospect.company_id:
            by_company.setdefault(prospect.company_id, []).append(prospect)

    rows = []
    for company in companies:
        score, reason = _lead_score(company, config)
        if min_score and score < min_score:
            continue
        best = pick_best_contact(by_company.get(company.id) or [])
        phone = (getattr(company, "phone", "") or "").strip()
        contact_name = contact_title = contact_email = confidence = ""
        if best is not None:
            contact_name = best.full_name()
            contact_title = (best.title or "").strip()
            if (best.phone or "").strip():
                phone = best.phone.strip()
            if (best.email or "").strip():
                contact_email = best.email.strip()
                confidence = (best.email_status or "").strip() or "guess"
        public = (getattr(company, "public_email", "") or "").strip()
        if not contact_email and public:
            contact_email = public
            confidence = "published"
        rows.append({
            "company_name": company.name,
            "segment": company.industry or "",
            "city": _city(company),
            "address": company.address or "",
            "phone": phone,
            "website": _website(company),
            "icp_score": score,
            "icp_reason": reason,
            "contact_name": contact_name,
            "contact_title": contact_title,
            "contact_email": contact_email,
            "email_confidence": confidence,
        })
    rows.sort(key=lambda r: (-int(r["icp_score"] or 0), r["company_name"].lower()))
    return rows


def leads_to_csv(rows: list[dict]) -> str:
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=LEAD_COLUMNS, extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        writer.writerow(row)
    return buf.getvalue()


async def export_leads_csv(
    state: StateManager,
    out_path: str | None = None,
    config=None,
    min_score: int = 0,
) -> tuple[int, str]:
    """Export the lead list. Returns (row_count, csv_text)."""
    rows = await collect_leads(state, config=config, min_score=min_score)
    text = leads_to_csv(rows)
    if out_path:
        with open(out_path, "w", newline="") as f:
            f.write(text)
        logger.info(f"Exported {len(rows)} leads to {out_path}")
    return len(rows), text
