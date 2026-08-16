"""Developer commands over explicitly declared runtime compositions."""

from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import replace
from typing import Any, cast

import uvicorn

from ops_pilot.agent.runtime import build_agent_runtime
from ops_pilot.benchmarks.aiopslab import run_aiopslab_problem
from ops_pilot.entrypoints.benchmark import build_benchmark_runtime_spec
from ops_pilot.entrypoints.eval import build_eval_runtime_spec
from ops_pilot.entrypoints.web import build_web_application_spec
from ops_pilot.health.status import build_runtime_status, health_snapshot
from ops_pilot.mcp.status import MCPLoadStatus
from ops_pilot.models.smoke import smoke_bind_tools, smoke_invoke, smoke_model_invocation
from ops_pilot.runtime.spec import RuntimeSpec
from ops_pilot.tools.smoke_tools import get_smoke_tools


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ops_pilot")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("profiles", help="Print the declared runtime compositions.")

    status = commands.add_parser("status", help="Build one declared runtime and print status metadata.")
    status.add_argument("--entry", choices=("web", "eval", "benchmark"), default="web")

    commands.add_parser("health", help="Print lightweight web-entry health metadata.")
    serve = commands.add_parser("serve", help="Start the web application runtime.")
    serve.add_argument("--host", default=None)
    serve.add_argument("--port", type=int, default=None)

    smoke = commands.add_parser("smoke", help="Run local smoke checks.")
    smoke_subcommands = smoke.add_subparsers(dest="smoke_command", required=True)
    for name in ("model", "agent", "a2a"):
        smoke_subcommands.add_parser(name)

    benchmark = commands.add_parser("benchmark", help="Run the isolated AIOpsLab composition.")
    benchmark.add_argument("--problem", required=True, help="AIOpsLab problem id.")
    benchmark.add_argument("--max-steps", type=int, default=30)

    args = parser.parse_args(argv)
    if args.command == "profiles":
        print(json.dumps({name: _describe_spec(spec) for name, spec in _profiles().items()}, indent=2, sort_keys=True))
        return 0
    if args.command == "status":
        return asyncio.run(_print_status(_profiles()[args.entry]))
    if args.command == "health":
        print(json.dumps(health_snapshot(build_web_application_spec().runtime), indent=2, sort_keys=True))
        return 0
    if args.command == "serve":
        return _serve_web(args.host, args.port)
    if args.command == "smoke":
        return _smoke(args.smoke_command)
    if args.command == "benchmark":
        return asyncio.run(_run_benchmark(args))
    return 2


def _profiles() -> dict[str, RuntimeSpec]:
    return {
        "web": build_web_application_spec().runtime,
        "eval": build_eval_runtime_spec(),
        "benchmark": build_benchmark_runtime_spec(),
    }


def _describe_spec(spec: RuntimeSpec) -> dict[str, Any]:
    return {
        "id": spec.id,
        "assistant_id": spec.assistant_id,
        "entrypoint": spec.entrypoint,
        "model": {"provider": spec.model.provider, "name": spec.model.name},
        "mcp_servers": [server.name for server in spec.mcp.servers],
        "persistence": spec.persistence.backend,
        "sandbox_enabled": spec.sandbox.enabled,
        "extensions": [factory.__name__ for factory in spec.extensions],
    }


async def _print_status(spec: RuntimeSpec) -> int:
    runtime = await build_agent_runtime(spec)
    try:
        print(json.dumps(build_runtime_status(runtime), indent=2, sort_keys=True))
        return 0
    finally:
        await runtime.aclose()


def _serve_web(host: str | None, port: int | None) -> int:
    from ops_pilot.backend import create_backend_app

    application = build_web_application_spec()
    application = replace(application, host=host or application.host, port=port or application.port)
    config = uvicorn.Config(
        create_backend_app(application),
        host=application.host,
        port=application.port,
        log_level="info",
        loop="none",
    )
    try:
        uvicorn.Server(config).run()
    except KeyboardInterrupt:
        pass
    return 0


async def _run_benchmark(args: argparse.Namespace) -> int:
    result = await run_aiopslab_problem(args.problem, max_steps=args.max_steps)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


def _smoke(command: str) -> int:
    spec = build_eval_runtime_spec()
    if command == "model":
        results = [smoke_model_invocation(spec.model), smoke_bind_tools(spec.model)]
        for result in results:
            print(f"{'ok' if result.ok else 'fail'}: {result.name}: {result.detail}")
        return 0 if all(result.ok for result in results) else 1
    if command == "agent":
        return asyncio.run(_smoke_agent(spec))
    if command == "a2a":
        return asyncio.run(_smoke_a2a())
    raise ValueError(f"Unknown smoke command: {command}")


async def _smoke_agent(spec: RuntimeSpec) -> int:
    runtime = await build_agent_runtime(spec.with_tools(get_smoke_tools()))
    try:
        print(
            await runtime.ainvoke_text(
                "Use add_numbers to compute 2 + 3, then reply with the result.",
                protocol="smoke",
                thread_id="smoke-agent",
            )
        )
        return 0
    finally:
        await runtime.aclose()


async def _smoke_a2a() -> int:
    from ops_pilot.backend import create_backend_app

    application = replace(build_web_application_spec(), enable_spaces=False)
    app = create_backend_app(application, runtime=cast(Any, _DummyRuntime(application.runtime)))
    async with app.router.lifespan_context(app):
        print("routes:", ", ".join(sorted(app.openapi().get("paths", {}))))
    return 0


class _DummyRuntime:
    graph = type("SmokeGraph", (), {"nodes": {}})()
    mcp = type("SmokeMCP", (), {"status": MCPLoadStatus(), "tools": (), "hitl_tools": ()})()
    tools = ()
    run_controller = None

    def __init__(self, spec: RuntimeSpec) -> None:
        self.spec = spec

    def runnable_config(self, **_: object) -> dict[str, Any]:
        return {}

    async def ainvoke_text(self, text: str, **_: object) -> str:
        return f"ok: {text}"

    async def cancel_run(self, *_: object, **__: object) -> bool:
        return True

    async def aclose(self) -> None:
        return None


def _smoke_invoke_for_compat() -> str:
    return smoke_invoke(build_eval_runtime_spec().model)


if __name__ == "__main__":
    raise SystemExit(main())
