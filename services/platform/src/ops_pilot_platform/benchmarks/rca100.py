"""OpsPilot's isolated RCA100 JSON-over-stdio adapter."""

import json
import sys
import time
from collections import Counter
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from dataclasses import field as dataclass_field
from hashlib import sha256
from pathlib import Path
from typing import Any, Literal, Self

from deepagents import GeneralPurposeSubagentProfile, HarnessProfile, register_harness_profile
from langchain.agents.middleware import AgentMiddleware, AgentState
from langchain.messages import AIMessage, ToolMessage
from langchain.tools.tool_node import ToolCallRequest
from langchain_core.output_parsers import PydanticOutputParser
from langgraph.runtime import Runtime
from langgraph.types import Command
from ops_pilot.agent.runtime import agent_runtime
from ops_pilot.runtime.spec import RuntimeSpec
from pydantic import BaseModel, ConfigDict, Field, model_validator

from ops_pilot_platform.benchmarks.rca100_tools import RCA100_TOOLS, RCA100Context, RCA100ToolCacheMiddleware
from ops_pilot_platform.entrypoints.benchmark import build_rca100_runtime_spec
from ops_pilot_platform.sre import SREKnowledgeProfile, apply_sre_knowledge

_FILESYSTEM_TOOLS = frozenset({"delete", "edit_file", "execute", "glob", "grep", "ls", "read_file", "write_file"})


@dataclass
class RCABenchmarkTelemetry(AgentMiddleware[AgentState, Any, Any]):
    """Observe benchmark execution through LangChain's middleware seam."""

    model_calls: int = 0
    tool_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    tool_counts: Counter[str] = dataclass_field(default_factory=Counter)
    model_provider: str = ""
    model_name: str = ""
    tool_event_sequence: int = 0
    model_events: list[dict[str, Any]] = dataclass_field(default_factory=list)
    tool_events: list[dict[str, Any]] = dataclass_field(default_factory=list)

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
        input_tokens = int(usage.get("input_tokens", 0) or 0)
        output_tokens = int(usage.get("output_tokens", 0) or 0)
        total_tokens = int(usage.get("total_tokens", 0) or 0)
        self.input_tokens += input_tokens
        self.output_tokens += output_tokens
        self.total_tokens += total_tokens
        self.model_events.append(
            {
                "sequence": self.model_calls,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "total_tokens": total_tokens,
                "tools": tools,
            }
        )
        sys.stderr.write(
            "RCA100_EVENT:"
            + json.dumps(
                {"model_call": self.model_calls, "tools": tools, "total_tokens": self.total_tokens},
                ensure_ascii=False,
            )
            + "\n"
        )
        sys.stderr.flush()

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command[Any]]],
    ) -> ToolMessage | Command[Any]:
        started = time.perf_counter()
        self.tool_event_sequence += 1
        event: dict[str, Any] = {
            "sequence": self.tool_event_sequence,
            "name": str(request.tool_call.get("name", "unknown")),
            "argument_keys": sorted(str(key) for key in (request.tool_call.get("args") or {})),
            "arguments_sha256": _stable_hash(request.tool_call.get("args") or {}),
        }
        try:
            result = await handler(request)
        except Exception as exc:
            event.update(
                {
                    "status": "error",
                    "duration_ms": round((time.perf_counter() - started) * 1000, 3),
                    "error_type": type(exc).__name__,
                }
            )
            self.tool_events.append(event)
            raise

        content = result.content if isinstance(result, ToolMessage) else ""
        rendered = content if isinstance(content, str) else json.dumps(content, ensure_ascii=False, default=str)
        event.update(
            {
                "status": result.status if isinstance(result, ToolMessage) else "command",
                "duration_ms": round((time.perf_counter() - started) * 1000, 3),
                "result_chars": len(rendered),
                "result_sha256": sha256(rendered.encode("utf-8")).hexdigest(),
            }
        )
        self.tool_events.append(event)
        return result

    def snapshot(self) -> dict[str, Any]:
        return {
            "model_calls": self.model_calls,
            "tool_calls": self.tool_calls,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.total_tokens,
            "model": {"provider": self.model_provider, "name": self.model_name},
            "model_events": self.model_events,
            "tool_events": self.tool_events,
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

    source_type: Literal["metric", "log", "trace", "event", "alert", "topology"]
    signal: str = Field(description="Exact observability signal name, without an entity-name prefix.")
    comparator: str = Field(min_length=1, description="Comparator reported by the observation.")
    value: float
    unit: str = Field(default="", description="Unit reported by the observation tool; preserve it exactly.")


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

    root_cause_entities: list[str] = Field(
        default_factory=list,
        description=(
            "Minimal canonical root entities; omit downstream operations once their root service is identified."
        ),
    )
    root_cause_types: list[str] = Field(
        default_factory=list,
        description="Canonical lowerCamelCase fault category identifiers, not free-form explanations.",
    )
    reasoning: list[IncidentReasoningStep] = Field(default_factory=list)


def build_rca100_agent_spec(
    *,
    knowledge_profile: SREKnowledgeProfile = "context-v1",
    telemetry: RCABenchmarkTelemetry | None = None,
) -> RuntimeSpec:
    """Contribute RCA100 policy through the runtime's official injection fields."""

    base_spec = build_rca100_runtime_spec(
        tools=RCA100_TOOLS,
        context_schema=RCA100Context,
    )
    spec = replace(
        base_spec,
        filesystem_tools=None,
        middleware=(
            *base_spec.middleware,
            RCA100ToolCacheMiddleware(),
            *((telemetry,) if telemetry is not None else ()),
        ),
    )
    return apply_sre_knowledge(spec, knowledge_profile)


async def run_rca100_agent(knowledge_profile: SREKnowledgeProfile = "context-v1") -> None:
    """Read one blind request from stdin and emit only the agent prediction."""

    request = RCA100Request.model_validate_json(sys.stdin.read())
    telemetry = RCABenchmarkTelemetry()
    spec = build_rca100_agent_spec(knowledge_profile=knowledge_profile, telemetry=telemetry)
    telemetry.model_provider = spec.model.provider
    telemetry.model_name = spec.model.name
    _configure_isolated_harness(spec, knowledge_profile=knowledge_profile)
    try:
        async with agent_runtime(spec) as runtime:
            prediction = await runtime.ainvoke_text(
                _diagnosis_prompt(request),
                protocol="benchmark:rca100",
                thread_id=f"rca100:{request.task_id}",
                run_id=f"rca100:{request.task_id}",
                context=RCA100Context(case_directory=request.case_directory),
                extra_metadata={
                    "benchmark": "rca100",
                    "task_id": request.task_id,
                    "sre_knowledge_profile": knowledge_profile,
                },
            )
            diagnosis = PydanticOutputParser(pydantic_object=IncidentDiagnosis).parse(prediction)
            sys.stdout.write(diagnosis.model_dump_json())
    finally:
        sys.stderr.write("RCA100_METRICS:" + json.dumps(telemetry.snapshot(), ensure_ascii=False) + "\n")


def _configure_isolated_harness(spec: RuntimeSpec, *, knowledge_profile: SREKnowledgeProfile) -> None:
    """Configure the official process-wide harness profile for this worker."""

    provider = "openai" if spec.model.provider == "deepseek" else spec.model.provider
    register_harness_profile(
        f"{provider}:{spec.model.name}",
        HarnessProfile(
            excluded_tools=(
                _FILESYSTEM_TOOLS if knowledge_profile == "baseline" else _FILESYSTEM_TOOLS - {"read_file"}
            ),
            general_purpose_subagent=GeneralPurposeSubagentProfile(enabled=False),
        ),
    )


def _stable_hash(value: Any) -> str:
    rendered = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return sha256(rendered.encode("utf-8")).hexdigest()


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
