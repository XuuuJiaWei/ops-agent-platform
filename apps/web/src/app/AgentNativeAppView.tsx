import {
  Activity,
  AlertTriangle,
  ArrowUpRight,
  CheckCircle2,
  Clock3,
  Gauge,
  ShieldAlert,
  Sparkles,
} from "lucide-react";

type AgentNativeAppViewProps = {
  activeThreadId: string | undefined;
};

const healthMetrics = [
  { label: "Priority", value: "High", detail: "Escalated", tone: "danger" },
  { label: "SLA", value: "At risk", detail: "2h 15m", tone: "warning" },
  { label: "Sentiment", value: "Negative", detail: "Recent survey", tone: "danger" },
  { label: "Users", value: "124", detail: "+23", tone: "success" },
] as const;

const timeline = [
  { time: "09:02", event: "Case opened by customer", owner: "Maya Chen" },
  { time: "09:14", event: "Investigation started", owner: "Tier 2 Ops" },
  { time: "09:40", event: "Escalated to engineering", owner: "Lead Engineer" },
  { time: "10:20", event: "SLA warning triggered", owner: "System" },
] as const;

const evidenceItems = [
  { label: "Kibana error-rate panel", meta: "checkout-service / prod", status: "Pinned" },
  { label: "Trace sample", meta: "payment handoff latency", status: "Needs review" },
  { label: "Recent deploy", meta: "build 2026.08.01-1142", status: "Correlated" },
] as const;

const runbookSteps = [
  { label: "Verify customer impact", state: "Done" },
  { label: "Compare deploy window", state: "Running" },
  { label: "Draft escalation note", state: "Queued" },
] as const;

export function AgentNativeAppView({ activeThreadId }: AgentNativeAppViewProps) {
  return (
    <div className="h-full overflow-y-auto bg-[#f7f8fa]">
      <div className="mx-auto flex w-full max-w-6xl flex-col gap-5 px-4 py-5 sm:px-6 lg:px-8">
        <section className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_20rem]">
          <div className="min-w-0 rounded-md border border-[var(--border-subtle)] bg-white p-4 shadow-sm">
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <p className="text-xs font-semibold uppercase text-[var(--text-secondary)]">Active investigation</p>
                <h1 className="mt-1 text-2xl font-semibold tracking-normal text-[var(--text-primary)]">Northstar Analytics SSO loop</h1>
                <p className="mt-2 max-w-2xl text-sm leading-6 text-[var(--text-secondary)]">
                  Production sign-in failures are clustered around SAML callback retries and recent identity-provider metadata refreshes.
                </p>
              </div>
              <span className="inline-flex shrink-0 items-center gap-1.5 rounded-md border border-[#fed7aa] bg-[#fff7ed] px-2.5 py-1 text-xs font-semibold text-[#9a3412]">
                <ShieldAlert aria-hidden="true" className="size-3.5" />
                P1
              </span>
            </div>

            <div className="mt-5 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
              {healthMetrics.map((metric) => (
                <MetricTile key={metric.label} {...metric} />
              ))}
            </div>
          </div>

          <aside className="rounded-md border border-[var(--border-subtle)] bg-white p-4 shadow-sm">
            <div className="flex items-center gap-2 text-sm font-semibold text-[var(--text-primary)]">
              <Sparkles aria-hidden="true" className="size-4 text-[var(--accent)]" />
              Agent state
            </div>
            <dl className="mt-4 space-y-3 text-sm">
              <StateRow label="Thread" value={activeThreadId ?? "new conversation"} />
              <StateRow label="Phase" value="Evidence gathering" />
              <StateRow label="Confidence" value="Medium" />
              <StateRow label="Next run" value="Awaiting operator" />
            </dl>
          </aside>
        </section>

        <section className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_22rem]">
          <div className="rounded-md border border-[var(--border-subtle)] bg-white p-4 shadow-sm">
            <div className="mb-4 flex items-center justify-between gap-3">
              <div>
                <h2 className="text-base font-semibold text-[var(--text-primary)]">Investigation timeline</h2>
                <p className="mt-1 text-xs text-[var(--text-secondary)]">Recent events</p>
              </div>
              <Clock3 aria-hidden="true" className="size-4 text-[var(--text-secondary)]" />
            </div>
            <div className="overflow-hidden rounded-md border border-[#e8edf2]">
              <table className="w-full table-fixed text-left text-sm">
                <thead className="bg-[#f5f7f9] text-xs uppercase text-[var(--text-secondary)]">
                  <tr>
                    <th className="w-20 px-3 py-2 font-semibold">Time</th>
                    <th className="px-3 py-2 font-semibold">Event</th>
                    <th className="w-32 px-3 py-2 font-semibold">By</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-[#edf1f4]">
                  {timeline.map((item) => (
                    <tr key={`${item.time}-${item.event}`}>
                      <td className="px-3 py-3 font-mono text-xs text-[var(--text-secondary)]">{item.time}</td>
                      <td className="px-3 py-3 text-[var(--text-primary)]">{item.event}</td>
                      <td className="px-3 py-3 text-[var(--text-secondary)]">{item.owner}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          <div className="rounded-md border border-[var(--border-subtle)] bg-white p-4 shadow-sm">
            <div className="mb-4 flex items-center justify-between gap-3">
              <div>
                <h2 className="text-base font-semibold text-[var(--text-primary)]">Runbook</h2>
                <p className="mt-1 text-xs text-[var(--text-secondary)]">Current queue</p>
              </div>
              <Gauge aria-hidden="true" className="size-4 text-[var(--text-secondary)]" />
            </div>
            <ol className="space-y-3">
              {runbookSteps.map((step) => (
                <li className="flex items-center justify-between gap-3 rounded-md border border-[#e8edf2] px-3 py-2" key={step.label}>
                  <span className="min-w-0 truncate text-sm text-[var(--text-primary)]">{step.label}</span>
                  <RunbookBadge state={step.state} />
                </li>
              ))}
            </ol>
          </div>
        </section>

        <section className="rounded-md border border-[var(--border-subtle)] bg-white p-4 shadow-sm">
          <div className="mb-4 flex items-center justify-between gap-3">
            <div>
              <h2 className="text-base font-semibold text-[var(--text-primary)]">Evidence</h2>
              <p className="mt-1 text-xs text-[var(--text-secondary)]">Attached artifacts</p>
            </div>
            <Activity aria-hidden="true" className="size-4 text-[var(--text-secondary)]" />
          </div>
          <div className="grid gap-3 md:grid-cols-3">
            {evidenceItems.map((item) => (
              <article className="rounded-md border border-[#e8edf2] p-3" key={item.label}>
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <h3 className="truncate text-sm font-semibold text-[var(--text-primary)]">{item.label}</h3>
                    <p className="mt-1 truncate text-xs text-[var(--text-secondary)]">{item.meta}</p>
                  </div>
                  <ArrowUpRight aria-hidden="true" className="size-4 shrink-0 text-[var(--text-secondary)]" />
                </div>
                <p className="mt-4 text-xs font-semibold text-[var(--accent-strong)]">{item.status}</p>
              </article>
            ))}
          </div>
        </section>
      </div>
    </div>
  );
}

type MetricTileProps = (typeof healthMetrics)[number];

function MetricTile({ detail, label, tone, value }: MetricTileProps) {
  const toneClass = {
    danger: "text-[var(--danger)]",
    success: "text-[var(--success)]",
    warning: "text-[var(--warning)]",
  }[tone];

  return (
    <div className="rounded-md border border-[#e8edf2] bg-[#fbfcfd] p-3">
      <p className="text-xs font-semibold uppercase text-[var(--text-secondary)]">{label}</p>
      <p className="mt-2 text-2xl font-semibold text-[var(--text-primary)]">{value}</p>
      <p className={`mt-1 text-xs font-semibold ${toneClass}`}>{detail}</p>
    </div>
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

function RunbookBadge({ state }: { state: string }) {
  if (state === "Done") {
    return (
      <span className="inline-flex shrink-0 items-center gap-1 rounded-md bg-[#e8f5ee] px-2 py-1 text-xs font-semibold text-[var(--success)]">
        <CheckCircle2 aria-hidden="true" className="size-3" />
        Done
      </span>
    );
  }

  if (state === "Running") {
    return (
      <span className="inline-flex shrink-0 items-center gap-1 rounded-md bg-[#eaf7f8] px-2 py-1 text-xs font-semibold text-[var(--accent-strong)]">
        <Activity aria-hidden="true" className="size-3" />
        Running
      </span>
    );
  }

  return (
    <span className="inline-flex shrink-0 items-center gap-1 rounded-md bg-[#fff7ed] px-2 py-1 text-xs font-semibold text-[var(--warning)]">
      <AlertTriangle aria-hidden="true" className="size-3" />
      Queued
    </span>
  );
}
