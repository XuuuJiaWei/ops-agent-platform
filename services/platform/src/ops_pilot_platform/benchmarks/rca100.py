"""OpsPilot's isolated RCA100 JSON-over-stdio adapter."""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any, Literal

import pyarrow.dataset as arrow_dataset
from langchain.tools import ToolRuntime, tool
from ops_pilot.agent.runtime import build_agent_runtime
from pydantic import BaseModel, ConfigDict, Field, model_validator

from ops_pilot_platform.entrypoints.benchmark import build_rca100_runtime_spec

RCA100Source = Literal["metrics", "logs", "traces", "events", "alerts", "topology"]
RCA100Operator = Literal["==", "!=", "<", "<=", ">", ">="]


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
    def validate_case_paths(self) -> RCA100Request:
        case_directory = self.case_directory.resolve()
        topology_path = self.topology_path.resolve()
        if topology_path != case_directory / "topology.json":
            raise ValueError("topology_path must point to topology.json inside case_directory.")
        if not case_directory.is_dir() or not topology_path.is_file():
            raise ValueError("RCA100 public case files are unavailable.")
        self.case_directory = case_directory
        self.topology_path = topology_path
        return self


class RCA100Filter(BaseModel):
    """One predicate pushed into PyArrow's Parquet scanner."""

    model_config = ConfigDict(extra="forbid")

    column: str
    operator: RCA100Operator
    value: str | int | float | bool | None


@dataclass(frozen=True)
class RCA100Context:
    """Per-run dependency hidden from the model-visible tool schema."""

    case_directory: Path


@tool
def query_rca_case(
    source: RCA100Source,
    runtime: ToolRuntime[RCA100Context],
    columns: list[str] | None = None,
    filters: list[RCA100Filter] | None = None,
    limit: Annotated[int, Field(ge=1, le=500)] = 100,
) -> str:
    """Read topology or filtered rows from one RCA100 case.

    Use `source="topology"` for the complete service graph. For an observation
    source, select only relevant columns and add filters to narrow large
    Parquet files. At most 500 rows are returned per call.
    """

    case_directory = runtime.context.case_directory
    if source == "topology":
        return (case_directory / "topology.json").read_text(encoding="utf-8")

    dataset = arrow_dataset.dataset(case_directory / f"{source}.parquet", format="parquet")
    available_columns = set(dataset.schema.names)
    selected_columns = columns or dataset.schema.names
    unknown_columns = set(selected_columns).difference(available_columns)
    for item in filters or []:
        if item.column not in available_columns:
            unknown_columns.add(item.column)
    if unknown_columns:
        names = ", ".join(sorted(unknown_columns))
        raise ValueError(f"Unknown {source} columns: {names}")

    expression = None
    for item in filters or []:
        predicate = _filter_expression(item)
        expression = predicate if expression is None else expression & predicate
    table = dataset.scanner(columns=selected_columns, filter=expression).head(limit)
    return json.dumps(
        {
            "source": source,
            "columns": table.column_names,
            "returned_rows": table.num_rows,
            "rows": table.to_pylist(),
        },
        ensure_ascii=False,
        default=str,
    )


async def run_rca100_agent() -> None:
    """Read one blind request from stdin and emit only the agent prediction."""

    request = RCA100Request.model_validate_json(sys.stdin.read())
    runtime = await build_agent_runtime(
        build_rca100_runtime_spec(
            tools=(query_rca_case,),
            context_schema=RCA100Context,
        )
    )
    try:
        prediction = await runtime.ainvoke_text(
            _diagnosis_prompt(request),
            protocol="benchmark:rca100",
            thread_id=f"rca100:{request.task_id}",
            run_id=f"rca100:{request.task_id}",
            context=RCA100Context(case_directory=request.case_directory),
            extra_metadata={"benchmark": "rca100", "task_id": request.task_id},
        )
        sys.stdout.write(prediction.strip())
    finally:
        await runtime.aclose()


def _filter_expression(item: RCA100Filter) -> Any:
    field = arrow_dataset.field(item.column)
    if item.value is None:
        if item.operator == "==":
            return field.is_null()
        if item.operator == "!=":
            return field.is_valid()
        raise ValueError("Null filters support only == and != operators.")
    return {
        "==": field == item.value,
        "!=": field != item.value,
        "<": field < item.value,
        "<=": field <= item.value,
        ">": field > item.value,
        ">=": field >= item.value,
    }[item.operator]


def _diagnosis_prompt(request: RCA100Request) -> str:
    return f"""Diagnose the blind RCA100 incident `{request.task_id}`.

Public task:
{json.dumps(request.task, ensure_ascii=False)}

Available Parquet columns:
{json.dumps(request.parquet_schemas, ensure_ascii=False)}

Use `query_rca_case` to inspect the topology and relevant observations. Base
the reasoning on concrete metric, log, trace, event, or alert evidence. Return
exactly one JSON object matching this schema, without Markdown or commentary:
{json.dumps(request.prediction_schema, ensure_ascii=False)}
"""
