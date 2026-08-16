from pathlib import Path

from ops_pilot.skills import resolve_skill_paths, validate_skill_paths


def test_example_skills_path_exists() -> None:
    repository_root = Path(__file__).resolve().parents[5]
    paths = resolve_skill_paths([repository_root / "skills" / "examples"])

    assert paths
    assert validate_skill_paths(paths) == paths
