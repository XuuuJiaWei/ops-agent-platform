"""Resolve configured local skills into DeepAgents-compatible sources."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import overload

from ops_pilot.config.paths import resolve_path
from ops_pilot.config.settings import Settings
from ops_pilot.skills.validator import validate_skill_paths


@overload
def resolve_skill_paths(settings: Settings) -> list[str]: ...


@overload
def resolve_skill_paths(settings: Iterable[str | Path]) -> tuple[Path, ...]: ...


def resolve_skill_paths(settings: Settings | Iterable[str | Path]) -> list[str] | tuple[Path, ...]:
    """Return normalized skill path strings for ``create_deep_agent``.

    The first version supports only local filesystem paths. Remote registries and
    runtime skill uploads are intentionally out of scope.
    """

    if isinstance(settings, Settings):
        valid_paths = validate_skill_paths(settings.skills_paths)
        return [_normalize(path) for path in valid_paths]
    return validate_skill_paths(tuple(resolve_path(path) for path in settings))


def _normalize(path: Path) -> str:
    return str(path.expanduser().resolve())
