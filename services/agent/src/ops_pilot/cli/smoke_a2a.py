"""CLI entry point for the A2A protocol wiring smoke path."""

from __future__ import annotations

from ops_pilot.a2a.agent_card import build_agent_card
from ops_pilot.a2a.app import create_a2a_app
from ops_pilot.config.settings import load_settings


async def run() -> int:
    settings = load_settings()
    print(build_agent_card(settings))
    app = await create_a2a_app(settings, runtime=_DummyRuntime())
    print("routes:", ", ".join(_route_paths(app)))
    return 0


class _DummyRuntime:
    async def ainvoke_text(self, text: str, **_: object) -> str:
        return f"ok: {text}"


def _route_paths(app) -> list[str]:
    return sorted({path for route in app.routes if (path := getattr(route, "path", None))})


def main() -> int:
    import asyncio

    return asyncio.run(run())


if __name__ == "__main__":
    raise SystemExit(main())
