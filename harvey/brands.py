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

_COMPETITOR = re.compile(
    r"grafica|lamigraf|fotolaser|rotulos?|etiquetas?|serigraf|"
    r"silkscreen|copyshop|copiadora|print shop|label shop|label print"
)


def _name_core(name: str) -> str:
    folded = fold(name)
    folded = re.split(r"\s+[-–|]\s+|/", folded)[0]
    folded = re.sub(r"\b(loja|filial|unidade|shopping)\b.*", "", folded)
    folded = re.sub(r"\s+\d+$", "", folded)
    return folded.strip()


def brand_key(name: str, brand: str = "", wikidata: str = "") -> str:
    """A stable key for a chain, or "" when this business is not one.

    Empty means "do not collapse". Two padarias with similar names stay
    two rows.
    """
    wiki = (wikidata or "").strip()
    if wiki:
        return "wd:" + wiki
    named = fold(brand)
    if named:
        return "brand:" + named
    core = _name_core(name)
    if not core:
        return ""
    for chain in _CHAINS:
        if core == chain or core.startswith(chain + " "):
            return "chain:" + chain
    return ""


def is_competitor_name(name: str) -> bool:
    """Print, label, and sticker shops. They sell what this list is for."""
    return bool(_COMPETITOR.search(fold(name)))
