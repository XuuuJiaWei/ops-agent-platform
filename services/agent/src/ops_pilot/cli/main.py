"""Developer command line interface."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections.abc import Sequence
from dataclasses import replace
from typing import Any

import uvicorn

from ops_pilot.agent.runtime import build_agent_runtime
from ops_pilot.config.mcp_schema import MCPConfig
from ops_pilot.config.settings import load_settings
from ops_pilot.eval.cli import add_chaos_subcommands, add_eval_subcommands, run_chaos_command, run_eval_command
from ops_pilot.health.status import build_runtime_status, health_snapshot
from ops_pilot.mcp.status import MCPLoadStatus
from ops_pilot.models.smoke import smoke_bind_tools, smoke_invoke, smoke_model_invocation
from ops_pilot.spaces import MemorySpaceRepository
from ops_pilot.tools.smoke_tools import get_smoke_tools


def main(argv: Sequence[str] | None = None) -> int:
    _configure_event_loop_policy()
    parser = argparse.ArgumentParser(prog="ops_pilot")
    subcommands = parser.add_subparsers(dest="command", required=True)

    subcommands.add_parser("settings", help="Print non-secret resolved settings.")
    subcommands.add_parser("status", help="Build the runtime and print status metadata.")
    subcommands.add_parser("health", help="Print lightweight health metadata without model init.")

    serve = subcommands.add_parser("serve", help="Start the unified backend server.")
    serve.add_argument("--host", default=None)
    serve.add_argument("--port", type=int, default=None)

    smoke = subcommands.add_parser("smoke", help="Run local smoke checks.")
    smoke_subcommands = smoke.add_subparsers(dest="smoke_command", required=True)
    smoke_subcommands.add_parser("model", help="Run SAP model invocation and bind_tools checks.")
    smoke_subcommands.add_parser("agent", help="Build the DeepAgent and invoke a simple prompt.")
    smoke_subcommands.add_parser("a2a", help="Build the A2A agent card and app route table.")

    add_eval_subcommands(subcommands)
    add_chaos_subcommands(subcommands)

    args = parser.parse_args(argv)
    if args.command == "settings":
        return _print_settings()
    if args.command == "status":
        return asyncio.run(_print_status())
    if args.command == "health":
        print(json.dumps(health_snapshot(load_settings()), indent=2, sort_keys=True))
        return 0
    if args.command == "serve":
        return _serve_backend(args.host, args.port)
    if args.command == "smoke":
        return _smoke(args.smoke_command)
    if args.command == "eval":
        return _run_server(run_eval_command(args))
    if args.command == "chaos":
        return _run_server(run_chaos_command(args))
    return 2


def _configure_event_loop_policy() -> None:
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


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
        "mcp_servers": [server.name for server in settings.mcp.servers],
        "mcp_hitl_tools": sorted(settings.mcp.hitl_tool_names()),
        "skills_paths": [str(path) for path in settings.skills_paths],
        "langfuse_enabled": settings.langfuse_enabled,
        "chat_base_path": settings.chat_base_path,
        "chat_host": settings.chat_host,
        "chat_port": settings.chat_port,
        "a2a_base_path": settings.a2a_base_path,
        "persistence_backend": settings.persistence_backend,
        "persistence_setup_on_start": settings.persistence_setup_on_start,
    }
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


async def _print_status() -> int:
    runtime = await build_agent_runtime()
    try:
        print(json.dumps(build_runtime_status(runtime), indent=2, sort_keys=True))
        return 0
    finally:
        await runtime.aclose()


def _serve_backend(host: str | None, port: int | None) -> int:
    from ops_pilot.backend import create_backend_app

    settings = load_settings()
    settings = replace(
        settings,
        chat_host=host or settings.chat_host,
        chat_port=port or settings.chat_port,
    )
    # Runtime-owned resources such as MCP stdio sessions and sandboxes are
    # created by the app lifespan inside uvicorn's event loop and cleaned up
    # from the same loop.
    # Uvicorn owns SIGINT through its capture_signals() contextmanager, runs a
    # graceful shutdown, then re-raises the captured signal by design — so
    # KeyboardInterrupt surfaces from run() and we swallow it at this CLI boundary
    # for a clean exit (the same thing uvicorn's own CLI does).
    app = create_backend_app(settings)
    config = uvicorn.Config(app, host=settings.chat_host, port=settings.chat_port, log_level="info", loop="none")
    try:
        uvicorn.Server(config).run()
    except KeyboardInterrupt:
        pass
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
    settings = replace(load_settings(), mcp=MCPConfig())
    runtime = await build_agent_runtime(settings=settings, extra_tools=get_smoke_tools())
    try:
        response = await runtime.ainvoke_text(
            "Use add_numbers to compute 2 + 3, then reply with the result.",
            protocol="smoke",
            thread_id="smoke-agent",
        )
        print(response)
        return 0
    finally:
        await runtime.aclose()


async def _smoke_a2a() -> int:
    from ops_pilot.a2a.agent_card import build_agent_card
    from ops_pilot.backend import create_backend_app

    settings = replace(
        load_settings(),
        persistence_backend="memory",
        spaces_resolver_enabled=False,
    )
    card = build_agent_card(settings)
    print(card)
    app = create_backend_app(settings, runtime=_DummyRuntime())
    async with app.router.lifespan_context(app):
        print("routes:", ", ".join(_route_paths(app)))
    return 0


def _smoke_invoke_for_compat() -> str:
    return smoke_invoke(load_settings())


class _DummyRuntime:
    graph = type("SmokeGraph", (), {"nodes": {}})()
    mcp = type("SmokeMCP", (), {"status": MCPLoadStatus(), "tools": (), "hitl_tools": ()})()
    spaces = MemorySpaceRepository()
    run_controller = None

    def runnable_config(self, **_: object) -> dict:
        return {}

    async def ainvoke_text(self, text: str, **_: object) -> str:
        return f"ok: {text}"

    async def cancel_run(self, *_: object, **__: object) -> bool:
        return True

    async def aclose(self) -> None:
        return None


def _route_paths(app) -> list[str]:
    return sorted(app.openapi().get("paths", {}))


if __name__ == "__main__":
    raise SystemExit(main())
