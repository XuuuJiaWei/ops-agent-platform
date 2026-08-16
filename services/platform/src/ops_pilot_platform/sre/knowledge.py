"""Read-only SRE knowledge composition over official DeepAgents backends."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Literal

from deepagents.backends import FilesystemBackend
from ops_pilot.runtime.spec import FilesystemPermissionSpec, RuntimeSpec

SREKnowledgeProfile = Literal["baseline", "context-v1", "context-v2"]

_KNOWLEDGE_ROOT = Path(__file__).with_name("knowledge")
_SKILL_SOURCE = "/skills"
_SEMANTIC_MEMORY = {
    "context-v1": "/memory/semantic/AGENTS.md",
    "context-v2": "/memory/context-v2/AGENTS.md",
}


def apply_sre_knowledge(spec: RuntimeSpec, profile: SREKnowledgeProfile) -> RuntimeSpec:
    """Compose one immutable, evaluator-safe SRE knowledge version.

    The benchmark baseline has no knowledge augmentation. Context candidates
    use DeepAgents' native Skills and Memory middleware with a virtual,
    read-only filesystem rooted at package-owned resources. No case data,
    taxonomy, or evaluator answer is available through this backend.
    """

    if profile == "baseline":
        return replace(
            spec,
            skills=(),
            memory=(),
            backend=None,
            permissions=(FilesystemPermissionSpec(operations=("read", "write"), paths=("/**",), mode="deny"),),
        )
    if profile not in _SEMANTIC_MEMORY:
        raise ValueError(f"Unknown SRE knowledge profile: {profile!r}.")

    return replace(
        spec,
        skills=(_SKILL_SOURCE,),
        memory=(_SEMANTIC_MEMORY[profile],),
        backend=FilesystemBackend(root_dir=_KNOWLEDGE_ROOT, virtual_mode=True),
        permissions=(FilesystemPermissionSpec(operations=("write",), paths=("/**",), mode="deny"),),
        metadata={**spec.metadata, "sre_knowledge_profile": profile},
    )
