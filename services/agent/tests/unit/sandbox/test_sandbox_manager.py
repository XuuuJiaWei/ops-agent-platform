from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from deepagents.backends.protocol import (
    DeleteResult,
    EditResult,
    ExecuteResponse,
    FileDownloadResponse,
    FileUploadResponse,
    GlobResult,
    GrepResult,
    LsResult,
    ReadResult,
    WriteResult,
)
from langgraph.config import var_child_runnable_config

from ops_pilot.config.settings import load_settings
from ops_pilot.sandbox import manager as manager_module
from ops_pilot.sandbox.manager import SandboxManager
from ops_pilot.sandbox.opensandbox_backend import SandboxRuntime


@dataclass
class FakeSandbox:
    id: str
    closed: bool = False
    destroyed: bool = False

    def destroy(self) -> None:
        self.destroyed = True

    def close(self) -> None:
        self.closed = True


@dataclass
class FakeBackend:
    sandbox_id: str
    files: dict[str, bytes] = field(default_factory=dict)
    commands: list[str] = field(default_factory=list)

    def execute(self, command: str, *, timeout: int | None = None) -> ExecuteResponse:
        self.commands.append(command)
        return ExecuteResponse(output="", exit_code=0, truncated=False)

    def upload_files(self, files: list[tuple[str, bytes]]) -> list[FileUploadResponse]:
        for path, content in files:
            self.files[path] = content
        return [FileUploadResponse(path=path, error=None) for path, _content in files]

    def download_files(self, paths: list[str]) -> list[FileDownloadResponse]:
        return [FileDownloadResponse(path=path, content=self.files.get(path), error=None) for path in paths]

    def ls(self, path: str) -> LsResult:
        prefix = path.rstrip("/") + "/"
        entries = []
        for stored_path, content in sorted(self.files.items()):
            if stored_path.startswith(prefix):
                entries.append({"path": stored_path, "is_dir": False, "size": len(content), "modified_at": ""})
        return LsResult(entries=entries)

    def read(self, file_path: str, offset: int = 0, limit: int = 2000) -> ReadResult:
        if file_path not in self.files:
            return ReadResult(error="missing")
        return ReadResult(file_data={"content": self.files[file_path].decode(), "encoding": "utf-8"})

    def write(self, file_path: str, content: str) -> WriteResult:
        self.files[file_path] = content.encode()
        return WriteResult(path=file_path)

    def edit(self, file_path: str, old_string: str, new_string: str, replace_all: bool = False) -> EditResult:
        content = self.files[file_path].decode()
        count = content.count(old_string) if replace_all else 1
        self.files[file_path] = content.replace(old_string, new_string, -1 if replace_all else 1).encode()
        return EditResult(path=file_path, occurrences=count)

    def delete(self, file_path: str) -> DeleteResult:
        self.files.pop(file_path, None)
        return DeleteResult(path=file_path)

    def grep(self, *_args: Any, **_kwargs: Any) -> GrepResult:
        return GrepResult(matches=[])

    def glob(self, *_args: Any, **_kwargs: Any) -> GlobResult:
        return GlobResult(matches=[])


def test_thread_scope_gives_each_thread_its_own_sandbox(monkeypatch) -> None:
    created: list[SandboxRuntime] = []
    manager = _manager(monkeypatch, created, scope="thread")

    with _runnable_config(thread_id="alpha"):
        result = manager.backend.write("/workspace/file.txt", "alpha")
        assert result.path == "/workspace/file.txt"
        manager.backend.execute("pwd")

    with _runnable_config(thread_id="beta"):
        manager.backend.write("/workspace/file.txt", "beta")

    assert len(created) == 2
    assert created[0].backend.files["/workspace/file.txt"] == b"alpha"
    assert created[1].backend.files["/workspace/file.txt"] == b"beta"
    assert created[0].backend.commands[-1] == "cd -- /workspace && pwd"


def test_process_scope_hides_logical_workspace_partition(monkeypatch) -> None:
    created: list[SandboxRuntime] = []
    manager = _manager(monkeypatch, created, scope="process")

    with _runnable_config(thread_id="alpha"):
        result = manager.backend.write("/workspace/file.txt", "alpha")

    with _runnable_config(thread_id="beta"):
        manager.backend.write("/workspace/file.txt", "beta")

    assert result.path == "/workspace/file.txt"
    assert len(created) == 1
    stored_paths = sorted(created[0].backend.files)
    assert stored_paths[0].startswith("/workspace/.ops-pilot/workspaces/")
    assert stored_paths[0].endswith("/workspace/file.txt")
    assert stored_paths[1].startswith("/workspace/.ops-pilot/workspaces/")
    assert stored_paths[1].endswith("/workspace/file.txt")
    assert "alpha" not in "\n".join(stored_paths)
    assert "beta" not in "\n".join(stored_paths)


def test_backend_shows_workspace_as_root_and_denies_outside_paths(monkeypatch) -> None:
    created: list[SandboxRuntime] = []
    manager = _manager(monkeypatch, created, scope="thread")

    with _runnable_config(thread_id="alpha"):
        root = manager.backend.ls("/")
        denied = manager.backend.write("/etc/passwd", "nope")

    assert root.entries == [{"path": "/workspace/", "is_dir": True, "size": 0, "modified_at": ""}]
    assert denied.error is not None
    assert "outside the agent workspace" in denied.error


def test_skills_are_synced_into_each_sandbox_lease(monkeypatch, tmp_path: Path) -> None:
    skill_dir = tmp_path / "demo"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text("# Demo\n", encoding="utf-8")
    created: list[SandboxRuntime] = []
    manager = _manager(monkeypatch, created, scope="thread")

    remote_paths = manager.configure_skills((str(skill_dir),))

    with _runnable_config(thread_id="alpha"):
        manager.backend.read("/workspace/skills/demo/SKILL.md")
    with _runnable_config(thread_id="beta"):
        manager.backend.read("/workspace/skills/demo/SKILL.md")

    assert remote_paths == ("/workspace/skills",)
    assert created[0].backend.files["/workspace/skills/demo/SKILL.md"] == b"# Demo\n"
    assert created[1].backend.files["/workspace/skills/demo/SKILL.md"] == b"# Demo\n"


def test_pool_exhaustion_does_not_close_existing_sandbox(monkeypatch) -> None:
    created: list[SandboxRuntime] = []
    manager = _manager(monkeypatch, created, scope="thread", max_active=1)

    with _runnable_config(thread_id="alpha"):
        manager.backend.write("/workspace/file.txt", "alpha")
    with _runnable_config(thread_id="beta"):
        result = manager.backend.write("/workspace/file.txt", "beta")

    assert result.error is not None
    assert "pool is exhausted" in result.error
    assert created[0].sandbox.destroyed is False


def _manager(monkeypatch, created: list[SandboxRuntime], *, scope: str, max_active: int = 16) -> SandboxManager:
    settings = load_settings(
        env={"OPEN_SANDBOX_API_KEY": "secret"},
        config={
            "open_sandbox": {
                "domain": "opensandbox.example.test",
                "scope": scope,
                "max_active": max_active,
            }
        },
    )

    def fake_create_sandbox_runtime(_settings) -> SandboxRuntime:
        sandbox = FakeSandbox(id=f"sandbox-{len(created) + 1}")
        runtime = SandboxRuntime(backend=FakeBackend(sandbox.id), sandbox=sandbox)
        created.append(runtime)
        return runtime

    monkeypatch.setattr(manager_module, "create_sandbox_runtime", fake_create_sandbox_runtime)
    return SandboxManager(settings)


class _runnable_config:
    def __init__(self, **configurable: str) -> None:
        self._configurable = configurable
        self._token = None

    def __enter__(self) -> None:
        self._token = var_child_runnable_config.set({"configurable": self._configurable})

    def __exit__(self, *_args: object) -> None:
        assert self._token is not None
        var_child_runnable_config.reset(self._token)
