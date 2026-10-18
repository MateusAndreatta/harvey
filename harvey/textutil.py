"""Small text helpers shared by discovery, profiling, and scoring.

Accent-insensitive on purpose: Brazilian pages and search terms mix
"vinícola", "vinicola", and "VINÍCOLA", and those are the same word.
"""

import unicodedata


def fold(value: str) -> str:
    """Lowercase, strip accents, and drop apostrophes and hyphens.

    Spaces stay, so "loja virtual" still has two words. Hyphens go, so
    "e-commerce" and "sócio-fundador" match "ecommerce" and "socio".
    """
    decomposed = unicodedata.normalize("NFKD", value or "")
    stripped = "".join(c for c in decomposed if not unicodedata.combining(c))
    return stripped.lower().replace("-", "").replace("'", "").replace("’", "")
