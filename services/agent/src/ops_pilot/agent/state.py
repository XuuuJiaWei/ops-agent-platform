"""Shared state typing for the DeepAgent graph.

The first version relies on DeepAgents' built-in state schema. This module is a
placeholder for future typed state extensions without forcing custom state into
the initial graph.
"""

from __future__ import annotations

from typing import Any, TypedDict


class MessageInput(TypedDict, total=False):
    messages: list[Any]

