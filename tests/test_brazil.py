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
from harvey.collectors.discover import (
    Business, DiscoveryQuery, OpenStreetMap, _upsert, build_queries,
)
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
    assert osm._tags("Alimentos")[0] == "shop=butcher"
    assert osm._tags("Cosméticos") == ["shop=cosmetics", "shop=perfumery"]
    assert osm._tags("Confecções") == ["shop=clothes", "craft=tailor", "craft=dressmaker"]
    assert osm._tags("Farmácias de manipulação") == [
        "shop=chemist", "shop=pharmacy", "amenity=pharmacy",
    ]
    assert osm._tags("Indústria") == ["industrial=factory", "man_made=works"]
    assert osm._tags("E-commerce") == ["shop=wholesale"]
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
    assert score == 100
    assert "Segmento compatível" in reason
    assert "Curitiba" in reason

    english = HarveyConfig(**_payload(language="en"))
    _, en_reason = score_company(company, english)
    assert "Segment matches" in en_reason


def test_example_yaml_is_a_lead_list_for_curitiba():
    cfg = load_config(str(EXAMPLE))
    assert email_sending_enabled(cfg) is False
    assert cfg.language == "pt-BR"
    assert cfg.compliance.regime == "br"
    queries = build_queries(cfg)
    match = [
        q for q in queries
        if q.term == "Cervejarias" and q.location == "Curitiba, PR"
    ]
    assert match and match[0].coordinate.startswith("-25.4284")
    assert len(queries) == 22


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
    assert int(by_name["Sem E-mail"]["icp_score"]) >= 90
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
    assert company.icp_score >= 90
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
