from __future__ import annotations

from types import SimpleNamespace

import pytest
from langfuse.api import NotFoundError

from ops_pilot.eval.dataset import (
    EvalDatasetError,
    langfuse_client_is_reachable,
    load_cases_from_yaml,
    sync_and_verify_cases_to_langfuse,
    validate_dataset_matches_local,
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
    assert cases[0].metadata()["dataset_schema_version"] == 4
    assert cases[1].timeout_s == 5.0


def test_load_cases_accepts_top_level_list(tmp_path):
    (tmp_path / "cases.yaml").write_text(
        "- id: solo\n  prompt: hello\n  category: smoke\n",
        encoding="utf-8",
    )

    cases = load_cases_from_yaml(tmp_path / "cases.yaml")

    assert [case.id for case in cases] == ["solo"]


def test_sentinel_and_provenance_fields_parse(tmp_path):
    (tmp_path / "cases.yaml").write_text(
        "cases:\n"
        "  - id: __sentinel\n"
        "    prompt: incident\n"
        "    category: sentinel\n"
        "    source: sentinel\n"
        "    version: '2025-11'\n"
        "    rubric: ground truth\n"
        "    fixed_output: canned agent text\n"
        "    expected_judge_pass: false\n",
        encoding="utf-8",
    )

    (case,) = load_cases_from_yaml(tmp_path / "cases.yaml")

    assert case.source == "sentinel"
    assert case.version == "2025-11"
    assert case.fixed_output == "canned agent text"
    assert case.expected_judge_pass is False
    metadata = case.metadata()
    assert metadata["fixed_output"] == "canned agent text"
    assert metadata["expected_judge_pass"] is False
    assert metadata["source"] == "sentinel"


def test_defaults_for_provenance_fields(tmp_path):
    (tmp_path / "cases.yaml").write_text(
        "- id: plain\n  prompt: hello\n  category: smoke\n",
        encoding="utf-8",
    )

    (case,) = load_cases_from_yaml(tmp_path / "cases.yaml")

    assert case.source == "synthetic"
    assert case.version is None
    assert case.fixed_output is None
    assert case.expected_judge_pass is None


def test_expected_judge_pass_must_be_boolean(tmp_path):
    (tmp_path / "cases.yaml").write_text(
        "- id: bad\n  prompt: hi\n  category: smoke\n  expected_judge_pass: yes-please\n",
        encoding="utf-8",
    )

    with pytest.raises(EvalDatasetError, match="expected_judge_pass"):
        load_cases_from_yaml(tmp_path / "cases.yaml")


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


def test_validate_dataset_matches_local_rejects_stale_cloud_item(tmp_path) -> None:
    path = tmp_path / "cases.yaml"
    path.write_text("- id: local\n  prompt: current\n  category: diagnosis\n", encoding="utf-8")
    case = load_cases_from_yaml(path)[0]
    online = {
        "id": case.id,
        "input": "stale",
        "expected_output": case.expected_output,
        "metadata": case.metadata(),
    }

    with pytest.raises(EvalDatasetError, match="input differs"):
        validate_dataset_matches_local([case], [online])


def test_validate_dataset_matches_local_accepts_exact_mirror(tmp_path) -> None:
    path = tmp_path / "cases.yaml"
    path.write_text("- id: local\n  prompt: current\n  category: diagnosis\n", encoding="utf-8")
    case = load_cases_from_yaml(path)[0]
    online = {
        "id": case.id,
        "input": case.prompt,
        "expected_output": case.expected_output,
        "metadata": case.metadata(),
    }

    validate_dataset_matches_local([case], [online])


def test_sync_and_verify_uses_local_truth_and_order(tmp_path) -> None:
    path = tmp_path / "cases.yaml"
    path.write_text(
        "- id: first\n  prompt: one\n  category: diagnosis\n- id: second\n  prompt: two\n  category: diagnosis\n",
        encoding="utf-8",
    )
    cases = load_cases_from_yaml(path)

    class FakeLangfuse:
        items: dict[str, SimpleNamespace] = {}

        def create_dataset(self, **_kwargs) -> None:
            pass

        def create_dataset_item(self, **kwargs) -> None:
            self.items[kwargs["id"]] = SimpleNamespace(
                id=kwargs["id"],
                input=kwargs["input"],
                expected_output=kwargs["expected_output"],
                metadata=kwargs["metadata"],
            )

        def flush(self) -> None:
            pass

        def get_dataset(self, _name):
            return SimpleNamespace(items=list(reversed(self.items.values())))

    result = sync_and_verify_cases_to_langfuse(cases, "chaos", langfuse=FakeLangfuse())

    assert [item.id for item in result] == ["first", "second"]
    assert [item.input for item in result] == ["one", "two"]


def test_langfuse_reachability_fails_closed_without_a_second_retry_layer() -> None:
    class FakeLangfuse:
        def auth_check(self):
            raise TimeoutError("TLS")

    assert langfuse_client_is_reachable(FakeLangfuse()) is False


def test_sync_and_verify_creates_a_missing_dataset_via_sdk_not_found(tmp_path) -> None:
    path = tmp_path / "cases.yaml"
    path.write_text("- id: first\n  prompt: one\n  category: diagnosis\n", encoding="utf-8")
    cases = load_cases_from_yaml(path)

    class FakeLangfuse:
        gets = 0
        creates = 0
        items: dict[str, SimpleNamespace] = {}

        def get_dataset(self, _name):
            self.gets += 1
            if self.gets == 1:
                raise NotFoundError(body={"message": "missing"})
            return SimpleNamespace(items=list(self.items.values()))

        def create_dataset(self, **_kwargs):
            self.creates += 1

        def create_dataset_item(self, **kwargs):
            self.items[kwargs["id"]] = SimpleNamespace(
                id=kwargs["id"],
                input=kwargs["input"],
                expected_output=kwargs["expected_output"],
                metadata=kwargs["metadata"],
            )

        def flush(self):
            pass

    client = FakeLangfuse()

    result = sync_and_verify_cases_to_langfuse(cases, "new", langfuse=client)

    assert [item.id for item in result] == ["first"]
    assert client.gets == 3
    assert client.creates == 1


def test_sync_skips_items_that_already_match_local_truth(tmp_path) -> None:
    path = tmp_path / "cases.yaml"
    path.write_text("- id: current\n  prompt: same\n  category: diagnosis\n", encoding="utf-8")
    case = load_cases_from_yaml(path)[0]

    class FakeLangfuse:
        creates = 0
        item = SimpleNamespace(
            id=case.id,
            input=case.prompt,
            expected_output=case.expected_output,
            metadata=case.metadata(),
        )

        def create_dataset(self, **_kwargs) -> None:
            pass

        def get_dataset(self, _name):
            return SimpleNamespace(items=[self.item])

        def create_dataset_item(self, **_kwargs) -> None:
            self.creates += 1

    client = FakeLangfuse()

    result = sync_and_verify_cases_to_langfuse([case], "chaos", langfuse=client)

    assert client.creates == 0
    assert result == (client.item,)
