from __future__ import annotations

from langfuse.experiment import ExperimentItemResult

from ops_pilot.eval.graders import category_pass_rates, contains, no_error, pass_rate, tool_called, tool_not_called
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
