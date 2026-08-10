"""Domain models for agent-authored Spaces and cards."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class CardType(StrEnum):
    KPI = "kpi"
    TABLE = "table"
    LINE_CHART = "line-chart"
    BAR_CHART = "bar-chart"
    DETAILS = "details"
    OBJECT_LIST = "object-list"
    MARKDOWN = "markdown"


class CardSize(StrEnum):
    SMALL = "small"
    MEDIUM = "medium"
    LARGE = "large"
    FULL = "full"


class KpiMetric(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str = Field(min_length=1, max_length=80)
    value: str | int | float
    unit: str | None = Field(default=None, max_length=24)
    trend: str | None = Field(default=None, max_length=32)
    trend_direction: str | None = Field(
        default=None,
        pattern="^(up|down|neutral)$",
        description="Semantic trend direction: up, down, or neutral.",
    )


class TableColumn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_.-]+$")
    label: str = Field(min_length=1, max_length=80)
    align: str = Field(default="left", pattern="^(left|center|right)$")


class ChartSeries(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=80)
    values: list[float] = Field(min_length=1, max_length=100)
    color: str | None = Field(default=None, max_length=32)


class DetailField(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str = Field(min_length=1, max_length=80)
    value: str | int | float | bool | None
    status: str | None = Field(default=None, pattern="^(positive|critical|negative|neutral)$")


class ObjectListItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=120)
    subtitle: str | None = Field(default=None, max_length=240)
    value: str | int | float | None = None
    status: str | None = Field(default=None, pattern="^(positive|critical|negative|neutral)$")


class CardContent(BaseModel):
    """Bounded declarative content catalog rendered by the frontend."""

    model_config = ConfigDict(extra="forbid")

    metrics: list[KpiMetric] = Field(default_factory=list, max_length=6)
    columns: list[TableColumn] = Field(default_factory=list, max_length=20)
    rows: list[dict[str, Any]] = Field(default_factory=list, max_length=100)
    categories: list[str] = Field(default_factory=list, max_length=100)
    series: list[ChartSeries] = Field(default_factory=list, max_length=8)
    fields: list[DetailField] = Field(default_factory=list, max_length=30)
    items: list[ObjectListItem] = Field(default_factory=list, max_length=30)
    markdown: str | None = Field(default=None, max_length=12_000)


# Primary content field each card type must populate to render meaningfully.
# Shared by the draft validator and the resolver's post-mapping validation.
REQUIRED_CONTENT_FIELD: dict[CardType, str] = {
    CardType.KPI: "metrics",
    CardType.TABLE: "columns",
    CardType.LINE_CHART: "series",
    CardType.BAR_CHART: "series",
    CardType.DETAILS: "fields",
    CardType.OBJECT_LIST: "items",
    CardType.MARKDOWN: "markdown",
}


class RefreshStatus(StrEnum):
    FRESH = "fresh"
    STALE = "stale"
    REFRESHING = "refreshing"
    ERROR = "error"


class CardBinding(BaseModel):
    """Declarative data-binding spec authored by the agent.

    Stores *how to fetch* a card's data (which registered read-only tool to
    call, with what params, and how to map the response) rather than the data
    itself. A backend resolver replays the binding on a schedule without
    re-invoking the LLM.
    """

    model_config = ConfigDict(extra="forbid")

    source_tool: str = Field(min_length=1, max_length=200)
    source_params: dict[str, Any] = Field(default_factory=dict)
    mapping: dict[str, str] | None = Field(
        default=None,
        description="Optional per-content-field JMESPath expressions applied to the tool response.",
    )
    refresh_mode: Literal["manual", "interval"] = "manual"
    interval_ms: int | None = Field(default=None, ge=15_000)


class CardDraft(BaseModel):
    """Agent-authored card definition before identity and timestamps are assigned."""

    model_config = ConfigDict(extra="forbid")

    type: CardType
    title: str = Field(min_length=1, max_length=120)
    subtitle: str | None = Field(default=None, max_length=240)
    size: CardSize = CardSize.MEDIUM
    content: CardContent
    binding: CardBinding | None = None

    @model_validator(mode="after")
    def validate_content_for_type(self) -> CardDraft:
        # Live cards (with a binding) may start with empty content before the
        # first resolver refresh populates it; only static cards must be
        # non-empty at authoring time.
        if self.binding is not None:
            return self
        required_field = REQUIRED_CONTENT_FIELD[self.type]
        if not getattr(self.content, required_field):
            raise ValueError(f"Card type '{self.type}' requires non-empty content.{required_field}.")
        if self.type == CardType.TABLE and not self.content.rows:
            raise ValueError("Card type 'table' requires non-empty content.rows.")
        if self.type in {CardType.LINE_CHART, CardType.BAR_CHART}:
            if not self.content.categories:
                raise ValueError(f"Card type '{self.type}' requires non-empty content.categories.")
            category_count = len(self.content.categories)
            if any(len(series.values) != category_count for series in self.content.series):
                raise ValueError("Every chart series must have one value per category.")
        return self


class SpaceCard(CardDraft):
    id: str
    created_at: datetime
    updated_at: datetime
    refresh_status: RefreshStatus = RefreshStatus.FRESH
    last_refreshed_at: datetime | None = None
    last_error: str | None = None


class Space(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    name: str = Field(min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=500)
    cards: list[SpaceCard] = Field(default_factory=list, max_length=100)
    version: int = Field(ge=1)
    created_at: datetime
    updated_at: datetime


class SpaceSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    description: str | None
    card_count: int
    version: int
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_space(cls, space: Space) -> SpaceSummary:
        return cls(
            id=space.id,
            name=space.name,
            description=space.description,
            card_count=len(space.cards),
            version=space.version,
            created_at=space.created_at,
            updated_at=space.updated_at,
        )


def utc_now() -> datetime:
    return datetime.now(UTC)
