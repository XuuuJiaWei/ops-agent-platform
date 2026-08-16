"""Public RCA100 case discovery and blind task contracts."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pyarrow.parquet import ParquetFile

from rca100_benchmark.contracts import RCA100Prediction

_TASK_ID = re.compile(r"t\d{3}")
_PARQUET_MODALITIES = ("metrics", "logs", "traces", "events", "alerts")


@dataclass(frozen=True)
class RCA100Case:
    """One public RCA100 task; it never loads ground-truth annotations."""

    dataset_root: Path
    task_id: str
    directory: Path
    task: dict[str, Any]

    @classmethod
    def load(cls, dataset_directory: Path, task_id: str) -> RCA100Case:
        if not _TASK_ID.fullmatch(task_id):
            raise ValueError("RCA100 task ids must have the form t001 through t103.")
        dataset_root = resolve_dataset_root(dataset_directory)
        directory = (dataset_root / "cases" / task_id).resolve()
        cases_root = (dataset_root / "cases").resolve()
        if not directory.is_dir() or not directory.is_relative_to(cases_root):
            raise FileNotFoundError(f"RCA100 case {task_id!r} was not found under {cases_root}.")
        task_path = directory / "task.json"
        task = _load_json(task_path)
        if task.get("task_id") != task_id:
            raise ValueError(f"RCA100 task.json for {task_id!r} has an unexpected task_id.")
        return cls(dataset_root=dataset_root, task_id=task_id, directory=directory, task=task)

    def validate_public_observations(self) -> None:
        """Confirm the complete agent-visible surface exists before evaluating a case."""

        missing = [
            name
            for name in (*[f"{modality}.parquet" for modality in _PARQUET_MODALITIES], "topology.json")
            if not (self.directory / name).is_file()
        ]
        if missing:
            raise FileNotFoundError(f"RCA100 case {self.task_id!r} is missing: {', '.join(missing)}.")

    def public_input(self) -> dict[str, Any]:
        """The complete input contract supplied to an external agent command."""

        self.validate_public_observations()
        return {
            "benchmark": "rca100",
            "task_id": self.task_id,
            "task": self.task,
            "case_directory": str(self.directory),
            "parquet_schemas": {
                modality: ParquetFile(self.directory / f"{modality}.parquet").schema_arrow.names
                for modality in _PARQUET_MODALITIES
            },
            "topology_path": str(self.directory / "topology.json"),
            "prediction_schema": RCA100Prediction.model_json_schema(),
        }


def discover_tasks(dataset_directory: Path) -> tuple[str, ...]:
    """Read the publisher's manifest or, when absent, the case directories."""

    dataset_root = resolve_dataset_root(dataset_directory)
    manifest = dataset_root / "manifest.txt"
    if manifest.is_file():
        tasks = tuple(line.strip() for line in manifest.read_text(encoding="utf-8").splitlines() if line.strip())
    else:
        tasks = tuple(path.name for path in sorted((dataset_root / "cases").iterdir()) if path.is_dir())
    if not tasks or any(not _TASK_ID.fullmatch(task_id) for task_id in tasks):
        raise ValueError(f"RCA100 manifest under {dataset_root} does not contain valid task ids.")
    return tasks


def resolve_dataset_root(directory: Path) -> Path:
    """Accept either the RCA100 directory or an AgenticOpsEval checkout root."""

    candidate = directory.expanduser().resolve()
    for dataset_root in (candidate, candidate / "RCA100"):
        if (dataset_root / "cases").is_dir():
            return dataset_root
    raise FileNotFoundError(
        f"RCA100 data was not found at {candidate}. Pass the directory containing cases/ and manifest.txt."
    )


def _load_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(f"RCA100 case is missing {path.name}.")
    with path.open(encoding="utf-8") as file:
        value = json.load(file)
    if not isinstance(value, dict):
        raise ValueError(f"Expected a JSON object in {path}.")
    return value
