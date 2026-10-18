"""ICP fit for a lead list.

Scoring here is deterministic. A lead-list run must work with no mailbox
and no model call: the reason in the CSV is a template, not a generated
email. Portuguese is a short phrase swap, not a translation of the
copywriting prompts.
"""

from harvey.textutil import fold

# Same seat, different language. A page that says "proprietário" matches
# an ICP title of "owner", and the other way around.
TITLE_GROUPS = (
    (
        "owner", "founder", "cofounder", "ceo", "president", "partner",
        "socio", "socia", "proprietario", "proprietaria", "dono", "dona",
        "fundador", "fundadora",
    ),
    (
        "buyer", "purchasing", "procurement",
        "comprador", "compradora", "compras",
    ),
    ("director", "diretor", "diretora"),
    ("manager", "gerente"),
    ("marketing",),
)


def title_matches(title: str, targets: list[str]) -> bool:
    """True when a job title matches any configured ICP title.

    Substring after accent-folding, then a same-seat group so Portuguese
    and English words for the same role count as one title.
    """
    found = fold(title)
    if not found:
        return False
    wanted = [fold(t) for t in targets if t and str(t).strip()]
    if not wanted:
        return False
    if any(t in found for t in wanted):
        return True
    found_groups = [
        group for group in TITLE_GROUPS if any(fold(word) in found for word in group)
    ]
    return any(
        any(fold(word) in target for word in group)
        for group in found_groups
        for target in wanted
    )


def is_owner_or_buyer(title: str) -> bool:
    """The person who owns the company or buys for it."""
    found = fold(title)
    if not found:
        return False
    seats = TITLE_GROUPS[0] + TITLE_GROUPS[1]
    return any(fold(word) in found for word in seats)


def pick_best_contact(prospects: list) -> object | None:
    """Prefer an owner or buyer, then someone with an email, then score."""
    if not prospects:
        return None

    def key(prospect):
        return (
            1 if is_owner_or_buyer(getattr(prospect, "title", "") or "") else 0,
            1 if (getattr(prospect, "email", "") or "").strip() else 0,
            int(getattr(prospect, "score", 0) or 0),
        )

    return max(prospects, key=key)


def score_company(company, config) -> tuple[int, str]:
    """Return (1-100, short reason) for one discovered business.

    0 is reserved for "not scored yet", so a finished score is at least 1.
    """
    language = getattr(config, "language", "en") or "en"
    portuguese = language == "pt-BR"
    icp = getattr(config, "icp", None)
    industries = list(getattr(icp, "industries", None) or [])
    places = list(getattr(icp, "geography", None) or [])

    industry = (getattr(company, "industry", "") or "").strip()
    city = (getattr(company, "city", "") or "").strip()
    location = (getattr(company, "location", "") or "").strip()
    where = city or location
    folded_industry = fold(industry)
    folded_where = fold(where)

    industry_hit = bool(folded_industry) and any(
        fold(item) and (fold(item) in folded_industry or folded_industry in fold(item))
        for item in industries
    )
    geo_hit = bool(folded_where) and any(
        fold(item) and (fold(item) in folded_where or folded_where in fold(item))
        for item in places
    )
    reachable = bool(
        (getattr(company, "phone", "") or "").strip()
        or (getattr(company, "website", "") or "").strip()
        or (getattr(company, "domain", "") or "").strip()
    )

    score = 35
    if industry_hit:
        score += 35
    if geo_hit:
        score += 20
    if reachable:
        score += 10
    score = max(1, min(100, score))

    if portuguese:
        parts = []
        if industry_hit:
            parts.append(f"Segmento compatível com o ICP ({industry}).")
        elif industries:
            parts.append("Segmento fora do ICP configurado.")
        if geo_hit:
            parts.append(f"Na região alvo ({where}).")
        elif places:
            parts.append("Fora da região alvo.")
        if reachable:
            parts.append("Tem telefone ou site para contato.")
        if not parts:
            parts.append("Sem dados de segmento para comparar com o ICP.")
    else:
        parts = []
        if industry_hit:
            parts.append(f"Segment matches the ICP ({industry}).")
        elif industries:
            parts.append("Segment is outside the configured ICP.")
        if geo_hit:
            parts.append(f"In the target geography ({where}).")
        elif places:
            parts.append("Outside the target geography.")
        if reachable:
            parts.append("Has a phone or a website.")
        if not parts:
            parts.append("No segment to compare with the ICP.")

    return score, " ".join(parts)
