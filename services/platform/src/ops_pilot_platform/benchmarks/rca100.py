"""OpsPilot's isolated RCA100 JSON-over-stdio adapter."""

import json
import sys
from collections import Counter
from dataclasses import dataclass, replace
from dataclasses import field as dataclass_field
from pathlib import Path
from typing import Any, Literal, Self

from deepagents import GeneralPurposeSubagentProfile, HarnessProfile, register_harness_profile
from langchain.agents.middleware import AgentMiddleware, AgentState
from langchain.messages import AIMessage
from langchain_core.output_parsers import PydanticOutputParser
from langgraph.runtime import Runtime
from ops_pilot.agent.runtime import agent_runtime
from ops_pilot.runtime.spec import RuntimeSpec
from pydantic import BaseModel, ConfigDict, Field, model_validator

from ops_pilot_platform.benchmarks.rca100_tools import RCA100_TOOLS, RCA100Context, RCA100ToolCacheMiddleware
from ops_pilot_platform.entrypoints.benchmark import build_rca100_runtime_spec

_FILESYSTEM_TOOLS = frozenset({"delete", "edit_file", "execute", "glob", "grep", "ls", "read_file", "write_file"})


class RCAToolFilterMiddleware(AgentMiddleware):
    """Hide DeepAgents filesystem scaffolding from this observation-only worker."""

    async def awrap_model_call(self, request: Any, handler: Any) -> Any:
        tools = [tool for tool in request.tools if _tool_name(tool) not in _FILESYSTEM_TOOLS]
        return await handler(request.override(tools=tools))


@dataclass
class RCABenchmarkTelemetry(AgentMiddleware[AgentState, Any, Any]):
    """Observe benchmark execution through LangChain's middleware seam."""

    model_calls: int = 0
    tool_calls: int = 0
    total_tokens: int = 0
    tool_counts: Counter[str] = dataclass_field(default_factory=Counter)

    def after_model(self, state: AgentState, runtime: Runtime[Any]) -> None:
        del runtime
        message = state["messages"][-1]
        if not isinstance(message, AIMessage):
            return
        self.model_calls += 1
        tools = [str(call.get("name", "unknown")) for call in message.tool_calls]
        self.tool_calls += len(tools)
        self.tool_counts.update(tools)
        usage = message.usage_metadata or {}
        self.total_tokens += int(usage.get("total_tokens", 0) or 0)
        sys.stderr.write(
            "RCA100_EVENT:"
            + json.dumps(
                {"model_call": self.model_calls, "tools": tools, "total_tokens": self.total_tokens},
                ensure_ascii=False,
            )
            + "\n"
        )
        sys.stderr.flush()

    def snapshot(self) -> dict[str, Any]:
        return {
            "model_calls": self.model_calls,
            "tool_calls": self.tool_calls,
            "total_tokens": self.total_tokens,
            "tools": dict(sorted(self.tool_counts.items())),
        }


class RCA100Request(BaseModel):
    """Public request sent by the framework-neutral RCA100 runner."""

    model_config = ConfigDict(extra="forbid")

    benchmark: Literal["rca100"]
    task_id: str
    task: dict[str, Any]
    case_directory: Path
    parquet_schemas: dict[str, list[str]]
    topology_path: Path
    prediction_schema: dict[str, Any]

    @model_validator(mode="after")
    def validate_case_paths(self) -> Self:
        case_directory = self.case_directory.resolve()
        topology_path = self.topology_path.resolve()
        if topology_path != case_directory / "topology.json":
            raise ValueError("topology_path must point to topology.json inside case_directory.")
        if not case_directory.is_dir() or not topology_path.is_file():
            raise ValueError("RCA100 public case files are unavailable.")
        self.case_directory = case_directory
        self.topology_path = topology_path
        return self


class IncidentEvidence(BaseModel):
    """One numeric or directly observable checkpoint supporting a diagnosis."""

    model_config = ConfigDict(extra="forbid")

    source_type: str
    signal: str
    comparator: str
    value: float
    unit: str = ""


class IncidentReasoningStep(BaseModel):
    """One causal step from origin through propagation to impact."""

    model_config = ConfigDict(extra="forbid")

    step_type: Literal["cause", "propagation", "impact"]
    target: str
    fault_type: str
    evidence: list[IncidentEvidence] = Field(default_factory=list)


class IncidentDiagnosis(BaseModel):
    """Structured diagnosis of a production incident."""

    model_config = ConfigDict(extra="forbid")

    root_cause_entities: list[str] = Field(default_factory=list)
    root_cause_types: list[str] = Field(default_factory=list)
    reasoning: list[IncidentReasoningStep] = Field(default_factory=list)


def build_rca100_agent_spec(
    *,
    telemetry: RCABenchmarkTelemetry | None = None,
) -> RuntimeSpec:
    """Contribute RCA100 policy through the runtime's official injection fields."""

    base_spec = build_rca100_runtime_spec(
        tools=RCA100_TOOLS,
        context_schema=RCA100Context,
    )
    return replace(
        base_spec,
        skills=(),
        memory=(),
        permissions=(),
        filesystem_tools=None,
        middleware=(
            *base_spec.middleware,
            RCAToolFilterMiddleware(),
            RCA100ToolCacheMiddleware(),
            *((telemetry,) if telemetry is not None else ()),
        ),
    )


async def run_rca100_agent() -> None:
    """Read one blind request from stdin and emit only the agent prediction."""

    request = RCA100Request.model_validate_json(sys.stdin.read())
    telemetry = RCABenchmarkTelemetry()
    spec = build_rca100_agent_spec(telemetry=telemetry)
    _configure_isolated_harness(spec)
    try:
        async with agent_runtime(spec) as runtime:
            prediction = await runtime.ainvoke_text(
                _diagnosis_prompt(request),
                protocol="benchmark:rca100",
                thread_id=f"rca100:{request.task_id}",
                run_id=f"rca100:{request.task_id}",
                context=RCA100Context(case_directory=request.case_directory),
                extra_metadata={"benchmark": "rca100", "task_id": request.task_id},
            )
            diagnosis = PydanticOutputParser(pydantic_object=IncidentDiagnosis).parse(prediction)
            sys.stdout.write(diagnosis.model_dump_json())
    finally:
        sys.stderr.write("RCA100_METRICS:" + json.dumps(telemetry.snapshot(), ensure_ascii=False) + "\n")


def _configure_isolated_harness(spec: RuntimeSpec) -> None:
    """Configure the official process-wide harness profile for this worker."""

    provider = "openai" if spec.model.provider == "deepseek" else spec.model.provider
    register_harness_profile(
        f"{provider}:{spec.model.name}",
        HarnessProfile(
            general_purpose_subagent=GeneralPurposeSubagentProfile(enabled=False),
        ),
    )


def _tool_name(tool: Any) -> str:
    if isinstance(tool, dict):
        return str(tool.get("name", ""))
    return str(getattr(tool, "name", ""))


def _diagnosis_prompt(request: RCA100Request) -> str:
    incident = {
        key: request.task[key]
        for key in (
            "alert_title",
            "alert_trigger_time",
            "alert_window",
            "alert_entity",
            "region_id",
            "alert_event_id",
            "alert_trans_id",
        )
        if request.task.get(key) not in (None, "", {}, [])
    }
    return f"""Investigate this production incident.

Incident context:
{json.dumps(incident, ensure_ascii=False)}

Available observation fields:
{json.dumps(request.parquet_schemas, ensure_ascii=False)}

Use query_metric, query_logs, and query_traces for the three primary
modalities. Use query_events, query_alerts, and query_topology for supporting
causal evidence. Return exactly one JSON object matching this schema, without
Markdown or commentary:
{json.dumps(IncidentDiagnosis.model_json_schema(), ensure_ascii=False)}
"""
