"""Command-line runner for a framework-neutral RCA100 evaluation."""

from __future__ import annotations

import argparse
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any, Literal

from rca100_benchmark.dataset import discover_tasks
from rca100_benchmark.runner import CommandAgent, RCA100Runner


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="rca100-benchmark")
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run", help="Run one blind RCA100 task or the full suite.")
    run.add_argument("--dataset-dir", type=Path, required=True, help="Directory containing RCA100/cases/.")
    selection = run.add_mutually_exclusive_group(required=True)
    selection.add_argument("--task", help="One task id, such as t001.")
    selection.add_argument("--all", action="store_true", help="Run every task from manifest.txt.")
    run.add_argument(
        "--answer-key-dir", type=Path, default=None, help="Controlled evaluator-only answer_key directory."
    )
    run.add_argument("--timeout-seconds", type=float, default=600)
    run.add_argument("--output", type=Path, default=None, help="Optional JSON output file.")
    run.add_argument(
        "--agent-command",
        nargs=argparse.REMAINDER,
        help=(
            "Command that reads the public JSON request from stdin and writes prediction JSON to stdout. Must be last."
        ),
    )

    args = parser.parse_args(argv)
    if args.command != "run":
        return 2
    if not args.agent_command:
        parser.error("--agent-command is required and must be the final option.")
    if args.timeout_seconds <= 0:
        parser.error("--timeout-seconds must be positive.")

    task_ids = discover_tasks(args.dataset_dir) if args.all else (args.task,)
    runner = RCA100Runner(
        dataset_directory=args.dataset_dir,
        answer_key_directory=args.answer_key_dir,
        agent=CommandAgent(command=tuple(args.agent_command), timeout_seconds=args.timeout_seconds),
    )
    started_at = datetime.now(UTC)
    if args.output is not None:
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

    result = runner.run_suite(task_ids, on_progress=save_progress)
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
        "artifact_schema_version": 1,
        "run": {
            "status": status,
            "started_at": started_at.isoformat(),
            "finished_at": datetime.now(UTC).isoformat() if status == "completed" else None,
            "dataset": "RCA100",
            "evaluator_enabled": args.answer_key_dir is not None,
            "timeout_seconds": args.timeout_seconds,
            "agent": {
                "executable": Path(args.agent_command[0]).name,
                "argument_count": len(args.agent_command) - 1,
            },
        },
    }


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
