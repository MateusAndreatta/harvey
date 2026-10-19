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


def _group_key(company) -> str:
    """Chain key from the name, even when the stored key is a wikidata id."""
    from harvey.brands import brand_key

    named = brand_key(company.name)
    if named.startswith("chain:"):
        return named
    stored = (company.brand or "").strip()
    return stored or named


def _same_place(left, right) -> bool:
    """Same normalized name within half a kilometre."""
    from harvey.brands import NEARBY_KM, name_key
    from harvey.places import haversine_km

    key = name_key(left.name)
    if not key or key != name_key(right.name):
        return False
    if None in (left.latitude, left.longitude, right.latitude, right.longitude):
        return False
    return haversine_km(
        left.latitude, left.longitude, right.latitude, right.longitude,
    ) <= NEARBY_KM


def _one_per_brand(companies: list) -> tuple[list, dict[str, int], dict[str, list[str]]]:
    """Keep the strongest row of each chain, and of each nearby duplicate.

    O Boticário with two brand keys (wikidata and the chain name) is one
    row. HORSCH do Brasil twice, 200 m apart, is one row. Independents
    with different names stay separate.
    """
    parent = list(range(len(companies)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(a: int, b: int):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    keys = [_group_key(company) for company in companies]
    for i in range(len(companies)):
        for j in range(i):
            if keys[i] and keys[i] == keys[j]:
                union(i, j)
            elif _same_place(companies[i], companies[j]):
                union(i, j)

    grouped: dict[int, list] = {}
    order: list[int] = []
    for i, company in enumerate(companies):
        root = find(i)
        if root not in grouped:
            order.append(root)
            grouped[root] = []
        grouped[root].append(company)

    kept = []
    counts: dict[str, int] = {}
    siblings: dict[str, list[str]] = {}
    for root in order:
        rows = grouped[root]
        best = max(rows, key=lambda company: (
            1 if (company.website or company.domain) else 0,
            1 if company.phone else 0,
            1 if company.address else 0,
            int(company.icp_score or 0),
        ))
        kept.append(best)
        counts[best.id] = len(rows)
        siblings[best.id] = [company.id for company in rows]
    return kept, counts, siblings


def _website(company) -> str:
    site = (getattr(company, "website", "") or "").strip()
    if site:
        return site
    domain = (getattr(company, "domain", "") or "").strip()
    return f"https://{domain}" if domain else ""


def _stored_city(company) -> str:
    city = (getattr(company, "city", "") or "").strip()
    if city:
        return city
    location = (getattr(company, "location", "") or "").strip()
    return location.split(",")[0].strip() if location else ""


def _vague_city(city: str) -> bool:
    from harvey.textutil import fold

    folded = fold(city)
    return (not city) or ("metropolit" in folded) or folded in {"rmc", "rmsp"}


def _city(company, cache: dict | None = None) -> str:
    """Municipality for the CSV.

    A cached reverse geocode wins: the stored city may be the neighbour
    that a town-center guess assigned (Bosch in CIC stored as Araucária).
    With no cache, a metro search label is left blank. The nearest town
    center is not used — a wrong city is worse than an empty one.
    """
    from harvey.places import reverse_cache_key

    lat = getattr(company, "latitude", None)
    lon = getattr(company, "longitude", None)
    if cache and lat is not None and lon is not None:
        cached = cache.get(reverse_cache_key(float(lat), float(lon))) or ""
        if cached and cached != "-":
            name, _, _uf = cached.partition("|")
            if name.strip():
                return name.strip()
    city = _stored_city(company)
    if _vague_city(city):
        return ""
    return city


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
    one_per_brand: bool = True,
) -> list[dict]:
    """One row per company, best owner or buyer attached when one exists.

    Companies with no contact and no email are included. A published
    inbox (contato@) is labeled ``published`` so it is not mistaken for
    a verified personal mailbox. Chain branches collapse to one row
    unless ``one_per_brand`` is false. Print and label shops are left out.
    """
    from harvey.brands import (
        drop_thin_lead, is_competitor_name, is_segment_reseller, resellers_excluded,
    )
    from harvey.scoring import pick_best_contact

    drop_resellers = resellers_excluded(config)
    companies = [
        company for company in await state.list_companies()
        if not is_competitor_name(company.name)
        and (company.kind or "") != "competitor"
        and not drop_thin_lead(
            company.name, company.phone, company.website,
            company.address, company.domain,
        )
        and not (
            drop_resellers and is_segment_reseller(
                company.name, company.industry or "", company.kind or "",
            )
        )
    ]
    cache = await state.settings_with_prefix("revgeo:")
    branch_counts: dict[str, int] = {}
    siblings: dict[str, list[str]] = {}
    if one_per_brand:
        companies, branch_counts, siblings = _one_per_brand(companies)
    prospects = await state.list_prospects()
    by_company: dict[str, list] = {}
    for prospect in prospects:
        if prospect.company_id:
            by_company.setdefault(prospect.company_id, []).append(prospect)

    rows = []
    for company in companies:
        score, reason = _lead_score(company, config)
        branches = branch_counts.get(company.id, 1)
        if branches > 1:
            if getattr(config, "language", "en") == "pt-BR":
                note = f"{branches} filiais agrupadas."
            else:
                note = f"{branches} branches grouped."
            reason = f"{reason} {note}".strip()
        contact_pool = []
        for sibling_id in siblings.get(company.id, [company.id]):
            contact_pool.extend(by_company.get(sibling_id) or [])
        if not contact_pool:
            contact_pool = by_company.get(company.id) or []
        if min_score and score < min_score:
            continue
        best = pick_best_contact(contact_pool)
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
            "city": _city(company, cache),
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
    one_per_brand: bool = True,
) -> tuple[int, str]:
    """Export the lead list. Returns (row_count, csv_text)."""
    rows = await collect_leads(
        state, config=config, min_score=min_score, one_per_brand=one_per_brand,
    )
    text = leads_to_csv(rows)
    if out_path:
        with open(out_path, "w", newline="") as f:
            f.write(text)
        logger.info(f"Exported {len(rows)} leads to {out_path}")
    return len(rows), text
