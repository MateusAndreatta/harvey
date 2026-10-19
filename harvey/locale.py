"""Output language and the compliance regime.

English stays the default. pt-BR changes scoring reasons and the signal
labels a person reads. It does not rewrite the cold-email prompts: this
install is for lead lists, and email copy stays in the language of those
prompt files unless a one-line directive is appended.
"""


def normalize_language(value) -> str:
    key = str(value or "en").strip().lower().replace("_", "-")
    if key in ("en", "en-us", "english"):
        return "en"
    if key in ("pt", "pt-br", "portuguese", "portugues"):
        return "pt-BR"
    raise ValueError(
        f"'{value}' is not a supported output language. Use en or pt-BR."
    )


def language_instruction(language: str) -> str:
    """One line for a model prompt. Empty in English, so defaults stay put."""
    if language == "pt-BR":
        return (
            "OUTPUT LANGUAGE: write notes and analysis in Brazilian Portuguese "
            "(pt-BR), in a natural B2B tone, using você. Do not translate "
            "proper names."
        )
    return ""


_REGIMES = {
    "": "",
    "us": "us",
    "usa": "us",
    "can-spam": "us",
    "canspam": "us",
    "uk": "uk",
    "gb": "uk",
    "pecr": "uk",
    "eu": "eu",
    "gdpr": "eu",
    "ca": "ca",
    "canada": "ca",
    "casl": "ca",
    "br": "br",
    "brazil": "br",
    "brasil": "br",
    "lgpd": "br",
}


def normalize_regime(value) -> str:
    key = str(value or "").strip().lower().replace("_", "-")
    if key not in _REGIMES:
        known = "us, uk, eu, ca, br"
        raise ValueError(
            f"'{value}' is not a compliance regime. Use one of: {known} "
            "(or lgpd, can-spam, pecr, gdpr, casl)."
        )
    return _REGIMES[key]


def compliance_note(regime: str) -> str:
    """A short prompt addendum. Empty unless a regime is selected."""
    notes = {
        "us": (
            "COMPLIANCE (CAN-SPAM, United States): truthful subject, real "
            "from-address, a physical mailing address, and a working opt-out "
            "honored immediately."
        ),
        "uk": (
            "COMPLIANCE (PECR / UK GDPR): B2B email needs a legitimate-interest "
            "basis relevant to the person's role, and objecting must be easy."
        ),
        "eu": (
            "COMPLIANCE (GDPR): legitimate interest, relevance to the role, "
            "an easy objection, and erasure requests honored."
        ),
        "ca": (
            "COMPLIANCE (CASL, Canada): consent depends on whether the address "
            "was published or there is an existing business relationship. "
            "When that basis is missing, do not send."
        ),
        "br": (
            "COMPLIANCE (LGPD, Brazil): B2B contact uses legitimate interest "
            "(art. 7, IX, and art. 10) only when the message is relevant to "
            "the person's professional role. Every email identifies the sender "
            "and includes a clear descadastro. Honor any descadastro immediately "
            "and permanently."
        ),
    }
    return notes.get(regime or "", "")


def email_sending_enabled(config) -> bool:
    """False when this install is building lead lists and not sending mail."""
    channels = getattr(config, "channels", None)
    email = getattr(channels, "email", None)
    if email is None or not getattr(email, "enabled", False):
        return False
    provider = (getattr(email, "provider", "") or "").strip().lower()
    return provider not in ("", "none", "off")
