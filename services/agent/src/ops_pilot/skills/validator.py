"""Validation for configured local DeepAgents skill paths."""

from __future__ import annotations

from pathlib import Path


class SkillValidationError(ValueError):
    """Raised when a configured local skills path is unusable."""


def validate_skill_paths(paths: tuple[Path, ...]) -> tuple[Path, ...]:
    for path in paths:
        validate_skill_path(path)
    return paths


def validate_skill_path(path: Path) -> None:
    if not path.exists():
        raise SkillValidationError(f"Configured skills path does not exist: {path}")
    if path.is_file():
        if path.name != "SKILL.md":
            raise SkillValidationError(f"Configured skill file must be named SKILL.md: {path}")
        return
    if not path.is_dir():
        raise SkillValidationError(f"Configured skills path is not a file or directory: {path}")
    if path.name == ".git":
        raise SkillValidationError(f"Configured skills path must not point at .git: {path}")
    if (path / "SKILL.md").exists():
        return
    if any(child.name == "SKILL.md" for child in path.rglob("SKILL.md")):
        return
    raise SkillValidationError(f"Configured skills directory contains no SKILL.md files: {path}")
