"""Langfuse-compatible eval graders."""

from __future__ import annotations

import json
import math
from collections import defaultdict
from collections.abc import Mapping
from typing import Any

from langfuse import Evaluation

from ops_pilot.config.settings import Settings
from ops_pilot.eval.trace import AgentTrace
from ops_pilot.models import create_chat_model

PASSING_SCORE = 1.0
FAILING_SCORE = 0.0

# Pass/fail graders return a 0/1 value tagged BOOLEAN so Langfuse renders them
# as True/False rather than a numeric score. pass_rate / category_pass_rates
# stay NUMERIC because they are ratios.
BOOLEAN = "BOOLEAN"


def deterministic_evaluators() -> list[Any]:
    return [no_error, contains, tool_called, tool_not_called, trajectory_metrics]


def build_item_evaluators(settings: Settings, *, include_judge: bool) -> list[Any]:
    evaluators = deterministic_evaluators()
    if include_judge:
        evaluators.append(create_rubric_judge(settings))
    return evaluators


def contains(*, output: Any, expected_output: Any = None, **_: Any) -> Evaluation:
    if not expected_output:
        return Evaluation(
            name="contains",
            value=PASSING_SCORE,
            comment="No expected_output configured; substring check skipped.",
            metadata={"skipped": True},
            data_type=BOOLEAN,
        )
    actual = _output_text(output).lower()
    expected = str(expected_output).lower()
    passed = expected in actual
    return Evaluation(
        name="contains",
        value=PASSING_SCORE if passed else FAILING_SCORE,
        comment="Expected substring found." if passed else f"Expected substring not found: {expected_output}",
        data_type=BOOLEAN,
    )


def tool_called(*, output: Any, metadata: Mapping[str, Any] | None = None, **_: Any) -> Evaluation:
    expected_tools = set(_metadata_strings(metadata, "expected_tools"))
    if not expected_tools:
        return Evaluation(
            name="tool_called",
            value=PASSING_SCORE,
            comment="No expected_tools configured; tool-called check skipped.",
            metadata={"skipped": True},
            data_type=BOOLEAN,
        )
    actual_tools = set(_output_tool_names(output))
    missing = sorted(expected_tools - actual_tools)
    return Evaluation(
        name="tool_called",
        value=PASSING_SCORE if not missing else FAILING_SCORE,
        comment="Expected tools were called." if not missing else "Missing expected tools: " + ", ".join(missing),
        metadata={"expected_tools": sorted(expected_tools), "actual_tools": sorted(actual_tools)},
        data_type=BOOLEAN,
    )


def tool_not_called(*, output: Any, metadata: Mapping[str, Any] | None = None, **_: Any) -> Evaluation:
    forbidden_tools = set(_metadata_strings(metadata, "forbidden_tools"))
    if not forbidden_tools:
        return Evaluation(
            name="tool_not_called",
            value=PASSING_SCORE,
            comment="No forbidden_tools configured; safety check skipped.",
            metadata={"skipped": True},
            data_type=BOOLEAN,
        )
    actual_tools = set(_output_tool_names(output))
    violations = sorted(forbidden_tools & actual_tools)
    return Evaluation(
        name="tool_not_called",
        value=PASSING_SCORE if not violations else FAILING_SCORE,
        comment=(
            "No forbidden tools were called." if not violations else "Forbidden tools called: " + ", ".join(violations)
        ),
        metadata={"forbidden_tools": sorted(forbidden_tools), "actual_tools": sorted(actual_tools)},
        data_type=BOOLEAN,
    )


def no_error(*, output: Any, **_: Any) -> Evaluation:
    error = _output_error(output)
    recursion_limit_hit = _output_recursion_limit_hit(output)
    passed = not error and not recursion_limit_hit
    if recursion_limit_hit:
        comment = "Agent hit the LangGraph recursion limit."
    elif error:
        comment = f"Agent raised an exception: {error}"
    else:
        comment = "Agent completed without an exception."
    return Evaluation(
        name="no_error",
        value=PASSING_SCORE if passed else FAILING_SCORE,
        comment=comment,
        metadata={"recursion_limit_hit": recursion_limit_hit},
        data_type=BOOLEAN,
    )


def trajectory_metrics(*, output: Any, metadata: Mapping[str, Any] | None = None, **_: Any) -> list[Evaluation]:
    """Emit non-gating trajectory and performance signals for error analysis."""

    expected_tools = set(_metadata_strings(metadata, "expected_tools"))
    actual_tools = tuple(_output_tool_names(output))
    recall = len(expected_tools & set(actual_tools)) / len(expected_tools) if expected_tools else None
    evaluations = [
        Evaluation(
            name="tool_call_count",
            value=float(len(actual_tools)),
            metadata={"gating": False},
        ),
        Evaluation(
            name="step_count",
            value=float(_output_number(output, "steps")),
            metadata={"gating": False},
        ),
        Evaluation(
            name="latency_seconds",
            value=float(_output_number(output, "latency_s")),
            metadata={"gating": False},
        ),
    ]
    if recall is not None:
        evaluations.append(
            Evaluation(
                name="expected_tool_recall",
                value=recall,
                comment=f"Called {len(expected_tools & set(actual_tools))}/{len(expected_tools)} expected tools.",
                metadata={"gating": False},
            )
        )
    return evaluations


def create_rubric_judge(settings: Settings) -> Any:
    judge_model: Any | None = None

    async def rubric_judge(
        *, input: Any, output: Any, metadata: Mapping[str, Any] | None = None, **_: Any
    ) -> Evaluation:
        nonlocal judge_model
        rubric = _metadata_string(metadata, "rubric")
        if not rubric:
            return Evaluation(
                name="rubric_judge",
                value=PASSING_SCORE,
                comment="No rubric configured; judge skipped.",
                metadata={"skipped": True},
            )
        if _output_error(output):
            return Evaluation(
                name="rubric_judge",
                value=FAILING_SCORE,
                comment="Agent task failed before rubric judging.",
                metadata={"pass": False},
            )
        try:
            if judge_model is None:
                judge_model = _structured_judge_model(create_chat_model(settings))
            raw_result = await _invoke_judge(judge_model, input=input, output=_output_text(output), rubric=rubric)
            parsed = _parse_judge_result(raw_result)
            passed = bool(parsed.get("pass"))
            score = _bounded_score(parsed.get("score"))
            reason = str(parsed.get("reason") or "No judge reason returned.")
            return Evaluation(
                name="rubric_judge",
                value=score if passed else FAILING_SCORE,
                comment=reason,
                metadata={"pass": passed, "raw_score": score},
            )
        except Exception as exc:  # noqa: BLE001 - judges are best-effort infrastructure.
            return Evaluation(
                name="rubric_judge",
                value=None,  # type: ignore[arg-type]
                comment=f"Rubric judge failed: {exc}",
                metadata={"evaluator_error": True},
            )

    rubric_judge.__name__ = "rubric_judge"
    return rubric_judge


def pass_rate(*, item_results: list[Any], **_: Any) -> Evaluation:
    total = len(item_results)
    passed = sum(1 for item_result in item_results if _item_passed(item_result))
    rate = passed / total if total else 0.0
    return Evaluation(name="pass_rate", value=rate, comment=f"{passed}/{total} eval cases passed.")


def category_pass_rates(*, item_results: list[Any], **_: Any) -> list[Evaluation]:
    totals: dict[str, int] = defaultdict(int)
    passes: dict[str, int] = defaultdict(int)
    for item_result in item_results:
        category = _item_category(item_result) or "uncategorized"
        totals[category] += 1
        if _item_passed(item_result):
            passes[category] += 1
    return [
        Evaluation(
            name=f"category_pass_rate:{category}",
            value=passes[category] / total if total else 0.0,
            comment=f"{passes[category]}/{total} cases passed in category '{category}'.",
            metadata={"category": category},
        )
        for category, total in sorted(totals.items())
    ]


def infrastructure_completion_rate(*, item_results: list[Any], **_: Any) -> Evaluation:
    total = len(item_results)
    completed = sum(1 for item_result in item_results if _item_infrastructure_completed(item_result))
    return Evaluation(
        name="infrastructure_completion_rate",
        value=completed / total if total else 0.0,
        comment=f"{completed}/{total} cases completed without runtime or infrastructure errors.",
    )


def conditional_task_pass_rate(*, item_results: list[Any], **_: Any) -> Evaluation:
    completed = [item_result for item_result in item_results if _item_infrastructure_completed(item_result)]
    passed = sum(1 for item_result in completed if _item_quality_passed(item_result))
    rate = passed / len(completed) if completed else None
    return Evaluation(
        name="conditional_task_pass_rate",
        value=rate,  # type: ignore[arg-type]
        comment=f"{passed}/{len(completed)} infrastructure-complete cases passed task-quality gates.",
        metadata={"denominator": "infrastructure_complete_cases"},
    )


def run_performance_metrics(*, item_results: list[Any], **_: Any) -> list[Evaluation]:
    completed = [item_result for item_result in item_results if _item_infrastructure_completed(item_result)]
    latencies = [_item_metric(item_result, "latency_seconds") for item_result in completed]
    latencies = sorted(value for value in latencies if value is not None)
    tool_calls = [_item_metric(item_result, "tool_call_count") for item_result in completed]
    tool_calls = [value for value in tool_calls if value is not None]
    return [
        Evaluation(
            name="latency_p50_seconds",
            value=_percentile(latencies, 0.50),  # type: ignore[arg-type]
            metadata={"gating": False, "sample_size": len(latencies)},
        ),
        Evaluation(
            name="latency_p95_seconds",
            value=_percentile(latencies, 0.95),  # type: ignore[arg-type]
            metadata={"gating": False, "sample_size": len(latencies)},
        ),
        Evaluation(
            name="mean_tool_calls",
            value=sum(tool_calls) / len(tool_calls) if tool_calls else None,  # type: ignore[arg-type]
            metadata={"gating": False, "sample_size": len(tool_calls)},
        ),
    ]


def infrastructure_error_rates(*, item_results: list[Any], **_: Any) -> list[Evaluation]:
    """Break infrastructure failures down by stable exception class."""

    total = len(item_results)
    counts: dict[str, int] = defaultdict(int)
    for item_result in item_results:
        output = getattr(item_result, "output", None)
        error_type = output.get("error_type") if isinstance(output, Mapping) else None
        if error_type:
            counts[str(error_type)] += 1
    return [
        Evaluation(
            name=f"infrastructure_error_rate:{error_type}",
            value=count / total if total else 0.0,
            comment=f"{count}/{total} cases failed with {error_type}.",
            metadata={"gating": False, "error_type": error_type},
        )
        for error_type, count in sorted(counts.items())
    ]


def _output_text(output: Any) -> str:
    if isinstance(output, AgentTrace):
        return output.final_text
    if isinstance(output, Mapping):
        value = output.get("final_text") or output.get("output") or output.get("content")
        return "" if value is None else str(value)
    return str(output)


def _output_number(output: Any, key: str) -> float:
    value = getattr(output, key, None)
    if isinstance(output, Mapping):
        value = output.get(key, value)
    return float(value) if isinstance(value, int | float) and math.isfinite(float(value)) else 0.0


def _output_tool_names(output: Any) -> tuple[str, ...]:
    if isinstance(output, AgentTrace):
        return tuple(tool_call.name for tool_call in output.tool_calls)
    if not isinstance(output, Mapping):
        return ()
    raw_tool_calls = output.get("tool_calls")
    if not isinstance(raw_tool_calls, list | tuple):
        return ()
    names: list[str] = []
    for raw_call in raw_tool_calls:
        name = None
        if isinstance(raw_call, Mapping):
            name = raw_call.get("name")
        else:
            name = getattr(raw_call, "name", None)
        if name:
            names.append(str(name))
    return tuple(names)


def _output_error(output: Any) -> str | None:
    if isinstance(output, Mapping):
        error = output.get("error")
        return str(error) if error else None
    return None


def _output_recursion_limit_hit(output: Any) -> bool:
    if not isinstance(output, Mapping):
        return False
    if bool(output.get("recursion_limit_hit")):
        return True
    error_type = str(output.get("error_type") or "")
    error = str(output.get("error") or "")
    return "GraphRecursion" in error_type or "recursion limit" in error.lower()


def _metadata_strings(metadata: Mapping[str, Any] | None, key: str) -> tuple[str, ...]:
    if not metadata:
        return ()
    value = metadata.get(key)
    if not isinstance(value, list | tuple):
        return ()
    return tuple(str(item) for item in value if item)


def _metadata_string(metadata: Mapping[str, Any] | None, key: str) -> str | None:
    if not metadata:
        return None
    value = metadata.get(key)
    return str(value) if value else None


def _structured_judge_model(model: Any) -> Any:
    with_structured_output = getattr(model, "with_structured_output", None)
    if not callable(with_structured_output):
        return model
    return with_structured_output(
        {
            "title": "RubricJudgeResult",
            "type": "object",
            "properties": {
                "pass": {"type": "boolean"},
                "score": {"type": "number", "minimum": 0, "maximum": 1},
                "reason": {"type": "string"},
            },
            "required": ["pass", "score", "reason"],
        }
    )


async def _invoke_judge(model: Any, *, input: Any, output: str, rubric: str) -> Any:
    messages = [
        (
            "system",
            "You are a strict evaluator for an ops agent. Return only the requested structured result.",
        ),
        (
            "user",
            "Evaluate the agent response against the rubric.\n\n"
            f"Prompt:\n{input}\n\nAgent response:\n{output}\n\nRubric:\n{rubric}",
        ),
    ]
    ainvoke = getattr(model, "ainvoke", None)
    if callable(ainvoke):
        return await ainvoke(messages)
    invoke = getattr(model, "invoke", None)
    if callable(invoke):
        return invoke(messages)
    raise TypeError("Judge model does not expose invoke() or ainvoke().")


def _parse_judge_result(raw_result: Any) -> dict[str, Any]:
    if isinstance(raw_result, Mapping):
        return dict(raw_result)
    content = getattr(raw_result, "content", raw_result)
    if isinstance(content, Mapping):
        return dict(content)
    if isinstance(content, list):
        content = "\n".join(str(item.get("text", item)) if isinstance(item, Mapping) else str(item) for item in content)
    if not isinstance(content, str):
        raise TypeError(f"Unsupported judge result type: {type(raw_result).__name__}")
    return json.loads(content)


def _bounded_score(value: Any) -> float:
    score = float(value)
    return min(1.0, max(0.0, score))


def _item_passed(item_result: Any) -> bool:
    evaluations = getattr(item_result, "evaluations", [])
    active = [evaluation for evaluation in evaluations if _evaluation_active(evaluation)]
    return bool(active) and all(_evaluation_passed(evaluation) for evaluation in active)


def _evaluation_active(evaluation: Any) -> bool:
    metadata = getattr(evaluation, "metadata", None)
    if isinstance(metadata, Mapping) and (
        metadata.get("skipped") or metadata.get("evaluator_error") or metadata.get("gating") is False
    ):
        return False
    return True


def _evaluation_passed(evaluation: Any) -> bool:
    metadata = getattr(evaluation, "metadata", None)
    if isinstance(metadata, Mapping) and "pass" in metadata:
        return bool(metadata["pass"])
    value = getattr(evaluation, "value", None)
    if isinstance(value, bool):
        return value
    if isinstance(value, int | float):
        if getattr(evaluation, "name", "") == "rubric_judge":
            return value >= 0.5
        return value >= PASSING_SCORE
    return False


def _item_category(item_result: Any) -> str | None:
    item = getattr(item_result, "item", None)
    metadata = item.get("metadata") if isinstance(item, Mapping) else getattr(item, "metadata", None)
    if isinstance(metadata, Mapping):
        category = metadata.get("category")
        if category:
            return str(category)
    return None


def _item_infrastructure_completed(item_result: Any) -> bool:
    evaluations = getattr(item_result, "evaluations", [])
    no_error_evaluation = next(
        (evaluation for evaluation in evaluations if getattr(evaluation, "name", "") == "no_error"),
        None,
    )
    return no_error_evaluation is not None and _evaluation_passed(no_error_evaluation)


def _item_quality_passed(item_result: Any) -> bool:
    evaluations = getattr(item_result, "evaluations", [])
    active = [
        evaluation
        for evaluation in evaluations
        if getattr(evaluation, "name", "") != "no_error" and _evaluation_active(evaluation)
    ]
    return bool(active) and all(_evaluation_passed(evaluation) for evaluation in active)


def _item_metric(item_result: Any, name: str) -> float | None:
    for evaluation in getattr(item_result, "evaluations", []):
        if getattr(evaluation, "name", "") == name:
            value = getattr(evaluation, "value", None)
            if isinstance(value, int | float):
                return float(value)
    return None


def _percentile(values: list[float], quantile: float) -> float | None:
    if not values:
        return None
    position = (len(values) - 1) * quantile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return values[lower]
    weight = position - lower
    return values[lower] * (1 - weight) + values[upper] * weight
