"""Application-owned runtime compositions.

Each entrypoint exposes an explicit factory instead of inheriting a process-wide
agent configuration.
"""

from ops_pilot_platform.entrypoints.benchmark import build_benchmark_runtime_spec
from ops_pilot_platform.entrypoints.eval import build_eval_runtime_spec
from ops_pilot_platform.entrypoints.web import WebApplicationSpec, build_web_application_spec

__all__ = [
    "WebApplicationSpec",
    "build_benchmark_runtime_spec",
    "build_eval_runtime_spec",
    "build_web_application_spec",
]
