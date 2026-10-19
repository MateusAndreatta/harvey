"""Brazil lead lists: OSM trades, profiler, language, export, no mailbox."""

import csv
import os
import tempfile
from pathlib import Path

import pytest
import pytest_asyncio

from harvey.agents.handler import is_opt_out
from harvey.agents.scout import Scout
from harvey.agents.writer import Writer
from harvey.brands import brand_key, is_competitor_name
from harvey.collectors.discover import (
    Business, DiscoveryQuery, OpenStreetMap, _upsert, build_queries, is_junk,
)
from harvey.trainer import preserve_operator_settings
from harvey.collectors.profile import (
    CAREERS_PATHS, CONTACT_PATHS, TEAM_PATHS,
    extract_published_contacts, people_from_html, title_looks_like_role,
)
from harvey.config import EnvConfig, HarveyConfig, load_config
from harvey.export import (
    CSV_COLUMNS, LEAD_COLUMNS, collect_leads, collect_prospects, export_leads_csv,
)
from harvey.locale import (
    compliance_note, email_sending_enabled, language_instruction,
    normalize_language, normalize_regime,
)
from harvey.main import decide_next_action, run_list_cycle
from harvey.models.company import Company
from harvey.models.prospect import Prospect
from harvey.scoring import score_company
from harvey.signals import SIGNAL_CATALOG, SIGNAL_PT_BR, localize_signal, seed_signal_catalog
from harvey.state import StateManager

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples" / "harvey.local.yaml"


def _payload(**overrides):
    data = {
        "persona": {
            "name": "Seu Nome", "company": "Sua Empresa", "role": "Comercial",
            "email": "voce@suaempresa.com.br", "linkedin": "", "tone": "direto",
        },
        "product": {
            "name": "Etiquetas e rótulos",
            "description": "Etiquetas e rótulos para produto físico.",
            "pricing": "Sob consulta",
            "key_benefits": ["Prazo"],
            "objection_responses": {},
        },
        "icp": {
            "industries": ["Cervejarias"],
            "company_size": "pequeno",
            "titles": ["Proprietário", "Comprador"],
            "geography": ["Curitiba, PR"],
            "geo_coordinates": {"Curitiba, PR": "-25.4284,-49.2733,40"},
        },
        "language": "pt-BR",
        "channels": {"email": {"enabled": False, "provider": "none"}},
        "compliance": {"regime": "br"},
    }
    data.update(overrides)
    return data


@pytest_asyncio.fixture
async def state():
    with tempfile.TemporaryDirectory() as tmpdir:
        sm = StateManager(os.path.join(tmpdir, "test.db"))
        await sm.init_db()
        await seed_signal_catalog(sm)
        yield sm


def test_osm_maps_brazilian_trades_without_catching_unrelated_terms():
    osm = OpenStreetMap()
    assert osm._tags("Cervejarias") == ["craft=brewery"]
    assert osm._tags("brewery") == ["craft=brewery"]
    assert osm._tags("VINÍCOLA") == ["craft=winery"]
    assert osm._tags("vinicola") == ["craft=winery"]
    assert osm._tags("Destilarias") == ["craft=distillery"]
    assert osm._tags("Padarias") == ["shop=bakery"]
    assert osm._tags("Confeitarias") == [
        "craft=confectionery", "shop=confectionery", "shop=pastry",
    ]
    alimentos = osm._tags("alimentos e bebidas")
    assert "craft=brewery" in alimentos
    assert "craft=winery" in alimentos
    assert "craft=distillery" in alimentos
    assert "craft=bakery" in alimentos
    assert "shop=butcher" not in alimentos
    assert osm._tags("Cosméticos") == ["shop=cosmetics", "shop=perfumery"]
    assert osm._tags("Confecções") == ["craft=tailor", "craft=dressmaker"]
    assert osm._tags("Farmácias de manipulação") == [
        "amenity=pharmacy|name~manipula",
        "shop=chemist|name~manipula",
    ]
    assert "amenity=pharmacy" in osm._tags("Farmácia")
    assert osm._tags("Indústria") == ["industrial=factory", "man_made=works"]
    assert osm._tags("E-commerce") == []
    brewery = osm._overpass_clause("craft=brewery", 1000, "1", "2")
    assert "nwr[" in brewery
    assert "node[" not in brewery
    assert '["name"]' in brewery
    manipula = osm._overpass_clause(
        "amenity=pharmacy|name~manipula", 1000, "1", "2",
    )
    assert '["name"~"manipula",i]' in manipula
    assert osm._kind({"craft": "brewery"}, "Lúpulo") == "producer"
    assert osm._kind({"shop": "butcher"}, "Açougue") == "retail"
    assert osm._kind({"craft": "printer"}, "Oficina") == "competitor"
    assert osm._kind({"shop": "copyshop"}, "Cópias") == "competitor"
    # First match still wins: dentist is mapped ahead of cosmetics.
    assert osm._tags("cosmetic dentist") == ["amenity=dentist"]
    assert osm._tags("B2B SaaS") == []


@pytest.mark.asyncio
async def test_unmapped_osm_term_names_a_supported_trade():
    with pytest.raises(RuntimeError, match="no category") as exc:
        await OpenStreetMap().fetch(
            None, {}, DiscoveryQuery(term="widgets", coordinate="1,2,10"),
        )
    assert "cervejaria" in str(exc.value)


def test_profile_reads_brazilian_paths_titles_and_published_contacts():
    assert "/quem-somos" in TEAM_PATHS
    assert "/nossa-equipe" in TEAM_PATHS
    assert "/trabalhe-conosco" in CAREERS_PATHS
    assert "/contato" in CONTACT_PATHS
    assert "/fale-conosco" in CONTACT_PATHS
    assert title_looks_like_role("Proprietário")

    html = """
    <h3>João da Silva</h3><p>Sócio-fundador</p>
    <h3>Ana Costa</h3><p>Gerente de compras</p>
    <h3>Fale Conosco</h3><p>WhatsApp</p>
    <h3>Michael Torres</h3><p>Owner</p>
    """
    people = {p["first_name"]: p for p in people_from_html(html)}
    assert people["João"]["is_decision_maker"] is True
    assert "Sócio" in people["João"]["title"] or "socio" in people["João"]["title"].lower()
    assert people["Ana"]["is_decision_maker"] is True
    assert "Fale" not in people
    assert people["Michael"]["title"] == "Owner"

    published = extract_published_contacts(
        '<a href="mailto:contato@exemplo.com.br">x</a>'
        '<a href="https://wa.me/5541999990000">zap</a>'
    )
    assert published["email"] == "contato@exemplo.com.br"
    assert published["phone"] == "(41) 99999-0000"


def test_language_and_regime_stay_minimal():
    assert normalize_language("en") == "en"
    assert normalize_language("pt_BR") == "pt-BR"
    assert normalize_language("portuguese") == "pt-BR"
    with pytest.raises(ValueError):
        normalize_language("nope")
    assert language_instruction("en") == ""
    assert "Portuguese" in language_instruction("pt-BR")

    assert normalize_regime("LGPD") == "br"
    assert normalize_regime("Brazil") == "br"
    assert normalize_regime("") == ""
    with pytest.raises(ValueError):
        normalize_regime("nope")
    assert "LGPD" in compliance_note("br")
    assert compliance_note("") == ""

    cfg = HarveyConfig(**_payload())
    assert cfg.language == "pt-BR"
    assert cfg.compliance.regime == "br"
    assert email_sending_enabled(cfg) is False

    english = HarveyConfig(**_payload(
        language="en",
        channels={"email": {"enabled": True, "provider": "gmail"}},
        compliance={"regime": ""},
    ))
    assert english.language == "en"
    assert english.compliance.regime == ""
    assert email_sending_enabled(english) is True


def test_portuguese_opt_out_is_an_opt_out():
    assert is_opt_out("Por favor, descadastre meu e-mail")
    assert is_opt_out("Não quero mais receber")
    assert is_opt_out("Please unsubscribe me")


def test_score_company_reason_follows_language():
    company = Company(
        name="Lúpulo", industry="Cervejarias", city="Curitiba",
        phone="(41) 3333-0000", location="Curitiba, PR",
    )
    score, reason = score_company(company, HarveyConfig(**_payload()))
    assert "Segmento compatível" in reason
    assert "Na região alvo" in reason
    assert "Curitiba" in reason

    english = HarveyConfig(**_payload(language="en"))
    _, en_reason = score_company(company, english)
    assert "Segment matches" in en_reason

    producer = Company(
        name="Lúpulo", industry="Cervejarias", city="Curitiba",
        phone="(41) 3333-0000", website="https://lupulo.example",
        kind="producer",
    )
    chain = Company(
        name="Droga Raia", industry="Farmácias de manipulação", city="Curitiba",
        phone="(41) 3333-0001", kind="retail",
    )
    producer_score, _ = score_company(producer, HarveyConfig(**_payload()))
    chain_score, chain_reason = score_company(chain, HarveyConfig(**_payload()))
    assert producer_score >= chain_score + 30
    assert "Produtor" in score_company(producer, HarveyConfig(**_payload()))[1]
    assert "Rede" in chain_reason

    suburb = Company(
        name="Cervejaria do Porto", industry="Cervejarias",
        city="São José dos Pinhais", kind="producer", phone="(41) 3333-0002",
    )
    metro = HarveyConfig(**_payload(
        icp={
            "industries": ["Cervejarias"],
            "company_size": "pequeno",
            "titles": ["Proprietário"],
            "geography": ["Curitiba e região metropolitana, PR"],
            "geo_coordinates": {
                "Curitiba e região metropolitana, PR": "-25.4284,-49.2733,40",
            },
        },
    ))
    _, suburb_reason = score_company(suburb, metro)
    assert "Na região alvo" in suburb_reason
    assert "Fora da região" not in suburb_reason

    nearby = Company(
        name="Cervejaria Colombo", industry="Cervejarias", city="Colombo",
        kind="producer", latitude=-25.29, longitude=-49.22,
    )
    _, nearby_reason = score_company(nearby, HarveyConfig(**_payload()))
    assert "Na região alvo" in nearby_reason

    far = Company(
        name="Cervejaria Londrina", industry="Cervejarias", city="Londrina",
        kind="producer",
    )
    _, far_reason = score_company(far, metro)
    assert "Fora da região alvo" in far_reason


def test_example_yaml_is_a_lead_list_for_curitiba():
    cfg = load_config(str(EXAMPLE))
    assert email_sending_enabled(cfg) is False
    assert cfg.language == "pt-BR"
    assert cfg.compliance.regime == "br"
    queries = build_queries(cfg)
    match = [
        q for q in queries
        if q.term == "Cervejarias" and "Curitiba" in q.location
    ]
    assert match and match[0].coordinate.startswith("-25.4284")
    assert len(queries) == 20


def test_signal_codes_stay_put_when_labels_switch():
    codes = [s["code"] for s in SIGNAL_CATALOG]
    assert set(SIGNAL_PT_BR) == set(codes)
    original = SIGNAL_CATALOG[0]["label"]
    shown = localize_signal(SIGNAL_CATALOG[0], "pt-BR")
    assert shown["code"] == SIGNAL_CATALOG[0]["code"]
    assert shown["label"] != original
    assert SIGNAL_CATALOG[0]["label"] == original
    assert localize_signal(SIGNAL_CATALOG[0], "en")["label"] == original


@pytest.mark.asyncio
async def test_discover_upsert_keeps_address_city_and_segment(state):
    cid, was_new = await _upsert(
        state,
        Business(
            name="Cervejaria Exemplo",
            phone="(41) 3333-4444",
            address="Rua das Flores, 10",
            location="Curitiba, PR",
            external_id="osm:node/99",
            provider="osm",
        ),
        DiscoveryQuery(term="Cervejarias", location="Curitiba, PR"),
    )
    assert was_new
    company = await state.get_company(cid)
    assert company.address == "Rua das Flores, 10"
    assert company.city == "Curitiba"
    assert company.industry == "Cervejarias"
    assert company.domain == ""


@pytest.mark.asyncio
async def test_lead_csv_includes_companies_without_email(state, tmp_path):
    cfg = HarveyConfig(**_payload())
    bare = await state.add_company(Company(
        name="Sem E-mail", industry="Cervejarias", city="Curitiba",
        address="Rua 1", phone="(41) 1111-1111", external_id="osm:node/1",
    ))
    published = await state.add_company(Company(
        name="Contato Publicado", industry="Cervejarias", city="Curitiba",
        public_email="contato@publicado.com.br", external_id="osm:node/2",
    ))
    named = await state.add_company(Company(
        name="Com Comprador", industry="Cervejarias", city="Curitiba",
        website="https://comprador.example", external_id="osm:node/3",
    ))
    await state.add_prospect(Prospect(
        first_name="Ana", last_name="Costa", title="Comprador",
        email="ana@comprador.example", email_status="guess",
        company="Com Comprador", company_id=named, score=50,
    ))
    await state.add_prospect(Prospect(
        first_name="Ada", last_name="Verified", title="Owner",
        email="ada@comprador.example", email_status="verified",
        company="Com Comprador", company_id=named, score=10,
    ))

    rows = await collect_leads(state, config=cfg)
    by_name = {r["company_name"]: r for r in rows}
    assert set(by_name) == {"Sem E-mail", "Contato Publicado", "Com Comprador"}
    assert by_name["Sem E-mail"]["contact_email"] == ""
    assert by_name["Sem E-mail"]["segment"] == "Cervejarias"
    assert by_name["Sem E-mail"]["city"] == "Curitiba"
    assert by_name["Sem E-mail"]["phone"] == "(41) 1111-1111"
    # A phone-only match used to land on 90 with every other row. The
    # spread keeps it well under that, and a website still ranks higher.
    bare_score = int(by_name["Sem E-mail"]["icp_score"])
    assert 30 <= bare_score < 90
    assert int(by_name["Com Comprador"]["icp_score"]) > bare_score
    assert by_name["Contato Publicado"]["email_confidence"] == "published"
    assert by_name["Contato Publicado"]["contact_email"] == "contato@publicado.com.br"
    # Owner/buyer with an email wins over a higher score that is neither.
    assert by_name["Com Comprador"]["contact_name"] == "Ana Costa"
    assert by_name["Com Comprador"]["email_confidence"] == "guess"
    assert by_name["Com Comprador"]["website"] == "https://comprador.example"

    out = tmp_path / "leads.csv"
    count, text = await export_leads_csv(state, out_path=str(out), config=cfg)
    assert count == 3
    parsed = list(csv.DictReader(text.splitlines()))
    assert list(parsed[0]) == LEAD_COLUMNS

    deliverable = await collect_prospects(state)
    assert {r["first_name"] for r in deliverable} == {"Ada"}
    assert list(deliverable[0])  # sequencer rows stay on the old columns
    from harvey.export import to_csv
    header = to_csv([]).strip().split(",")
    assert header == CSV_COLUMNS
    assert bare and published


@pytest.mark.asyncio
async def test_scout_scores_profile_contacts_without_a_mailbox(state, monkeypatch):
    async def fail_profile(*args, **kwargs):
        raise AssertionError("profile should not run when nothing has a domain")
    monkeypatch.setattr("harvey.main.run_profile_stage", fail_profile)

    cfg = HarveyConfig(**_payload())
    cid = await state.add_company(Company(
        name="Cervejaria do João", industry="Cervejarias", city="Curitiba",
        phone="(41) 9999-0000", external_id="osm:node/7",
    ))
    await state.add_observation(
        "DECISION_MAKER_TITLE", company_id=cid, collector="profile",
        value_text="João da Silva — Sócio-fundador",
    )
    scout = Scout(object(), state, cfg, EnvConfig())
    cycle = await run_list_cycle(state, scout)
    assert cycle["scored"] == 1
    assert cycle["imported"] == 1
    assert cycle["profiled"] == 0

    company = await state.get_company(cid)
    assert 40 <= company.icp_score < 90
    assert "Contato: João da Silva" in company.icp_reason
    prospects = await state.list_prospects()
    assert len(prospects) == 1
    assert prospects[0].email == ""
    assert prospects[0].source == "profile"


@pytest.mark.asyncio
async def test_email_off_does_not_choose_or_write_a_campaign():
    summary = {
        "prospects": {"new": 4},
        "draft_campaigns": 2,
        "open_conversations": 3,
    }
    off = HarveyConfig(**_payload())
    assert await decide_next_action(None, None, off, summary=summary) == "prospect"

    on = HarveyConfig(**_payload(
        language="en",
        channels={"email": {"enabled": True, "provider": "gmail"}},
        compliance={"regime": ""},
    ))
    assert await decide_next_action(None, None, on, summary=summary) == "handle_replies"

    class Boom:
        def load_skills_for_agent(self, *args, **kwargs):
            raise AssertionError("writer should not load skills when email is off")

    await Writer(Boom(), None, off, EnvConfig()).run()


@pytest.mark.asyncio
async def test_dashboard_does_not_require_a_mailbox_for_lead_lists(monkeypatch):
    from harvey import dashboard

    monkeypatch.setattr(dashboard, "_resolve_config_file", lambda: EXAMPLE)
    status = await dashboard.get_setup_status()
    by_id = {c["id"]: c for c in status["checks"]}
    assert by_id["email_provider"]["required"] is False
    assert by_id["email_provider"]["done"] is True
    assert "lead lists" in by_id["email_provider"]["label"]
    assert by_id["verifier"]["required"] is False
    assert by_id["env_file"]["required"] is False


def test_print_shops_are_competitors_and_chains_have_a_brand_key():
    assert is_junk("", "Fotolaser Gráfica")
    assert is_junk("lamigraf.com.br", "Lamigraf")
    assert is_competitor_name("Rótulos & Etiquetas")
    assert is_junk("", "Cervejaria do Porto") is False
    assert brand_key("Droga Raia Batel") == "chain:droga raia"
    assert brand_key("O Boticário Shopping") == "chain:o boticario"
    assert brand_key("C&A Palladium") == "chain:c&a"
    assert brand_key("Cervejaria do Porto") == ""
    assert brand_key("Filial Norte", brand="Nissei") == "brand:nissei"
    assert brand_key("Loja 3", wikidata="Q123") == "wd:Q123"


@pytest.mark.asyncio
async def test_chain_branches_collapse_and_competitors_drop_out(state):
    cfg = HarveyConfig(**_payload())
    first, was_new = await _upsert(
        state,
        Business(
            name="Droga Raia Centro", location="Curitiba, PR",
            external_id="osm:node/1", provider="osm", brand="chain:droga raia",
        ),
        DiscoveryQuery(term="Farmácia", location="Curitiba, PR"),
    )
    second, again = await _upsert(
        state,
        Business(
            name="Droga Raia Batel", phone="(41) 3000-0000",
            location="Curitiba, PR", external_id="osm:node/2", provider="osm",
            brand="chain:droga raia",
        ),
        DiscoveryQuery(term="Farmácia", location="Curitiba, PR"),
    )
    assert was_new and not again
    assert first == second
    saved = await state.get_company(first)
    assert saved.phone == "(41) 3000-0000"
    assert saved.brand == "chain:droga raia"

    await state.add_company(Company(
        name="O Boticário Shopping", city="Curitiba", external_id="osm:node/3",
    ))
    await state.add_company(Company(
        name="O Boticário Centro", city="Curitiba", phone="(41) 9",
        external_id="osm:node/4",
    ))
    await state.add_company(Company(
        name="Cervejaria do Porto", industry="Cervejarias", city="Curitiba",
        external_id="osm:node/5",
    ))
    await state.add_company(Company(
        name="Fotolaser Gráfica", city="Curitiba", external_id="osm:node/6",
    ))

    rows = await collect_leads(state, config=cfg)
    names = {row["company_name"] for row in rows}
    assert "Fotolaser Gráfica" not in names
    assert "Cervejaria do Porto" in names
    boticario = [row for row in rows if "Botic" in row["company_name"]]
    assert len(boticario) == 1
    assert "2 filiais agrupadas" in boticario[0]["icp_reason"]

    every_branch = await collect_leads(state, config=cfg, one_per_brand=False)
    assert sum("Botic" in row["company_name"] for row in every_branch) == 2


@pytest.mark.asyncio
async def test_v13_upgrades_a_database_that_already_applied_the_draft_v12(tmp_path):
    """PR #1 owns v12 (cursor_calls). A live DB may already be at the draft
    v12 that added the lead columns, so v13 must skip those and still add
    the Cursor counter."""
    import aiosqlite

    from harvey.state import MIGRATIONS

    assert len(MIGRATIONS) == 13
    db_path = str(tmp_path / "draft.db")
    async with aiosqlite.connect(db_path) as db:
        for script in MIGRATIONS[:11]:
            await db.executescript(script)
        for column, typedef in (
            ("address", "TEXT DEFAULT ''"),
            ("city", "TEXT DEFAULT ''"),
            ("public_email", "TEXT DEFAULT ''"),
            ("icp_score", "INTEGER DEFAULT 0"),
            ("icp_reason", "TEXT DEFAULT ''"),
        ):
            await db.execute(f"ALTER TABLE companies ADD COLUMN {column} {typedef}")
        await db.execute("PRAGMA user_version = 12")
        await db.commit()

    sm = StateManager(db_path)
    await sm.init_db()
    async with aiosqlite.connect(db_path) as db:
        async with db.execute("PRAGMA user_version") as cursor:
            (version,) = await cursor.fetchone()
        async with db.execute("PRAGMA table_info(companies)") as cursor:
            company_cols = {row[1] for row in await cursor.fetchall()}
        async with db.execute("PRAGMA table_info(usage_log)") as cursor:
            usage_cols = [row[1] for row in await cursor.fetchall()]
    assert version == 13
    assert {"address", "brand", "latitude", "longitude", "kind", "icp_score"} <= company_cols
    assert usage_cols.count("cursor_calls") == 1


def test_train_keeps_a_filled_lead_list_config():
    generated = {
        "persona": {"name": "Generated Name", "company": "Generated Co"},
        "product": {"name": "Generated Product", "description": "From the site"},
        "icp": {
            "industries": ["SaaS"],
            "company_size": "1-10",
            "titles": ["CEO", "VP Sales"],
            "geography": ["United States"],
            "geo_coordinates": {},
        },
        "language": "en",
        "compliance": {"regime": ""},
        "channels": {"email": {"enabled": True, "provider": "instantly"}},
        "usage": {
            "quiet_hours": {
                "start": "22:00", "end": "07:00", "timezone": "America/New_York",
            },
        },
    }
    existing = {
        "product": {"name": "Etiquetas e rótulos"},
        "icp": {
            "industries": ["Cervejarias"],
            "company_size": "",
            "titles": ["Proprietário"],
            "geography": ["Curitiba e região metropolitana, PR"],
            "geo_coordinates": {
                "Curitiba e região metropolitana, PR": "-25.4284,-49.2733,40",
            },
        },
        "language": "pt-BR",
        "compliance": {"regime": "br"},
        "channels": {"email": {"enabled": False, "provider": "none"}},
        "usage": {
            "quiet_hours": {
                "start": "22:00", "end": "07:00", "timezone": "America/Sao_Paulo",
            },
        },
    }
    out = preserve_operator_settings(generated, existing)
    assert out["language"] == "pt-BR"
    assert out["compliance"]["regime"] == "br"
    assert out["icp"]["industries"] == ["Cervejarias"]
    assert out["icp"]["titles"] == ["Proprietário"]
    assert out["icp"]["company_size"] == "1-10"
    assert out["icp"]["geo_coordinates"][
        "Curitiba e região metropolitana, PR"
    ].startswith("-25.4284")
    assert out["channels"]["email"]["enabled"] is False
    assert out["channels"]["email"]["provider"] == "none"
    assert out["usage"]["quiet_hours"]["timezone"] == "America/Sao_Paulo"
    assert out["product"]["name"] == "Generated Product"
    assert out["persona"]["company"] == "Generated Co"
