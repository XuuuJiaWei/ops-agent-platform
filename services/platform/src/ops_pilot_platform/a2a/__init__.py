"""A2A adapter package.

Keep package imports lightweight so unit tests and local utilities can import
the agent card without constructing the shared DeepAgent runtime.
"""

from ops_pilot_platform.a2a.agent_card import build_agent_card

__all__ = ["build_agent_card"]
