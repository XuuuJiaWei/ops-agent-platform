from ops_pilot.skills import resolve_skill_paths, validate_skill_paths


def test_example_skills_path_exists() -> None:
    paths = resolve_skill_paths(["./skills/examples/"])

    assert paths
    assert validate_skill_paths(paths) == paths
