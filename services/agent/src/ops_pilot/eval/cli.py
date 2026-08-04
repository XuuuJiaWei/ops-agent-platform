"""CLI wiring for eval commands."""

from __future__ import annotations

import argparse
from typing import Any

from ops_pilot.eval.dataset import DEFAULT_CASES_DIR
from ops_pilot.eval.runner import run_eval


def add_eval_subcommands(subcommands: argparse._SubParsersAction[Any]) -> None:
    eval_parser = subcommands.add_parser("eval", help="Run Langfuse-backed agent evaluations.")
    eval_subcommands = eval_parser.add_subparsers(dest="eval_command", required=True)
    run = eval_subcommands.add_parser("run", help="Run an eval dataset experiment.")
    run.add_argument("--dataset-name", required=True)
    run.add_argument("--run-name", default="local")
    run.add_argument("--cases-dir", default=str(DEFAULT_CASES_DIR))
    run.add_argument("--concurrency", type=int, default=4)
    run.add_argument("--min-pass-rate", type=float, default=None)
    run.add_argument("--sync", action="store_true", help="Upsert local YAML cases to Langfuse before running.")


async def run_eval_command(args: argparse.Namespace) -> int:
    if args.eval_command == "run":
        summary = await run_eval(
            args.dataset_name,
            run_name=args.run_name,
            concurrency=args.concurrency,
            min_pass_rate=args.min_pass_rate,
            cases_dir=args.cases_dir,
            sync=args.sync,
        )
        return summary.exit_code
    raise ValueError(f"Unknown eval command: {args.eval_command}")
