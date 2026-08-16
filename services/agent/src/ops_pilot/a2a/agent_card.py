"""Agent Card metadata for the A2A surface."""

from __future__ import annotations


def build_agent_card(*, assistant_id: str, host: str, port: int, a2a_base_path: str):
    """Return an official A2A AgentCard for public discovery."""

    from a2a.types import (
        AgentCapabilities,
        AgentCard,
        AgentInterface,
        AgentProvider,
        AgentSkill,
    )

    base_url = f"http://{host}:{port}{a2a_base_path}"

    return AgentCard(
        name="ops_pilot",
        description="Local DeepAgents runtime backed by SAP AI Core / Generative AI Hub.",
        provider=AgentProvider(
            organization="ops_pilot contributors",
            url="https://github.com/XuuuJiaWei/ops-agent-platform",
        ),
        version="0.1.0",
        capabilities=AgentCapabilities(streaming=True, push_notifications=False),
        default_input_modes=["text/plain"],
        default_output_modes=["text/plain", "task-status"],
        skills=[
            AgentSkill(
                id=assistant_id,
                name="Operations assistant",
                description="Answer operations questions and use configured MCP tools.",
                tags=["operations", "sap-ai-core", "deepagents"],
                examples=["Summarize the current production incident status."],
                input_modes=["text/plain"],
                output_modes=["text/plain", "task-status"],
            )
        ],
        supported_interfaces=[
            AgentInterface(
                protocol_binding="JSONRPC",
                protocol_version="1.0",
                url=f"{base_url}/jsonrpc",
            )
        ],
    )
