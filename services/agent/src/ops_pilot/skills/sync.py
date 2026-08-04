"""Synchronize local DeepAgents skills into a remote backend."""

from __future__ import annotations

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
    for source in paths:
        plans = _build_sync_plans(Path(source), remote_root)
        for plan in plans:
            if plan.remote_source not in remote_sources:
                remote_sources.append(plan.remote_source)
            uploads.extend(_collect_uploads(plan.local_root, plan.remote_root))

    if uploads:
        _mkdir_remote_parents(backend, uploads)
        responses = backend.upload_files(uploads)
        failures = [response for response in responses if getattr(response, "error", None)]
        if failures:
            failed_paths = ", ".join(getattr(response, "path", "<unknown>") for response in failures)
            raise RuntimeError(f"Failed to upload skill files to sandbox: {failed_paths}")

    return SkillSyncResult(remote_paths=tuple(remote_sources), file_count=len(uploads))


@dataclass(frozen=True)
class _SyncPlan:
    local_root: Path
    remote_source: str
    remote_root: str


def _build_sync_plans(source: Path, remote_root: str) -> list[_SyncPlan]:
    resolved = source.expanduser().resolve()

    if resolved.is_file():
        return [_build_single_skill_plan(resolved.parent, remote_root)]

    if (resolved / "SKILL.md").exists():
        return [_build_single_skill_plan(resolved, remote_root)]

    skill_dirs = sorted(
        (skill_md.parent for skill_md in resolved.rglob("SKILL.md")),
        key=lambda path: (*_path_depth_key(path.parent), str(path)),
    )
    source_dirs = sorted({skill_dir.parent for skill_dir in skill_dirs}, key=_path_depth_key)
    source_roots = {source_dir: _source_root_for(resolved, source_dir, remote_root) for source_dir in source_dirs}
    return [
        _SyncPlan(
            local_root=skill_dir,
            remote_source=source_roots[skill_dir.parent],
            remote_root=_remote_path(source_roots[skill_dir.parent], skill_dir.name),
        )
        for skill_dir in skill_dirs
    ]


def _build_single_skill_plan(skill_dir: Path, remote_root: str) -> _SyncPlan:
    source_root = remote_root
    return _SyncPlan(
        local_root=skill_dir,
        remote_source=source_root,
        remote_root=_remote_path(source_root, skill_dir.name),
    )


def _source_root_for(container_root: Path, source_dir: Path, remote_root: str) -> str:
    if source_dir == container_root:
        return remote_root
    return _remote_path(remote_root, *source_dir.relative_to(container_root).parts)


def _path_depth_key(path: Path) -> tuple[int, str]:
    return (len(path.parts), str(path))


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
