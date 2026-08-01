"""Path helpers for repo-local configuration values."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = Path(__file__).resolve().parents[2]
SERVICE_ROOT = Path(__file__).resolve().parents[3]


@lru_cache(maxsize=1)
def repo_root() -> Path:
    """Return the repository root by walking up from this file."""

    current = Path(__file__).resolve()
    for parent in current.parents:
        if (parent / "docs").is_dir() and (parent / ".env.example").exists():
            return parent
    return current.parents[5]


REPO_ROOT = repo_root()


def resolve_path(value: str | Path, *, must_exist: bool = False) -> Path:
    """Resolve a configured path against likely local execution roots."""

    raw = Path(value).expanduser()
    if raw.is_absolute():
        candidate = raw.resolve()
        if must_exist and not candidate.exists():
            raise FileNotFoundError(candidate)
        return candidate

    candidates = [
        Path.cwd() / raw,
        SERVICE_ROOT / raw,
        REPO_ROOT / raw,
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate.resolve()

    fallback = (REPO_ROOT / raw).resolve()
    if must_exist:
        raise FileNotFoundError(fallback)
    return fallback


def resolve_repo_path(value: str | Path | None) -> Path | None:
    if value is None or str(value).strip() == "":
        return None
    return resolve_path(value)


def display_path(path: Path) -> str:
    """Return a compact path for logs and status payloads."""

    try:
        return str(path.resolve().relative_to(REPO_ROOT))
    except ValueError:
        return str(path)
