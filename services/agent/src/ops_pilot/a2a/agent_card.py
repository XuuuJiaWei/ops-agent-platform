"""Agent Card metadata for the A2A surface."""

from __future__ import annotations

from ops_pilot.config.settings import Settings


def build_agent_card(settings: Settings):
    """Return an official A2A AgentCard for public discovery."""

    from a2a.types import (
        AgentCapabilities,
        AgentCard,
        AgentInterface,
        AgentProvider,
        AgentSkill,
    )

    base_url = f"http://{settings.chat_host}:{settings.chat_port}{settings.a2a_base_path}"

    return AgentCard(
        name="ops_pilot",
        description="Local DeepAgents runtime backed by SAP AI Core / Generative AI Hub.",
        provider=AgentProvider(organization="SAP", url="https://www.sap.com"),
        version="0.1.0",
        capabilities=AgentCapabilities(streaming=True, push_notifications=False),
        default_input_modes=["text/plain"],
        default_output_modes=["text/plain", "task-status"],
        skills=[
            AgentSkill(
                id=settings.assistant_id,
                name="Operations assistant",
                description="Answer operations questions and use configured MCP tools.",
                tags=["operations", "sap-ai-core", "deepagents"],
                examples=["Summarize the current Dynatrace problem status."],
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
