"""LangGraph server export.

``langgraph.json`` points at the ``graph`` object below. Importing this module is
therefore the startup validation point for SAP model discovery, required MCP
servers, skills, checkpointing, and tracing setup.
"""

from __future__ import annotations

from ops_pilot.agent.factory import create_agent_runtime

runtime = create_agent_runtime(attach_checkpointer=False)
agent = runtime.graph
graph = agent
