"""Public agent input and prediction schemas for RCA100."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class RCA100Evidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_type: str
    signal: str
    comparator: str
    value: float
    unit: str = ""


class RCA100ReasoningStep(BaseModel):
    model_config = ConfigDict(extra="forbid")

    step_type: Literal["cause", "propagation", "impact"]
    target: str
    fault_type: str
    evidence: list[RCA100Evidence] = Field(default_factory=list)


class RCA100Prediction(BaseModel):
    """The agent's structured diagnosis, independent of any agent framework."""

    model_config = ConfigDict(extra="forbid")

    root_cause_entities: list[str] = Field(default_factory=list)
    root_cause_types: list[str] = Field(default_factory=list)
    reasoning: list[RCA100ReasoningStep] = Field(default_factory=list)
