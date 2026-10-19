"""Chain brands and print-shop competitors.

A lead list wants one row per chain, not thirteen Droga Raia branches, and
it does not want the gráficas that sell the same thing the operator sells.
Independent businesses that merely share a common word stay separate.
"""

import re

from harvey.textutil import fold

# National retail brands that show up as many untagged branches. Matched on
# the folded name after the branch suffix is stripped. OSM brand /
# brand:wikidata wins when the element carries it.
CHAIN_NAMES = (
    "droga raia",
    "drogasil",
    "drogarias nissei",
    "nissei",
    "pague menos",
    "droga menos",
    "panvel",
    "ultrafarma",
    "o boticario",
    "boticario",
    "c&a",
    "cea",
    "marisa",
    "lojas renner",
    "renner",
    "riachuelo",
    "lojas americanas",
    "americanas",
    "magazine luiza",
    "magalu",
    "casas bahia",
    "sams club",
    "sam club",
    "carrefour",
    "assai",
    "atacadao",
    "mcdonald",
    "burger king",
    "starbucks",
    "subway",
    "outback",
    "giraffas",
    "habib",
    "bobs",
    "cacau show",
    "natura",
    "avon",
    "havianas",
)

# Longer names first so "drogarias nissei" wins over "nissei".
_CHAINS = tuple(sorted((fold(name) for name in CHAIN_NAMES), key=len, reverse=True))

# Same storefront twice in OSM, a couple hundred metres apart.
NEARBY_KM = 0.5

_COMPETITOR = re.compile(
    r"grafica|lamigraf|fotolaser|rotulos?|etiquetas?|serigraf|"
    r"silkscreen|copyshop|copiadora|print shop|label shop|label print"
)

# Consultant listings, not the factory. Mary Kay in OSM is the consultant.
# "Aqui tem Natura" is a reseller counter. Natura the manufacturer does not
# match unless the name says consultor or the cosmetics-brand rule below.
_RESELLER = re.compile(
    r"consultor|consultora|revendedora|revendedor|mary kay|marykay|aqui tem"
)

# Franchise counters in a cosmetics search. A plant whose name says
# indústria stays. Used only when the segment itself is cosmetics.
_COSMETICS_SEGMENT = re.compile(r"cosmet|perfum|beleza|maquiag|higien")
_COSMETICS_COUNTER = re.compile(
    r"boticario|natura|mary kay|marykay|avon|eudora|hinode|franquia"
)

_MANUFACTURER = re.compile(r"industri|fabrica|manufatur|laboratorio")


def _name_core(name: str) -> str:
    folded = fold(name)
    folded = re.split(r"\s+[-–|]\s+|/", folded)[0]
    folded = re.sub(r"\b(loja|filial|unidade|shopping)\b.*", "", folded)
    folded = re.sub(r"\s+\d+$", "", folded)
    return folded.strip()


def name_key(name: str) -> str:
    """Folded name with the branch suffix removed. Empty when nothing remains."""
    return _name_core(name)


def _chain_from(text: str) -> str:
    core = _name_core(text)
    if not core:
        return ""
    for chain in _CHAINS:
        if core == chain or core.startswith(chain + " "):
            return chain
    return ""


def brand_key(name: str, brand: str = "", wikidata: str = "") -> str:
    """A stable key for a chain, or "" when this business is not one.

    A known chain name wins over brand:wikidata. O Boticário is one brand
    whether one branch carries Q7073219 and the next carries only the name.
    Empty means "do not collapse". Two padarias with similar names stay
    two rows.
    """
    chained = _chain_from(name) or _chain_from(brand)
    if chained:
        return "chain:" + chained
    wiki = (wikidata or "").strip()
    if wiki:
        return "wd:" + wiki
    # An unknown brand tag (Votorantim on a cement plant) is not a retail
    # chain. Collapsing every plant that shares a corporate brand, and then
    # scoring it as a chain of shops, drops the factories the list is for.
    return ""


def is_competitor_name(name: str) -> bool:
    """Print, label, and sticker shops. They sell what this list is for."""
    return bool(_COMPETITOR.search(fold(name)))


def is_reseller_name(name: str) -> bool:
    """Consultant and reseller listings (Mary Kay, consultora Natura)."""
    folded = fold(name)
    if not folded:
        return False
    if _RESELLER.search(folded):
        return True
    return "natura" in folded and bool(re.search(r"\b(espaco|sala|home)\b", folded))


def is_manufacturer_name(name: str) -> bool:
    """The name itself says factory, not shop."""
    return bool(_MANUFACTURER.search(fold(name)))


def is_segment_reseller(name: str, industry: str = "", kind: str = "") -> bool:
    """Consultant or cosmetics franchise counter, not the plant.

    Mary Kay and "Aqui tem Natura" match on the name alone. O Boticário,
    Natura, and Avon match only inside a cosmetics segment, and a producer
    (kind or a name that says indústria) is kept.
    """
    if (kind or "").strip().lower() == "producer" or is_manufacturer_name(name):
        return False
    if is_reseller_name(name):
        return True
    if not _COSMETICS_SEGMENT.search(fold(industry)):
        return False
    return bool(_COSMETICS_COUNTER.search(fold(name)))


def resellers_excluded(config) -> bool:
    """Drop reseller rows unless the ICP sets ``exclude_resellers: false``."""
    icp = getattr(config, "icp", None)
    if icp is None:
        return True
    return getattr(icp, "exclude_resellers", True) is not False


def is_short_name(name: str) -> bool:
    """A name like 'ggg': three of the same letter, nothing else.

    One- and two-letter names are left alone. Chains such as C&A are three
    characters and are not this.
    """
    compact = fold(name).replace(" ", "")
    if len(compact) != 3 or not compact.isalpha():
        return False
    if _chain_from(name):
        return False
    return len(set(compact)) == 1


_GENERIC_NAME = re.compile(
    r"^(sos )?(atelie( de costura)?|costura|confeccao|loja|comercio|"
    r"empresa|salao|studio|estudio|oficina)$"
)


def is_generic_name(name: str) -> bool:
    """A label like 'Ateliê de costura' or 'SOS costura' with no company in it.

    Anchored, so 'costura da silva' stays.
    """
    return bool(_GENERIC_NAME.match(fold(name)))


def drop_thin_lead(name: str, phone: str = "", website: str = "",
                   address: str = "", domain: str = "") -> bool:
    """Junk rows: a tiny name, or a generic one with no phone, site, or address."""
    if is_short_name(name):
        return True
    if not is_generic_name(name):
        return False
    return not any(str(part or "").strip() for part in (phone, website, address, domain))
