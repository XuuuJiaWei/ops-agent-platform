"""Public agent input and prediction schemas for RCA100."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class RCA100Evidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_type: Literal["metric", "log", "trace", "event", "alert", "topology"]
    signal: str = Field(description="Exact observability signal name, without an entity-name prefix.")
    comparator: str = Field(min_length=1, description="Comparator reported by the observation.")
    value: float
    unit: str = Field(default="", description="Unit reported by the observation tool; preserve it exactly.")


class RCA100ReasoningStep(BaseModel):
    model_config = ConfigDict(extra="forbid")

    step_type: Literal["cause", "propagation", "impact"]
    target: str
    fault_type: str
    evidence: list[RCA100Evidence] = Field(default_factory=list)


class RCA100Prediction(BaseModel):
    """The agent's structured diagnosis, independent of any agent framework."""

    model_config = ConfigDict(extra="forbid")

    root_cause_entities: list[str] = Field(
        default_factory=list,
        description=(
            "Minimal canonical root entities; omit downstream operations once their root service is identified."
        ),
    )
    root_cause_types: list[str] = Field(
        default_factory=list,
        description="Canonical lowerCamelCase fault category identifiers, not free-form explanations.",
    )
    reasoning: list[RCA100ReasoningStep] = Field(default_factory=list)
