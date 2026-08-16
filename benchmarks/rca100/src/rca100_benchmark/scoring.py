"""Deterministic RCA100 scoring, isolated from public case loading."""

from __future__ import annotations

import json
import math
import re
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

from rca100_benchmark.contracts import RCA100Evidence, RCA100Prediction, RCA100ReasoningStep


def load_ground_truth(answer_key_directory: Path, task_id: str) -> dict[str, Any]:
    """Load a controlled answer key only after the agent has completed its task."""

    path = answer_key_directory / f"{task_id}.gt.json"
    if not path.is_file():
        raise FileNotFoundError(f"RCA100 answer key is missing {path.name}.")
    with path.open(encoding="utf-8") as file:
        ground_truth = json.load(file)
    if not isinstance(ground_truth, dict):
        raise ValueError(f"Expected a JSON object in {path}.")
    return ground_truth


def score_prediction(
    prediction: RCA100Prediction | None,
    ground_truth: Mapping[str, Any],
    taxonomy_path: Path,
) -> dict[str, Any]:
    """Calculate published RCA100 entity/fault/process weighting.

    RCA100 specifies ``0.4 * Entity + 0.3 * Fault + 0.3 * Process``. The
    public description defines Process as causal-node and observability-checkpoint
    coverage, so this standalone evaluator gives those two components equal
    weight and compares numeric checkpoint conditions exactly (within float
    precision).
    """

    prediction = prediction or RCA100Prediction()
    raw_ground_truth = _decode_raw_ground_truth(ground_truth)
    expected_entities = _normalized_set(ground_truth.get("root_cause_entities", []))
    predicted_entities = _normalized_set(prediction.root_cause_entities)
    matched_entities = expected_entities & predicted_entities
    entity_precision = _safe_ratio(len(matched_entities), len(predicted_entities))
    entity_recall = _safe_ratio(len(matched_entities), len(expected_entities))
    entity_score = _safe_ratio(2 * entity_precision * entity_recall, entity_precision + entity_recall)

    taxonomy = _load_json(taxonomy_path) if taxonomy_path.is_file() else {}
    expected_types = list(ground_truth.get("root_cause_types", []))
    if not expected_types:
        expected_types = list(raw_ground_truth.get("metadata", {}).get("root_cause_types", []))
    fault_score = _score_fault_types(prediction.root_cause_types, expected_types, taxonomy)

    expected_steps = list(raw_ground_truth.get("reasoning", {}).get("steps", []))
    matched_steps = _match_reasoning_steps(prediction.reasoning, expected_steps, taxonomy)
    node_match_rate = _safe_ratio(len(matched_steps), len(expected_steps))
    expected_evidence = [
        evidence
        for step in expected_steps
        for evidence in step.get("observability", [])
        if evidence.get("required", True)
    ]
    predicted_evidence = [evidence for step in prediction.reasoning for evidence in step.evidence]
    evidence_hit_rate = _evidence_hit_rate(predicted_evidence, expected_evidence)
    process_score = (node_match_rate + evidence_hit_rate) / 2

    return {
        "entity": {"precision": entity_precision, "recall": entity_recall, "score": entity_score},
        "fault": {"score": fault_score},
        "process": {
            "node_match_rate": node_match_rate,
            "evidence_hit_rate": evidence_hit_rate,
            "score": process_score,
        },
        "final_score": 0.4 * entity_score + 0.3 * fault_score + 0.3 * process_score,
    }


def _decode_raw_ground_truth(ground_truth: Mapping[str, Any]) -> dict[str, Any]:
    raw = ground_truth.get("raw_ground_truth", {})
    if isinstance(raw, str):
        decoded = json.loads(raw)
        return decoded if isinstance(decoded, dict) else {}
    return raw if isinstance(raw, dict) else {}


def _match_reasoning_steps(
    predicted: Sequence[RCA100ReasoningStep], expected: Sequence[Mapping[str, Any]], taxonomy: Mapping[str, Any]
) -> list[tuple[RCA100ReasoningStep, Mapping[str, Any]]]:
    available = list(expected)
    matches: list[tuple[RCA100ReasoningStep, Mapping[str, Any]]] = []
    for candidate in predicted:
        for index, target in enumerate(available):
            if (
                _normalize(candidate.target) == _normalize(str(target.get("target", "")))
                and candidate.step_type == target.get("step_type")
                and _fault_credit(candidate.fault_type, str(target.get("fault_id", "")), taxonomy) == 1.0
            ):
                matches.append((candidate, target))
                available.pop(index)
                break
    return matches


def _evidence_hit_rate(predicted: Sequence[RCA100Evidence], expected: Sequence[Mapping[str, Any]]) -> float:
    if not expected:
        return 1.0
    hits = 0
    for target in expected:
        condition = target.get("expected", {})
        for candidate in predicted:
            if (
                _normalize(candidate.source_type) == _normalize(str(target.get("source_type", "")))
                and _normalize(candidate.signal) == _normalize(str(target.get("signal", "")))
                and candidate.comparator == condition.get("comparator")
                and _normalize(candidate.unit) == _normalize(str(condition.get("unit", "")))
                and math.isclose(candidate.value, float(condition.get("value")), rel_tol=1e-6, abs_tol=1e-9)
            ):
                hits += 1
                break
    return hits / len(expected)


def _score_fault_types(predicted: Sequence[str], expected: Sequence[str], taxonomy: Mapping[str, Any]) -> float:
    if not expected:
        return 0.0
    return sum(
        max((_fault_credit(candidate, target, taxonomy) for candidate in predicted), default=0.0) for target in expected
    ) / len(expected)


def _fault_credit(candidate: str, target: str, taxonomy: Mapping[str, Any]) -> float:
    index = _fault_index(taxonomy)
    candidate_definition = index.get(_normalize(candidate))
    target_definition = index.get(_normalize(target))
    if candidate_definition is None or target_definition is None:
        return 1.0 if _normalize(candidate) == _normalize(target) else 0.0
    if candidate_definition["canonical"] == target_definition["canonical"]:
        return 1.0
    if candidate_definition["L2"] == target_definition["L2"]:
        return 0.5
    if candidate_definition["L1"] == target_definition["L1"]:
        return 0.25
    return 0.0


def _fault_index(taxonomy: Mapping[str, Any]) -> dict[str, Mapping[str, str]]:
    index: dict[str, Mapping[str, str]] = {}
    for fault_id, definition in taxonomy.get("fault_definitions", {}).items():
        if not isinstance(definition, Mapping):
            continue
        normalized_definition = {
            "canonical": _normalize(str(definition.get("canonical", fault_id))),
            "L1": str(definition.get("L1", "")),
            "L2": str(definition.get("L2", "")),
        }
        index[_normalize(str(fault_id))] = normalized_definition
        index[normalized_definition["canonical"]] = normalized_definition
    return index


def _load_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as file:
        value = json.load(file)
    return value if isinstance(value, dict) else {}


def _normalized_set(values: Iterable[object]) -> set[str]:
    return {_normalize(str(value)) for value in values if _normalize(str(value))}


def _normalize(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.casefold())


def _safe_ratio(numerator: int | float, denominator: int | float) -> float:
    return float(numerator / denominator) if denominator else 0.0
