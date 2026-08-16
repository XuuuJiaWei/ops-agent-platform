"""Provider-neutral token usage metrics for agent evaluation."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from langfuse import Evaluation


def token_usage_metrics(*, output: Any, metadata: Mapping[str, Any] | None = None, **_: Any) -> list[Evaluation]:
    """Emit per-case token usage when the model provider reports usage metadata.

    Judge calibration sentinels intentionally do not run the agent and therefore
    must not contribute zero-token samples to model-efficiency aggregates.
    """

    if metadata and metadata.get("fixed_output") is not None:
        return []
    if not _output_bool(output, "token_usage_available"):
        return []

    return [
        _metric("input_token_count", _output_number(output, "input_tokens")),
        _metric("output_token_count", _output_number(output, "output_tokens")),
        _metric("total_token_count", _output_number(output, "total_tokens")),
    ]


def run_token_metrics(*, item_results: list[Any], **_: Any) -> list[Evaluation]:
    """Aggregate provider-reported token usage without inventing USD pricing.

    Dollar cost is deliberately omitted here because pricing is provider/model/date
    specific. The benchmark records raw token counts as the stable measurement;
    a pricing layer can be applied separately with an explicit price snapshot.
    """

    input_tokens = _metric_values(item_results, "input_token_count")
    output_tokens = _metric_values(item_results, "output_token_count")
    total_tokens = _metric_values(item_results, "total_token_count")
    eligible = sum(1 for item_result in item_results if not _is_fixed_output(item_result))
    coverage = len(total_tokens) / eligible if eligible else 0.0

    evaluations = [
        Evaluation(
            name="token_usage_coverage",
            value=coverage,
            comment=f"Provider token usage available for {len(total_tokens)}/{eligible} agent cases.",
            metadata={"gating": False, "sample_size": eligible},
        )
    ]
    if not total_tokens:
        return evaluations

    evaluations.extend(
        [
            Evaluation(
                name="mean_input_tokens",
                value=sum(input_tokens) / len(input_tokens) if input_tokens else 0.0,
                metadata={"gating": False, "sample_size": len(input_tokens)},
            ),
            Evaluation(
                name="mean_output_tokens",
                value=sum(output_tokens) / len(output_tokens) if output_tokens else 0.0,
                metadata={"gating": False, "sample_size": len(output_tokens)},
            ),
            Evaluation(
                name="mean_total_tokens",
                value=sum(total_tokens) / len(total_tokens),
                metadata={"gating": False, "sample_size": len(total_tokens)},
            ),
            Evaluation(
                name="total_tokens",
                value=sum(total_tokens),
                metadata={"gating": False, "sample_size": len(total_tokens)},
            ),
        ]
    )
    return evaluations


def _metric(name: str, value: float) -> Evaluation:
    return Evaluation(name=name, value=value, metadata={"gating": False})


def _metric_values(item_results: list[Any], name: str) -> list[float]:
    values: list[float] = []
    for item_result in item_results:
        for evaluation in getattr(item_result, "evaluations", []):
            if getattr(evaluation, "name", "") != name:
                continue
            value = getattr(evaluation, "value", None)
            if isinstance(value, bool):
                continue
            if isinstance(value, int | float):
                values.append(float(value))
    return values


def _item_metadata(item_result: Any) -> Mapping[str, Any]:
    item = getattr(item_result, "item", None)
    metadata = item.get("metadata") if isinstance(item, Mapping) else getattr(item, "metadata", None)
    return metadata if isinstance(metadata, Mapping) else {}


def _is_fixed_output(item_result: Any) -> bool:
    return _item_metadata(item_result).get("fixed_output") is not None


def _output_number(output: Any, key: str) -> float:
    value = output.get(key) if isinstance(output, Mapping) else getattr(output, key, None)
    if isinstance(value, bool):
        return 0.0
    return float(value) if isinstance(value, int | float) else 0.0


def _output_bool(output: Any, key: str) -> bool:
    value = output.get(key) if isinstance(output, Mapping) else getattr(output, key, None)
    return bool(value)
