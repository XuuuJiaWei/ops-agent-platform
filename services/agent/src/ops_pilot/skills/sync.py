"""Synchronize local DeepAgents skills into a remote backend."""

from __future__ import annotations

import re
import shlex
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

DEFAULT_REMOTE_SKILLS_ROOT = "/workspace/skills"
_SKIPPED_DIRS = {".git", "__pycache__", ".pytest_cache", ".ruff_cache", "node_modules"}


@dataclass(frozen=True)
class SkillSyncResult:
    remote_paths: tuple[str, ...]
    file_count: int


def sync_skill_paths_to_backend(
    paths: Iterable[str | Path],
    backend: Any,
    *,
    remote_root: str = DEFAULT_REMOTE_SKILLS_ROOT,
) -> SkillSyncResult:
    """Upload configured local skill files and return backend-visible sources."""

    uploads: list[tuple[str, bytes]] = []
    remote_sources: list[str] = []
    for index, source in enumerate(paths):
        plans = _build_sync_plans(Path(source), index, remote_root)
        for plan in plans:
            remote_sources.append(plan.remote_source)
            uploads.extend(_collect_uploads(plan.local_root, plan.remote_root))

    if uploads:
        _mkdir_remote_parents(backend, uploads)
        responses = backend.upload_files(uploads)
        failures = [response for response in responses if getattr(response, "error", None)]
        if failures:
            failed_paths = ", ".join(
                getattr(response, "path", "<unknown>") for response in failures
            )
            raise RuntimeError(f"Failed to upload skill files to sandbox: {failed_paths}")

    return SkillSyncResult(remote_paths=tuple(remote_sources), file_count=len(uploads))


@dataclass(frozen=True)
class _SyncPlan:
    local_root: Path
    remote_source: str
    remote_root: str


def _build_sync_plans(source: Path, index: int, remote_root: str) -> list[_SyncPlan]:
    resolved = source.expanduser().resolve()

    if resolved.is_file():
        return [_build_single_skill_plan(resolved.parent, index, remote_root)]

    if (resolved / "SKILL.md").exists():
        return [_build_single_skill_plan(resolved, index, remote_root)]

    source_dirs = sorted({skill_md.parent.parent for skill_md in resolved.rglob("SKILL.md")})
    return [
        _build_source_dir_plan(source_dir, index, remote_root, sub_index, len(source_dirs))
        for sub_index, source_dir in enumerate(source_dirs)
    ]


def _build_single_skill_plan(skill_dir: Path, index: int, remote_root: str) -> _SyncPlan:
    source_root = _remote_path(remote_root, f"{index:02d}-{_safe_name(skill_dir.name)}")
    return _SyncPlan(
        local_root=skill_dir,
        remote_source=source_root,
        remote_root=_remote_path(source_root, skill_dir.name),
    )


def _build_source_dir_plan(
    source_dir: Path, index: int, remote_root: str, sub_index: int, total: int
) -> _SyncPlan:
    prefix = f"{index:02d}" if total == 1 else f"{index:02d}-{sub_index:02d}"
    source_root = _remote_path(remote_root, f"{prefix}-{_safe_name(source_dir.name)}")
    return _SyncPlan(local_root=source_dir, remote_source=source_root, remote_root=source_root)


def _collect_uploads(local_root: Path, remote_root: str) -> list[tuple[str, bytes]]:
    uploads: list[tuple[str, bytes]] = []
    for path in sorted(local_root.rglob("*")):
        if _should_skip(path, local_root):
            continue
        if not path.is_file() or path.is_symlink():
            continue
        relative = path.relative_to(local_root).parts
        uploads.append((_remote_path(remote_root, *relative), path.read_bytes()))
    return uploads


def _should_skip(path: Path, local_root: Path) -> bool:
    relative_parts = path.relative_to(local_root).parts
    return any(part in _SKIPPED_DIRS for part in relative_parts)


def _mkdir_remote_parents(backend: Any, uploads: list[tuple[str, bytes]]) -> None:
    directories = sorted({str(PurePosixPath(path).parent) for path, _ in uploads})
    if not directories:
        return
    command = "mkdir -p -- " + " ".join(shlex.quote(directory) for directory in directories)
    result = backend.execute(command)
    if getattr(result, "exit_code", 0) != 0:
        output = getattr(result, "output", "")
        raise RuntimeError(f"Failed to create sandbox skill directories: {output}")


def _remote_path(root: str, *parts: str) -> str:
    current = PurePosixPath(root)
    for part in parts:
        current /= part
    return str(current)


def _safe_name(value: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("._-")
    return safe or "skills"
