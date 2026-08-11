"""Environment-variable interpolation for regular configuration values.

Config files reference secrets and deployment-specific values from the process
environment with ``${VAR}`` placeholders. Interpolation is deliberately scoped
to a whitelist of *data* fields (MCP server ``url``/``headers``/``env`` values
and ``open_sandbox.domain``); process-spec fields (``command``/``args``/
``cwd``) are never expanded so config cannot mutate process launch semantics.

``env`` is always passed in rather than read from ``os.environ`` directly, so
callers (and tests) control the source deterministically.
"""

from __future__ import annotations

import re
from collections.abc import Mapping

# ``$$`` escapes a literal ``$``; ``${VAR}`` references an env var. The escape
# alternative comes first so it wins over the placeholder form.
ENV_PATTERN = re.compile(r"\$\$|\$\{([A-Z0-9_]+)\}")


class MissingEnvironmentError(RuntimeError):
    """Raised when a whitelisted field references an unset/empty env var."""

    def __init__(self, missing: tuple[str, ...]) -> None:
        self.missing = missing
        variables = ", ".join(missing)
        super().__init__(f"Missing environment variable(s) referenced by config: {variables}")


def expand_value(value: str, env: Mapping[str, str]) -> str:
    """Expand ``${VAR}`` placeholders in one string against ``env``.

    ``$$`` becomes a literal ``$``. An unset or empty-string variable counts as
    missing and raises :class:`MissingEnvironmentError` listing every offender.
    """

    missing: set[str] = set()

    def replace_match(match: re.Match[str]) -> str:
        if match.group(0) == "$$":
            return "$"
        name = match.group(1)
        resolved = env.get(name)
        if resolved in (None, ""):
            missing.add(name)
            return match.group(0)
        return resolved

    expanded = ENV_PATTERN.sub(replace_match, value)
    if missing:
        raise MissingEnvironmentError(tuple(sorted(missing)))
    return expanded


def expand_mapping(values: Mapping[str, str], env: Mapping[str, str]) -> dict[str, str]:
    """Expand every value of a ``str -> str`` mapping (headers/env blocks)."""

    return {key: expand_value(value, env) for key, value in values.items()}


def expand_optional(value: str | None, env: Mapping[str, str]) -> str | None:
    """Expand a value that may be absent; ``None``/``""`` pass through untouched."""

    if value in (None, ""):
        return value
    return expand_value(value, env)
