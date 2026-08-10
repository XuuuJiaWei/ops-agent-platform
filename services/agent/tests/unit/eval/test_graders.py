from __future__ import annotations

from langfuse.experiment import ExperimentItemResult

from ops_pilot.eval.graders import (
    category_pass_rates,
    conditional_task_pass_rate,
    contains,
    infrastructure_completion_rate,
    infrastructure_error_rates,
    no_error,
    pass_rate,
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
    assert "Missing expected tools" in result.comment


def test_tool_not_called_detects_forbidden_tool():
    result = tool_not_called(
        output={"tool_calls": [{"name": "delete_entity"}]},
        metadata={"forbidden_tools": ["delete_entity"]},
    )

    assert result.value == 0.0
    assert "Forbidden tools called" in result.comment


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
