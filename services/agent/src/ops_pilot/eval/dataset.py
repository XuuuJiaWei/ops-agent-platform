"""Dataset case schema and Langfuse sync helpers."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ops_pilot.config.paths import SERVICE_ROOT, resolve_path
from ops_pilot.config.settings import Settings

DEFAULT_CASES_DIR = SERVICE_ROOT / "eval" / "cases"
DATASET_SCHEMA_VERSION = 2


class EvalDatasetError(ValueError):
    """Raised when an eval dataset case file is malformed."""


@dataclass(frozen=True)
class InjectSpec:
    """A chaos fault to inject before running a diagnosis case.

    ``flag``/``variant`` drive the flagd ConfigMap (see ``eval/chaos.py``);
    ``settle_s`` is how long to wait after enabling the flag for signals to
    appear, ``cooldown_s`` how long to drain after disabling it. ``signal`` is
    parsed-but-unused, reserved for a future readiness-poll (Phase 2).

    This lives in ``EvalCase.metadata()`` only — it NEVER reaches the agent's
    prompt (``to_experiment_item()["input"]``), so the injected fault stays
    ground truth the agent must discover, not a leaked answer.
    """

    flag: str
    variant: str
    settle_s: float = 120.0
    cooldown_s: float = 30.0
    signal: Mapping[str, Any] | None = None

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any], *, source: str) -> InjectSpec:
        from ops_pilot.eval.chaos import FAULT_FLAGS

        flag = _required_string(data, "flag", source)
        if flag not in FAULT_FLAGS:
            available = ", ".join(sorted(FAULT_FLAGS))
            raise EvalDatasetError(f"{source}: inject.flag '{flag}' is not a known fault flag. Available: {available}.")
        variant = _required_string(data, "variant", source)
        settle_s = _float_value(data.get("settle_s", 120.0), "inject.settle_s", source)
        cooldown_s = _float_value(data.get("cooldown_s", 30.0), "inject.cooldown_s", source)
        if settle_s < 0 or cooldown_s < 0:
            raise EvalDatasetError(f"{source}: inject.settle_s and inject.cooldown_s must be >= 0.")
        signal = data.get("signal")
        if signal is not None and not isinstance(signal, Mapping):
            raise EvalDatasetError(f"{source}: inject.signal must be a mapping if present.")
        return cls(
            flag=flag,
            variant=variant,
            settle_s=settle_s,
            cooldown_s=cooldown_s,
            signal=dict(signal) if isinstance(signal, Mapping) else None,
        )

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "flag": self.flag,
            "variant": self.variant,
            "settle_s": self.settle_s,
            "cooldown_s": self.cooldown_s,
        }
        if self.signal is not None:
            payload["signal"] = dict(self.signal)
        return payload


@dataclass(frozen=True)
class EvalCase:
    id: str
    prompt: str
    category: str
    split: str = "validation"
    expected_output: str | None = None
    expected_tools: tuple[str, ...] = field(default_factory=tuple)
    forbidden_tools: tuple[str, ...] = field(default_factory=tuple)
    rubric: str | None = None
    tags: tuple[str, ...] = field(default_factory=tuple)
    timeout_s: float = 60.0
    inject: InjectSpec | None = None

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any], *, source: str = "<eval-case>") -> EvalCase:
        case_id = _required_string(data, "id", source)
        prompt = _required_string(data, "prompt", source)
        category = _required_string(data, "category", source)
        split = _optional_string(data.get("split"), "split", source) or "validation"
        expected_output = _optional_string(data.get("expected_output"), "expected_output", source)
        rubric = _optional_string(data.get("rubric"), "rubric", source)
        timeout_s = _float_value(data.get("timeout_s", 60.0), "timeout_s", source)
        if timeout_s <= 0:
            raise EvalDatasetError(f"{source}: timeout_s must be greater than 0.")

        inject_data = data.get("inject")
        if inject_data is not None and not isinstance(inject_data, Mapping):
            raise EvalDatasetError(f"{source}: field 'inject' must be a mapping.")
        inject = InjectSpec.from_mapping(inject_data, source=source) if inject_data is not None else None

        return cls(
            id=case_id,
            prompt=prompt,
            category=category,
            split=split,
            expected_output=expected_output,
            expected_tools=_string_tuple(data.get("expected_tools", ()), "expected_tools", source),
            forbidden_tools=_string_tuple(data.get("forbidden_tools", ()), "forbidden_tools", source),
            rubric=rubric,
            tags=_string_tuple(data.get("tags", ()), "tags", source),
            timeout_s=timeout_s,
            inject=inject,
        )

    def metadata(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "category": self.category,
            "split": self.split,
            "dataset_schema_version": DATASET_SCHEMA_VERSION,
            "expected_tools": list(self.expected_tools),
            "forbidden_tools": list(self.forbidden_tools),
            "rubric": self.rubric,
            "tags": list(self.tags),
            "timeout_s": self.timeout_s,
            "inject": self.inject.to_dict() if self.inject else None,
        }

    def to_experiment_item(self) -> dict[str, Any]:
        # NOTE: only `input` (= the prompt) reaches the agent. `inject` lives in
        # metadata alongside `rubric`, so the injected fault stays ground truth
        # the agent must diagnose — never a leaked answer in the prompt.
        return {
            "input": self.prompt,
            "expected_output": self.expected_output,
            "metadata": self.metadata(),
        }


def load_cases_from_yaml(path: str | Path = DEFAULT_CASES_DIR) -> tuple[EvalCase, ...]:
    """Load eval cases from one YAML file or every YAML file in a directory.

    Each file holds either a top-level list of case mappings or a mapping with a
    ``cases:`` list. Case ids must be unique across all loaded files.
    """

    import yaml

    resolved = resolve_path(path, must_exist=True)
    files = tuple(sorted(_iter_yaml_files(resolved))) if resolved.is_dir() else (resolved,)
    cases: list[EvalCase] = []
    seen_ids: set[str] = set()
    for file_path in files:
        if file_path.suffix not in (".yaml", ".yml"):
            raise EvalDatasetError(f"Eval case file must be .yaml or .yml: {file_path}")
        try:
            document = yaml.safe_load(file_path.read_text(encoding="utf-8"))
        except yaml.YAMLError as exc:
            raise EvalDatasetError(f"{file_path}: invalid YAML: {exc}") from exc
        for index, payload in enumerate(_document_cases(document, file_path), start=1):
            source = f"{file_path}#{index}"
            if not isinstance(payload, Mapping):
                raise EvalDatasetError(f"{source}: each eval case must be a mapping.")
            case = EvalCase.from_mapping(payload, source=source)
            if case.id in seen_ids:
                raise EvalDatasetError(f"{source}: duplicate eval case id: {case.id}")
            seen_ids.add(case.id)
            cases.append(case)
    if not cases:
        raise EvalDatasetError(f"No eval cases found in {resolved}")
    return tuple(cases)


def validate_expected_tool_names(cases: Iterable[Any], available_tools: Iterable[str]) -> None:
    """Fail fast when dataset expectations drift from the runtime tool catalog."""

    available = {str(name) for name in available_tools}
    stale: dict[str, list[str]] = {}
    for item in cases:
        metadata = item.metadata() if isinstance(item, EvalCase) else _item_metadata(item)
        expected = metadata.get("expected_tools") or ()
        missing = sorted({str(name) for name in expected} - available)
        if missing:
            case_id = str(metadata.get("id") or getattr(item, "id", "<unknown>"))
            stale[case_id] = missing
    if stale:
        details = "; ".join(f"{case_id}: {', '.join(names)}" for case_id, names in sorted(stale.items()))
        raise EvalDatasetError(f"Eval dataset references tools absent from the current runtime: {details}")


def _iter_yaml_files(directory: Path) -> list[Path]:
    return [*directory.glob("*.yaml"), *directory.glob("*.yml")]


def _item_metadata(item: Any) -> dict[str, Any]:
    value = item.get("metadata") if isinstance(item, Mapping) else getattr(item, "metadata", None)
    return dict(value) if isinstance(value, Mapping) else {}


def _document_cases(document: Any, file_path: Path) -> list[Any]:
    if document is None:
        return []
    if isinstance(document, Mapping):
        cases = document.get("cases")
        if cases is None:
            raise EvalDatasetError(f"{file_path}: mapping documents must define a 'cases' list.")
        document = cases
    if not isinstance(document, list):
        raise EvalDatasetError(f"{file_path}: expected a list of cases or a 'cases' list.")
    return document


def sync_cases_to_langfuse(
    cases: Iterable[EvalCase],
    dataset_name: str,
    settings: Settings | None = None,
    *,
    langfuse: Any | None = None,
) -> int:
    """Upsert local cases into a Langfuse dataset and return the item count."""

    client = langfuse or create_langfuse_client(settings)
    _ensure_langfuse_dataset(client, dataset_name)
    count = 0
    for case in cases:
        client.create_dataset_item(
            dataset_name=dataset_name,
            id=case.id,
            input=case.prompt,
            expected_output=case.expected_output,
            metadata=case.metadata(),
        )
        count += 1
    flush = getattr(client, "flush", None)
    if callable(flush):
        flush()
    return count


def create_langfuse_client(settings: Settings | None = None) -> Any:
    try:
        from langfuse import Langfuse, get_client
    except ImportError as exc:
        raise EvalDatasetError("Langfuse package is not installed; run `uv sync` in services/agent.") from exc
    if settings is None:
        return get_client()
    return Langfuse(
        public_key=settings.langfuse_public_key,
        secret_key=settings.langfuse_secret_key,
        base_url=settings.langfuse_base_url,
        environment=settings.app_env,
    )


def langfuse_client_is_reachable(langfuse: Any) -> bool:
    """Verify connectivity to a (self-hosted) Langfuse instance before running an experiment."""

    auth_check = getattr(langfuse, "auth_check", None)
    if not callable(auth_check):
        return True
    try:
        return bool(auth_check())
    except Exception:  # noqa: BLE001 - unreachable host / bad creds must degrade, not crash.
        return False


def close_langfuse_client(langfuse: Any) -> None:
    """Flush and shut down a Langfuse client so short-lived runs upload before exit."""

    for method_name in ("flush", "shutdown"):
        method = getattr(langfuse, method_name, None)
        if callable(method):
            try:
                method()
            except Exception:  # noqa: BLE001 - best-effort teardown at process boundary.
                pass


def _ensure_langfuse_dataset(langfuse: Any, dataset_name: str) -> None:
    try:
        langfuse.create_dataset(
            name=dataset_name,
            description="ops_pilot agent evaluation dataset",
            metadata={"source": "ops_pilot local YAML eval cases"},
        )
    except Exception as exc:  # noqa: BLE001 - SDK raises generated API exception classes.
        message = str(exc).lower()
        if "already" not in message and "exists" not in message and "409" not in message:
            raise


def _required_string(data: Mapping[str, Any], key: str, source: str) -> str:
    value = data.get(key)
    parsed = _optional_string(value, key, source)
    if parsed is None:
        raise EvalDatasetError(f"{source}: field '{key}' is required.")
    return parsed


def _optional_string(value: Any, key: str, source: str) -> str | None:
    if value in (None, ""):
        return None
    if not isinstance(value, str):
        raise EvalDatasetError(f"{source}: field '{key}' must be a string.")
    parsed = value.strip()
    if not parsed:
        return None
    return parsed


def _string_tuple(value: Any, key: str, source: str) -> tuple[str, ...]:
    if value in (None, ""):
        return ()
    if not isinstance(value, Sequence) or isinstance(value, str):
        raise EvalDatasetError(f"{source}: field '{key}' must be a list of strings.")
    parsed: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise EvalDatasetError(f"{source}: field '{key}' must contain only non-empty strings.")
        parsed.append(item.strip())
    return tuple(parsed)


def _float_value(value: Any, key: str, source: str) -> float:
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise EvalDatasetError(f"{source}: field '{key}' must be a number.") from exc
