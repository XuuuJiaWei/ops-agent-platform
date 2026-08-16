"""Scoped sandbox execution environment management."""

from __future__ import annotations

import hashlib
import shlex
import threading
from collections import OrderedDict
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any, Literal

from deepagents.backends.protocol import (
    DeleteResult,
    EditResult,
    ExecuteResponse,
    FileDownloadResponse,
    FileInfo,
    FileUploadResponse,
    GlobResult,
    GrepResult,
    LsResult,
    ReadResult,
    SandboxBackendProtocol,
    WriteResult,
)
from langgraph.config import get_config

from ops_pilot.runtime.spec import SandboxSpec
from ops_pilot.sandbox.opensandbox_backend import SandboxRuntime, create_sandbox_runtime
from ops_pilot.skills.sync import SkillSyncPlan, plan_skill_paths, sync_skill_plan_to_backend

SandboxScope = Literal["process", "thread", "run"]


@dataclass(frozen=True)
class SandboxLease:
    """A resolved sandbox plus the workspace paths visible to the agent."""

    runtime: SandboxRuntime
    sandbox_key: str
    workspace_key: str
    workspace_path: str
    skills_path: str

    @property
    def backend(self) -> Any:
        return self.runtime.backend


@dataclass(frozen=True)
class _InvocationScope:
    thread_id: str | None
    run_id: str | None

    @property
    def thread_key(self) -> str:
        return self.thread_id or "process"

    @property
    def run_key(self) -> str:
        return self.run_id or self.thread_key


class SandboxManager:
    """Owns sandbox leases and hides allocation policy from DeepAgents."""

    def __init__(self, spec: SandboxSpec) -> None:
        self.spec = spec
        self.scope: SandboxScope = spec.scope
        self.visible_workspace = spec.workspace_path
        self.visible_skills = _join_posix(self.visible_workspace, "skills")
        self.internal_root = spec.internal_root
        self.backend = ScopedSandboxBackend(self)
        self._lock = threading.RLock()
        self._leases: OrderedDict[str, SandboxRuntime] = OrderedDict()
        self._skill_plan = SkillSyncPlan(remote_paths=(), uploads=())
        self._initialized_workspaces: set[tuple[str, str]] = set()
        self._synced_skills: set[str] = set()
        self._closed = False

    def configure_skills(self, paths: tuple[str, ...]) -> tuple[str, ...]:
        """Register local skills for upload into every sandbox lease."""

        plan = plan_skill_paths(paths, remote_root=self.visible_skills)
        with self._lock:
            self._skill_plan = plan
            self._synced_skills.clear()
        return plan.remote_paths

    def lease_for_current_invocation(self) -> SandboxLease:
        """Return a ready lease for the current LangGraph invocation."""

        invocation = _current_invocation_scope()
        sandbox_key = self._sandbox_key(invocation)
        workspace_key = self._workspace_key(invocation)
        with self._lock:
            self._raise_if_closed()
            runtime = self._ready_runtime(sandbox_key)
            lease = SandboxLease(
                runtime=runtime,
                sandbox_key=sandbox_key,
                workspace_key=workspace_key,
                workspace_path=self._workspace_path(workspace_key),
                skills_path=self._skills_path(),
            )
            self._initialize_lease(lease)
            self._leases.move_to_end(sandbox_key)
            return lease

    def as_dict(self) -> dict[str, Any]:
        with self._lock:
            active = [runtime.as_dict() for runtime in self._leases.values()]
        return {
            "enabled": True,
            "mode": "opensandbox",
            "allocation_scope": self.scope,
            "workspace_path": self.visible_workspace,
            "max_active": self.spec.max_active,
            "active_sandboxes": len(active),
            "sandboxes": active,
            "domain": self.spec.domain,
            "protocol": self.spec.protocol,
            "image": self.spec.image,
            "use_server_proxy": self.spec.use_server_proxy,
        }

    def is_expired(self) -> bool:
        """Runtime manager should not rebuild globally for per-lease TTLs."""

        return False

    def should_renew(self) -> bool:
        """Per-lease renewal is handled lazily by the pool."""

        return False

    def close(self) -> None:
        with self._lock:
            self._closed = True
            leases = list(self._leases.items())
            self._leases.clear()
            self._initialized_workspaces.clear()
            self._synced_skills.clear()
        failed: list[tuple[str, SandboxRuntime]] = []
        errors: list[Exception] = []
        for key, runtime in leases:
            try:
                runtime.close()
            except Exception as exc:  # noqa: BLE001 - attempt every owned lease before reporting cleanup failure.
                failed.append((key, runtime))
                errors.append(exc)
        if failed:
            with self._lock:
                self._leases.update(failed)
        if errors:
            raise ExceptionGroup("Failed to release one or more sandbox leases.", errors)

    def _sandbox_key(self, scope: _InvocationScope) -> str:
        if self.scope == "process":
            return "process"
        if self.scope == "run":
            return f"run:{scope.run_key}"
        return f"thread:{scope.thread_key}"

    def _workspace_key(self, scope: _InvocationScope) -> str:
        if self.scope == "process":
            return f"workspace:{scope.run_key if scope.run_id else scope.thread_key}"
        return self._sandbox_key(scope)

    def _workspace_path(self, workspace_key: str) -> str:
        if self.scope == "process":
            return _join_posix(self.internal_root, "workspaces", _stable_key(workspace_key), "workspace")
        return self.visible_workspace

    def _skills_path(self) -> str:
        if self.scope == "process":
            return _join_posix(self.internal_root, "shared", "skills")
        return self.visible_skills

    def _ready_runtime(self, sandbox_key: str) -> SandboxRuntime:
        existing = self._leases.get(sandbox_key)
        if existing is not None:
            if existing.is_expired():
                self._drop_runtime(sandbox_key, existing)
            elif existing.should_renew():
                renewed = existing.renew()
                if renewed is False:
                    self._drop_runtime(sandbox_key, existing)
                else:
                    return existing
            else:
                return existing

        if len(self._leases) >= self.spec.max_active:
            raise RuntimeError(
                f"OpenSandbox pool is exhausted: {len(self._leases)}/{self.spec.max_active} active sandboxes."
            )
        runtime = create_sandbox_runtime(self.spec)
        if runtime is None:
            raise RuntimeError("OpenSandbox is not enabled for this runtime.")
        self._leases[sandbox_key] = runtime
        return runtime

    def _drop_runtime(self, sandbox_key: str, runtime: SandboxRuntime) -> None:
        self._leases.pop(sandbox_key, None)
        sandbox_id = _runtime_key(runtime)
        self._initialized_workspaces = {key for key in self._initialized_workspaces if key[0] != sandbox_id}
        self._synced_skills.discard(sandbox_id)
        runtime.close()

    def _initialize_lease(self, lease: SandboxLease) -> None:
        sandbox_id = _runtime_key(lease.runtime)
        workspace_marker = (sandbox_id, lease.workspace_key)
        if workspace_marker not in self._initialized_workspaces:
            result = lease.backend.execute(
                "mkdir -p -- " + shlex.quote(lease.workspace_path) + " " + shlex.quote(lease.skills_path)
            )
            if getattr(result, "exit_code", 0) != 0:
                raise RuntimeError(f"Failed to initialize sandbox workspace: {getattr(result, 'output', '')}")
            self._initialized_workspaces.add(workspace_marker)

        if sandbox_id not in self._synced_skills:
            skill_plan = _retarget_skill_plan(self._skill_plan, self.visible_skills, lease.skills_path)
            sync_skill_plan_to_backend(skill_plan, lease.backend)
            self._synced_skills.add(sandbox_id)

    def _raise_if_closed(self) -> None:
        if self._closed:
            raise RuntimeError("Sandbox manager is closed.")


class ScopedSandboxBackend(SandboxBackendProtocol):
    """DeepAgents backend that projects each invocation into a scoped workspace."""

    def __init__(self, manager: SandboxManager) -> None:
        self._manager = manager

    @property
    def id(self) -> str:
        return self._manager.lease_for_current_invocation().runtime.sandbox_id or "opensandbox"

    def execute(self, command: str, *, timeout: int | None = None) -> ExecuteResponse:
        try:
            lease = self._manager.lease_for_current_invocation()
        except RuntimeError as exc:
            return ExecuteResponse(output=str(exc), exit_code=1, truncated=False)
        wrapped = "cd -- " + shlex.quote(lease.workspace_path) + " && " + command
        if timeout is not None:
            return lease.backend.execute(wrapped, timeout=timeout)
        return lease.backend.execute(wrapped)

    def ls(self, path: str) -> LsResult:
        try:
            lease = self._manager.lease_for_current_invocation()
        except RuntimeError as exc:
            return LsResult(error=str(exc))
        try:
            normalized = _normalize_path(path)
        except ValueError as exc:
            return LsResult(error=str(exc))
        if normalized == "/":
            return LsResult(entries=[_file_info(self._manager.visible_workspace, is_dir=True)])
        try:
            physical = self._physical_path(normalized, lease, write=False)
        except ValueError as exc:
            return LsResult(error=str(exc))
        result = lease.backend.ls(physical)
        if result.entries is not None:
            result.entries = [self._remap_file_info(entry, lease) for entry in result.entries]
        return result

    def read(self, file_path: str, offset: int = 0, limit: int = 2000) -> ReadResult:
        try:
            lease = self._manager.lease_for_current_invocation()
        except RuntimeError as exc:
            return ReadResult(error=str(exc))
        try:
            physical = self._physical_path(file_path, lease, write=False)
        except ValueError as exc:
            return ReadResult(error=str(exc))
        return lease.backend.read(physical, offset=offset, limit=limit)

    def write(self, file_path: str, content: str) -> WriteResult:
        try:
            lease = self._manager.lease_for_current_invocation()
        except RuntimeError as exc:
            return WriteResult(error=str(exc))
        try:
            physical = self._physical_path(file_path, lease, write=True)
        except ValueError as exc:
            return WriteResult(error=str(exc))
        result = lease.backend.write(physical, content)
        if result.path is not None:
            result.path = _normalize_path(file_path)
        return result

    def edit(self, file_path: str, old_string: str, new_string: str, replace_all: bool = False) -> EditResult:  # noqa: FBT001, FBT002
        try:
            lease = self._manager.lease_for_current_invocation()
        except RuntimeError as exc:
            return EditResult(error=str(exc))
        try:
            physical = self._physical_path(file_path, lease, write=True)
        except ValueError as exc:
            return EditResult(error=str(exc))
        result = lease.backend.edit(physical, old_string, new_string, replace_all)
        if result.path is not None:
            result.path = _normalize_path(file_path)
        return result

    def delete(self, file_path: str) -> DeleteResult:
        try:
            lease = self._manager.lease_for_current_invocation()
        except RuntimeError as exc:
            return DeleteResult(error=str(exc))
        try:
            physical = self._physical_path(file_path, lease, write=True)
        except ValueError as exc:
            return DeleteResult(error=str(exc))
        result = lease.backend.delete(physical)
        if result.path is not None:
            result.path = _normalize_path(file_path)
        return result

    def grep(
        self,
        pattern: str,
        path: str | None = None,
        glob: str | None = None,
        *,
        max_count: int | None = None,
    ) -> GrepResult:
        try:
            lease = self._manager.lease_for_current_invocation()
        except RuntimeError as exc:
            return GrepResult(error=str(exc))
        try:
            physical_path = self._physical_path(path or self._manager.visible_workspace, lease, write=False)
            physical_glob = self._map_pattern(glob, lease) if glob is not None else None
        except ValueError as exc:
            return GrepResult(error=str(exc))
        result = lease.backend.grep(pattern, physical_path, physical_glob, max_count=max_count)
        if result.matches is not None:
            result.matches = [{**match, "path": self._visible_path(match["path"], lease)} for match in result.matches]
        return result

    def glob(self, pattern: str, path: str | None = None) -> GlobResult:
        try:
            lease = self._manager.lease_for_current_invocation()
        except RuntimeError as exc:
            return GlobResult(error=str(exc))
        try:
            physical_path = self._physical_path(path or self._manager.visible_workspace, lease, write=False)
            physical_pattern = self._map_pattern(pattern, lease)
        except ValueError as exc:
            return GlobResult(error=str(exc))
        result = lease.backend.glob(physical_pattern, physical_path)
        if result.matches is not None:
            result.matches = [self._remap_file_info(match, lease) for match in result.matches]
        return result

    def upload_files(self, files: list[tuple[str, bytes]]) -> list[FileUploadResponse]:
        try:
            lease = self._manager.lease_for_current_invocation()
        except RuntimeError as exc:
            return [FileUploadResponse(path=path, error=str(exc)) for path, _content in files]
        mapped: list[tuple[str, bytes]] = []
        index_map: list[int] = []
        responses: list[FileUploadResponse | None] = [None] * len(files)
        for index, (path, content) in enumerate(files):
            try:
                mapped.append((self._physical_path(path, lease, write=True), content))
                index_map.append(index)
            except ValueError as exc:
                responses[index] = FileUploadResponse(path=path, error=str(exc))
        if mapped:
            for original_index, response in zip(index_map, lease.backend.upload_files(mapped), strict=False):
                responses[original_index] = FileUploadResponse(path=files[original_index][0], error=response.error)
        return [
            response if response is not None else FileUploadResponse(path=files[index][0], error=None)
            for index, response in enumerate(responses)
        ]

    def download_files(self, paths: list[str]) -> list[FileDownloadResponse]:
        try:
            lease = self._manager.lease_for_current_invocation()
        except RuntimeError as exc:
            return [FileDownloadResponse(path=path, content=None, error=str(exc)) for path in paths]
        mapped: list[str] = []
        index_map: list[int] = []
        responses: list[FileDownloadResponse | None] = [None] * len(paths)
        for index, path in enumerate(paths):
            try:
                mapped.append(self._physical_path(path, lease, write=False))
                index_map.append(index)
            except ValueError as exc:
                responses[index] = FileDownloadResponse(path=path, content=None, error=str(exc))
        if mapped:
            for original_index, response in zip(index_map, lease.backend.download_files(mapped), strict=False):
                responses[original_index] = FileDownloadResponse(
                    path=paths[original_index], content=response.content, error=response.error
                )
        return [
            response
            if response is not None
            else FileDownloadResponse(path=paths[index], content=None, error="file_not_found")
            for index, response in enumerate(responses)
        ]

    def _physical_path(self, path: str, lease: SandboxLease, *, write: bool) -> str:
        normalized = _normalize_path(path)
        in_workspace = normalized == self._manager.visible_workspace or normalized.startswith(
            self._manager.visible_workspace + "/"
        )
        if in_workspace:
            if normalized == self._manager.visible_skills or normalized.startswith(self._manager.visible_skills + "/"):
                if write:
                    raise ValueError(f"Path '{normalized}' is read-only")
                return _replace_prefix(normalized, self._manager.visible_skills, lease.skills_path)
            return _replace_prefix(normalized, self._manager.visible_workspace, lease.workspace_path)
        raise ValueError(f"Path '{normalized}' is outside the agent workspace {self._manager.visible_workspace}")

    def _map_pattern(self, pattern: str, lease: SandboxLease) -> str:
        if pattern.startswith(self._manager.visible_workspace + "/") or pattern == self._manager.visible_workspace:
            return self._physical_path(pattern, lease, write=False)
        return pattern

    def _visible_path(self, physical_path: str, lease: SandboxLease) -> str:
        if physical_path == lease.skills_path or physical_path.startswith(lease.skills_path + "/"):
            return _replace_prefix(physical_path, lease.skills_path, self._manager.visible_skills)
        if physical_path == lease.workspace_path or physical_path.startswith(lease.workspace_path + "/"):
            return _replace_prefix(physical_path, lease.workspace_path, self._manager.visible_workspace)
        return physical_path

    def _remap_file_info(self, info: FileInfo, lease: SandboxLease) -> FileInfo:
        return {**info, "path": self._visible_path(info["path"], lease)}


def create_sandbox_manager(spec: SandboxSpec) -> SandboxManager | None:
    """Create the configured sandbox manager, if OpenSandbox is enabled."""

    if not spec.enabled:
        return None
    return SandboxManager(spec)


def _current_invocation_scope() -> _InvocationScope:
    try:
        config = get_config()
    except RuntimeError:
        config = {}
    configurable = _mapping(config.get("configurable"))
    metadata = _mapping(config.get("metadata"))
    return _InvocationScope(
        thread_id=_string_value(configurable.get("thread_id") or metadata.get("thread_id")),
        run_id=_string_value(configurable.get("run_id") or metadata.get("run_id")),
    )


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _string_value(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _normalize_path(path: str) -> str:
    if not isinstance(path, str) or not path.startswith("/"):
        raise ValueError(f"Path '{path}' must be absolute")
    normalized = str(PurePosixPath(path))
    if ".." in PurePosixPath(normalized).parts:
        raise ValueError(f"Path '{path}' must not contain '..'")
    return normalized.rstrip("/") or "/"


def _replace_prefix(path: str, old_prefix: str, new_prefix: str) -> str:
    if path == old_prefix:
        return new_prefix
    return _join_posix(new_prefix, path[len(old_prefix) :].lstrip("/"))


def _join_posix(root: str, *parts: str) -> str:
    current = PurePosixPath(root)
    for part in parts:
        if part:
            current /= part
    return str(current)


def _stable_key(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:24]


def _runtime_key(runtime: SandboxRuntime) -> str:
    return runtime.sandbox_id or str(id(runtime))


def _file_info(path: str, *, is_dir: bool) -> FileInfo:
    return {"path": path if path.endswith("/") else path + "/", "is_dir": is_dir, "size": 0, "modified_at": ""}


def _retarget_skill_plan(plan: SkillSyncPlan, visible_root: str, physical_root: str) -> SkillSyncPlan:
    if not plan.uploads or visible_root == physical_root:
        return plan
    return SkillSyncPlan(
        remote_paths=tuple(_replace_prefix(path, visible_root, physical_root) for path in plan.remote_paths),
        uploads=tuple((_replace_prefix(path, visible_root, physical_root), content) for path, content in plan.uploads),
    )
