"""Local-only tools for harness smoke checks."""

from __future__ import annotations

from langchain_core.tools import tool


@tool
def local_echo(text: str) -> str:
    """Echo text for local smoke testing."""
    return text


@tool
def add_numbers(left: int, right: int) -> int:
    """Add two integers for local DeepAgent tool-call smoke testing."""
    return left + right


def get_smoke_tools():
    """Return local-only tools used by smoke checks and first-run validation."""

    return [local_echo, add_numbers]
