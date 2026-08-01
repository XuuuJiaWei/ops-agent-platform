"""Developer command line interface."""

from __future__ import annotations

import argparse
import asyncio
import json
from collections.abc import Sequence
from dataclasses import replace
from typing import Any

import uvicorn

from ops_pilot.agent.factory import create_agent_runtime_async
from ops_pilot.config.settings import load_settings
from ops_pilot.health.status import build_runtime_status, health_snapshot
from ops_pilot.models.smoke import smoke_bind_tools, smoke_invoke, smoke_model_invocation


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ops_pilot")
    subcommands = parser.add_subparsers(dest="command", required=True)

    subcommands.add_parser("settings", help="Print non-secret resolved settings.")
    subcommands.add_parser("status", help="Build the runtime and print status metadata.")
    subcommands.add_parser("health", help="Print lightweight health metadata without model init.")

    a2a = subcommands.add_parser("a2a", help="Run A2A protocol commands.")
    a2a_subcommands = a2a.add_subparsers(dest="a2a_command", required=True)
    a2a_serve = a2a_subcommands.add_parser("serve", help="Start the local A2A server.")
    a2a_serve.add_argument("--host", default=None)
    a2a_serve.add_argument("--port", type=int, default=None)

    chat = subcommands.add_parser("chat", help="Run CopilotKit/AG-UI chat protocol commands.")
    chat_subcommands = chat.add_subparsers(dest="chat_command", required=True)
    chat_serve = chat_subcommands.add_parser("serve", help="Start the local AG-UI chat server.")
    chat_serve.add_argument("--host", default=None)
    chat_serve.add_argument("--port", type=int, default=None)

    smoke = subcommands.add_parser("smoke", help="Run local smoke checks.")
    smoke_subcommands = smoke.add_subparsers(dest="smoke_command", required=True)
    smoke_subcommands.add_parser("model", help="Run SAP model invocation and bind_tools checks.")
    smoke_subcommands.add_parser("agent", help="Build the DeepAgent and invoke a simple prompt.")
    smoke_subcommands.add_parser("a2a", help="Build the A2A agent card and app route table.")

    args = parser.parse_args(argv)
    if args.command == "settings":
        return _print_settings()
    if args.command == "status":
        return asyncio.run(_print_status())
    if args.command == "health":
        print(json.dumps(health_snapshot(load_settings()), indent=2, sort_keys=True))
        return 0
    if args.command == "a2a" and args.a2a_command == "serve":
        return _run_server(_serve_a2a(args.host, args.port))
    if args.command == "chat" and args.chat_command == "serve":
        return _run_server(_serve_chat(args.host, args.port))
    if args.command == "smoke":
        return _smoke(args.smoke_command)
    return 2


def _run_server(coro: Any) -> int:
    try:
        return asyncio.run(coro)
    except KeyboardInterrupt:
        return 0


def _print_settings() -> int:
    settings = load_settings()
    payload = {
        "app_env": settings.app_env,
        "assistant_id": settings.assistant_id,
        "sap_max_tokens": settings.sap_max_tokens,
        "sap_model_name": settings.sap_model_name,
        "system_prompt_configured": bool(settings.system_prompt),
        "mcp_config_path": str(settings.mcp_config_path) if settings.mcp_config_path else None,
        "skills_paths": [str(path) for path in settings.skills_paths],
        "enable_smoke_tools": settings.enable_smoke_tools,
        "langfuse_enabled": settings.langfuse_enabled,
        "chat_base_path": settings.chat_base_path,
        "chat_host": settings.chat_host,
        "chat_port": settings.chat_port,
        "a2a_base_path": settings.a2a_base_path,
        "a2a_task_store": settings.a2a_task_store,
    }
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


async def _print_status() -> int:
    runtime = await create_agent_runtime_async()
    print(json.dumps(build_runtime_status(runtime), indent=2, sort_keys=True))
    return 0


async def _serve_a2a(host: str | None, port: int | None) -> int:
    from ops_pilot.a2a.app import create_a2a_app

    settings = load_settings()
    settings = replace(
        settings,
        a2a_host=host or settings.a2a_host,
        a2a_port=port or settings.a2a_port,
    )
    app = await create_a2a_app(settings)
    config = uvicorn.Config(app, host=settings.a2a_host, port=settings.a2a_port, log_level="info")
    server = uvicorn.Server(config)
    try:
        await server.serve()
    except KeyboardInterrupt:
        return 0
    return 0


async def _serve_chat(host: str | None, port: int | None) -> int:
    from ops_pilot.agui.app import create_agui_app

    settings = load_settings()
    settings = replace(
        settings,
        chat_host=host or settings.chat_host,
        chat_port=port or settings.chat_port,
        chat_base_path="/",
    )
    app = await create_agui_app(settings)
    config = uvicorn.Config(app, host=settings.chat_host, port=settings.chat_port, log_level="info")
    server = uvicorn.Server(config)
    try:
        await server.serve()
    except KeyboardInterrupt:
        return 0
    return 0


def _smoke(command: str) -> int:
    if command == "model":
        return _smoke_model()
    if command == "agent":
        return asyncio.run(_smoke_agent())
    if command == "a2a":
        return asyncio.run(_smoke_a2a())
    raise ValueError(f"Unknown smoke command: {command}")


def _smoke_model() -> int:
    results = [smoke_model_invocation(), smoke_bind_tools()]
    for result in results:
        prefix = "ok" if result.ok else "fail"
        print(f"{prefix}: {result.name}: {result.detail}")
    return 0 if all(result.ok for result in results) else 1


async def _smoke_agent() -> int:
    runtime = await create_agent_runtime_async()
    response = await runtime.ainvoke_text(
        "Reply with OK.",
        protocol="smoke",
        thread_id="smoke-agent",
    )
    print(response)
    return 0


async def _smoke_a2a() -> int:
    from ops_pilot.a2a.agent_card import build_agent_card
    from ops_pilot.a2a.app import create_a2a_app

    settings = load_settings()
    card = build_agent_card(settings)
    print(card)
    app = await create_a2a_app(settings, runtime=_DummyRuntime())
    print("routes:", ", ".join(_route_paths(app)))
    return 0


def _smoke_invoke_for_compat() -> str:
    return smoke_invoke(load_settings())


class _DummyRuntime:
    async def ainvoke_text(self, text: str, **_: object) -> str:
        return f"ok: {text}"


def _route_paths(app) -> list[str]:
    return sorted({path for route in app.routes if (path := getattr(route, "path", None))})


if __name__ == "__main__":
    raise SystemExit(main())
