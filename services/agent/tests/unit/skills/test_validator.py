import pytest

from ops_pilot.skills.validator import SkillValidationError, validate_skill_paths


def test_validate_skill_paths_accepts_directory_with_nested_skill(tmp_path):
    skill_dir = tmp_path / "examples" / "ops-basic"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("---\nname: ops-basic\n---\n", encoding="utf-8")

    assert validate_skill_paths((tmp_path / "examples",)) == (tmp_path / "examples",)


def test_validate_skill_paths_rejects_missing_skill_files(tmp_path):
    empty_dir = tmp_path / "empty"
    empty_dir.mkdir()

    with pytest.raises(SkillValidationError):
        validate_skill_paths((empty_dir,))
