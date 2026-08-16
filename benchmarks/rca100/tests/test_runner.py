from __future__ import annotations

import json
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from rca100_benchmark.contracts import RCA100Prediction
from rca100_benchmark.runner import RCA100Runner
from rca100_benchmark.scoring import score_prediction


def _write_public_case(root: Path) -> None:
    case = root / "cases" / "t001"
    case.mkdir(parents=True)
    (root / "manifest.txt").write_text("t001\n", encoding="utf-8")
    (case / "task.json").write_text(
        json.dumps(
            {
                "task_id": "t001",
                "prompt_text": "checkout error alert",
                "alert_entity": {"entity_name": "checkout"},
                "available_modalities": ["metrics", "logs", "traces", "events", "alerts", "topology"],
            }
        ),
        encoding="utf-8",
    )
    for modality in ("metrics", "logs", "traces", "events", "alerts"):
        pq.write_table(pa.table({"time": [1], "source": [modality]}), case / f"{modality}.parquet")
    (case / "topology.json").write_text(json.dumps({"entities": [], "edges": []}), encoding="utf-8")


def _ground_truth() -> dict[str, object]:
    return {
        "root_cause_entities": ["payment"],
        "root_cause_types": ["httpError5xx"],
        "raw_ground_truth": json.dumps(
            {
                "reasoning": {
                    "steps": [
                        {
                            "step_type": "cause",
                            "target": "payment",
                            "fault_id": "F014-httpError5xx",
                            "observability": [
                                {
                                    "source_type": "metric",
                                    "signal": "error_rate",
                                    "expected": {"comparator": ">=", "value": 0.5, "unit": "ratio"},
                                }
                            ],
                        }
                    ]
                }
            }
        ),
    }


def _write_answer_key(answer_key: Path) -> None:
    answer_key.mkdir()
    (answer_key / "taxonomy.json").write_text(
        json.dumps(
            {
                "fault_definitions": {
                    "F014-httpError5xx": {"canonical": "httperror5xx", "L1": "2", "L2": "2.1"},
                    "F029-redisUnavailable": {"canonical": "redisunavailable", "L1": "2", "L2": "2.1"},
                }
            }
        ),
        encoding="utf-8",
    )
    (answer_key / "t001.gt.json").write_text(json.dumps(_ground_truth()), encoding="utf-8")


class Agent:
    public_input: dict[str, object] | None = None

    def diagnose(self, public_input: dict[str, object]) -> str:
        self.public_input = public_input
        return json.dumps(
            {
                "root_cause_entities": ["payment"],
                "root_cause_types": ["httpError5xx"],
                "reasoning": [
                    {
                        "step_type": "cause",
                        "target": "payment",
                        "fault_type": "httpError5xx",
                        "evidence": [
                            {
                                "source_type": "metric",
                                "signal": "error_rate",
                                "comparator": ">=",
                                "value": 0.5,
                                "unit": "ratio",
                            }
                        ],
                    }
                ],
            }
        )


def test_runner_is_framework_neutral_and_scores_only_after_agent_output(tmp_path: Path) -> None:
    dataset = tmp_path / "public-rca100"
    answer_key = tmp_path / "controlled-answer-key"
    _write_public_case(dataset)
    _write_answer_key(answer_key)
    agent = Agent()

    result = RCA100Runner(dataset, agent, answer_key).run_task("t001")

    assert agent.public_input is not None
    assert agent.public_input["task_id"] == "t001"
    assert agent.public_input["case_directory"] == str((dataset / "cases" / "t001").resolve())
    assert "answer_key" not in json.dumps(agent.public_input)
    assert result["task_metrics"]["final_score"] == 1.0


def test_runner_rejects_an_answer_key_inside_the_public_dataset(tmp_path: Path) -> None:
    _write_public_case(tmp_path)
    (tmp_path / "answer_key").mkdir()

    with pytest.raises(ValueError, match="outside the public dataset"):
        RCA100Runner(tmp_path, Agent(), tmp_path / "answer_key")


def test_fault_scoring_uses_taxonomy_partial_credit(tmp_path: Path) -> None:
    answer_key = tmp_path / "answer-key"
    _write_answer_key(answer_key)
    prediction = RCA100Prediction.model_validate(
        {"root_cause_entities": ["payment"], "root_cause_types": ["redisUnavailable"], "reasoning": []}
    )

    scores = score_prediction(prediction, _ground_truth(), answer_key / "taxonomy.json")

    assert scores["entity"]["score"] == 1.0
    assert scores["fault"]["score"] == 0.5
    assert scores["process"]["score"] == 0.0
    assert scores["final_score"] == pytest.approx(0.55)
