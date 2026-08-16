from __future__ import annotations

from types import SimpleNamespace

from ops_pilot.eval.token_metrics import run_token_metrics, token_usage_metrics
from ops_pilot.eval.trace import _extract_token_usage


def _values(evaluations: list[object]) -> dict[str, float]:
    return {
        str(getattr(evaluation, "name")): float(getattr(evaluation, "value"))
        for evaluation in evaluations
        if isinstance(getattr(evaluation, "value", None), int | float)
    }


def test_extract_token_usage_from_langchain_usage_metadata() -> None:
    usage = _extract_token_usage(
        [
            {"usage_metadata": {"input_tokens": 100, "output_tokens": 20, "total_tokens": 120}},
            {"usage_metadata": {"input_tokens": 140, "output_tokens": 30, "total_tokens": 170}},
        ]
    )

    assert usage == (240, 50, 290, True)


def test_extract_token_usage_from_openai_compatible_response_metadata() -> None:
    usage = _extract_token_usage(
        [
            {
                "response_metadata": {
                    "token_usage": {"prompt_tokens": 11, "completion_tokens": 7, "total_tokens": 18}
                }
            }
        ]
    )

    assert usage == (11, 7, 18, True)


def test_extract_token_usage_derives_total_when_provider_omits_it() -> None:
    usage = _extract_token_usage([{"usage_metadata": {"input_tokens": 9, "output_tokens": 4}}])

    assert usage == (9, 4, 13, True)


def test_token_usage_metrics_skip_sentinels_and_missing_usage() -> None:
    assert token_usage_metrics(output={"token_usage_available": False}, metadata={}) == []
    assert (
        token_usage_metrics(
            output={
                "token_usage_available": True,
                "input_tokens": 1,
                "output_tokens": 2,
                "total_tokens": 3,
            },
            metadata={"fixed_output": "judge sentinel"},
        )
        == []
    )


def test_token_usage_metrics_emit_provider_neutral_counts() -> None:
    evaluations = token_usage_metrics(
        output={
            "token_usage_available": True,
            "input_tokens": 120,
            "output_tokens": 35,
            "total_tokens": 155,
        },
        metadata={},
    )

    assert _values(evaluations) == {
        "input_token_count": 120.0,
        "output_token_count": 35.0,
        "total_token_count": 155.0,
    }


def test_run_token_metrics_aggregate_only_real_agent_cases() -> None:
    first = SimpleNamespace(
        evaluations=token_usage_metrics(
            output={
                "token_usage_available": True,
                "input_tokens": 100,
                "output_tokens": 20,
                "total_tokens": 120,
            },
            metadata={},
        ),
        item={"metadata": {"id": "first"}},
    )
    second = SimpleNamespace(
        evaluations=token_usage_metrics(
            output={
                "token_usage_available": True,
                "input_tokens": 200,
                "output_tokens": 40,
                "total_tokens": 240,
            },
            metadata={},
        ),
        item={"metadata": {"id": "second"}},
    )
    sentinel = SimpleNamespace(evaluations=[], item={"metadata": {"fixed_output": "known answer"}})

    metrics = _values(run_token_metrics(item_results=[first, second, sentinel]))

    assert metrics["token_usage_coverage"] == 1.0
    assert metrics["mean_input_tokens"] == 150.0
    assert metrics["mean_output_tokens"] == 30.0
    assert metrics["mean_total_tokens"] == 180.0
    assert metrics["total_tokens"] == 360.0
