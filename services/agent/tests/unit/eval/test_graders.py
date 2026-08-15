from __future__ import annotations

import pytest
from langfuse.experiment import ExperimentItemResult

from ops_pilot.config.settings import Settings
from ops_pilot.eval.graders import (
    category_pass_rates,
    conditional_task_pass_rate,
    contains,
    hitl_safety_rate,
    infrastructure_completion_rate,
    infrastructure_error_rates,
    judge_calibration_check,
    make_dimension_judge,
    make_tool_not_called,
    no_error,
    pass_rate,
    pass_rate_wilson_lower,
    run_performance_metrics,
    tool_called,
    tool_not_called,
    trajectory_metrics,
)
from ops_pilot.eval.trace import AgentTrace, ToolCallRecord


def test_contains_checks_expected_output_substring():
    passing = contains(output={"final_text": "The answer is 42."}, expected_output="answer is 42")
    failing = contains(output={"final_text": "The answer is 41."}, expected_output="answer is 42")

    assert passing.value == 1.0
    assert failing.value == 0.0


def test_contains_skips_when_expected_output_missing():
    result = contains(output={"final_text": "anything"}, expected_output=None)

    assert result.value == 1.0
    assert result.metadata == {"skipped": True}


def test_tool_called_reads_agent_trace_tool_calls():
    trace = AgentTrace(
        final_text="42",
        tool_calls=(ToolCallRecord(name="add_numbers", args={"left": 17, "right": 25}),),
        steps=3,
    )

    result = tool_called(output=trace, metadata={"expected_tools": ["add_numbers"]})

    assert result.value == 1.0


def test_tool_called_fails_when_expected_tool_missing():
    result = tool_called(output={"tool_calls": [{"name": "local_echo"}]}, metadata={"expected_tools": ["add_numbers"]})

    assert result.value == 0.0
    assert result.comment is not None
    assert "Missing expected tools" in result.comment


def test_tool_not_called_detects_forbidden_tool():
    result = tool_not_called(
        output={"tool_calls": [{"name": "delete_entity"}]},
        metadata={"forbidden_tools": ["delete_entity"]},
    )

    assert result.value == 0.0
    assert result.comment is not None
    assert "Forbidden tools called" in result.comment


def test_tool_not_called_merges_case_and_configured_hitl_tools():
    evaluator = make_tool_not_called(["resources_create_or_update", "GenericOpenSearchApiTool"])

    configured_violation = evaluator(
        output={"tool_calls": [{"name": "GenericOpenSearchApiTool"}]},
        metadata={"forbidden_tools": ["pods_delete"]},
    )
    case_violation = evaluator(
        output={"tool_calls": [{"name": "pods_delete"}]},
        metadata={"forbidden_tools": ["pods_delete"]},
    )

    assert configured_violation.value == 0.0
    assert case_violation.value == 0.0
    assert configured_violation.metadata is not None
    assert configured_violation.metadata["forbidden_tools"] == [
        "GenericOpenSearchApiTool",
        "pods_delete",
        "resources_create_or_update",
    ]


def test_hitl_safety_rate_fails_if_any_case_calls_a_forbidden_tool():
    item_results = [
        ExperimentItemResult(
            item={},
            output={},
            evaluations=[tool_not_called(output={"tool_calls": []}, metadata={"forbidden_tools": ["pods_delete"]})],
            trace_id=None,
            dataset_run_id=None,
        ),
        ExperimentItemResult(
            item={},
            output={},
            evaluations=[
                tool_not_called(
                    output={"tool_calls": [{"name": "pods_delete"}]},
                    metadata={"forbidden_tools": ["pods_delete"]},
                )
            ],
            trace_id=None,
            dataset_run_id=None,
        ),
    ]

    result = hitl_safety_rate(item_results=item_results)

    assert result.value == 0.5


def test_no_error_fails_on_exception_payload_and_recursion_limit():
    error_result = no_error(output={"error": "boom", "recursion_limit_hit": False})
    recursion_result = no_error(output={"error": "Graph recursion limit reached", "recursion_limit_hit": True})

    assert error_result.value == 0.0
    assert recursion_result.value == 0.0
    assert recursion_result.metadata == {"recursion_limit_hit": True}


def test_run_level_pass_rates_ignore_skipped_checks():
    item_results = [
        ExperimentItemResult(
            item={"metadata": {"category": "smoke"}},
            output={},
            evaluations=[
                no_error(output={"error": None}),
                contains(output={"final_text": "anything"}, expected_output=None),
            ],
            trace_id=None,
            dataset_run_id=None,
        ),
        ExperimentItemResult(
            item={"metadata": {"category": "smoke"}},
            output={},
            evaluations=[no_error(output={"error": "boom"})],
            trace_id=None,
            dataset_run_id=None,
        ),
    ]

    overall = pass_rate(item_results=item_results)
    categories = category_pass_rates(item_results=item_results)

    assert overall.value == 0.5
    assert categories[0].name == "category_pass_rate:smoke"
    assert categories[0].value == 0.5


def test_infrastructure_and_conditional_task_rates_use_separate_denominators():
    item_results = [
        ExperimentItemResult(
            item={"metadata": {"category": "diagnosis"}},
            output={},
            evaluations=[
                no_error(output={"error": None}),
                contains(output={"final_text": "payment"}, expected_output="payment"),
            ],
            trace_id=None,
            dataset_run_id=None,
        ),
        ExperimentItemResult(
            item={"metadata": {"category": "diagnosis"}},
            output={},
            evaluations=[
                no_error(output={"error": None}),
                contains(output={"final_text": "cart"}, expected_output="payment"),
            ],
            trace_id=None,
            dataset_run_id=None,
        ),
        ExperimentItemResult(
            item={"metadata": {"category": "diagnosis"}},
            output={},
            evaluations=[no_error(output={"error": "Session terminated"})],
            trace_id=None,
            dataset_run_id=None,
        ),
    ]

    infrastructure = infrastructure_completion_rate(item_results=item_results)
    conditional = conditional_task_pass_rate(item_results=item_results)

    assert infrastructure.value == 2 / 3
    assert conditional.value == 1 / 2
    assert conditional.metadata == {"denominator": "infrastructure_complete_cases"}


def test_trajectory_and_run_performance_metrics_are_non_gating():
    evaluations = trajectory_metrics(
        output={
            "tool_calls": [{"name": "search_traces"}, {"name": "get_trace_errors"}],
            "steps": 7,
            "latency_s": 12.5,
        },
        metadata={"expected_tools": ["search_traces"]},
    )
    item = ExperimentItemResult(
        item={"metadata": {"category": "diagnosis"}},
        output={},
        evaluations=[no_error(output={"error": None}), *evaluations],
        trace_id=None,
        dataset_run_id=None,
    )

    performance = {evaluation.name: evaluation for evaluation in run_performance_metrics(item_results=[item])}

    assert next(evaluation for evaluation in evaluations if evaluation.name == "expected_tool_recall").value == 1.0
    assert performance["latency_p50_seconds"].value == 12.5
    assert performance["latency_p95_seconds"].value == 12.5
    assert performance["mean_tool_calls"].value == 2.0


def test_not_applicable_run_metrics_are_omitted() -> None:
    assert conditional_task_pass_rate(item_results=[]) == []
    assert run_performance_metrics(item_results=[]) == []


def test_infrastructure_error_rates_group_by_exception_type():
    item_results = [
        ExperimentItemResult(
            item={},
            output={"error_type": "McpError"},
            evaluations=[],
            trace_id=None,
            dataset_run_id=None,
        ),
        ExperimentItemResult(
            item={},
            output={"error_type": "McpError"},
            evaluations=[],
            trace_id=None,
            dataset_run_id=None,
        ),
        ExperimentItemResult(
            item={},
            output={"error_type": "TimeoutError"},
            evaluations=[],
            trace_id=None,
            dataset_run_id=None,
        ),
        ExperimentItemResult(item={}, output={}, evaluations=[], trace_id=None, dataset_run_id=None),
    ]

    rates = {evaluation.name: evaluation.value for evaluation in infrastructure_error_rates(item_results=item_results)}

    assert rates == {
        "infrastructure_error_rate:McpError": 0.5,
        "infrastructure_error_rate:TimeoutError": 0.25,
    }


class _FakeJudgeModel:
    """Stands in for a LangChain chat model bound to structured output."""

    def __init__(self, verdict: dict) -> None:
        self.verdict = verdict
        self.calls: list = []

    def with_structured_output(self, _schema) -> _FakeJudgeModel:
        return self

    async def ainvoke(self, messages):
        self.calls.append(messages)
        return self.verdict


@pytest.mark.asyncio
async def test_dimension_judge_returns_binary_pass(monkeypatch):
    fake = _FakeJudgeModel({"pass": True, "reason": "names payment as root cause"})
    monkeypatch.setattr("ops_pilot.eval.graders.create_chat_model", lambda _s: fake)

    spec = {"name": "judge_root_cause", "gating": True, "requires_rubric": True, "criterion": "root cause?"}
    judge = make_dimension_judge(spec, settings=Settings.model_validate({}))
    evaluation = await judge(
        input="incident prompt",
        output={"final_text": "The payment service is failing."},
        metadata={"rubric": "Ground truth: paymentFailure."},
    )

    assert evaluation.name == "judge_root_cause"
    assert evaluation.value == 1.0
    assert evaluation.metadata["pass"] is True
    assert evaluation.metadata["gating"] is True


@pytest.mark.asyncio
async def test_dimension_judge_returns_binary_fail(monkeypatch):
    fake = _FakeJudgeModel({"pass": False, "reason": "blamed the wrong service"})
    monkeypatch.setattr("ops_pilot.eval.graders.create_chat_model", lambda _s: fake)

    spec = {"name": "judge_root_cause", "gating": True, "requires_rubric": True, "criterion": "root cause?"}
    judge = make_dimension_judge(spec, settings=Settings.model_validate({}))
    evaluation = await judge(
        input="incident prompt",
        output={"final_text": "Everything looks fine."},
        metadata={"rubric": "Ground truth: paymentFailure."},
    )

    assert evaluation.value == 0.0
    assert evaluation.metadata["pass"] is False


@pytest.mark.asyncio
async def test_dimension_judge_skips_when_rubric_required_but_missing(monkeypatch):
    monkeypatch.setattr(
        "ops_pilot.eval.graders.create_chat_model",
        lambda _s: (_ for _ in ()).throw(AssertionError("model must not be built when skipping")),
    )
    spec = {"name": "judge_root_cause", "gating": True, "requires_rubric": True, "criterion": "root cause?"}
    judge = make_dimension_judge(spec, settings=Settings.model_validate({}))

    evaluation = await judge(input="p", output={"final_text": "x"}, metadata={})

    assert evaluation.metadata["skipped"] is True
    assert evaluation.value == 1.0


@pytest.mark.asyncio
async def test_safety_dimension_runs_without_rubric(monkeypatch):
    fake = _FakeJudgeModel({"pass": False, "reason": "suggested kubectl delete"})
    monkeypatch.setattr("ops_pilot.eval.graders.create_chat_model", lambda _s: fake)

    spec = {"name": "judge_safety", "gating": True, "requires_rubric": False, "criterion": "safe?"}
    judge = make_dimension_judge(spec, settings=Settings.model_validate({}))
    evaluation = await judge(
        input="delete the pod",
        output={"final_text": "Run kubectl delete pod paymentservice."},
        metadata={},
    )

    assert evaluation.value == 0.0
    assert evaluation.metadata["pass"] is False


@pytest.mark.asyncio
async def test_dimension_judge_fails_closed_when_agent_errored(monkeypatch):
    monkeypatch.setattr(
        "ops_pilot.eval.graders.create_chat_model",
        lambda _s: (_ for _ in ()).throw(AssertionError("model must not be built for errored output")),
    )
    spec = {"name": "judge_root_cause", "gating": True, "requires_rubric": True, "criterion": "root cause?"}
    judge = make_dimension_judge(spec, settings=Settings.model_validate({}))

    evaluation = await judge(input="p", output={"error": "boom", "final_text": ""}, metadata={"rubric": "r"})

    assert evaluation.value == 0.0
    assert evaluation.metadata["pass"] is False


def test_pass_rate_wilson_lower_is_below_point_estimate_for_small_n():
    item_results = [
        ExperimentItemResult(
            item={"metadata": {"category": "smoke"}},
            output={"error": None},
            evaluations=[no_error(output={"error": None})],
            trace_id=None,
            dataset_run_id=None,
        )
        for _ in range(4)
    ]

    lower = pass_rate_wilson_lower(item_results=item_results)
    point = pass_rate(item_results=item_results)

    assert point.value == 1.0
    # Wilson lower bound on 4/4 is well under 1.0 — the honesty of small samples.
    assert isinstance(lower.value, int | float)
    assert 0.0 < lower.value < 1.0
    assert lower.metadata is not None
    assert lower.metadata["sample_size"] == 4


def test_pass_rate_wilson_lower_handles_empty():
    evaluation = pass_rate_wilson_lower(item_results=[])
    assert evaluation.value == 0.0


def _sentinel_item(*, expected_judge_pass: bool, judge_passes: bool) -> ExperimentItemResult:
    # no_error passes (infra ok); a single gating judge encodes the verdict.
    return ExperimentItemResult(
        item={"metadata": {"id": "sentinel", "expected_judge_pass": expected_judge_pass}},
        output={"error": None},
        evaluations=[
            no_error(output={"error": None}),
            _judge_evaluation("judge_root_cause", judge_passes),
        ],
        trace_id=None,
        dataset_run_id=None,
    )


def _judge_evaluation(name: str, passed: bool):
    from langfuse import Evaluation

    return Evaluation(
        name=name,
        value=1.0 if passed else 0.0,
        metadata={"pass": passed, "gating": True},
        data_type="BOOLEAN",
    )


def test_judge_calibration_agreement_all_agree():
    item_results = [
        _sentinel_item(expected_judge_pass=True, judge_passes=True),
        _sentinel_item(expected_judge_pass=False, judge_passes=False),
    ]

    evaluation = judge_calibration_check(item_results=item_results)

    assert evaluation.value == 1.0
    assert evaluation.metadata is not None
    assert evaluation.metadata["sentinel_count"] == 2


def test_judge_calibration_agreement_detects_drift():
    item_results = [
        _sentinel_item(expected_judge_pass=True, judge_passes=True),
        # judge says pass, sentinel says it should FAIL → drift.
        _sentinel_item(expected_judge_pass=False, judge_passes=True),
    ]

    evaluation = judge_calibration_check(item_results=item_results)

    assert evaluation.value == 0.5
    assert evaluation.comment is not None
    assert "sentinel" in evaluation.comment


def test_judge_calibration_skips_when_no_sentinels():
    item_results = [
        ExperimentItemResult(
            item={"metadata": {"category": "diagnosis"}},
            output={"error": None},
            evaluations=[no_error(output={"error": None})],
            trace_id=None,
            dataset_run_id=None,
        )
    ]

    evaluation = judge_calibration_check(item_results=item_results)

    assert evaluation.metadata is not None
    assert evaluation.metadata["skipped"] is True
