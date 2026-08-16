"""Command-line runner for a framework-neutral RCA100 evaluation."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

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
    result = runner.run_suite(task_ids)
    rendered = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered)
    return 1 if result["summary"]["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
