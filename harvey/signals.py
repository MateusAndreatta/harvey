"""The signal vocabulary Harvey proposes, and the user confirms.

Harvey never decides on its own what makes a good prospect. It proposes a
catalog of signals it knows how to collect — each with a plain-language
description, what it costs, and why it might matter — and the user confirms,
edits, or rejects them in the dashboard before any collection runs.

Only ``confirmed`` signals get collected. That keeps spend intentional and
keeps the resulting cohorts explainable: a prospect list is a query over
signals a human chose, not a black box.

Design note: every signal is recorded as an OBSERVATION (a row), never a
column. A new signal needs no migration, history comes free, and confidence
and provenance travel with the fact.
"""

# category: discovery | profile | people | verification
# value_type: num | text | bool
# cost_note: what collecting it actually costs, in plain language
SIGNAL_CATALOG: list[dict] = [
    # ── Discovery: who exists, and how visible are they ──
    {
        "code": "SERP_RANK",
        "label": "Search rank position",
        "description": (
            "Where the business ranks for its core '<service> <city>' search. "
            "The most useful prospecting signal there is: positions 11-30 are "
            "the sweet spot — visible enough to be trying, not winning yet. "
            "Top 10 are already winning (harder sell); 31+ are cheaper but "
            "less motivated."
        ),
        "category": "discovery",
        "value_type": "num",
        "collector": "discover",
        "cost_note": "~$0.0006 per search (paid SERP API, queued endpoint)",
        "confidence_floor": 0.0,
    },
    {
        "code": "FOUND_IN_SERP",
        "label": "Discovered via search",
        "description": "The business appeared in a target-market search — how Harvey found it at all.",
        "category": "discovery",
        "value_type": "text",
        "collector": "discover",
        "cost_note": "included in the search above",
        "confidence_floor": 0.0,
    },

    {
        "code": "NO_WEBSITE",
        "label": "No website at all",
        "description": (
            "The business has a listing and a phone number but no site. If you "
            "sell websites this is the highest-intent signal that exists — and "
            "it is a filter you can query for directly, not something you infer."
        ),
        "category": "discovery",
        "value_type": "bool",
        "collector": "discover",
        "cost_note": "included in the business listing lookup",
        "confidence_floor": 0.0,
    },
    {
        "code": "UNCLAIMED_LISTING",
        "label": "Unclaimed Google listing",
        "description": (
            "Nobody has claimed their Google Business Profile, so they are not "
            "managing how they show up locally. Strong signal for anyone "
            "selling local marketing."
        ),
        "category": "discovery",
        "value_type": "bool",
        "collector": "discover",
        "cost_note": "included in the business listing lookup",
        "confidence_floor": 0.0,
    },
    {
        "code": "REVIEW_RATING",
        "label": "Review rating",
        "description": (
            "Their average star rating. Useful in both directions: a low "
            "rating is a reputation problem to solve, a high one with few "
            "reviews is proof they are good but invisible."
        ),
        "category": "discovery",
        "value_type": "num",
        "collector": "discover",
        "cost_note": "included in the business listing lookup",
        "confidence_floor": 0.0,
    },
    {
        "code": "REVIEW_COUNT",
        "label": "Number of reviews",
        "description": (
            "How many reviews they have. A rough proxy for size and for how "
            "much attention they pay to their online presence."
        ),
        "category": "discovery",
        "value_type": "num",
        "collector": "discover",
        "cost_note": "included in the business listing lookup",
        "confidence_floor": 0.0,
    },

    # ── Profile: what they are (free — HTML Harvey already fetches) ──
    {
        "code": "INCUMBENT_AGENCY",
        "label": "Has a marketing/web agency",
        "description": (
            "An agency credited in the site footer ('Website by X'). High-value: "
            "it tells you who you're displacing, and every detection builds a "
            "roster you can target as a whole book of business. Only recorded "
            "when the credit wording is explicit — a wrong incumbent is worse "
            "than none."
        ),
        "category": "profile",
        "value_type": "text",
        "collector": "profile",
        "cost_note": "free (homepage HTML)",
        "confidence_floor": 0.75,
    },
    {
        "code": "RUNNING_GOOGLE_ADS",
        "label": "Running Google Ads",
        "description": "Google Ads tag on the site — they are spending on acquisition TODAY. Strong budget signal.",
        "category": "profile",
        "value_type": "bool",
        "collector": "profile",
        "cost_note": "free (homepage HTML)",
        "confidence_floor": 0.0,
    },
    {
        "code": "RUNNING_META_ADS",
        "label": "Running Meta/Facebook Ads",
        "description": "Meta Pixel on the site — actively spending on paid social.",
        "category": "profile",
        "value_type": "bool",
        "collector": "profile",
        "cost_note": "free (homepage HTML)",
        "confidence_floor": 0.0,
    },
    {
        "code": "TECH_STACK",
        "label": "Website platform / tools",
        "description": "What the site is built on and which tools it runs (WordPress, Shopify, HubSpot, chat widgets, booking tools).",
        "category": "profile",
        "value_type": "text",
        "collector": "profile",
        "cost_note": "free (homepage HTML)",
        "confidence_floor": 0.0,
    },
    {
        "code": "NO_SCHEMA_MARKUP",
        "label": "Missing structured data",
        "description": "No JSON-LD schema markup — a concrete, checkable SEO gap you can name in an email.",
        "category": "profile",
        "value_type": "bool",
        "collector": "profile",
        "cost_note": "free (homepage HTML)",
        "confidence_floor": 0.0,
    },
    {
        "code": "NO_ONLINE_BOOKING",
        "label": "No online booking/scheduling",
        "description": "No booking or scheduling widget detected — leads have to phone in, so after-hours demand is lost.",
        "category": "profile",
        "value_type": "bool",
        "collector": "profile",
        "cost_note": "free (homepage HTML)",
        "confidence_floor": 0.0,
    },
    {
        "code": "SITE_PAGE_COUNT",
        "label": "Site size",
        "description": "Page count from sitemap.xml. A very thin site suggests little investment; a large stale one suggests neglect.",
        "category": "profile",
        "value_type": "num",
        "collector": "profile",
        "cost_note": "free (sitemap.xml)",
        "confidence_floor": 0.0,
    },
    {
        "code": "BLOG_STALE",
        "label": "Content gone stale",
        "description": "No new content in a long time — content marketing started and abandoned.",
        "category": "profile",
        "value_type": "num",
        "collector": "profile",
        "cost_note": "free (sitemap.xml)",
        "confidence_floor": 0.0,
    },
    {
        "code": "BLOCKS_AI_CRAWLERS",
        "label": "Blocks AI crawlers",
        "description": "robots.txt blocks AI crawlers — they'll be invisible in AI search answers.",
        "category": "profile",
        "value_type": "bool",
        "collector": "profile",
        "cost_note": "free (robots.txt)",
        "confidence_floor": 0.0,
    },
    {
        "code": "HIRING_ROLE",
        "label": "Hiring for a relevant role",
        "description": "An open role on their careers page that implies they're buying in your category right now.",
        "category": "profile",
        "value_type": "text",
        "collector": "profile",
        "cost_note": "free (careers page)",
        "confidence_floor": 0.0,
    },

    # ── People: who decides ──
    {
        "code": "CONTACT_FOUND",
        "label": "Named contact found",
        "description": "A named person scraped from the team/about page, with their title.",
        "category": "people",
        "value_type": "text",
        "collector": "people",
        "cost_note": "free (team page)",
        "confidence_floor": 0.0,
    },
    {
        "code": "DECISION_MAKER_TITLE",
        "label": "Decision-maker title",
        "description": "Title matches an owner/decision-maker pattern (Owner, President, Practice Manager, Marketing Director).",
        "category": "people",
        "value_type": "text",
        "collector": "people",
        "cost_note": "free (team page)",
        "confidence_floor": 0.0,
    },
    {
        "code": "REGISTRY_VERIFIED",
        "label": "Confirmed in a public registry",
        "description": (
            "The person was confirmed in an authoritative public registry "
            "(licensing board, professional registry). Also filters out "
            "scraping artifacts — a name that matches nothing usually wasn't a person."
        ),
        "category": "people",
        "value_type": "text",
        "collector": "people",
        "cost_note": "free (public registry API)",
        "confidence_floor": 0.0,
    },
    {
        "code": "LIKELY_OWNER",
        "label": "Likely the owner",
        "description": "Registry indicators suggest this person owns the business rather than working there.",
        "category": "people",
        "value_type": "bool",
        "collector": "people",
        "cost_note": "free (public registry API)",
        "confidence_floor": 0.0,
    },

    # ── Verification ──
    {
        "code": "EMAIL_PATTERN",
        "label": "Company email pattern",
        "description": "The domain's address format (first.last@, flast@). One real address cracks the whole company.",
        "category": "verification",
        "value_type": "text",
        "collector": "verify",
        "cost_note": "free, or ~1 lookup credit",
        "confidence_floor": 0.0,
    },
    {
        "code": "EMAIL_STATUS",
        "label": "Email deliverability",
        "description": "Whether the address is verified, catch-all/risky, an unverified guess, or invalid.",
        "category": "verification",
        "value_type": "text",
        "collector": "verify",
        "cost_note": "1 verification credit (free tiers available)",
        "confidence_floor": 0.0,
    },
    {
        "code": "CONTACT_FORM_URL",
        "label": "Contact form available",
        "description": (
            "A contact form on the site. Worth knowing because it reaches the "
            "business without needing an email address at all — and roughly "
            "half of domains can't be email-verified."
        ),
        "category": "verification",
        "value_type": "text",
        "collector": "profile",
        "cost_note": "free (site HTML)",
        "confidence_floor": 0.0,
    },
]


async def seed_signal_catalog(state) -> int:
    """Register the catalog as PROPOSED signals awaiting user confirmation.

    Idempotent, and never overrides a decision the user already made: an
    existing signal keeps its confirmed/rejected status.
    """
    for sig in SIGNAL_CATALOG:
        await state.upsert_signal_code(
            sig["code"],
            label=sig["label"],
            description=sig["description"],
            category=sig["category"],
            value_type=sig["value_type"],
            collector=sig["collector"],
            cost_note=sig["cost_note"],
            confidence_floor=sig.get("confidence_floor", 0.0),
        )
    return len(SIGNAL_CATALOG)


# Display-time copy. The database keeps the English labels so a reseed
# does not flip language, and the codes never change.
SIGNAL_PT_BR: dict[str, dict[str, str]] = {
    "SERP_RANK": {
        "label": "Posição na busca",
        "description": (
            "Onde a empresa aparece na busca '<serviço> <cidade>'. "
            "As posições 11-30 são o melhor alvo: visível o bastante para "
            "estar tentando, ainda sem ganhar. O top 10 já ganha; abaixo de "
            "30 é mais barato e menos motivado."
        ),
        "cost_note": "~US$ 0,0006 por busca (API de SERP paga)",
    },
    "FOUND_IN_SERP": {
        "label": "Encontrada na busca",
        "description": "A empresa apareceu numa busca do mercado-alvo — foi assim que o Harvey a achou.",
        "cost_note": "incluído na busca acima",
    },
    "NO_WEBSITE": {
        "label": "Sem site",
        "description": (
            "Tem ficha e telefone, mas nenhum site. Se você vende sites, "
            "este é o sinal de maior intenção — e dá para filtrar direto."
        ),
        "cost_note": "incluído na consulta de fichas",
    },
    "UNCLAIMED_LISTING": {
        "label": "Ficha do Google não reivindicada",
        "description": (
            "Ninguém reivindicou o perfil da empresa no Google, então ela "
            "não cuida de como aparece localmente."
        ),
        "cost_note": "incluído na consulta de fichas",
    },
    "REVIEW_RATING": {
        "label": "Nota das avaliações",
        "description": (
            "A média de estrelas. Nota baixa é problema de reputação; nota "
            "alta com poucas avaliações mostra qualidade sem visibilidade."
        ),
        "cost_note": "incluído na consulta de fichas",
    },
    "REVIEW_COUNT": {
        "label": "Número de avaliações",
        "description": "Quantas avaliações a empresa tem. Um proxy grosseiro de tamanho e de atenção à presença online.",
        "cost_note": "incluído na consulta de fichas",
    },
    "INCUMBENT_AGENCY": {
        "label": "Tem agência de marketing ou web",
        "description": (
            "Uma agência creditada no rodapé ('site por X'). Diz quem você "
            "está substituindo. Só é gravado quando o crédito é explícito."
        ),
        "cost_note": "grátis (HTML da home)",
    },
    "RUNNING_GOOGLE_ADS": {
        "label": "Anunciando no Google",
        "description": "Tag do Google Ads no site — estão gastando com aquisição agora.",
        "cost_note": "grátis (HTML da home)",
    },
    "RUNNING_META_ADS": {
        "label": "Anunciando no Meta/Facebook",
        "description": "Pixel da Meta no site — gasto ativo em mídia social paga.",
        "cost_note": "grátis (HTML da home)",
    },
    "TECH_STACK": {
        "label": "Plataforma e ferramentas do site",
        "description": "Em que o site foi feito e quais ferramentas rodam (WordPress, Shopify, HubSpot, chat, agenda).",
        "cost_note": "grátis (HTML da home)",
    },
    "NO_SCHEMA_MARKUP": {
        "label": "Sem dados estruturados",
        "description": "Sem marcação JSON-LD — uma lacuna de SEO concreta, que dá para citar.",
        "cost_note": "grátis (HTML da home)",
    },
    "NO_ONLINE_BOOKING": {
        "label": "Sem agendamento online",
        "description": "Nenhum widget de agenda. O lead precisa ligar, e a demanda fora do horário se perde.",
        "cost_note": "grátis (HTML da home)",
    },
    "SITE_PAGE_COUNT": {
        "label": "Tamanho do site",
        "description": "Quantidade de páginas no sitemap.xml. Site muito fino sugere pouco investimento; site grande e parado sugere abandono.",
        "cost_note": "grátis (sitemap.xml)",
    },
    "BLOG_STALE": {
        "label": "Conteúdo parado",
        "description": "Faz tempo que não publicam — o conteúdo começou e foi abandonado.",
        "cost_note": "grátis (sitemap.xml)",
    },
    "BLOCKS_AI_CRAWLERS": {
        "label": "Bloqueia rastreadores de IA",
        "description": "O robots.txt bloqueia rastreadores de IA — a empresa some das respostas de busca por IA.",
        "cost_note": "grátis (robots.txt)",
    },
    "HIRING_ROLE": {
        "label": "Contratando para um cargo relevante",
        "description": "Uma vaga na página de carreiras que indica compra na sua categoria agora.",
        "cost_note": "grátis (página de carreiras)",
    },
    "CONTACT_FOUND": {
        "label": "Contato nomeado",
        "description": "Uma pessoa nomeada na página de equipe ou sobre, com o cargo.",
        "cost_note": "grátis (página da equipe)",
    },
    "DECISION_MAKER_TITLE": {
        "label": "Cargo de quem decide",
        "description": "O cargo parece de dono ou de quem decide (proprietário, diretor, gerente de compras).",
        "cost_note": "grátis (página da equipe)",
    },
    "REGISTRY_VERIFIED": {
        "label": "Confirmado em registro público",
        "description": (
            "A pessoa foi confirmada num registro público (conselho, "
            "registro profissional). Também filtra nomes que não eram pessoas."
        ),
        "cost_note": "grátis (API de registro público)",
    },
    "LIKELY_OWNER": {
        "label": "Provável dono",
        "description": "Indicadores do registro sugerem que esta pessoa é dona do negócio, não só funcionária.",
        "cost_note": "grátis (API de registro público)",
    },
    "EMAIL_PATTERN": {
        "label": "Padrão de e-mail da empresa",
        "description": "O formato do endereço no domínio (nome.sobrenome@, nsobrenome@). Um endereço real abre a empresa inteira.",
        "cost_note": "grátis, ou ~1 crédito de consulta",
    },
    "EMAIL_STATUS": {
        "label": "Entregabilidade do e-mail",
        "description": "Se o endereço foi verificado, é catch-all/arriscado, um palpite, ou inválido.",
        "cost_note": "1 crédito de verificação (há faixa grátis)",
    },
    "CONTACT_FORM_URL": {
        "label": "Formulário de contato",
        "description": (
            "Um formulário no site. Alcança a empresa sem e-mail — e cerca "
            "de metade dos domínios não tem e-mail verificável. WhatsApp também conta."
        ),
        "cost_note": "grátis (HTML do site)",
    },
}

CATEGORY_PT_BR = {
    "discovery": (
        "Descoberta — quem existe",
        "Como o Harvey encontra empresas e o quanto elas aparecem. "
        "É a única etapa que pode custar dinheiro.",
    ),
    "profile": (
        "Perfil — o que elas são",
        "Lido das páginas que a empresa já publica. Grátis, sem modelo, "
        "três requisições por empresa.",
    ),
    "people": (
        "Pessoas — quem decide",
        "Pessoas nomeadas e se elas podem dizer sim.",
    ),
    "verification": (
        "Contato — dá para alcançar",
        "Se o endereço entrega, e o que fazer quando não entrega.",
    ),
}


def active_language() -> str:
    """The configured output language, or English if config cannot be read."""
    try:
        from harvey.config import load_config
        return getattr(load_config(), "language", "en") or "en"
    except Exception:
        return "en"


def localize_signal(sig: dict, language: str) -> dict:
    """A copy with pt-BR label and description. Codes stay as stored."""
    out = dict(sig)
    if language != "pt-BR":
        return out
    overlay = SIGNAL_PT_BR.get(out.get("code") or "")
    if not overlay:
        return out
    out["label"] = overlay["label"]
    out["description"] = overlay["description"]
    if overlay.get("cost_note"):
        out["cost_note"] = overlay["cost_note"]
    return out


def localize_category(key: str, language: str, label: str, blurb: str) -> tuple[str, str]:
    """Category heading for the Signals tab. The group key is unchanged."""
    if language == "pt-BR" and key in CATEGORY_PT_BR:
        return CATEGORY_PT_BR[key]
    return label, blurb
