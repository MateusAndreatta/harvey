"""ICP fit for a lead list.

Scoring here is deterministic. A lead-list run must work with no mailbox
and no model call: the reason in the CSV is a template, not a generated
email. Portuguese is a short phrase swap, not a translation of the
copywriting prompts.

The points are spread on purpose. A search already filtered by trade, so
"segment matches" cannot be most of the score or every row lands on 90.
"""

import re

from harvey.brands import (
    brand_key, is_distribution_name, is_manufacturer_name, is_reseller_name,
)
from harvey.places import haversine_km
from harvey.textutil import fold

# Official Região Metropolitana de Curitiba, and the main municípios of the
# RMSP. Used when the geography label says "região metropolitana" and the
# row has no coordinates of its own. A plain "Curitiba, PR" does not expand
# to the whole metro; the radius does that when the row has a lat/lon.
CURITIBA_METRO = frozenset(fold(name) for name in (
    "Adrianópolis", "Agudos do Sul", "Almirante Tamandaré", "Araucária",
    "Balsa Nova", "Bocaiúva do Sul", "Campina Grande do Sul", "Campo Largo",
    "Campo Magro", "Campo do Tenente", "Cerro Azul", "Colombo", "Contenda",
    "Curitiba", "Doutor Ulysses", "Fazenda Rio Grande", "Itaperuçu", "Lapa",
    "Mandirituba", "Piên", "Pinhais", "Piraquara", "Quatro Barras",
    "Quitandinha", "Rio Branco do Sul", "Rio Negro", "São José dos Pinhais",
    "Tijucas do Sul", "Tunas do Paraná",
))

SAO_PAULO_METRO = frozenset(fold(name) for name in (
    "São Paulo", "Guarulhos", "São Bernardo do Campo", "Santo André",
    "Osasco", "São Caetano do Sul", "Mauá", "Diadema", "Carapicuíba",
    "Mogi das Cruzes", "Itaquaquecetuba", "Taboão da Serra", "Barueri",
    "Embu das Artes", "Cotia", "Santana de Parnaíba", "Ferraz de Vasconcelos",
    "Francisco Morato", "Itapevi", "Suzano", "Ribeirão Pires", "Caieiras",
    "Franco da Rocha", "Poá", "Arujá", "Mairiporã", "Jandira",
    "Itapecerica da Serra", "Rio Grande da Serra", "Vargem Grande Paulista",
    "Cajamar", "Santa Isabel", "Embu-Guaçu", "Biritiba Mirim", "Guararema",
    "Salesópolis", "Juquitiba", "Pirapora do Bom Jesus", "São Lourenço da Serra",
))

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


def _parse_coordinate(raw: str) -> tuple[float, float, float] | None:
    parts = [p.strip() for p in (raw or "").split(",")]
    if len(parts) < 2:
        return None
    try:
        lat, lon = float(parts[0]), float(parts[1])
        radius = float(parts[2]) if len(parts) > 2 and parts[2] else 40.0
    except ValueError:
        return None
    return lat, lon, radius


def _metro_towns(label: str) -> frozenset[str] | None:
    folded = fold(label)
    if "metropolit" not in folded and "grande " not in folded and folded not in ("rmc", "rmsp"):
        return None
    if "curitiba" in folded or folded == "rmc":
        return CURITIBA_METRO
    if "sao paulo" in folded or folded == "rmsp":
        return SAO_PAULO_METRO
    return None


def _text_geo(where: str, places: list[str]) -> bool:
    folded_where = fold(where)
    if not folded_where:
        return False
    return any(
        fold(item) and (fold(item) in folded_where or folded_where in fold(item))
        for item in places
    )


def in_target_region(company, config) -> bool:
    """True when the business sits in a configured geography.

    A radius wins when the row has coordinates: São José dos Pinhais is in
    range of Curitiba even though the names do not match. A geography label
    that says "região metropolitana" also accepts the known towns of that
    metro, which covers rows saved before coordinates were stored. The old
    text comparison remains for labels like "Curitiba, PR".
    """
    icp = getattr(config, "icp", None)
    places = list(getattr(icp, "geography", None) or [])
    coords = dict(getattr(icp, "geo_coordinates", None) or {})
    city = (getattr(company, "city", "") or "").strip()
    location = (getattr(company, "location", "") or "").strip()
    where = city or location

    lat = getattr(company, "latitude", None)
    lon = getattr(company, "longitude", None)
    if lat is not None and lon is not None and coords:
        for raw in coords.values():
            point = _parse_coordinate(str(raw))
            if point and haversine_km(float(lat), float(lon), point[0], point[1]) <= point[2]:
                return True

    folded_city = fold(city or where.split(",")[0])
    for label in list(places) + list(coords):
        towns = _metro_towns(str(label))
        if towns and folded_city in towns:
            return True

    return _text_geo(where, places) or _text_geo(where, list(coords))


def _is_chain(company) -> bool:
    """A retail chain, not a manufacturer that carries a corporate brand.

    ``brand:votorantim`` on Cimento Rio Branco is a plant. The penalty is
    for Droga Raia and O Boticário, whose key starts with ``chain:`` or
    whose name is one of those retail brands.
    """
    kind = (getattr(company, "kind", "") or "").strip().lower()
    name = getattr(company, "name", "") or ""
    if kind == "producer" or is_manufacturer_name(name):
        return False
    brand = (getattr(company, "brand", "") or "").strip()
    if brand.startswith("chain:"):
        return True
    return brand_key(name).startswith("chain:")


def _trait_tokens(company) -> set[str]:
    tokens: set[str] = set()
    for sig in getattr(company, "signals", None) or []:
        if isinstance(sig, dict) and sig.get("type") == "osm_traits":
            tokens.update(str(sig.get("detail") or "").split())
    return tokens


_LEGAL_ENTITY = re.compile(r"\b(ltda|eireli|s\.a\.|s/a)\b")


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
    kind = (getattr(company, "kind", "") or "").strip().lower()

    industry_hit = bool(folded_industry) and any(
        fold(item) and (fold(item) in folded_industry or folded_industry in fold(item))
        for item in industries
    )
    geo_hit = in_target_region(company, config) if (places or getattr(icp, "geo_coordinates", None)) else False
    chain = _is_chain(company)
    website = bool(
        (getattr(company, "website", "") or "").strip()
        or (getattr(company, "domain", "") or "").strip()
    )
    phone = bool((getattr(company, "phone", "") or "").strip())
    address = bool((getattr(company, "address", "") or "").strip())
    public_email = bool((getattr(company, "public_email", "") or "").strip())
    name = getattr(company, "name", "") or ""
    folded_name = fold(name)
    # A stored "producer" from an older run is still logistics when the
    # name is a distribution center.
    producer = kind == "producer" and not is_distribution_name(name)
    reseller = kind == "reseller" or is_reseller_name(name)
    traits = _trait_tokens(company)
    plant_name = bool(re.search(r"industri|fabrica", folded_name))
    legal_entity = bool(_LEGAL_ENTITY.search(folded_name))
    # OSM tags a compounding pharmacy as a shop. The operator already named
    # that segment, so the tag is not a demotion to generic retail.
    retail = (kind == "retail" or (chain and not producer)) and not industry_hit

    # The weights are chosen so the common combinations do not land on the
    # same number. A producer with nothing else, a producer with a phone,
    # and a shop with a phone and a site each score differently.
    score = 15
    if industry_hit:
        score += 8
    if geo_hit:
        score += 8
    role = ""
    if reseller:
        score -= 22
        role = "reseller"
    elif producer:
        score += 20
        role = "producer"
    elif industry_hit:
        score += 14
        role = "target"
    elif retail:
        score -= 6
        role = "retail"
    if chain:
        score -= 18
    if website:
        score += 17
    if phone:
        score += 11
    if address:
        score += 7
    if public_email:
        score += 5
    # The 51 pile is producer + industry + geography and nothing else.
    # A name that says indústria or Ltda, and OSM traits stored at
    # discovery, split that pile. Traits need a rediscover; the name
    # does not.
    if plant_name:
        score += 6
    if legal_entity:
        score += 4
    if "hours" in traits:
        score += 3
    if "industrial" in traits:
        score += 5
    if "building" in traits:
        score += 4
    if "footprint" in traits:
        score += 5
    score = max(1, min(100, score))
    plant_signal = plant_name or legal_entity or bool(
        traits & {"hours", "industrial", "building", "footprint"}
    )

    if portuguese:
        parts = []
        if industry_hit:
            parts.append(f"Segmento compatível com o ICP ({industry}).")
        elif industries:
            parts.append("Segmento fora do ICP configurado.")
        if geo_hit:
            parts.append(f"Na região alvo ({where})." if where else "Na região alvo.")
        elif places:
            parts.append("Fora da região alvo.")
        if role == "producer":
            parts.append("Produtor, não só ponto de varejo.")
        elif role == "target":
            parts.append("Segmento alvo, não um varejo genérico.")
        elif role == "retail":
            parts.append("Varejo.")
        elif role == "reseller":
            parts.append("Revenda ou consultor, não o fabricante.")
        if chain:
            parts.append("Rede: filiais contam como uma marca.")
        if website:
            parts.append("Tem site.")
        if phone:
            parts.append("Tem telefone.")
        if address:
            parts.append("Tem endereço.")
        if public_email:
            parts.append("Tem e-mail publicado.")
        if plant_signal:
            parts.append("Nome ou mapa indica planta.")
        if not parts:
            parts.append("Sem dados de segmento para comparar com o ICP.")
    else:
        parts = []
        if industry_hit:
            parts.append(f"Segment matches the ICP ({industry}).")
        elif industries:
            parts.append("Segment is outside the configured ICP.")
        if geo_hit:
            parts.append(f"In the target geography ({where})." if where else "In the target geography.")
        elif places:
            parts.append("Outside the target geography.")
        if role == "producer":
            parts.append("Producer, not only a retail counter.")
        elif role == "target":
            parts.append("Target segment, not a generic retailer.")
        elif role == "retail":
            parts.append("Retail.")
        elif role == "reseller":
            parts.append("Reseller or consultant, not the manufacturer.")
        if chain:
            parts.append("Chain: branches count as one brand.")
        if website:
            parts.append("Has a website.")
        if phone:
            parts.append("Has a phone.")
        if address:
            parts.append("Has a street address.")
        if public_email:
            parts.append("Has a published email.")
        if plant_signal:
            parts.append("Name or map marks a plant.")
        if not parts:
            parts.append("No segment to compare with the ICP.")

    return score, " ".join(parts)
