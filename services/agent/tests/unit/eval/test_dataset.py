from __future__ import annotations

import pytest

from ops_pilot.eval.dataset import EvalDatasetError, load_cases_from_yaml


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
