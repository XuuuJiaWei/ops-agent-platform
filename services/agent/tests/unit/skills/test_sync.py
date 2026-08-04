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

    assert result.remote_paths == ("/remote",)
    assert result.file_count == 2
    uploaded_paths = {path for path, _ in backend.uploads}
    assert uploaded_paths == {
        "/remote/ops-basic/SKILL.md",
        "/remote/ops-basic/scripts/check.py",
    }
    assert backend.commands == ["mkdir -p -- /remote/ops-basic /remote/ops-basic/scripts"]


def test_sync_nested_skills_container_expands_to_discoverable_sources(tmp_path) -> None:
    skill_dir = tmp_path / "skills" / "examples" / "ops-basic"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("---\nname: ops-basic\n---\n", encoding="utf-8")
    backend = FakeBackend()

    result = sync_skill_paths_to_backend([tmp_path / "skills"], backend, remote_root="/remote")

    assert result.remote_paths == ("/remote/examples",)
    assert backend.uploads == [("/remote/examples/ops-basic/SKILL.md", b"---\nname: ops-basic\n---\n")]


def test_sync_mixed_real_and_example_skills_uploads_only_skill_dirs(tmp_path) -> None:
    real_skill = tmp_path / "skills" / "mongo-atlas-dynatrace"
    real_skill.mkdir(parents=True)
    (real_skill / "SKILL.md").write_text("---\nname: mongo\n---\n", encoding="utf-8")
    example_skill = tmp_path / "skills" / "examples" / "ops-basic"
    example_skill.mkdir(parents=True)
    (example_skill / "SKILL.md").write_text("---\nname: ops-basic\n---\n", encoding="utf-8")
    (tmp_path / "skills" / "README.md").write_text("not a skill\n", encoding="utf-8")
    backend = FakeBackend()

    result = sync_skill_paths_to_backend([tmp_path / "skills"], backend, remote_root="/remote")

    assert result.remote_paths == ("/remote", "/remote/examples")
    uploaded_paths = {path for path, _ in backend.uploads}
    assert uploaded_paths == {
        "/remote/mongo-atlas-dynatrace/SKILL.md",
        "/remote/examples/ops-basic/SKILL.md",
    }


def test_sync_single_skill_directory_as_discoverable_source(tmp_path) -> None:
    skill_dir = tmp_path / "ops-basic"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text("---\nname: ops-basic\n---\n", encoding="utf-8")
    backend = FakeBackend()

    result = sync_skill_paths_to_backend([skill_dir], backend, remote_root="/remote")

    assert result.remote_paths == ("/remote",)
    assert backend.uploads == [("/remote/ops-basic/SKILL.md", b"---\nname: ops-basic\n---\n")]


def test_sync_skill_md_file_as_discoverable_source(tmp_path) -> None:
    skill_dir = tmp_path / "ops-basic"
    skill_dir.mkdir()
    skill_md = skill_dir / "SKILL.md"
    skill_md.write_text("---\nname: ops-basic\n---\n", encoding="utf-8")
    backend = FakeBackend()

    result = sync_skill_paths_to_backend([skill_md], backend, remote_root="/remote")

    assert result.remote_paths == ("/remote",)
    assert backend.uploads == [("/remote/ops-basic/SKILL.md", b"---\nname: ops-basic\n---\n")]


def test_sync_reports_upload_failures(tmp_path) -> None:
    skill_dir = tmp_path / "examples" / "ops-basic"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("---\nname: ops-basic\n---\n", encoding="utf-8")
    backend = FakeBackend(upload_error="permission_denied")

    with pytest.raises(RuntimeError, match="Failed to upload skill files"):
        sync_skill_paths_to_backend([tmp_path / "examples"], backend, remote_root="/remote")
