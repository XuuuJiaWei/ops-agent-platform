"""Shared test helpers for the unit suite."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pytest

from ops_pilot.config.settings import Settings, load_settings


def build_settings(
    *,
    config: Mapping[str, Any] | None = None,
    env: Mapping[str, str] | None = None,
) -> Settings:
    """Build Settings from an in-memory config mapping, never touching disk.

    ``config`` is the nested regular-config mapping (YAML shape); ``env`` holds
    secret overrides. Passing ``config`` (even empty) skips the config-file read.
    """

    return load_settings(env=env or {}, config=config or {})


@pytest.fixture
def make_settings():
    """Factory fixture returning :func:`build_settings`."""

    return build_settings
