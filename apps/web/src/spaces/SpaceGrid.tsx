import { Responsive, useContainerWidth, type Layout, type ResponsiveLayouts } from "react-grid-layout";
import "react-grid-layout/css/styles.css";
import { SpaceCardView } from "@/spaces/SpaceCardView";
import type { CardSize, SpaceCard } from "@/spaces/types";

type Breakpoint = "lg" | "md" | "sm" | "xs";

const breakpoints: Record<Breakpoint, number> = { lg: 1200, md: 820, sm: 560, xs: 0 };
const columns: Record<Breakpoint, number> = { lg: 12, md: 8, sm: 4, xs: 2 };
const gridGap: [number, number] = [12, 12];
const gridRowHeight = 48;
const markdownCharactersPerHeightUnit: Record<Breakpoint, number> = { lg: 320, md: 240, sm: 160, xs: 100 };

export function SpaceGrid({ cards }: { cards: SpaceCard[] }) {
  const { containerRef, mounted, width } = useContainerWidth({ measureBeforeMount: true });
  const layouts: ResponsiveLayouts<Breakpoint> = {
    lg: buildLayout(cards, "lg"),
    md: buildLayout(cards, "md"),
    sm: buildLayout(cards, "sm"),
    xs: buildLayout(cards, "xs"),
  };

  return (
    <div ref={containerRef}>
      {mounted ? (
        <Responsive<Breakpoint>
          breakpoints={breakpoints}
          cols={columns}
          containerPadding={[0, 0]}
          dragConfig={{ enabled: false }}
          layouts={layouts}
          margin={gridGap}
          resizeConfig={{ enabled: false }}
          rowHeight={gridRowHeight}
          width={width}
        >
          {cards.map((card) => (
            <div key={card.id}>
              <SpaceCardView card={card} />
            </div>
          ))}
        </Responsive>
      ) : null}
    </div>
  );
}

function buildLayout(cards: SpaceCard[], breakpoint: Breakpoint): Layout {
  const cols = columns[breakpoint];
  let x = 0;
  let y = 0;
  let rowHeight = 0;

  return cards.map((card) => {
    const w = cardWidth(card.size, breakpoint);
    const h = cardHeight(card, breakpoint);
    if (x + w > cols) {
      x = 0;
      y += rowHeight;
      rowHeight = 0;
    }
    const item = { i: card.id, x, y, w, h, static: true };
    x += w;
    rowHeight = Math.max(rowHeight, h);
    return item;
  });
}

function cardWidth(size: CardSize, breakpoint: Breakpoint) {
  if (breakpoint === "xs") return 2;
  if (breakpoint === "sm") return size === "small" ? 2 : 4;
  if (breakpoint === "md") {
    if (size === "small") return 4;
    if (size === "medium") return 4;
    return 8;
  }
  if (size === "small") return 3;
  if (size === "medium") return 6;
  if (size === "large") return 8;
  return 12;
}

function cardHeight(card: SpaceCard, breakpoint: Breakpoint) {
  if (card.type === "kpi") {
    const metricRows = Math.ceil(card.content.metrics.length / 2);
    return clampGridRows(metricRows + 3, 4, 8);
  }
  if (card.type === "line-chart" || card.type === "bar-chart") return 6;
  if (card.type === "table") {
    return clampGridRows(Math.ceil(card.content.rows.length / 3) + 3, 4, 7);
  }
  if (card.type === "details") {
    const fieldColumns = breakpoint === "xs" || breakpoint === "sm" ? 1 : 2;
    const fieldRows = Math.ceil(card.content.fields.length / fieldColumns);
    return clampGridRows(fieldRows + (fieldColumns === 1 ? 1 : 2), 4, 10);
  }
  if (card.type === "object-list") {
    return clampGridRows(Math.ceil(card.content.items.length * 0.9) + 3, 4, 8);
  }
  if (card.type === "markdown") {
    const charactersPerHeightUnit = markdownCharactersPerHeightUnit[breakpoint];
    return clampGridRows(Math.ceil((card.content.markdown?.length ?? 0) / charactersPerHeightUnit) + 3, 4, 12);
  }
  return 5;
}

function clampGridRows(value: number, minimum: number, maximum: number) {
  return Math.min(maximum, Math.max(minimum, value));
}
