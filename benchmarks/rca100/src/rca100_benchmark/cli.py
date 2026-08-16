"""Command-line runner for a framework-neutral RCA100 evaluation."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any, Literal

from rca100_benchmark.dataset import discover_tasks, resolve_dataset_root
from rca100_benchmark.feedback import compare_experiments
from rca100_benchmark.runner import CommandAgent, RCA100Runner


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="rca100-benchmark")
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run", help="Run one blind RCA100 task or the full suite.")
    run.add_argument("--dataset-dir", type=Path, required=True, help="Directory containing RCA100/cases/.")
    selection = run.add_mutually_exclusive_group(required=True)
    selection.add_argument("--task", help="One task id, such as t001.")
    selection.add_argument("--tasks", nargs="+", help="An ordered task subset, such as t001 t065 t073.")
    selection.add_argument("--all", action="store_true", help="Run every task from manifest.txt.")
    run.add_argument(
        "--answer-key-dir", type=Path, default=None, help="Controlled evaluator-only answer_key directory."
    )
    run.add_argument("--timeout-seconds", type=float, default=600)
    run.add_argument("--output", type=Path, default=None, help="Optional JSON output file.")
    run.add_argument("--resume", action="store_true", help="Resume a matching output artifact and retry failed tasks.")
    run.add_argument("--variant", default="default", help="Experiment variant recorded in the artifact.")
    run.add_argument(
        "--agent-command",
        nargs=argparse.REMAINDER,
        help=(
            "Command that reads the public JSON request from stdin and writes prediction JSON to stdout. Must be last."
        ),
    )
    compare = commands.add_parser("compare", help="Compare same-task baseline and candidate artifacts.")
    compare.add_argument("--baseline", type=Path, required=True)
    compare.add_argument("--candidate", type=Path, required=True)
    compare.add_argument("--tasks", nargs="+", default=None, help="Optional task subset present in both artifacts.")
    compare.add_argument("--output", type=Path, default=None)
    compare.add_argument("--min-final-gain-pct", type=float, default=0.0)

    args = parser.parse_args(argv)
    if args.command == "compare":
        result = compare_experiments(
            args.baseline,
            args.candidate,
            task_ids=tuple(args.tasks) if args.tasks else None,
            min_final_gain_percentage_points=args.min_final_gain_pct,
        )
        rendered = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True)
        if args.output is not None:
            _write_json_atomic(args.output, rendered)
        print(rendered)
        return 0
    if args.command != "run":
        return 2
    if not args.agent_command:
        parser.error("--agent-command is required and must be the final option.")
    if args.timeout_seconds <= 0:
        parser.error("--timeout-seconds must be positive.")
    if args.resume and args.output is None:
        parser.error("--resume requires --output.")

    task_ids = _selected_tasks(args)
    runner = RCA100Runner(
        dataset_directory=args.dataset_dir,
        answer_key_directory=args.answer_key_dir,
        agent=CommandAgent(command=tuple(args.agent_command), timeout_seconds=args.timeout_seconds),
    )
    initial_runs: tuple[dict[str, Any], ...] = ()
    started_at = datetime.now(UTC)
    if args.resume:
        previous, started_at = _load_resume_artifact(args.output, task_ids, args)
        initial_runs = tuple(previous.get("runs", []))
    elif args.output is not None:
        _write_artifact(
            args.output,
            _empty_suite(task_ids),
            args=args,
            started_at=started_at,
            status="running",
        )

    def save_progress(progress: dict[str, Any]) -> None:
        if args.output is not None:
            _write_artifact(args.output, progress, args=args, started_at=started_at, status="running")

    result = runner.run_suite(task_ids, initial_runs=initial_runs, on_progress=save_progress)
    artifact = _artifact(result, args=args, started_at=started_at, status="completed")
    rendered = json.dumps(artifact, ensure_ascii=False, indent=2, sort_keys=True)
    if args.output is not None:
        _write_json_atomic(args.output, rendered)
    print(rendered)
    return 1 if result["summary"]["failed"] else 0


def _empty_suite(task_ids: tuple[str, ...]) -> dict[str, Any]:
    return {
        "benchmark": "rca100",
        "tasks_requested": list(task_ids),
        "runs": [],
        "summary": {"completed": 0, "failed": 0, "evaluated": 0, "mean_final_score": None},
    }


def _artifact(
    result: dict[str, Any],
    *,
    args: argparse.Namespace,
    started_at: datetime,
    status: Literal["running", "completed"],
) -> dict[str, Any]:
    return {
        **result,
        "artifact_schema_version": 2,
        "run": {
            "status": status,
            "started_at": started_at.isoformat(),
            "finished_at": datetime.now(UTC).isoformat() if status == "completed" else None,
            "dataset": "RCA100",
            "dataset_root": str(resolve_dataset_root(args.dataset_dir)),
            "task_set_sha256": hashlib.sha256(",".join(result["tasks_requested"]).encode("utf-8")).hexdigest(),
            "variant": args.variant,
            "evaluator_enabled": args.answer_key_dir is not None,
            "timeout_seconds": args.timeout_seconds,
            "agent": {
                "executable": Path(args.agent_command[0]).name,
                "argument_count": len(args.agent_command) - 1,
            },
        },
    }


def _selected_tasks(args: argparse.Namespace) -> tuple[str, ...]:
    available = set(discover_tasks(args.dataset_dir))
    selected = discover_tasks(args.dataset_dir) if args.all else tuple(args.tasks or (args.task,))
    unknown = [task_id for task_id in selected if task_id not in available]
    if unknown:
        raise ValueError(f"RCA100 dataset does not contain requested tasks: {', '.join(unknown)}.")
    if len(set(selected)) != len(selected):
        raise ValueError("RCA100 task selection contains duplicate ids.")
    return selected


def _load_resume_artifact(
    output: Path | None,
    task_ids: tuple[str, ...],
    args: argparse.Namespace,
) -> tuple[dict[str, Any], datetime]:
    if output is None or not output.is_file():
        raise FileNotFoundError("The --resume output artifact does not exist.")
    with output.expanduser().resolve().open(encoding="utf-8") as file:
        artifact = json.load(file)
    if not isinstance(artifact, dict) or artifact.get("benchmark") != "rca100":
        raise ValueError("The resume artifact is not an RCA100 artifact.")
    if tuple(artifact.get("tasks_requested", [])) != task_ids:
        raise ValueError("The resume artifact task set does not match this run.")
    run = artifact.get("run")
    if not isinstance(run, dict) or run.get("variant") != args.variant:
        raise ValueError("The resume artifact variant does not match this run.")
    if run.get("dataset_root") != str(resolve_dataset_root(args.dataset_dir)):
        raise ValueError("The resume artifact dataset root does not match this run.")
    started_at = datetime.fromisoformat(str(run["started_at"]))
    return artifact, started_at


def _write_artifact(
    output: Path,
    result: dict[str, Any],
    *,
    args: argparse.Namespace,
    started_at: datetime,
    status: Literal["running", "completed"],
) -> None:
    rendered = json.dumps(
        _artifact(result, args=args, started_at=started_at, status=status),
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    )
    _write_json_atomic(output, rendered)


def _write_json_atomic(output: Path, rendered: str) -> None:
    output = output.expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=output.parent,
            prefix=f".{output.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temporary.write(rendered)
            temporary.flush()
            os.fsync(temporary.fileno())
            temporary_path = Path(temporary.name)
        temporary_path.replace(output)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


if __name__ == "__main__":
    raise SystemExit(main())
