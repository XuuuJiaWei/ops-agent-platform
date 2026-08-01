"""Future-facing custom subagent configuration shape."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ops_pilot.config.paths import resolve_repo_path


class SubagentConfigError(ValueError):
    """Raised when future subagent config is malformed."""


@dataclass(frozen=True)
class SubagentConfig:
    name: str
    description: str
    system_prompt: str | None = None
    tools: tuple[str, ...] = field(default_factory=tuple)
    skills: tuple[str, ...] = field(default_factory=tuple)
    model: str | None = None

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> SubagentConfig:
        try:
            name = _required_string(data, "name")
            description = _required_string(data, "description")
        except KeyError as exc:
            raise SubagentConfigError(f"Subagent is missing required field: {exc.args[0]}") from exc

        return cls(
            name=name,
            description=description,
            system_prompt=_optional_string(data.get("system_prompt")),
            tools=_string_tuple(data.get("tools", ()), "tools"),
            skills=_string_tuple(data.get("skills", ()), "skills"),
            model=_optional_string(data.get("model")),
        )


@dataclass(frozen=True)
class SubagentsConfig:
    subagents: tuple[SubagentConfig, ...] = field(default_factory=tuple)

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> SubagentsConfig:
        raw_subagents = data.get("subagents", [])
        if not isinstance(raw_subagents, list):
            raise SubagentConfigError("Subagents config field 'subagents' must be a list.")
        return cls(tuple(SubagentConfig.from_mapping(item) for item in raw_subagents))

    @classmethod
    def load(cls, path: Path) -> SubagentsConfig:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise SubagentConfigError(f"Subagents config file not found: {path}") from exc
        except json.JSONDecodeError as exc:
            message = f"Subagents config file is not valid JSON: {path}: {exc}"
            raise SubagentConfigError(message) from exc
        if not isinstance(data, Mapping):
            raise SubagentConfigError("Subagents config root must be a JSON object.")
        return cls.from_mapping(data)

    @classmethod
    def from_file(cls, path_value: str | Path | None) -> SubagentsConfig:
        path = resolve_repo_path(path_value)
        if path is None or not path.exists():
            return cls()
        return cls.load(path)


def _required_string(data: Mapping[str, Any], key: str) -> str:
    value = data[key]
    if not isinstance(value, str) or not value.strip():
        raise SubagentConfigError(f"Subagent field '{key}' must be a non-empty string.")
    return value


def _optional_string(value: Any) -> str | None:
    if value in (None, ""):
        return None
    if not isinstance(value, str):
        raise SubagentConfigError("Optional subagent value must be a string.")
    return value


def _string_tuple(value: Any, field_name: str) -> tuple[str, ...]:
    if value in (None, ""):
        return ()
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise SubagentConfigError(f"Subagent field '{field_name}' must be a list of strings.")
    return tuple(value)
