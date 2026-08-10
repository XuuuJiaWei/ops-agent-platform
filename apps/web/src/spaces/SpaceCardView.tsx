import {
  Activity,
  AlertCircle,
  ArrowDownRight,
  ArrowRight,
  ArrowUpRight,
  BarChart3,
  FileText,
  Gauge,
  ListTree,
  RefreshCw,
  Table2,
} from "lucide-react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { ReactNode } from "react";
import type { CardDraft, SpaceCard } from "@/spaces/types";

const chartColors = ["#2563eb", "#7c3aed", "#0891b2", "#16a34a", "#ea580c", "#dc2626"];

type SpaceCardViewProps = {
  card: CardDraft | SpaceCard;
  compact?: boolean;
};

export function SpaceCardView({ card, compact = false }: SpaceCardViewProps) {
  return (
    <article className="flex h-full min-h-44 flex-col overflow-hidden rounded-xl border border-slate-200 bg-white shadow-[0_1px_2px_rgba(15,23,42,0.04)]">
      <header className="flex shrink-0 items-start gap-3 border-b border-slate-100 px-5 py-3">
        <span className="mt-0.5 grid size-8 shrink-0 place-items-center rounded-lg bg-blue-50 text-blue-700">
          <CardIcon type={card.type} />
        </span>
        <div className="min-w-0">
          <h3 className="truncate text-sm font-semibold text-slate-950">{card.title}</h3>
          {card.subtitle ? <p className="mt-0.5 line-clamp-2 text-xs leading-5 text-slate-500">{card.subtitle}</p> : null}
        </div>
        <FreshnessBadge card={card} />
      </header>
      <div className="min-h-0 flex-1 overflow-auto p-4">
        <CardContent card={card} compact={compact} />
      </div>
    </article>
  );
}

function isLiveCard(card: CardDraft | SpaceCard): card is SpaceCard {
  return "binding" in card && card.binding != null;
}

function FreshnessBadge({ card }: { card: CardDraft | SpaceCard }) {
  if (!isLiveCard(card)) return null;
  const status = card.refresh_status ?? "fresh";
  if (status === "error") {
    return (
      <span
        className="ml-auto mt-0.5 flex shrink-0 items-center gap-1 rounded-full bg-red-50 px-2 py-0.5 text-[11px] font-medium text-red-700"
        title={card.last_error ?? "Refresh failed"}
      >
        <AlertCircle aria-hidden="true" className="size-3" />
        error
      </span>
    );
  }
  if (status === "refreshing") {
    return (
      <span className="ml-auto mt-0.5 flex shrink-0 items-center gap-1 rounded-full bg-blue-50 px-2 py-0.5 text-[11px] font-medium text-blue-700">
        <RefreshCw aria-hidden="true" className="size-3 animate-spin" />
        refreshing
      </span>
    );
  }
  return (
    <span
      className="ml-auto mt-0.5 flex shrink-0 items-center gap-1 rounded-full bg-slate-50 px-2 py-0.5 text-[11px] font-medium text-slate-500"
      title={card.last_refreshed_at ? `Last updated ${new Date(card.last_refreshed_at).toLocaleString()}` : undefined}
    >
      <RefreshCw aria-hidden="true" className="size-3" />
      {relativeTime(card.last_refreshed_at)}
    </span>
  );
}

function relativeTime(iso: string | null | undefined): string {
  if (!iso) return "live";
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return "live";
  const seconds = Math.max(0, Math.round((Date.now() - then) / 1000));
  if (seconds < 60) return `${seconds}s ago`;
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.round(minutes / 60);
  return `${hours}h ago`;
}

function CardIcon({ type }: { type: CardDraft["type"] }) {
  const className = "size-4";
  if (type === "kpi") return <Gauge aria-hidden="true" className={className} />;
  if (type === "table") return <Table2 aria-hidden="true" className={className} />;
  if (type === "line-chart") return <Activity aria-hidden="true" className={className} />;
  if (type === "bar-chart") return <BarChart3 aria-hidden="true" className={className} />;
  if (type === "object-list") return <ListTree aria-hidden="true" className={className} />;
  return <FileText aria-hidden="true" className={className} />;
}

function CardContent({ card, compact }: { card: CardDraft | SpaceCard; compact: boolean }) {
  if (card.type === "kpi") return <KpiContent card={card} />;
  if (card.type === "table") return <TableContent card={card} />;
  if (card.type === "line-chart" || card.type === "bar-chart") return <ChartContent card={card} compact={compact} />;
  if (card.type === "details") return <DetailsContent card={card} />;
  if (card.type === "object-list") return <ObjectListContent card={card} />;
  return <p className="whitespace-pre-wrap text-sm leading-6 text-slate-700">{card.content.markdown}</p>;
}

function KpiContent({ card }: { card: CardDraft | SpaceCard }) {
  return (
    <div className="grid grid-cols-2 gap-x-5 gap-y-3">
      {card.content.metrics.map((metric) => (
        <div key={metric.label} className="min-w-0">
          <div className="flex items-baseline gap-1.5">
            <span className="truncate text-3xl font-medium tracking-tight text-slate-950">{metric.value}</span>
            {metric.unit ? <span className="text-sm text-slate-500">{metric.unit}</span> : null}
          </div>
          <p className="mt-0.5 truncate text-xs text-slate-500">{metric.label}</p>
          {metric.trend ? (
            <p className={`mt-1 flex items-center gap-1 text-xs font-medium ${trendClass(metric.trend_direction)}`}>
              <TrendIcon direction={metric.trend_direction} />
              {metric.trend}
            </p>
          ) : null}
        </div>
      ))}
    </div>
  );
}

function TrendIcon({ direction }: { direction: "up" | "down" | "neutral" | null | undefined }) {
  const className = "size-3.5";
  if (direction === "up") return <ArrowUpRight aria-hidden="true" className={className} />;
  if (direction === "down") return <ArrowDownRight aria-hidden="true" className={className} />;
  return <ArrowRight aria-hidden="true" className={className} />;
}

function trendClass(direction: "up" | "down" | "neutral" | null | undefined) {
  if (direction === "up") return "text-emerald-700";
  if (direction === "down") return "text-amber-700";
  return "text-slate-500";
}

function TableContent({ card }: { card: CardDraft | SpaceCard }) {
  return (
    <div className="max-h-full overflow-auto">
      <table className="w-full border-separate border-spacing-0 text-left text-xs">
        <thead className="sticky top-0 bg-white text-slate-500">
          <tr>
            {card.content.columns.map((column) => (
              <th className="border-b border-slate-200 px-3 py-2 font-medium" key={column.key} style={{ textAlign: column.align }}>
                {column.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="text-slate-700">
          {card.content.rows.map((row, index) => (
            <tr key={index}>
              {card.content.columns.map((column) => (
                <td className="border-b border-slate-100 px-3 py-2.5" key={column.key} style={{ textAlign: column.align }}>
                  {displayValue(row[column.key])}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function ChartContent({ card, compact }: { card: CardDraft | SpaceCard; compact: boolean }) {
  const data = card.content.categories.map((category, index) => ({
    category,
    ...Object.fromEntries(card.content.series.map((series) => [series.name, series.values[index]])),
  }));
  const Chart = card.type === "line-chart" ? LineChart : BarChart;

  return (
    <div className={compact ? "h-56" : "h-full min-h-52"}>
      <ResponsiveContainer height="100%" minWidth={0} width="100%">
        <Chart data={data} margin={{ top: 8, right: 12, bottom: 0, left: -12 }}>
          <CartesianGrid stroke="#e2e8f0" strokeDasharray="2 4" vertical={false} />
          <XAxis axisLine={false} dataKey="category" fontSize={11} tickLine={false} />
          <YAxis axisLine={false} fontSize={11} tickLine={false} width={52} />
          <Tooltip contentStyle={{ borderColor: "#e2e8f0", borderRadius: 8, fontSize: 12 }} />
          {card.content.series.length > 1 ? <Legend iconSize={8} wrapperStyle={{ fontSize: 11 }} /> : null}
          {card.content.series.map((series, index) =>
            card.type === "line-chart" ? (
              <Line
                dataKey={series.name}
                dot={{ r: 3 }}
                key={series.name}
                stroke={series.color ?? chartColors[index % chartColors.length]}
                strokeWidth={2.5}
                type="monotone"
              />
            ) : (
              <Bar
                dataKey={series.name}
                fill={series.color ?? chartColors[index % chartColors.length]}
                key={series.name}
                radius={[4, 4, 0, 0]}
              />
            ),
          )}
        </Chart>
      </ResponsiveContainer>
    </div>
  );
}

function DetailsContent({ card }: { card: CardDraft | SpaceCard }) {
  return (
    <dl className="grid grid-cols-1 gap-x-6 sm:grid-cols-2">
      {card.content.fields.map((field) => (
        <div className="flex items-center justify-between gap-4 border-b border-slate-100 py-3" key={field.label}>
          <dt className="text-xs text-slate-500">{field.label}</dt>
          <dd className={`text-right text-sm font-medium ${statusClass(field.status)}`}>{displayValue(field.value)}</dd>
        </div>
      ))}
    </dl>
  );
}

function ObjectListContent({ card }: { card: CardDraft | SpaceCard }) {
  return (
    <ul className="divide-y divide-slate-100">
      {card.content.items.map((item, index) => (
        <li className="flex items-center justify-between gap-4 py-3 first:pt-0" key={`${item.title}-${index}`}>
          <div className="min-w-0">
            <p className="truncate text-sm font-medium text-slate-800">{item.title}</p>
            {item.subtitle ? <p className="mt-0.5 truncate text-xs text-slate-500">{item.subtitle}</p> : null}
          </div>
          {item.value !== undefined ? <span className={`shrink-0 text-sm font-semibold ${statusClass(item.status)}`}>{displayValue(item.value)}</span> : null}
        </li>
      ))}
    </ul>
  );
}

function statusClass(status: "positive" | "critical" | "negative" | "neutral" | null | undefined) {
  if (status === "positive") return "text-emerald-700";
  if (status === "critical") return "text-amber-700";
  if (status === "negative") return "text-red-700";
  return "text-slate-700";
}

function displayValue(value: unknown): ReactNode {
  if (value === null || value === undefined) return "—";
  if (typeof value === "boolean") return value ? "Yes" : "No";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}
