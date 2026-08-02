import { useAgent } from "@copilotkit/react-core/v2";
import {
  Activity,
  AlertTriangle,
  Clock3,
  Gauge,
  ShieldAlert,
  Sparkles,
} from "lucide-react";
import type { BrowserEnv } from "@/lib/env";
import {
  type DynatraceDashboard,
  type DynatraceMetric,
  type DynatraceProblem,
  readDynatraceDashboard,
} from "./dynatrace";

type AgentNativeAppViewProps = {
  activeThreadId: string | undefined;
  env: BrowserEnv;
};

export function AgentNativeAppView({ activeThreadId, env }: AgentNativeAppViewProps) {
  // Official CopilotKit "render shared state in-app" pattern: read agent.state
  // unconditionally (with a default) — the component re-renders on every state
  // mutation. See docs: shared-state/rendering-in-app.
  const { agent } = useAgent({ agentId: env.assistantId });
  const dashboard = readDynatraceDashboard(agent?.state);

  return (
    <div className="h-full overflow-y-auto bg-[#f7f8fa]">
      <div className="mx-auto flex w-full max-w-6xl flex-col gap-5 px-4 py-5 sm:px-6 lg:px-8">
        <DashboardBody activeThreadId={activeThreadId} dashboard={dashboard} />
      </div>
    </div>
  );
}

function DashboardBody({
  activeThreadId,
  dashboard,
}: {
  activeThreadId: string | undefined;
  dashboard: DynatraceDashboard | undefined;
}) {
  if (!dashboard) {
    return <EmptyState />;
  }

  const status = dashboard.status ?? "ready";
  const metrics = dashboard.metrics ?? [];
  const problems = dashboard.problems ?? [];
  const focus = dashboard.focus_entity ?? "your services";

  return (
    <>
      <section className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_20rem]">
        <div className="min-w-0 rounded-md border border-[var(--border-subtle)] bg-white p-4 shadow-sm">
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0">
              <p className="text-xs font-semibold uppercase text-[var(--text-secondary)]">Dynatrace observability</p>
              <h1 className="mt-1 text-2xl font-semibold tracking-normal text-[var(--text-primary)]">
                {dashboard.focus_entity ?? "Service health"}
              </h1>
              <p className="mt-2 max-w-2xl text-sm leading-6 text-[var(--text-secondary)]">
                {dashboard.note ?? `Live snapshot the agent assembled from Dynatrace for ${focus}.`}
              </p>
            </div>
            <StatusBadge status={status} />
          </div>

          {status === "loading" && metrics.length === 0 ? (
            <MetricSkeletonRow />
          ) : (
            <div className="mt-5 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
              {metrics.length > 0 ? (
                metrics.map((metric) => <MetricTile key={metric.key} metric={metric} />)
              ) : (
                <p className="text-sm text-[var(--text-secondary)]">No metrics reported for this view.</p>
              )}
            </div>
          )}
        </div>

        <aside className="rounded-md border border-[var(--border-subtle)] bg-white p-4 shadow-sm">
          <div className="flex items-center gap-2 text-sm font-semibold text-[var(--text-primary)]">
            <Sparkles aria-hidden="true" className="size-4 text-[var(--accent)]" />
            Agent state
          </div>
          <dl className="mt-4 space-y-3 text-sm">
            <StateRow label="Thread" value={activeThreadId ?? "new conversation"} />
            <StateRow label="Focus" value={dashboard.focus_entity ?? "—"} />
            <StateRow label="Window" value={dashboard.time_window ?? "—"} />
            <StateRow label="Status" value={status} />
            <StateRow label="Updated" value={formatTimestamp(dashboard.generated_at)} />
          </dl>
        </aside>
      </section>

      <section className="rounded-md border border-[var(--border-subtle)] bg-white p-4 shadow-sm">
        <div className="mb-4 flex items-center justify-between gap-3">
          <div>
            <h2 className="text-base font-semibold text-[var(--text-primary)]">Open problems</h2>
            <p className="mt-1 text-xs text-[var(--text-secondary)]">Surfaced by the agent</p>
          </div>
          <Clock3 aria-hidden="true" className="size-4 text-[var(--text-secondary)]" />
        </div>
        {problems.length > 0 ? (
          <div className="overflow-hidden rounded-md border border-[#e8edf2]">
            <table className="w-full table-fixed text-left text-sm">
              <thead className="bg-[#f5f7f9] text-xs uppercase text-[var(--text-secondary)]">
                <tr>
                  <th className="w-28 px-3 py-2 font-semibold">Severity</th>
                  <th className="px-3 py-2 font-semibold">Problem</th>
                  <th className="w-40 px-3 py-2 font-semibold">Entity</th>
                  <th className="w-40 px-3 py-2 font-semibold">Started</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[#edf1f4]">
                {problems.map((problem) => (
                  <ProblemRow key={problem.id} problem={problem} />
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="rounded-md border border-dashed border-[#e8edf2] px-3 py-6 text-center text-sm text-[var(--text-secondary)]">
            {status === "loading" ? "Agent is checking for open problems…" : "No open problems reported."}
          </p>
        )}
      </section>
    </>
  );
}

function EmptyState() {
  return (
    <section className="rounded-md border border-dashed border-[var(--border-subtle)] bg-white p-10 text-center shadow-sm">
      <Gauge aria-hidden="true" className="mx-auto size-8 text-[var(--text-secondary)]" />
      <h1 className="mt-4 text-lg font-semibold text-[var(--text-primary)]">No dashboard yet</h1>
      <p className="mx-auto mt-2 max-w-md text-sm leading-6 text-[var(--text-secondary)]">
        Ask the agent in chat to pull Dynatrace data — e.g. <em>“show checkout service health for the last 2 hours”</em>.
        The dashboard populates here from the agent’s findings.
      </p>
    </section>
  );
}

function MetricTile({ metric }: { metric: DynatraceMetric }) {
  const tone = metric.tone ?? "normal";
  const toneClass = {
    danger: "text-[var(--danger)]",
    success: "text-[var(--success)]",
    warning: "text-[var(--warning)]",
    normal: "text-[var(--text-secondary)]",
  }[tone];

  return (
    <div className="rounded-md border border-[#e8edf2] bg-[#fbfcfd] p-3">
      <p className="text-xs font-semibold uppercase text-[var(--text-secondary)]">{metric.label}</p>
      <p className="mt-2 text-2xl font-semibold text-[var(--text-primary)]">
        {metric.value}
        {metric.unit ? <span className="ml-1 text-base font-medium text-[var(--text-secondary)]">{metric.unit}</span> : null}
      </p>
      <p className={`mt-1 text-xs font-semibold capitalize ${toneClass}`}>{tone}</p>
    </div>
  );
}

function MetricSkeletonRow() {
  return (
    <div className="mt-5 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
      {[0, 1, 2, 3].map((index) => (
        <div className="rounded-md border border-[#e8edf2] bg-[#fbfcfd] p-3" key={index}>
          <div className="h-3 w-16 animate-pulse rounded bg-[#e8edf2]" />
          <div className="mt-3 h-7 w-20 animate-pulse rounded bg-[#e8edf2]" />
          <div className="mt-2 h-3 w-12 animate-pulse rounded bg-[#e8edf2]" />
        </div>
      ))}
    </div>
  );
}

function ProblemRow({ problem }: { problem: DynatraceProblem }) {
  return (
    <tr>
      <td className="px-3 py-3">
        <SeverityBadge severity={problem.severity} />
      </td>
      <td className="px-3 py-3 text-[var(--text-primary)]">{problem.title}</td>
      <td className="px-3 py-3 text-[var(--text-secondary)]">{problem.entity ?? "—"}</td>
      <td className="px-3 py-3 font-mono text-xs text-[var(--text-secondary)]">{formatTimestamp(problem.started_at)}</td>
    </tr>
  );
}

function StatusBadge({ status }: { status: NonNullable<DynatraceDashboard["status"]> }) {
  if (status === "error") {
    return (
      <span className="inline-flex shrink-0 items-center gap-1.5 rounded-md border border-[#fecaca] bg-[#fef2f2] px-2.5 py-1 text-xs font-semibold text-[var(--danger)]">
        <AlertTriangle aria-hidden="true" className="size-3.5" />
        Error
      </span>
    );
  }
  if (status === "loading") {
    return (
      <span className="inline-flex shrink-0 items-center gap-1.5 rounded-md border border-[#bae6fd] bg-[#f0f9ff] px-2.5 py-1 text-xs font-semibold text-[var(--accent-strong)]">
        <Activity aria-hidden="true" className="size-3.5 animate-pulse" />
        Loading
      </span>
    );
  }
  return (
    <span className="inline-flex shrink-0 items-center gap-1.5 rounded-md border border-[#fed7aa] bg-[#fff7ed] px-2.5 py-1 text-xs font-semibold text-[#9a3412]">
      <ShieldAlert aria-hidden="true" className="size-3.5" />
      Live
    </span>
  );
}

function SeverityBadge({ severity }: { severity: string }) {
  const normalized = severity.toUpperCase();
  const isCritical = ["AVAILABILITY", "ERROR", "CRITICAL", "RESOURCE_CONTENTION"].some((key) =>
    normalized.includes(key),
  );
  const className = isCritical
    ? "bg-[#fef2f2] text-[var(--danger)]"
    : "bg-[#fff7ed] text-[var(--warning)]";
  return (
    <span className={`inline-flex shrink-0 items-center rounded-md px-2 py-1 text-xs font-semibold ${className}`}>
      {severity}
    </span>
  );
}

function StateRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="grid grid-cols-[5rem_minmax(0,1fr)] gap-2 border-b border-[#edf1f4] pb-3 last:border-b-0 last:pb-0">
      <dt className="text-xs font-semibold uppercase text-[var(--text-secondary)]">{label}</dt>
      <dd className="truncate text-right font-mono text-xs text-[var(--text-primary)]">{value}</dd>
    </div>
  );
}

function formatTimestamp(value: string | undefined): string {
  if (!value) {
    return "—";
  }
  const parsed = new Date(value);
  return Number.isNaN(parsed.valueOf()) ? value : parsed.toLocaleString();
}
