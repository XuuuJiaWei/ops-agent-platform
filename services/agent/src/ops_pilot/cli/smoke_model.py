"""CLI entry point for SAP model smoke checks."""

from __future__ import annotations

from ops_pilot.models.smoke import smoke_bind_tools, smoke_model_invocation


def main() -> int:
    results = [smoke_model_invocation(), smoke_bind_tools()]
    for result in results:
        prefix = "ok" if result.ok else "fail"
        print(f"{prefix}: {result.name}: {result.detail}")
    return 0 if all(result.ok for result in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())

