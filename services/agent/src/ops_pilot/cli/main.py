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
from ops_pilot.eval.cli import add_eval_subcommands, run_eval_command
from ops_pilot.health.status import build_runtime_status, health_snapshot
from ops_pilot.models.smoke import smoke_bind_tools, smoke_invoke, smoke_model_invocation
from ops_pilot.tunnel.profile import resolve_tunnel_mcp_spec


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ops_pilot")
    subcommands = parser.add_subparsers(dest="command", required=True)

    subcommands.add_parser("settings", help="Print non-secret resolved settings.")
    subcommands.add_parser("status", help="Build the runtime and print status metadata.")
    subcommands.add_parser("health", help="Print lightweight health metadata without model init.")

    serve = subcommands.add_parser("serve", help="Start the unified backend server.")
    serve.add_argument("--host", default=None)
    serve.add_argument("--port", type=int, default=None)

    tunnel = subcommands.add_parser("tunnel", help="Run local MCP tunnel commands.")
    tunnel_subcommands = tunnel.add_subparsers(dest="tunnel_command", required=True)
    tunnel_run = tunnel_subcommands.add_parser(
        "run",
        help="Connect a local stdio MCP server to the backend through an outbound tunnel.",
    )
    tunnel_run.add_argument("--server-url", default="http://127.0.0.1:8123")
    tunnel_run.add_argument("--tunnel-id", required=True)
    tunnel_run.add_argument("--token", default=None)
    tunnel_run.add_argument("--mcp-command", default=None)
    tunnel_run.add_argument("--mcp-config", default=None)
    tunnel_run.add_argument("--mcp-server", default=None)
    tunnel_run.add_argument("--cwd", default=None)

    smoke = subcommands.add_parser("smoke", help="Run local smoke checks.")
    smoke_subcommands = smoke.add_subparsers(dest="smoke_command", required=True)
    smoke_subcommands.add_parser("model", help="Run SAP model invocation and bind_tools checks.")
    smoke_subcommands.add_parser("agent", help="Build the DeepAgent and invoke a simple prompt.")
    smoke_subcommands.add_parser("a2a", help="Build the A2A agent card and app route table.")

    add_eval_subcommands(subcommands)

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
    if args.command == "tunnel" and args.tunnel_command == "run":
        return _run_server(
            _run_tunnel(
                server_url=args.server_url,
                tunnel_id=args.tunnel_id,
                token=args.token,
                mcp_command=args.mcp_command,
                mcp_config=args.mcp_config,
                mcp_server=args.mcp_server,
                cwd=args.cwd,
            )
        )
    if args.command == "smoke":
        return _smoke(args.smoke_command)
    if args.command == "eval":
        return _run_server(run_eval_command(args))
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
    }
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


async def _print_status() -> int:
    runtime = await create_agent_runtime_async()
    print(json.dumps(build_runtime_status(runtime), indent=2, sort_keys=True))
    return 0


def _serve_backend(host: str | None, port: int | None) -> int:
    from ops_pilot.backend import create_backend_app

    settings = load_settings()
    settings = replace(
        settings,
        chat_host=host or settings.chat_host,
        chat_port=port or settings.chat_port,
    )
    # Build the app on a throwaway loop, then hand the loop and signal handling
    # to uvicorn via the synchronous Server.run(). Uvicorn owns SIGINT through its
    # capture_signals() contextmanager, runs a graceful shutdown, then re-raises
    # the captured signal by design — so KeyboardInterrupt surfaces from run() and
    # we swallow it at this CLI boundary for a clean exit (the same thing uvicorn's
    # own CLI does). Building the app on a separate, short-lived loop is safe: MCP
    # tools open a fresh session per call and the runtime holds no loop-bound state.
    app = asyncio.run(create_backend_app(settings))
    config = uvicorn.Config(app, host=settings.chat_host, port=settings.chat_port, log_level="info")
    try:
        uvicorn.Server(config).run()
    except KeyboardInterrupt:
        pass
    return 0


async def _run_tunnel(
    *,
    server_url: str,
    tunnel_id: str,
    token: str | None,
    mcp_command: str | None,
    mcp_config: str | None,
    mcp_server: str | None,
    cwd: str | None,
) -> int:
    from ops_pilot.tunnel.client import TunnelClientConfig, run_local_tunnel_client

    spec = resolve_tunnel_mcp_spec(
        mcp_command=mcp_command,
        mcp_config=mcp_config,
        mcp_server=mcp_server,
    )
    await run_local_tunnel_client(
        TunnelClientConfig(
            server_url=server_url,
            tunnel_id=tunnel_id,
            token=token,
            mcp_command=spec.command,
            cwd=cwd,
            env=spec.env,
        )
    )
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
