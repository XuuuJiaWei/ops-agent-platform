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
    run.add_argument(
        "--only",
        nargs="+",
        default=None,
        metavar="CASE_ID",
        help="Run only these case IDs. Space-separated, e.g. --only otel-safety-no-pod-delete.",
    )

    sync = eval_subcommands.add_parser(
        "sync",
        help="Upsert local YAML cases to a Langfuse dataset without running the agent.",
    )
    sync.add_argument("--dataset-name", required=True)
    sync.add_argument("--cases-dir", default=str(DEFAULT_CASES_DIR))

    calibration = eval_subcommands.add_parser(
        "calibration",
        help="Verify the LLM judges against known-answer sentinels (no agent/cluster; seconds).",
    )
    calibration.add_argument("--run-name", default="calibration")
    calibration.add_argument("--concurrency", type=int, default=4)


def add_chaos_subcommands(subcommands: argparse._SubParsersAction[Any]) -> None:
    chaos_parser = subcommands.add_parser(
        "chaos",
        help="Control OTel-demo flagd fault flags and run the chaos->eval loop.",
    )
    chaos_subcommands = chaos_parser.add_subparsers(dest="chaos_command", required=True)

    chaos_subcommands.add_parser("reset", help="Set every fault flag to off (safety net).")
    chaos_subcommands.add_parser("status", help="Show the current variant of every flag.")

    set_flag_parser = chaos_subcommands.add_parser("set", help="Set one fault flag to a variant.")
    set_flag_parser.add_argument("flag", help="Flag key, e.g. paymentFailure.")
    set_flag_parser.add_argument("variant", help="Variant, e.g. on / 50% / 10sec.")

    run = chaos_subcommands.add_parser(
        "run",
        help="Enable one flag per inject-bearing case, run it online, and record to Langfuse.",
    )
    run.add_argument("--dataset-name", default="otel_scenarios")
    run.add_argument("--run-name", default=None)
    run.add_argument("--cases-dir", default=str(DEFAULT_CASES_DIR))
    run.add_argument("--only", nargs="+", default=None, help="Restrict to these case ids.")


async def run_eval_command(args: argparse.Namespace) -> int:
    if args.eval_command == "run":
        summary = await run_eval(
            args.dataset_name,
            run_name=args.run_name,
            concurrency=args.concurrency,
            min_pass_rate=args.min_pass_rate,
            cases_dir=args.cases_dir,
            only=args.only,
        )
        return summary.exit_code
    if args.eval_command == "calibration":
        # Judge-drift check: sentinel cases carry fixed_output + expected_judge_pass,
        # so no agent or cluster runs. judge_calibration_agreement is a HARD gate.
        calibration_cases = DEFAULT_CASES_DIR / "judge_calibration.yaml"
        summary = await run_eval(
            "otel_scenarios",
            run_name=args.run_name,
            concurrency=args.concurrency,
            cases_dir=calibration_cases,
        )
        return summary.exit_code
    if args.eval_command == "sync":
        return _run_sync_command(args)
    raise ValueError(f"Unknown eval command: {args.eval_command}")


def _run_sync_command(args: argparse.Namespace) -> int:
    from ops_pilot.config.settings import load_settings
    from ops_pilot.eval.dataset import (
        close_langfuse_client,
        create_langfuse_client,
        langfuse_client_is_reachable,
        load_cases_from_yaml,
        sync_cases_to_langfuse,
    )

    settings = load_settings()
    if not settings.langfuse_enabled:
        print(
            "error: Langfuse is not configured. Set LANGFUSE_PUBLIC_KEY and "
            "LANGFUSE_SECRET_KEY in .env and langfuse.base_url in config.yaml."
        )
        return 1

    cases = load_cases_from_yaml(args.cases_dir)
    langfuse = create_langfuse_client(settings)
    try:
        if not langfuse_client_is_reachable(langfuse):
            print(
                f"error: Langfuse is unreachable at {settings.langfuse_base_url} "
                "(auth_check failed). Check the base URL and API keys."
            )
            return 1
        count = sync_cases_to_langfuse(cases, args.dataset_name, settings, langfuse=langfuse)
    finally:
        close_langfuse_client(langfuse)

    print(f"uploaded {count} eval cases to Langfuse dataset '{args.dataset_name}' at {settings.langfuse_base_url}.")
    return 0


async def run_chaos_command(args: argparse.Namespace) -> int:
    from ops_pilot.config.settings import load_settings
    from ops_pilot.eval import chaos

    settings = load_settings()
    command = args.chaos_command

    if command == "status":
        variants = chaos.current_variants(settings)
        _print_flag_variants(variants)
        return 0
    if command == "reset":
        variants = chaos.reset_all(settings)
        print("reset all fault flags to off.")
        _print_flag_variants(variants)
        return 0
    if command == "set":
        chaos.set_flag(settings, args.flag, args.variant)
        print(f"set flag '{args.flag}' to '{args.variant}'.")
        return 0
    if command == "run":
        return await chaos.run_chaos_eval(
            settings=settings,
            dataset_name=args.dataset_name,
            only=args.only,
            cases_dir=args.cases_dir,
            run_name=args.run_name,
        )
    raise ValueError(f"Unknown chaos command: {command}")


def _print_flag_variants(variants: dict[str, str]) -> None:
    from ops_pilot.eval.chaos import FAULT_FLAGS, OFF_VARIANT

    for flag in sorted(variants):
        variant = variants[flag]
        is_active_fault = flag in FAULT_FLAGS and variant != OFF_VARIANT
        marker = "  <-- ACTIVE FAULT" if is_active_fault else ""
        print(f"  {flag:32} {variant}{marker}")
