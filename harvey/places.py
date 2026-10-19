"""Distance helpers for a lead list.

OpenStreetMap often has a lat/lon and no addr:city. The search label
("Curitiba e região metropolitana") is not a city. The municipality comes
from a cached reverse geocode (Nominatim zoom 10), which is a point inside
the boundary. The bundled centroids are only a distance reference: south
Curitiba (CIC) is closer to Araucária's town center than to Curitiba's, so
nearest-centroid assigns the wrong city.
"""

import math

# Farther than this, the nearest town center is a guess, not the city.
MAX_MUNICIPALITY_KM = 30.0

# (name, state, latitude, longitude) — town-center approximations.
MUNICIPALITIES = (
    ("Curitiba", "PR", -25.4284, -49.2733),
    ("São José dos Pinhais", "PR", -25.5347, -49.2064),
    ("Colombo", "PR", -25.2925, -49.2262),
    ("Pinhais", "PR", -25.4447, -49.1925),
    ("Araucária", "PR", -25.5928, -49.4100),
    ("Almirante Tamandaré", "PR", -25.3246, -49.3101),
    ("Campo Largo", "PR", -25.4596, -49.5273),
    ("Fazenda Rio Grande", "PR", -25.6576, -49.3073),
    ("Piraquara", "PR", -25.4421, -49.0624),
    ("Campina Grande do Sul", "PR", -25.3054, -49.0552),
    ("Quatro Barras", "PR", -25.3656, -49.0769),
    ("Campo Magro", "PR", -25.3687, -49.4506),
    ("Mandirituba", "PR", -25.7788, -49.3258),
    ("Contenda", "PR", -25.6760, -49.5353),
    ("Rio Branco do Sul", "PR", -25.1896, -49.3140),
    ("Itaperuçu", "PR", -25.2194, -49.3456),
    ("Lapa", "PR", -25.7672, -49.7164),
    ("Balsa Nova", "PR", -25.5835, -49.6358),
    ("Bocaiúva do Sul", "PR", -25.2067, -49.1144),
    ("Tijucas do Sul", "PR", -25.9311, -49.1950),
    ("Agudos do Sul", "PR", -25.9900, -49.3347),
    ("Quitandinha", "PR", -25.8728, -49.4972),
    ("Piên", "PR", -26.0969, -49.4283),
    ("Campo do Tenente", "PR", -25.9783, -49.6844),
    ("Adrianópolis", "PR", -24.6606, -48.9911),
    ("Cerro Azul", "PR", -24.8233, -49.2608),
    ("Doutor Ulysses", "PR", -24.5667, -49.4211),
    ("Tunas do Paraná", "PR", -24.9733, -49.0875),
    ("Rio Negro", "PR", -26.1056, -49.7975),
    ("São Paulo", "SP", -23.5505, -46.6333),
    ("Guarulhos", "SP", -23.4543, -46.5337),
    ("São Bernardo do Campo", "SP", -23.6914, -46.5646),
    ("Santo André", "SP", -23.6639, -46.5383),
    ("Osasco", "SP", -23.5325, -46.7917),
    ("São Caetano do Sul", "SP", -23.6229, -46.5548),
    ("Mauá", "SP", -23.6677, -46.4613),
    ("Diadema", "SP", -23.6861, -46.6228),
    ("Carapicuíba", "SP", -23.5225, -46.8356),
    ("Mogi das Cruzes", "SP", -23.5228, -46.1854),
    ("Itaquaquecetuba", "SP", -23.4861, -46.3486),
    ("Taboão da Serra", "SP", -23.6222, -46.7817),
    ("Barueri", "SP", -23.5112, -46.8764),
    ("Embu das Artes", "SP", -23.6489, -46.8522),
    ("Cotia", "SP", -23.6039, -46.9192),
    ("Santana de Parnaíba", "SP", -23.4442, -46.9178),
    ("Ferraz de Vasconcelos", "SP", -23.5411, -46.3689),
    ("Francisco Morato", "SP", -23.2817, -46.7450),
    ("Itapevi", "SP", -23.5489, -46.9342),
    ("Suzano", "SP", -23.5428, -46.3108),
    ("Ribeirão Pires", "SP", -23.7106, -46.4133),
    ("Caieiras", "SP", -23.3642, -46.7406),
    ("Franco da Rocha", "SP", -23.3228, -46.7292),
    ("Poá", "SP", -23.5281, -46.3450),
    ("Arujá", "SP", -23.3964, -46.3208),
    ("Mairiporã", "SP", -23.3186, -46.5867),
    ("Jandira", "SP", -23.5275, -46.9025),
    ("Itapecerica da Serra", "SP", -23.7169, -46.8492),
    ("Rio Grande da Serra", "SP", -23.7453, -46.3978),
    ("Vargem Grande Paulista", "SP", -23.5994, -47.0225),
    ("Cajamar", "SP", -23.3556, -46.8781),
    ("Santa Isabel", "SP", -23.3158, -46.2214),
    ("Embu-Guaçu", "SP", -23.8297, -46.8114),
    ("Biritiba Mirim", "SP", -23.5728, -46.0386),
    ("Guararema", "SP", -23.4153, -46.0350),
    ("Salesópolis", "SP", -23.5286, -45.8464),
    ("Juquitiba", "SP", -23.9319, -47.0686),
    ("Pirapora do Bom Jesus", "SP", -23.3972, -46.9992),
    ("São Lourenço da Serra", "SP", -23.8494, -46.9431),
)


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * radius * math.asin(min(1.0, math.sqrt(a)))


def bounding_box(lat: float, lng: float, radius_m: int) -> tuple[float, float, float, float]:
    """South, west, north, east covering ``radius_m`` around the point.

    Overpass ``around:`` is slow. A bbox is a rectangle the circle fits in;
    callers drop the corners that sit outside the radius.
    """
    radius_km = max(radius_m, 0) / 1000.0
    dlat = radius_km / 111.32
    cos = math.cos(math.radians(lat))
    dlng = radius_km / (111.32 * max(0.2, abs(cos)))
    return lat - dlat, lng - dlng, lat + dlat, lng + dlng


def nearest_municipality(lat: float, lon: float, max_km: float = MAX_MUNICIPALITY_KM):
    """``(name, state)`` of the closest bundled town center, or None.

    Not a city assignment. On a municipal border the nearest center is the
    neighbour. Callers that need the municipality use a reverse geocode.
    """
    best = None
    best_km = max_km
    for name, state, mlat, mlon in MUNICIPALITIES:
        dist = haversine_km(lat, lon, mlat, mlon)
        if dist <= best_km:
            best_km = dist
            best = (name, state)
    return best


def reverse_cache_key(lat: float, lon: float) -> str:
    """Settings key for one reverse-geocoded point, about a metre."""
    return f"revgeo:{lat:.5f},{lon:.5f}"


# Full state name (accent-folded) → UF. Nominatim often returns "Paraná".
_STATE_UF = {
    "acre": "AC", "alagoas": "AL", "amapa": "AP", "amazonas": "AM",
    "bahia": "BA", "ceara": "CE", "distrito federal": "DF",
    "espirito santo": "ES", "goias": "GO", "maranhao": "MA",
    "mato grosso": "MT", "mato grosso do sul": "MS", "minas gerais": "MG",
    "para": "PA", "paraiba": "PB", "parana": "PR", "pernambuco": "PE",
    "piaui": "PI", "rio de janeiro": "RJ", "rio grande do norte": "RN",
    "rio grande do sul": "RS", "rondonia": "RO", "roraima": "RR",
    "santa catarina": "SC", "sao paulo": "SP", "sergipe": "SE", "tocantins": "TO",
}


def municipality_from_address(address: dict | None) -> tuple[str, str]:
    """``(city, UF)`` from a Nominatim address dict.

    Municipality, city, town, and village are the city. Suburb, district,
    neighbourhood, and industrial estate are not — CIC is inside Curitiba.
    """
    from harvey.textutil import fold

    address = address or {}
    city = (
        address.get("municipality")
        or address.get("city")
        or address.get("town")
        or address.get("village")
        or ""
    )
    city = str(city).strip()
    iso = str(
        address.get("ISO3166-2-lvl4") or address.get("ISO3166-2-lvl6") or ""
    ).strip().upper()
    uf = ""
    if iso.startswith("BR-") and len(iso) >= 5:
        uf = iso.split("-", 1)[1][:2]
    if not uf:
        uf = _STATE_UF.get(fold(str(address.get("state") or "")), "")
    return city, uf
