"""A2A adapter package.

Keep package imports lightweight so unit tests and local utilities can import
task-store helpers without constructing the shared DeepAgent runtime.
"""

from ops_pilot.a2a.agent_card import build_agent_card
from ops_pilot.a2a.task_store import InMemoryTaskStore, TaskRecord

__all__ = ["InMemoryTaskStore", "TaskRecord", "build_agent_card"]
