#!/usr/bin/env python3
"""Stand-in for cursor-agent. Behavior is selected with environment variables.

HARVEY_FAKE_CURSOR_MODE
    success (default), tool_call, auth, timeout, usage_limit, mutate
HARVEY_FAKE_CURSOR_STATUS
    authenticated (default) or unauthenticated, for the status command
HARVEY_FAKE_CURSOR_MODELS
    ok (default), auth, or limit, for the models command
HARVEY_FAKE_CURSOR_RESULT
    text placed in the success result (default "oi")
HARVEY_FAKE_CURSOR_LOG
    path to append one JSON object per invocation
HARVEY_FAKE_CURSOR_MARKER
    written only if a tool_call run is still alive after the tool event
"""

import json
import os
import sys
import time

FORBIDDEN = ("--force", "--yolo", "--approve-mcps", "--auto-review")


def _log(row: dict) -> None:
    path = os.environ.get("HARVEY_FAKE_CURSOR_LOG", "")
    if not path:
        return
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(row) + "\n")


def _arg(args: list[str], flag: str) -> str:
    if flag not in args:
        return ""
    index = args.index(flag)
    if index + 1 >= len(args):
        return ""
    return args[index + 1]


def _emit(event: dict) -> None:
    print(json.dumps(event), flush=True)


def main() -> int:
    args = sys.argv[1:]
    key = os.environ.get("CURSOR_API_KEY", "").strip()

    if "--version" in args or "-v" in args:
        _log({"cmd": "version", "argv": args})
        print("2026.10.16-e3cb207")
        return 0

    if "status" in args or "whoami" in args:
        _log({"cmd": "status", "argv": args})
        authed = os.environ.get("HARVEY_FAKE_CURSOR_STATUS", "authenticated")
        if authed == "authenticated":
            print(json.dumps({
                "status": "authenticated",
                "isAuthenticated": True,
                "hasAccessToken": True,
            }))
        else:
            print(json.dumps({
                "status": "unauthenticated",
                "isAuthenticated": False,
            }))
        return 0

    if "models" in args or "--list-models" in args:
        _log({"cmd": "models", "argv": args, "has_api_key": bool(key)})
        models_mode = os.environ.get("HARVEY_FAKE_CURSOR_MODELS", "ok")
        if models_mode == "auth":
            print("Error: Not authenticated. Invalid API key.", file=sys.stderr)
            return 1
        if models_mode == "limit":
            print("You've hit your usage limit.", file=sys.stderr)
            return 1
        print("composer-2.5")
        print("grok-4.7")
        return 0

    stdin_data = b""
    try:
        if not sys.stdin.isatty():
            stdin_data = sys.stdin.buffer.read()
    except Exception:
        stdin_data = b""

    workspace = _arg(args, "--workspace")
    cli_text = ""
    cli_path = os.path.join(workspace, ".cursor", "cli.json") if workspace else ""
    if cli_path and os.path.isfile(cli_path):
        with open(cli_path, encoding="utf-8") as handle:
            cli_text = handle.read()
    config_dir = os.environ.get("CURSOR_CONFIG_DIR", "")
    global_text = ""
    global_path = os.path.join(config_dir, "cli-config.json") if config_dir else ""
    if global_path and os.path.isfile(global_path):
        with open(global_path, encoding="utf-8") as handle:
            global_text = handle.read()
    prompt_args = args[args.index("--") + 1:] if "--" in args else []
    forbidden = [flag for flag in FORBIDDEN if flag in args]
    _log({
        "cmd": "prompt",
        "argv": args,
        "forbidden": forbidden,
        "mode": _arg(args, "--mode"),
        "format": _arg(args, "--output-format"),
        "model": _arg(args, "--model"),
        "trust": "--trust" in args,
        "has_api_key": bool(key),
        "api_key_in_argv": bool(key) and any(key in part for part in args),
        "stdin_len": len(stdin_data),
        "prompt_argc": len(prompt_args),
        "cli_has_shell_deny": "Shell(*)" in cli_text,
        "global_has_shell_deny": "Shell(*)" in global_text,
        "cli_json": cli_text,
        "global_config": global_text,
    })

    if forbidden or "Shell(*)" not in cli_text or "Shell(*)" not in global_text:
        print("missing deny-all config or forbidden flag", file=sys.stderr)
        return 3
    if _arg(args, "--mode") != "ask" or _arg(args, "--output-format") != "stream-json":
        print("ask mode and stream-json are required", file=sys.stderr)
        return 3
    if "-p" not in args and "--print" not in args:
        print("print mode is required", file=sys.stderr)
        return 3

    mode = os.environ.get("HARVEY_FAKE_CURSOR_MODE", "success")
    if mode == "timeout":
        time.sleep(30)
        return 0
    if mode == "auth":
        print("Error: Not authenticated. Run cursor-agent login.", file=sys.stderr)
        return 1
    if mode == "usage_limit":
        print("You've hit your usage limit for this billing period.", file=sys.stderr)
        return 1
    if mode == "mutate":
        with open(os.path.join(workspace, "notes.txt"), "w", encoding="utf-8") as handle:
            handle.write("written without a tool event")

    session_id = "sess-live"
    _emit({
        "type": "system",
        "subtype": "init",
        "model": "composer-2.5",
        "session_id": session_id,
        "permissionMode": "default",
    })
    if mode == "tool_call":
        _emit({
            "type": "tool_call",
            "subtype": "started",
            "call_id": "call-1",
            "tool_call": {"readToolCall": {"args": {"path": "secrets.env"}}},
            "session_id": session_id,
        })
        time.sleep(3)
        marker = os.environ.get("HARVEY_FAKE_CURSOR_MARKER", "")
        if marker:
            with open(marker, "w", encoding="utf-8") as handle:
                handle.write("survived")
        _emit({
            "type": "result",
            "subtype": "success",
            "is_error": False,
            "result": "should-not-return",
            "session_id": session_id,
            "usage": {"inputTokens": 1, "outputTokens": 1, "cacheReadTokens": 0, "cacheWriteTokens": 0},
        })
        return 0

    text = os.environ.get("HARVEY_FAKE_CURSOR_RESULT", "oi")
    _emit({
        "type": "assistant",
        "message": {"role": "assistant", "content": [{"type": "text", "text": text}]},
        "session_id": session_id,
    })
    _emit({
        "type": "result",
        "subtype": "success",
        "is_error": False,
        "duration_ms": 4927,
        "duration_api_ms": 4927,
        "result": text,
        "session_id": session_id,
        "request_id": "req-live",
        "usage": {
            "inputTokens": 8669,
            "outputTokens": 33,
            "cacheReadTokens": 3872,
            "cacheWriteTokens": 0,
        },
    })
    return 0


if __name__ == "__main__":
    sys.exit(main())
