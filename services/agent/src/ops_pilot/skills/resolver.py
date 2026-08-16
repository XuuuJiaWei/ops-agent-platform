"""Resolve configured local skills into DeepAgents-compatible sources."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from ops_pilot.config.paths import resolve_path
from ops_pilot.skills.validator import validate_skill_paths


def resolve_skill_paths(paths: Iterable[str | Path]) -> tuple[Path, ...]:
    """Return normalized skill path strings for ``create_deep_agent``.

    The first version supports only local filesystem paths. Remote registries and
    runtime skill uploads are intentionally out of scope.
    """

    return validate_skill_paths(tuple(resolve_path(path) for path in paths))


def _normalize(path: Path) -> str:
    return str(path.expanduser().resolve())
