from __future__ import annotations

from dataclasses import dataclass

import pytest

from ops_pilot.skills.sync import sync_skill_paths_to_backend


@dataclass(frozen=True)
class FakeExecuteResult:
    exit_code: int = 0
    output: str = ""


@dataclass(frozen=True)
class FakeUploadResponse:
    path: str
    error: str | None = None


class FakeBackend:
    def __init__(self, *, upload_error: str | None = None) -> None:
        self.commands: list[str] = []
        self.uploads: list[tuple[str, bytes]] = []
        self.upload_error = upload_error

    def execute(self, command: str) -> FakeExecuteResult:
        self.commands.append(command)
        return FakeExecuteResult()

    def upload_files(self, files: list[tuple[str, bytes]]) -> list[FakeUploadResponse]:
        self.uploads.extend(files)
        return [FakeUploadResponse(path=path, error=self.upload_error) for path, _ in files]


def test_sync_collection_skills_directory_to_remote_backend(tmp_path) -> None:
    skill_dir = tmp_path / "examples" / "ops-basic"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("---\nname: ops-basic\n---\n", encoding="utf-8")
    scripts = skill_dir / "scripts"
    scripts.mkdir()
    (scripts / "check.py").write_text("print('ok')\n", encoding="utf-8")
    backend = FakeBackend()

    result = sync_skill_paths_to_backend([tmp_path / "examples"], backend, remote_root="/remote")

    assert result.remote_paths == ("/remote/00-examples",)
    assert result.file_count == 2
    uploaded_paths = {path for path, _ in backend.uploads}
    assert uploaded_paths == {
        "/remote/00-examples/ops-basic/SKILL.md",
        "/remote/00-examples/ops-basic/scripts/check.py",
    }
    assert backend.commands == [
        "mkdir -p -- /remote/00-examples/ops-basic /remote/00-examples/ops-basic/scripts"
    ]


def test_sync_nested_skills_container_expands_to_discoverable_sources(tmp_path) -> None:
    skill_dir = tmp_path / "skills" / "examples" / "ops-basic"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("---\nname: ops-basic\n---\n", encoding="utf-8")
    backend = FakeBackend()

    result = sync_skill_paths_to_backend([tmp_path / "skills"], backend, remote_root="/remote")

    assert result.remote_paths == ("/remote/00-examples",)
    assert backend.uploads == [
        ("/remote/00-examples/ops-basic/SKILL.md", b"---\nname: ops-basic\n---\n")
    ]


def test_sync_single_skill_directory_as_discoverable_source(tmp_path) -> None:
    skill_dir = tmp_path / "ops-basic"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text("---\nname: ops-basic\n---\n", encoding="utf-8")
    backend = FakeBackend()

    result = sync_skill_paths_to_backend([skill_dir], backend, remote_root="/remote")

    assert result.remote_paths == ("/remote/00-ops-basic",)
    assert backend.uploads == [
        ("/remote/00-ops-basic/ops-basic/SKILL.md", b"---\nname: ops-basic\n---\n")
    ]


def test_sync_skill_md_file_as_discoverable_source(tmp_path) -> None:
    skill_dir = tmp_path / "ops-basic"
    skill_dir.mkdir()
    skill_md = skill_dir / "SKILL.md"
    skill_md.write_text("---\nname: ops-basic\n---\n", encoding="utf-8")
    backend = FakeBackend()

    result = sync_skill_paths_to_backend([skill_md], backend, remote_root="/remote")

    assert result.remote_paths == ("/remote/00-ops-basic",)
    assert backend.uploads == [
        ("/remote/00-ops-basic/ops-basic/SKILL.md", b"---\nname: ops-basic\n---\n")
    ]


def test_sync_reports_upload_failures(tmp_path) -> None:
    skill_dir = tmp_path / "examples" / "ops-basic"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("---\nname: ops-basic\n---\n", encoding="utf-8")
    backend = FakeBackend(upload_error="permission_denied")

    with pytest.raises(RuntimeError, match="Failed to upload skill files"):
        sync_skill_paths_to_backend([tmp_path / "examples"], backend, remote_root="/remote")
