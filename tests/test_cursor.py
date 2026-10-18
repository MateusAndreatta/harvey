"""Cursor brain provider: text-only cursor-agent, no silent fallback.

The fake binary covers success (with the live usage shape), a tool_call
that must be killed, auth failure, timeout, usage limit, a set
CURSOR_API_KEY (status stays logged out), and the writer/scout/trainer paths.
"""

import asyncio
import json
import os
import time
from pathlib import Path

import pytest
import pytest_asyncio
from pydantic import ValidationError

import harvey.brain as brain_mod
from harvey.brain import Brain
from harvey.config import BrainConfig, ConfigError, UsageConfig, load_brain_config
from harvey.cursor_cli import (
    SUGGESTED_MODEL,
    CursorError,
    build_prompt_argv,
    classify_cli_text,
    event_requests_tool,
    normalize_usage,
    reject_forbidden,
    status_is_authenticated,
    wrap_prompt,
)
from harvey.state import StateManager

FAKE = Path(__file__).resolve().parent / "fake_cursor_agent.py"

BASE = {
    "persona": {"name": "H", "company": "A", "role": "B", "email": "e", "linkedin": "", "tone": "t"},
    "product": {"name": "P", "description": "D", "pricing": "$1", "key_benefits": ["saves time"],
                "objection_responses": {}},
    "icp": {"industries": ["roofing"], "company_size": "5-50", "titles": ["owner"],
            "geography": []},
}


@pytest.fixture
def cursor_log(tmp_path, monkeypatch):
    FAKE.chmod(0o755)
    log = tmp_path / "calls.jsonl"
    monkeypatch.setenv("HARVEY_FAKE_CURSOR_LOG", str(log))
    monkeypatch.delenv("CURSOR_API_KEY", raising=False)
    monkeypatch.delenv("HARVEY_FAKE_CURSOR_MODE", raising=False)
    monkeypatch.delenv("HARVEY_FAKE_CURSOR_RESULT", raising=False)
    monkeypatch.delenv("HARVEY_FAKE_CURSOR_STATUS", raising=False)
    monkeypatch.delenv("HARVEY_FAKE_CURSOR_MODELS", raising=False)
    monkeypatch.delenv("HARVEY_FAKE_CURSOR_MARKER", raising=False)
    monkeypatch.setattr("harvey.cursor_cli.find_cursor_agent", lambda: str(FAKE))
    return log


def _calls(log: Path) -> list[dict]:
    if not log.exists():
        return []
    return [json.loads(line) for line in log.read_text().splitlines() if line.strip()]


@pytest_asyncio.fixture
async def state(tmp_path):
    sm = StateManager(str(tmp_path / "harvey.db"))
    await sm.init_db()
    return sm


def _brain(state, model="composer-2.5"):
    return Brain(state, BrainConfig(provider="cursor", model=model))


def test_cursor_config_accepts_the_provider():
    cfg = BrainConfig(provider=" Cursor ", model="composer-2.5")
    assert cfg.provider == "cursor" and cfg.model == "composer-2.5"
    assert UsageConfig().max_daily_cursor_calls == 200
    assert UsageConfig(max_daily_cursor_calls=0).max_daily_cursor_calls == 0
    with pytest.raises(ValidationError):
        UsageConfig(max_daily_cursor_calls=-1)
    with pytest.raises(ValidationError):
        BrainConfig(provider="gemini")


def test_load_brain_config_keeps_cursor(tmp_path):
    path = tmp_path / "harvey.yaml"
    path.write_text("brain:\n  provider: cursor\n  model: composer-2.5\n")
    assert load_brain_config(str(path)) == BrainConfig(provider="cursor", model="composer-2.5")
    path.write_text("brain:\n  provider: gemini\n")
    with pytest.raises(ConfigError):
        load_brain_config(str(path))


def test_usage_and_tool_helpers():
    assert normalize_usage({
        "inputTokens": 8669, "outputTokens": 33,
        "cacheReadTokens": 3872, "cacheWriteTokens": 0,
    }) == {
        "input_tokens": 8669, "output_tokens": 33,
        "cache_read_tokens": 3872, "cache_creation_tokens": 0,
    }
    assert normalize_usage(None)["output_tokens"] == 0
    assert status_is_authenticated({"isAuthenticated": True, "status": "nope"})
    assert status_is_authenticated({"status": "authenticated"})
    assert not status_is_authenticated({"status": "unauthenticated", "isAuthenticated": False})
    assert not status_is_authenticated(None)
    assert event_requests_tool({"type": "tool_call", "subtype": "started"})
    assert event_requests_tool({
        "type": "assistant",
        "message": {"content": [{"type": "tool_use", "text": "x"}]},
    })
    assert not event_requests_tool({
        "type": "assistant",
        "message": {"content": [{"type": "text", "text": "I will not use a tool"}]},
    })
    assert classify_cli_text("Error: Not authenticated").kind == "auth"
    assert classify_cli_text("You've hit your usage limit").kind == "usage_limit"
    assert classify_cli_text("all good") is None
    argv, stdin = build_prompt_argv("cursor-agent", SUGGESTED_MODEL, "/tmp/ws", "hello")
    assert argv[0] == "cursor-agent"
    assert "--force" not in argv and "--yolo" not in argv and "--approve-mcps" not in argv
    assert argv[argv.index("--mode") + 1] == "ask"
    assert argv[argv.index("--output-format") + 1] == "stream-json"
    assert argv[argv.index("--model") + 1] == SUGGESTED_MODEL
    assert stdin is None and argv[-1] == wrap_prompt("hello")
    _argv, long_stdin = build_prompt_argv("cursor-agent", "composer-2.5", "/tmp/ws", "x" * 9000)
    assert long_stdin is not None and "x" * 9000 not in _argv
    flag_argv, flag_stdin = build_prompt_argv("cursor-agent", "composer-2.5", "/tmp/ws", "--force")
    assert flag_stdin is not None and "--force" not in flag_argv[1:]
    with pytest.raises(CursorError) as err:
        reject_forbidden(["cursor-agent", "--force"])
    assert err.value.kind == "isolation"


@pytest.mark.asyncio
async def test_success_records_live_usage_shape(state, cursor_log, monkeypatch):
    async def no_claude(*_a, **_k):
        raise AssertionError("Cursor brain must not run the Claude CLI")

    monkeypatch.setattr(brain_mod.asyncio, "create_subprocess_exec", no_claude)
    brain = _brain(state)
    assert type(brain.quota).__name__ == "CursorCallBudget"
    assert await brain.think("say oi", agent="writer", task="draft", max_retries=0) == "oi"
    assert await state.get_usage_today("cursor") == 1
    assert await state.get_usage_today("claude") == 0
    assert await state.get_usage_today("codex") == 0
    rows = await state.usage_by_provider(days=1)
    assert rows[0]["provider"] == "cursor"
    assert rows[0]["input_tokens"] == 8669
    assert rows[0]["output_tokens"] == 33
    assert rows[0]["cache_read_tokens"] == 3872
    assert rows[0]["cache_creation_tokens"] == 0
    assert rows[0]["cost_usd"] == 0.0
    assert (await state.usage_by_model(days=1))[0]["model"] == "composer-2.5"

    import aiosqlite
    async with aiosqlite.connect(state.db_path) as db:
        cursor = await db.execute(
            "SELECT session_id, request_key, duration_ms, source FROM usage_events"
        )
        session_id, request_key, duration_ms, source = await cursor.fetchone()
    assert session_id == "sess-live"
    assert request_key == "req-live"
    assert duration_ms == 4927
    assert source == "cursor_agent"

    prompts = [row for row in _calls(cursor_log) if row["cmd"] == "prompt"]
    assert len(prompts) == 1
    row = prompts[0]
    assert row["mode"] == "ask" and row["format"] == "stream-json" and row["trust"]
    assert row["model"] == "composer-2.5"
    assert row["forbidden"] == []
    assert row["cli_has_shell_deny"] and row["global_has_shell_deny"]
    assert "Shell(*)" in row["cli_json"] and "Write(**)" in row["cli_json"]
    assert "Mcp(*:*)" in row["global_config"]
    assert row["api_key_in_argv"] is False


@pytest.mark.asyncio
async def test_think_json_and_blank_model_uses_composer(state, cursor_log, monkeypatch):
    monkeypatch.setenv("HARVEY_FAKE_CURSOR_RESULT", '{"intent": "interested"}')
    brain = Brain(state, BrainConfig(provider="cursor"))
    assert brain.cursor.effective_model() == SUGGESTED_MODEL
    assert await brain.think_json("classify", max_retries=0) == {"intent": "interested"}
    prompt = [row for row in _calls(cursor_log) if row["cmd"] == "prompt"][-1]
    assert prompt["model"] == "composer-2.5"


@pytest.mark.asyncio
async def test_tool_call_kills_the_process(state, cursor_log, monkeypatch, tmp_path):
    marker = tmp_path / "survived.txt"
    monkeypatch.setenv("HARVEY_FAKE_CURSOR_MODE", "tool_call")
    monkeypatch.setenv("HARVEY_FAKE_CURSOR_MARKER", str(marker))
    brain = _brain(state)
    started = time.monotonic()
    assert await brain.think("read the file", timeout=8, max_retries=0) == ""
    assert time.monotonic() - started < 7
    assert not marker.exists()
    assert "tool" in brain.paused_reason.lower()
    assert await state.get_usage_today("cursor") == 0
    # A second call does not start another runtime while the pause holds.
    assert await brain.think("again", timeout=8, max_retries=0) == ""
    assert len([row for row in _calls(cursor_log) if row["cmd"] == "prompt"]) == 1


@pytest.mark.asyncio
async def test_workspace_write_without_a_tool_event_is_isolation(state, cursor_log, monkeypatch):
    monkeypatch.setenv("HARVEY_FAKE_CURSOR_MODE", "mutate")
    brain = _brain(state)
    assert await brain.think("hi", timeout=8, max_retries=0) == ""
    assert brain.paused_reason
    assert await state.get_usage_today("cursor") == 0


@pytest.mark.asyncio
async def test_auth_error_pauses(state, cursor_log, monkeypatch):
    monkeypatch.setenv("HARVEY_FAKE_CURSOR_MODE", "auth")
    brain = _brain(state)
    assert await brain.think("hi", timeout=8, max_retries=0) == ""
    assert "login" in brain.paused_reason.lower() or "cursor_api_key" in brain.paused_reason.lower()
    assert await state.get_usage_today("cursor") == 0


@pytest.mark.asyncio
async def test_timeout_is_retryable_and_not_sticky(state, cursor_log, monkeypatch):
    monkeypatch.setenv("HARVEY_FAKE_CURSOR_MODE", "timeout")
    monkeypatch.setattr(brain_mod, "RETRY_BASE_DELAY", 0)
    brain = _brain(state)
    started = time.monotonic()
    assert await brain.think("hi", timeout=0.6, max_retries=0) == ""
    assert time.monotonic() - started < 8
    assert brain.paused_reason == ""
    assert await state.get_usage_today("cursor") == 0


@pytest.mark.asyncio
async def test_usage_limit_closes_the_budget(state, cursor_log, monkeypatch):
    monkeypatch.setenv("HARVEY_FAKE_CURSOR_MODE", "usage_limit")
    brain = _brain(state)
    assert await brain.think("hi", timeout=8, max_retries=0) == ""
    assert "usage limit" in brain.paused_reason.lower()
    assert await brain.is_within_budget(1000, max_percent=None) is False
    assert await state.get_usage_today("cursor") == 0


@pytest.mark.asyncio
async def test_call_cap_counts_only_cursor_calls(state, cursor_log):
    brain = _brain(state)
    for _ in range(3):
        await state.increment_usage(provider="claude")
        await state.increment_usage(provider="codex")
    assert await brain.is_within_budget(2, max_percent=None) is True
    await state.increment_usage(provider="cursor")
    await state.increment_usage(provider="cursor")
    assert await brain.is_within_budget(2, max_percent=None) is False


@pytest.mark.asyncio
async def test_preflight_login_and_api_key(state, cursor_log, monkeypatch):
    brain = _brain(state)
    assert await brain.preflight() == ""
    cmds = [row["cmd"] for row in _calls(cursor_log)]
    assert "version" in cmds and "status" in cmds and "models" not in cmds

    cursor_log.write_text("")
    monkeypatch.setenv("HARVEY_FAKE_CURSOR_STATUS", "unauthenticated")
    logged_out = _brain(state)
    problem = await logged_out.preflight()
    assert "not logged in" in problem.lower() or "cursor_api_key" in problem.lower()
    assert "status" in [row["cmd"] for row in _calls(cursor_log)]

    # status reports logged out when the only credential is the API key.
    cursor_log.write_text("")
    monkeypatch.setenv("CURSOR_API_KEY", "crsr_test_key")
    authed = _brain(state)
    assert await authed.preflight() == ""
    rows = _calls(cursor_log)
    assert "models" in [row["cmd"] for row in rows]
    assert "status" not in [row["cmd"] for row in rows]
    assert any(row.get("has_api_key") for row in rows)

    cursor_log.write_text("")
    monkeypatch.setenv("HARVEY_FAKE_CURSOR_MODELS", "auth")
    rejected = _brain(state)
    problem = await rejected.preflight()
    assert "cursor_api_key" in problem.lower()
    assert await rejected.think("hi", timeout=5, max_retries=0) == ""


@pytest.mark.asyncio
async def test_prompt_does_not_put_the_api_key_on_argv(state, cursor_log, monkeypatch):
    monkeypatch.setenv("CURSOR_API_KEY", "crsr_test_key")
    monkeypatch.setenv("HARVEY_FAKE_CURSOR_MODELS", "ok")
    brain = _brain(state)
    assert await brain.think("hi", timeout=8, max_retries=0) == "oi"
    prompt = [row for row in _calls(cursor_log) if row["cmd"] == "prompt"][0]
    assert prompt["has_api_key"] is True
    assert prompt["api_key_in_argv"] is False
    assert "crsr_test_key" not in json.dumps(prompt["argv"])


@pytest.mark.asyncio
async def test_long_prompt_uses_stdin(state, cursor_log):
    brain = _brain(state)
    text = "y" * 9000
    assert await brain.think(text, timeout=8, max_retries=0) == "oi"
    prompt = [row for row in _calls(cursor_log) if row["cmd"] == "prompt"][0]
    assert prompt["stdin_len"] > 9000
    assert text not in json.dumps(prompt["argv"])
    assert prompt["prompt_argc"] == 0


@pytest.mark.asyncio
async def test_missing_cli_is_setup(state, monkeypatch):
    monkeypatch.setattr("harvey.cursor_cli.find_cursor_agent", lambda: None)
    brain = Brain(state, BrainConfig(provider="cursor", model="composer-2.5"))
    brain.cursor._cursor_path = None
    problem = await brain.preflight()
    assert "not found" in problem.lower()
    assert await brain.think("hi", max_retries=0) == ""
    assert "not found" in brain.paused_reason.lower()


@pytest.mark.asyncio
async def test_writer_scout_and_trainer_use_cursor(state, cursor_log, monkeypatch):
    from harvey.agents.scout import Scout
    from harvey.agents.writer import Writer
    from harvey.config import EnvConfig, HarveyConfig
    from harvey.models.prospect import Prospect
    from harvey.trainer import Trainer

    config = HarveyConfig(**BASE, brain={"provider": "cursor", "model": "composer-2.5"})
    sequence = [
        {"step": 1, "subject": "quick note", "body": "Hi {{first_name}} at {{company}}", "delay_days": 0},
        {"step": 2, "subject": "one more", "body": "Following up {{first_name}}", "delay_days": 3},
        {"step": 3, "subject": "closing", "body": "All good {{first_name}}", "delay_days": 4},
    ]
    monkeypatch.setenv("HARVEY_FAKE_CURSOR_RESULT", json.dumps(sequence))
    writer = Writer(_brain(state), state, config)
    steps = await writer._write_sequence([
        Prospect(first_name="Ada", last_name="Lovelace", title="Owner", company="Acme"),
    ])
    assert [step.subject for step in steps] == ["quick note", "one more", "closing"]
    assert await state.get_usage_today("cursor") == 1
    assert await state.get_usage_today("claude") == 0

    monkeypatch.setenv("HARVEY_FAKE_CURSOR_RESULT", json.dumps(
        [{"index": 1, "score": 88, "personalization": "roofing jobs"}]
    ))
    scout = Scout(_brain(state), state, config, EnvConfig())
    scored = await scout._score_contacts([
        Prospect(first_name="Ada", last_name="Lovelace", title="Owner", company="Acme",
                 industry="roofing"),
    ])
    assert scored and scored[0].score == 88
    assert scored[0].personalization_notes == "roofing jobs"

    product = {
        "company_name": "Acme",
        "product_name": "Widget",
        "product_description": "Widgets for roofers.",
        "pricing": "$1",
        "key_benefits": ["fast"],
    }
    monkeypatch.setenv("HARVEY_FAKE_CURSOR_RESULT", json.dumps(product))
    trainer = Trainer(brain_config=BrainConfig(provider="cursor", model="composer-2.5"))
    trainer.state = state
    trainer.brain = _brain(state)
    trainer.scraped_pages = {"https://acme.example": "We sell widgets to roofers."}
    info = await trainer._extract_product_info()
    assert info["product_name"] == "Widget"
    built = trainer._build_config(product, {"industries": ["roofing"]}, {}, "acme.example")
    assert built["brain"]["provider"] == "cursor"
    assert built["brain"]["model"] == "composer-2.5"
    prompts = [row for row in _calls(cursor_log) if row["cmd"] == "prompt"]
    assert prompts and all(row["model"] == "composer-2.5" for row in prompts)
    assert all("--force" not in row["argv"] for row in prompts)


@pytest.mark.asyncio
async def test_heartbeat_budgets_cursor_by_call_cap(monkeypatch, tmp_path):
    import harvey.main as main_mod
    from harvey.config import EnvConfig, HarveyConfig

    seen = {}

    async def budget(self, max_daily_calls=200, max_percent=None):
        seen["calls"] = max_daily_calls
        seen["percent"] = max_percent
        return False

    async def ready(self):
        return ""

    async def sleep(seconds, stop):
        seen["slept"] = seconds
        stop.set()
        return True

    cfg = HarveyConfig(
        **BASE,
        brain={"provider": "cursor", "model": "composer-2.5"},
        usage={"max_daily_cursor_calls": 17, "max_daily_claude_percent": 80},
    )
    monkeypatch.setattr(main_mod, "load_config", lambda: cfg)
    monkeypatch.setattr(main_mod, "load_env", lambda: EnvConfig())
    monkeypatch.setattr(main_mod, "in_quiet_hours", lambda _config: False)
    monkeypatch.setattr(main_mod, "StateManager", lambda: StateManager(str(tmp_path / "h.db")))
    monkeypatch.setattr(Brain, "is_within_budget", budget)
    monkeypatch.setattr(Brain, "preflight", ready)
    monkeypatch.setattr(main_mod, "_interruptible_sleep", sleep)
    await main_mod.heartbeat(asyncio.Event())
    assert seen["calls"] == 17 and seen["percent"] is None
    assert seen["slept"] == 3600


def test_dashboard_and_cli_show_cursor(cursor_log, monkeypatch, tmp_path):
    import harvey.config as config_mod
    import harvey.dashboard as dash
    from fastapi.testclient import TestClient

    db = tmp_path / "dash.db"
    asyncio.run(StateManager(str(db)).init_db())
    monkeypatch.setattr(dash, "DB_PATH", db)
    monkeypatch.setattr(dash, "_quota_clients", {})
    monkeypatch.setattr(dash, "_active_brain", lambda: BrainConfig(provider="cursor", model="composer-2.5"))
    monkeypatch.setattr(config_mod, "cursor_call_cap", lambda: 40)

    async def seed():
        sm = StateManager(str(db))
        await sm.init_db()
        await sm.increment_usage(provider="cursor")
        await sm.record_usage_event(
            provider="cursor", model="composer-2.5", input_tokens=8669,
            output_tokens=33, cache_read_tokens=3872, source="cursor_agent",
        )
    asyncio.run(seed())

    with TestClient(dash.app) as client:
        usage = client.get("/api/usage").json()
        stats = client.get("/api/stats").json()
    assert usage["provider"] == "cursor"
    assert usage["quota_status"] == "call_budget"
    assert usage["quota"] is None
    assert usage["cursor_daily_cap"] == 40
    assert usage["cursor_calls_today"] == 1
    assert stats["cursor_calls_today"] == 1
    assert stats["brain_provider"] == "cursor"
    assert [row["provider"] for row in usage["by_provider"]] == ["cursor"]

    from tests.test_brain_provider import _render_js
    card = _render_js("quotaCardHtml", usage)
    assert "Cursor call budget" in card and "40" in card
    assert "Quota unavailable" not in card
    chips = _render_js("brainCallChips", stats)
    assert "Cursor" in chips and "calls today" in chips


def test_cli_usage_prints_the_call_budget(cursor_log, monkeypatch, tmp_path, capsys):
    import harvey.cli as cli
    import harvey.config as config_mod
    import harvey.state as state_mod

    db = tmp_path / "u.db"

    async def seed():
        sm = StateManager(str(db))
        await sm.init_db()
        await sm.increment_usage(provider="cursor")
    asyncio.run(seed())
    monkeypatch.setattr(config_mod, "load_brain_config",
                        lambda: BrainConfig(provider="cursor", model="composer-2.5"))
    monkeypatch.setattr(config_mod, "cursor_call_cap", lambda: 40)
    monkeypatch.setattr(state_mod, "StateManager", lambda: StateManager(str(db)))
    cli.cmd_usage(type("A", (), {"days": 30})())
    out = capsys.readouterr().out
    assert "Cursor Usage" in out
    assert "1 / 40" in out
    assert "no live quota" in out
    assert "Claude Usage" not in out
