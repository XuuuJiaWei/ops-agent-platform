"""Framework-neutral RCA100 runner and a JSON-over-stdio agent adapter."""

from __future__ import annotations

import json
import subprocess
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from pydantic import ValidationError

from rca100_benchmark.contracts import RCA100Prediction
from rca100_benchmark.dataset import RCA100Case, resolve_dataset_root
from rca100_benchmark.scoring import load_ground_truth, score_prediction


class RCA100Agent(Protocol):
    """Minimal contract for any agent implementation or test double."""

    def diagnose(self, public_input: dict[str, object]) -> str: ...


@dataclass(frozen=True)
class CommandAgent:
    """Run an external agent executable with one public JSON request on stdin."""

    command: tuple[str, ...]
    timeout_seconds: float = 600
    working_directory: Path | None = None

    def diagnose(self, public_input: dict[str, object]) -> str:
        completed = subprocess.run(
            self.command,
            input=json.dumps(public_input, ensure_ascii=False),
            text=True,
            encoding="utf-8",
            capture_output=True,
            cwd=self.working_directory,
            timeout=self.timeout_seconds,
            check=False,
        )
        if completed.returncode != 0:
            stderr = completed.stderr.strip()
            raise RuntimeError(f"Agent command exited with status {completed.returncode}: {stderr}")
        return completed.stdout


@dataclass(frozen=True)
class RCA100Runner:
    """Execute a blind task without depending on any particular agent runtime."""

    dataset_directory: Path
    agent: RCA100Agent
    answer_key_directory: Path | None = None

    def __post_init__(self) -> None:
        if self.answer_key_directory is not None:
            answer_key = self.answer_key_directory.expanduser().resolve()
            dataset_root = resolve_dataset_root(self.dataset_directory)
            if answer_key.is_relative_to(dataset_root):
                raise ValueError("Put the controlled RCA100 answer key outside the public dataset directory.")

    def run_task(self, task_id: str) -> dict[str, Any]:
        case = RCA100Case.load(self.dataset_directory, task_id)
        started = time.perf_counter()
        raw_response = self.agent.diagnose(case.public_input())
        prediction: RCA100Prediction | None
        prediction_error: str | None = None
        try:
            prediction = parse_prediction(raw_response)
        except ValueError as exc:
            prediction = None
            prediction_error = str(exc)

        result: dict[str, Any] = {
            "benchmark": "rca100",
            "task_id": task_id,
            "prediction": prediction.model_dump(mode="json") if prediction is not None else None,
            "prediction_error": prediction_error,
            "raw_response": raw_response,
            "benchmark_metrics": {"elapsed_s": time.perf_counter() - started},
        }
        if self.answer_key_directory is None:
            result["evaluation_available"] = False
            return result

        answer_key = self.answer_key_directory.expanduser().resolve()
        result["evaluation_available"] = True
        result["task_metrics"] = score_prediction(
            prediction,
            load_ground_truth(answer_key, task_id),
            answer_key / "taxonomy.json",
        )
        return result

    def run_suite(self, task_ids: Sequence[str]) -> dict[str, Any]:
        runs: list[dict[str, Any]] = []
        for task_id in task_ids:
            try:
                runs.append(self.run_task(task_id))
            except Exception as exc:  # noqa: BLE001 - retain results for every independently runnable task.
                runs.append({"benchmark": "rca100", "task_id": task_id, "error": str(exc)})
        scores = [
            float(metrics["final_score"])
            for run in runs
            if isinstance((metrics := run.get("task_metrics")), dict) and "final_score" in metrics
        ]
        return {
            "benchmark": "rca100",
            "tasks_requested": list(task_ids),
            "runs": runs,
            "summary": {
                "completed": sum("error" not in run for run in runs),
                "failed": sum("error" in run for run in runs),
                "evaluated": len(scores),
                "mean_final_score": sum(scores) / len(scores) if scores else None,
            },
        }


def parse_prediction(response: str) -> RCA100Prediction:
    """Extract a single valid prediction object from a command's stdout."""

    decoder = json.JSONDecoder()
    for index, character in enumerate(response):
        if character != "{":
            continue
        try:
            payload, _ = decoder.raw_decode(response[index:])
        except json.JSONDecodeError:
            continue
        try:
            return RCA100Prediction.model_validate(payload)
        except ValidationError as exc:
            raise ValueError(f"Agent output does not match the RCA100 prediction schema: {exc}") from exc
    raise ValueError("Agent output does not contain an RCA100 prediction JSON object.")


AgentFactory = Callable[[], RCA100Agent]
