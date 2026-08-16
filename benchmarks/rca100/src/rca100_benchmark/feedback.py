"""Deterministic comparison and activation gate for RCA100 experiments."""

from __future__ import annotations

import json
from pathlib import Path
from statistics import fmean
from typing import Any


def compare_experiments(
    baseline_path: Path,
    candidate_path: Path,
    *,
    task_ids: tuple[str, ...] | None = None,
    min_final_gain_percentage_points: float = 0.0,
) -> dict[str, Any]:
    """Compare two same-task artifacts and recommend activation or rollback."""

    baseline = _load_artifact(baseline_path)
    candidate = _load_artifact(candidate_path)
    if task_ids is None:
        baseline_tasks = tuple(str(task) for task in baseline.get("tasks_requested", []))
        candidate_tasks = tuple(str(task) for task in candidate.get("tasks_requested", []))
        if not baseline_tasks or baseline_tasks != candidate_tasks:
            raise ValueError("Baseline and candidate artifacts must contain the same non-empty ordered task set.")
        task_ids = baseline_tasks
    if not task_ids or len(set(task_ids)) != len(task_ids):
        raise ValueError("Comparison task selection must be non-empty and unique.")
    baseline = _project_artifact(baseline, task_ids)
    candidate = _project_artifact(candidate, task_ids)

    baseline_summary = summarize_experiment(baseline)
    candidate_summary = summarize_experiment(candidate)
    quality_keys = (
        "completion_rate_pct",
        "parse_success_rate_pct",
        "mean_entity_score_pct",
        "mean_fault_score_pct",
        "mean_process_score_pct",
        "mean_final_score_pct",
    )
    efficiency_keys = ("mean_model_calls", "mean_tool_calls", "mean_total_tokens", "mean_elapsed_s")
    quality_delta = {key: _difference(candidate_summary.get(key), baseline_summary.get(key)) for key in quality_keys}
    efficiency_delta = {
        key: _relative_change(candidate_summary.get(key), baseline_summary.get(key)) for key in efficiency_keys
    }

    required_non_regressions = (
        "completion_rate_pct",
        "parse_success_rate_pct",
        "mean_entity_score_pct",
        "mean_fault_score_pct",
        "mean_process_score_pct",
    )
    criteria = {
        "all_tasks_complete": candidate_summary["completion_rate_pct"] == 100.0,
        "all_predictions_parse": candidate_summary["parse_success_rate_pct"] == 100.0,
        "all_tasks_evaluated": candidate_summary["evaluation_coverage_pct"] == 100.0,
        "quality_components_non_regressing": all(
            (quality_delta[key] or 0.0) >= 0.0 for key in required_non_regressions
        ),
        "minimum_final_gain_met": (quality_delta["mean_final_score_pct"] or 0.0) >= min_final_gain_percentage_points,
    }
    regressed = any((quality_delta[key] or 0.0) < 0.0 for key in required_non_regressions) or (
        (quality_delta["mean_final_score_pct"] or 0.0) < 0.0
    )
    recommendation = "activate" if all(criteria.values()) else "rollback" if regressed else "hold"

    return {
        "comparison_schema_version": 1,
        "benchmark": "rca100",
        "tasks": list(task_ids),
        "task_count": len(task_ids),
        "variants": {
            "baseline": _variant_name(baseline, baseline_path),
            "candidate": _variant_name(candidate, candidate_path),
        },
        "baseline": baseline_summary,
        "candidate": candidate_summary,
        "delta": {
            "quality_percentage_points": quality_delta,
            "efficiency_relative_pct": efficiency_delta,
        },
        "gate": {
            "min_final_gain_percentage_points": min_final_gain_percentage_points,
            "criteria": criteria,
            "recommendation": recommendation,
        },
        "case_feedback": _case_feedback(baseline, candidate, task_ids),
    }


def summarize_experiment(artifact: dict[str, Any]) -> dict[str, float]:
    tasks = tuple(str(task) for task in artifact.get("tasks_requested", []))
    runs = [run for run in artifact.get("runs", []) if isinstance(run, dict)]
    denominator = len(tasks)
    completed = [run for run in runs if "error" not in run]
    parsed = [run for run in completed if isinstance(run.get("prediction"), dict)]
    evaluated = [run for run in completed if isinstance(run.get("task_metrics"), dict)]
    return {
        "completion_rate_pct": _rate(len(completed), denominator),
        "parse_success_rate_pct": _rate(len(parsed), denominator),
        "evaluation_coverage_pct": _rate(len(evaluated), denominator),
        "mean_entity_score_pct": _mean_nested_pct(evaluated, "entity", "score"),
        "mean_fault_score_pct": _mean_nested_pct(evaluated, "fault", "score"),
        "mean_process_score_pct": _mean_nested_pct(evaluated, "process", "score"),
        "mean_final_score_pct": _mean_value(evaluated, ("task_metrics", "final_score"), scale=100.0),
        "mean_model_calls": _mean_value(completed, ("benchmark_metrics", "model_calls")),
        "mean_tool_calls": _mean_value(completed, ("benchmark_metrics", "tool_calls")),
        "mean_total_tokens": _mean_value(completed, ("benchmark_metrics", "total_tokens")),
        "mean_elapsed_s": _mean_value(completed, ("benchmark_metrics", "elapsed_s")),
    }


def _case_feedback(
    baseline: dict[str, Any], candidate: dict[str, Any], task_ids: tuple[str, ...]
) -> list[dict[str, Any]]:
    baseline_runs = _runs_by_task(baseline)
    candidate_runs = _runs_by_task(candidate)
    feedback: list[dict[str, Any]] = []
    for task_id in task_ids:
        before = baseline_runs.get(task_id, {})
        after = candidate_runs.get(task_id, {})
        after_metrics = after.get("task_metrics") if isinstance(after.get("task_metrics"), dict) else {}
        score_deltas = {
            "entity": _score_delta(after, before, "entity"),
            "fault": _score_delta(after, before, "fault"),
            "process": _score_delta(after, before, "process"),
            "final": _difference(
                _nested(after, "task_metrics", "final_score"),
                _nested(before, "task_metrics", "final_score"),
                scale=100.0,
            ),
        }
        deficits = [
            component
            for component in ("entity", "fault", "process")
            if float(_nested(after_metrics, component, "score") or 0.0) < 1.0
        ]
        if "error" in after:
            status = "error"
        elif after.get("prediction") is None:
            status = "invalid_prediction"
        else:
            status = "evaluated"
        feedback.append(
            {
                "task_id": task_id,
                "status": status,
                "score_delta_percentage_points": score_deltas,
                "candidate_deficits": deficits,
                "candidate_model_calls": _nested(after, "benchmark_metrics", "model_calls"),
                "candidate_tool_calls": _nested(after, "benchmark_metrics", "tool_calls"),
            }
        )
    return feedback


def _load_artifact(path: Path) -> dict[str, Any]:
    with path.expanduser().resolve().open(encoding="utf-8") as file:
        value = json.load(file)
    if not isinstance(value, dict) or value.get("benchmark") != "rca100":
        raise ValueError(f"Expected an RCA100 artifact at {path}.")
    return value


def _variant_name(artifact: dict[str, Any], path: Path) -> str:
    run = artifact.get("run")
    if isinstance(run, dict) and run.get("variant"):
        return str(run["variant"])
    return path.stem


def _runs_by_task(artifact: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(run["task_id"]): run for run in artifact.get("runs", []) if isinstance(run, dict) and run.get("task_id")
    }


def _project_artifact(artifact: dict[str, Any], task_ids: tuple[str, ...]) -> dict[str, Any]:
    runs = _runs_by_task(artifact)
    missing = [task_id for task_id in task_ids if task_id not in runs]
    if missing:
        raise ValueError(f"Artifact is missing comparison tasks: {', '.join(missing)}.")
    return {**artifact, "tasks_requested": list(task_ids), "runs": [runs[task_id] for task_id in task_ids]}


def _mean_nested_pct(runs: list[dict[str, Any]], component: str, key: str) -> float:
    return _mean_value(runs, ("task_metrics", component, key), scale=100.0)


def _mean_value(runs: list[dict[str, Any]], path: tuple[str, ...], *, scale: float = 1.0) -> float:
    values = [float(value) * scale for run in runs if (value := _nested(run, *path)) is not None]
    return round(fmean(values), 4) if values else 0.0


def _score_delta(after: dict[str, Any], before: dict[str, Any], component: str) -> float | None:
    return _difference(
        _nested(after, "task_metrics", component, "score"),
        _nested(before, "task_metrics", component, "score"),
        scale=100.0,
    )


def _nested(value: Any, *path: str) -> Any:
    current = value
    for key in path:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _rate(numerator: int, denominator: int) -> float:
    return round(100.0 * numerator / denominator, 4) if denominator else 0.0


def _difference(candidate: Any, baseline: Any, *, scale: float = 1.0) -> float | None:
    if candidate is None or baseline is None:
        return None
    return round((float(candidate) - float(baseline)) * scale, 4)


def _relative_change(candidate: Any, baseline: Any) -> float | None:
    if candidate is None or baseline in (None, 0, 0.0):
        return None
    return round(100.0 * (float(candidate) - float(baseline)) / float(baseline), 4)
