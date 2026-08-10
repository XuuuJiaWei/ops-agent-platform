from __future__ import annotations

import pytest

from ops_pilot.eval.dataset import (
    DEFAULT_CASES_DIR,
    EvalDatasetError,
    load_cases_from_yaml,
    validate_dataset_schema,
    validate_expected_tool_names,
)


def test_load_cases_from_yaml_directory(tmp_path):
    (tmp_path / "smoke.yaml").write_text(
        "cases:\n"
        "  - id: one\n"
        "    prompt: say hi\n"
        "    category: smoke\n"
        "    expected_tools: [local_echo]\n"
        "    tags: [local]\n"
        "  - id: two\n"
        "    prompt: add\n"
        "    category: smoke\n"
        "    expected_output: '3'\n"
        "    timeout_s: 5\n",
        encoding="utf-8",
    )

    cases = load_cases_from_yaml(tmp_path)

    assert [case.id for case in cases] == ["one", "two"]
    assert cases[0].expected_tools == ("local_echo",)
    assert cases[0].metadata()["category"] == "smoke"
    assert cases[0].metadata()["split"] == "validation"
    assert cases[0].metadata()["dataset_schema_version"] == 3
    assert cases[1].timeout_s == 5.0


def test_load_cases_accepts_top_level_list(tmp_path):
    (tmp_path / "cases.yaml").write_text(
        "- id: solo\n  prompt: hello\n  category: smoke\n",
        encoding="utf-8",
    )

    cases = load_cases_from_yaml(tmp_path / "cases.yaml")

    assert [case.id for case in cases] == ["solo"]


def test_load_cases_rejects_duplicate_ids(tmp_path):
    (tmp_path / "cases.yaml").write_text(
        "cases:\n"
        "  - id: dup\n    prompt: one\n    category: smoke\n"
        "  - id: dup\n    prompt: two\n    category: smoke\n",
        encoding="utf-8",
    )

    with pytest.raises(EvalDatasetError, match="duplicate eval case id"):
        load_cases_from_yaml(tmp_path / "cases.yaml")


def test_load_cases_rejects_invalid_sequence_fields(tmp_path):
    path = tmp_path / "cases.yaml"
    path.write_text(
        "cases:\n  - id: bad\n    prompt: one\n    category: smoke\n    expected_tools: local_echo\n",
        encoding="utf-8",
    )

    with pytest.raises(EvalDatasetError, match="expected_tools"):
        load_cases_from_yaml(path)


def test_load_cases_rejects_invalid_yaml(tmp_path):
    path = tmp_path / "cases.yaml"
    path.write_text("cases:\n  - id: bad\n    prompt: [unclosed\n", encoding="utf-8")

    with pytest.raises(EvalDatasetError, match="invalid YAML"):
        load_cases_from_yaml(path)


def test_ops_diagnosis_cases_have_a_bounded_agent_budget() -> None:
    cases = load_cases_from_yaml(DEFAULT_CASES_DIR / "ops_scenarios.yaml")
    diagnosis_cases = [case for case in cases if case.category == "diagnosis"]

    assert len(diagnosis_cases) == 8
    assert all(case.timeout_s == 300 for case in diagnosis_cases)


def test_product_catalog_fault_has_target_evaluation_context() -> None:
    cases = load_cases_from_yaml(DEFAULT_CASES_DIR / "ops_scenarios.yaml")
    case = next(case for case in cases if case.id == "otel-product-catalog-failure")

    assert case.inject is not None
    assert case.inject.target == {"product_id": "OLJCESPC7Z"}


def test_expected_tool_names_are_validated_against_runtime_catalog() -> None:
    cases = load_cases_from_yaml(DEFAULT_CASES_DIR / "ops_scenarios.yaml")
    available = {
        "search_traces",
        "query",
        "get_services",
        "pods_list_in_namespace",
        "get_trace_errors",
    }

    validate_expected_tool_names(cases, available)


def test_stale_expected_tool_name_fails_fast(tmp_path) -> None:
    path = tmp_path / "cases.yaml"
    path.write_text(
        "cases:\n  - id: stale\n    prompt: inspect\n    category: validation\n    expected_tools: [old_name]\n",
        encoding="utf-8",
    )

    with pytest.raises(EvalDatasetError, match="stale: old_name"):
        validate_expected_tool_names(load_cases_from_yaml(path), {"new_name"})


def test_stale_online_dataset_schema_fails_fast() -> None:
    items = [{"metadata": {"id": "old", "dataset_schema_version": 2}}]

    with pytest.raises(EvalDatasetError, match="ops_pilot eval sync"):
        validate_dataset_schema(items)
