"""Repository paths owned by the executable composition host."""

from __future__ import annotations

from pathlib import Path


def _repo_root() -> Path:
    current = Path(__file__).resolve()
    for parent in current.parents:
        if (parent / "config" / "runtime.example.yaml").is_file():
            return parent
    raise RuntimeError("Could not locate the OpsPilot repository root.")


REPO_ROOT = _repo_root()


def resolve_repo_path(value: str | Path) -> Path:
    path = Path(value).expanduser()
    return path.resolve() if path.is_absolute() else (REPO_ROOT / path).resolve()
