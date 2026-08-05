import { useAgent } from "@copilotkit/react-core/v2";
import {
  Activity,
  AlertTriangle,
  ChevronRight,
  CircleDot,
  Clock3,
  Database,
  ExternalLink,
  FileText,
  GitBranch,
  Sparkles,
  Target,
  Waypoints,
} from "lucide-react";
import { useState } from "react";
import type { BrowserEnv } from "@/lib/env";
import {
  type Storyline,
  type StorylineNode,
  type StorylineRole,
  type StorylineSeverity,
  formatConfidence,
  formatEpochMs,
  formatWindow,
  normalizeRole,
  normalizeSeverity,
  readStoryline,
  sortNodesByTime,
} from "./storyline";

type AgentNativeAppViewProps = {
  activeThreadId: string | undefined;
  env: BrowserEnv;
};

export function AgentNativeAppView({ activeThreadId, env }: AgentNativeAppViewProps) {
  // Official CopilotKit "render shared state in-app" pattern: read agent.state
  // unconditionally (with a default) — the component re-renders on every state
  // mutation. See docs: shared-state/rendering-in-app.
  const { agent } = useAgent({ agentId: env.assistantId });
  const storyline = readStoryline(agent?.state);

  return (
    <div className="h-full overflow-y-auto bg-[#f7f8fa]">
      <div className="mx-auto flex w-full max-w-6xl flex-col gap-5 px-4 py-5 sm:px-6 lg:px-8">
        <StorylineBody activeThreadId={activeThreadId} storyline={storyline} />
      </div>
    </div>
  );
}

function StorylineBody({
  activeThreadId,
  storyline,
}: {
  activeThreadId: string | undefined;
  storyline: Storyline | undefined;
}) {
  if (!storyline) {
    return <EmptyState />;
  }

  const status = storyline.status ?? "ready";
  const nodes = sortNodesByTime(storyline.nodes ?? []);
  const entities = storyline.entities ?? [];
  const gaps = storyline.gaps ?? [];
  const rootCause = storyline.root_cause ?? undefined;

  return (
    <>
      <section className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_20rem]">
        <div className="min-w-0 rounded-md border border-[var(--border-subtle)] bg-white p-4 shadow-sm">
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0">
              <p className="text-xs font-semibold uppercase text-[var(--text-secondary)]">Multi-source fault storyline</p>
              <h1 className="mt-1 text-2xl font-semibold tracking-normal text-[var(--text-primary)]">
                {rootCause?.entity_name ?? entities[0] ?? "Correlated timeline"}
              </h1>
              {status === "loading" && !storyline.narrative ? (
                <NarrativeSkeleton />
              ) : (
                <p className="mt-2 max-w-2xl text-sm leading-6 text-[var(--text-secondary)]">
                  {storyline.narrative ?? "The agent is correlating Dynatrace and Kibana signals in this window."}
                </p>
              )}
            </div>
            <StatusBadge status={status} />
          </div>

          {rootCause ? <RootCauseBanner node={rootCause} confidence={storyline.confidence} /> : null}
        </div>

        <aside className="rounded-md border border-[var(--border-subtle)] bg-white p-4 shadow-sm">
          <div className="flex items-center gap-2 text-sm font-semibold text-[var(--text-primary)]">
            <Sparkles aria-hidden="true" className="size-4 text-[var(--accent)]" />
            Correlation summary
          </div>
          <dl className="mt-4 space-y-3 text-sm">
            <StateRow label="Thread" value={activeThreadId ?? "new conversation"} />
            <StateRow label="Window" value={formatWindow(storyline.window)} />
            <StateRow label="Entities" value={entities.length > 0 ? String(entities.length) : "—"} />
            <StateRow label="Signals" value={nodes.length > 0 ? String(nodes.length) : "—"} />
            <StateRow label="Confidence" value={formatConfidence(storyline.confidence)} />
            <StateRow label="Updated" value={formatTimestamp(storyline.generated_at)} />
          </dl>
          {entities.length > 0 ? (
            <div className="mt-4 border-t border-[#edf1f4] pt-3">
              <p className="text-xs font-semibold uppercase text-[var(--text-secondary)]">Involved entities</p>
              <ul className="mt-2 flex flex-wrap gap-1.5">
                {entities.map((entity) => (
                  <li
                    className="inline-flex items-center rounded-md bg-[#f0f4f8] px-2 py-0.5 font-mono text-[11px] text-[var(--text-primary)]"
                    key={entity}
                  >
                    {entity}
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
        </aside>
      </section>

      {gaps.length > 0 ? <GapsBanner gaps={gaps} /> : null}

      <section className="rounded-md border border-[var(--border-subtle)] bg-white p-4 shadow-sm">
        <div className="mb-4 flex items-center justify-between gap-3">
          <div>
            <h2 className="text-base font-semibold text-[var(--text-primary)]">Correlated timeline</h2>
            <p className="mt-1 text-xs text-[var(--text-secondary)]">Signals aligned across Dynatrace &amp; Kibana</p>
          </div>
          <Clock3 aria-hidden="true" className="size-4 text-[var(--text-secondary)]" />
        </div>
        {nodes.length > 0 ? (
          <ol className="relative ml-2 border-l border-[#e3e9ef]">
            {nodes.map((node, index) => (
              <TimelineNode
                isRootCause={isSameNode(node, rootCause)}
                key={nodeKey(node, index)}
                node={node}
              />
            ))}
          </ol>
        ) : (
          <p className="rounded-md border border-dashed border-[#e8edf2] px-3 py-6 text-center text-sm text-[var(--text-secondary)]">
            {status === "loading" ? "Agent is gathering and aligning signals…" : "No correlated signals in this window."}
          </p>
        )}
      </section>
    </>
  );
}

function EmptyState() {
  return (
    <section className="rounded-md border border-dashed border-[var(--border-subtle)] bg-white p-10 text-center shadow-sm">
      <Waypoints aria-hidden="true" className="mx-auto size-8 text-[var(--text-secondary)]" />
      <h1 className="mt-4 text-lg font-semibold text-[var(--text-primary)]">No storyline yet</h1>
      <p className="mx-auto mt-2 max-w-md text-sm leading-6 text-[var(--text-secondary)]">
        Ask the agent to correlate a fault — e.g. <em>“what happened to event-consumer in the last 30 minutes?”</em> or{" "}
        <em>“explain problem P-26081082”</em>. The agent aligns Dynatrace problems/events with Kibana logs and builds the
        timeline here.
      </p>
    </section>
  );
}

function RootCauseBanner({
  node,
  confidence,
}: {
  node: StorylineNode;
  confidence: number | null | undefined;
}) {
  return (
    <div className="mt-4 flex items-start gap-3 rounded-md border border-[#fecaca] bg-[#fef2f2] px-3 py-3">
      <Target aria-hidden="true" className="mt-0.5 size-4 shrink-0 text-[var(--danger)]" />
      <div className="min-w-0">
        <p className="text-xs font-semibold uppercase text-[var(--danger)]">
          Likely root cause · {formatConfidence(confidence)} confidence
        </p>
        <p className="mt-1 text-sm font-medium text-[var(--text-primary)]">{node.title}</p>
        <p className="mt-0.5 font-mono text-[11px] text-[var(--text-secondary)]">
          {node.kind}
          {node.entity_name ? ` · ${node.entity_name}` : ""}
        </p>
      </div>
    </div>
  );
}

function GapsBanner({ gaps }: { gaps: string[] }) {
  return (
    <section className="rounded-md border border-[#fde68a] bg-[#fffbeb] px-4 py-3 shadow-sm">
      <div className="flex items-center gap-2 text-sm font-semibold text-[#92400e]">
        <AlertTriangle aria-hidden="true" className="size-4" />
        Coverage gaps
      </div>
      <ul className="mt-2 space-y-1 text-sm text-[#92400e]">
        {gaps.map((gap, index) => (
          <li className="flex items-start gap-2" key={index}>
            <span aria-hidden="true" className="mt-1.5 size-1 shrink-0 rounded-full bg-[#b45309]" />
            <span>{gap}</span>
          </li>
        ))}
      </ul>
    </section>
  );
}

function TimelineNode({ node, isRootCause }: { node: StorylineNode; isRootCause: boolean }) {
  const [expanded, setExpanded] = useState(false);
  const severity = normalizeSeverity(node.severity);
  const role = normalizeRole(node.role);
  const hasEvidence = node.evidence && Object.keys(node.evidence).length > 0;

  return (
    <li className="relative ml-4 pb-5 last:pb-0">
      <span
        aria-hidden="true"
        className={`absolute -left-[1.3125rem] top-1 flex size-3 items-center justify-center rounded-full ring-4 ring-white ${dotClass(severity)}`}
      />
      <div
        className={`rounded-md border p-3 ${isRootCause ? "border-[#fecaca] bg-[#fef6f6]" : "border-[#e8edf2] bg-[#fbfcfd]"}`}
      >
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <SourceBadge source={node.source} />
              <RoleBadge role={role} />
              {isRootCause ? (
                <span className="inline-flex items-center gap-1 rounded bg-[#fef2f2] px-1.5 py-0.5 text-[10px] font-semibold uppercase text-[var(--danger)]">
                  <Target aria-hidden="true" className="size-3" />
                  Root cause
                </span>
              ) : null}
            </div>
            <p className="mt-1.5 text-sm font-medium text-[var(--text-primary)]">{node.title}</p>
            <p className="mt-0.5 font-mono text-[11px] text-[var(--text-secondary)]">
              {node.kind}
              {node.entity_name ? ` · ${node.entity_name}` : ""}
            </p>
          </div>
          <time className="shrink-0 font-mono text-[11px] text-[var(--text-secondary)]">{formatEpochMs(node.ts)}</time>
        </div>

        {hasEvidence || node.deep_link ? (
          <div className="mt-2 flex items-center gap-3 border-t border-[#eef2f5] pt-2">
            {hasEvidence ? (
              <button
                aria-expanded={expanded}
                className="inline-flex items-center gap-1 text-[11px] font-semibold text-[var(--accent-strong)] hover:underline"
                onClick={() => setExpanded((open) => !open)}
                type="button"
              >
                <ChevronRight
                  aria-hidden="true"
                  className={`size-3 transition-transform ${expanded ? "rotate-90" : ""}`}
                />
                Evidence
              </button>
            ) : null}
            {node.deep_link ? (
              <a
                className="inline-flex items-center gap-1 text-[11px] font-semibold text-[var(--accent-strong)] hover:underline"
                href={node.deep_link}
                rel="noreferrer"
                target="_blank"
              >
                <ExternalLink aria-hidden="true" className="size-3" />
                Open source
              </a>
            ) : null}
          </div>
        ) : null}

        {expanded && hasEvidence ? (
          <pre className="mt-2 overflow-x-auto rounded border border-[#e8edf2] bg-white p-2 font-mono text-[11px] leading-5 text-[var(--text-secondary)]">
            {JSON.stringify(node.evidence, null, 2)}
          </pre>
        ) : null}
      </div>
    </li>
  );
}

function SourceBadge({ source }: { source: string }) {
  const { Icon, label, className } = sourceMeta(source);
  return (
    <span className={`inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase ${className}`}>
      <Icon aria-hidden="true" className="size-3" />
      {label}
    </span>
  );
}

function RoleBadge({ role }: { role: StorylineRole }) {
  const meta: Record<StorylineRole, { label: string; className: string }> = {
    trigger: { label: "Trigger", className: "bg-[#fef2f2] text-[var(--danger)]" },
    propagation: { label: "Propagation", className: "bg-[#fff7ed] text-[#9a3412]" },
    symptom: { label: "Symptom", className: "bg-[#f0f9ff] text-[var(--accent-strong)]" },
    context: { label: "Context", className: "bg-[#f3f4f6] text-[var(--text-secondary)]" },
  };
  const { label, className } = meta[role];
  return (
    <span className={`inline-flex items-center rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase ${className}`}>
      {label}
    </span>
  );
}

function StatusBadge({ status }: { status: NonNullable<Storyline["status"]> }) {
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
        Correlating
      </span>
    );
  }
  return (
    <span className="inline-flex shrink-0 items-center gap-1.5 rounded-md border border-[#bbf7d0] bg-[#f0fdf4] px-2.5 py-1 text-xs font-semibold text-[#166534]">
      <CircleDot aria-hidden="true" className="size-3.5" />
      Ready
    </span>
  );
}

function StateRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="grid grid-cols-[6rem_minmax(0,1fr)] gap-2 border-b border-[#edf1f4] pb-3 last:border-b-0 last:pb-0">
      <dt className="text-xs font-semibold uppercase text-[var(--text-secondary)]">{label}</dt>
      <dd className="truncate text-right font-mono text-xs text-[var(--text-primary)]">{value}</dd>
    </div>
  );
}

function NarrativeSkeleton() {
  return (
    <div className="mt-3 space-y-2">
      <div className="h-3 w-full animate-pulse rounded bg-[#e8edf2]" />
      <div className="h-3 w-11/12 animate-pulse rounded bg-[#e8edf2]" />
      <div className="h-3 w-3/4 animate-pulse rounded bg-[#e8edf2]" />
    </div>
  );
}

function dotClass(severity: StorylineSeverity): string {
  return {
    critical: "bg-[var(--danger)]",
    error: "bg-[#ea580c]",
    warn: "bg-[var(--warning)]",
    info: "bg-[#94a3b8]",
  }[severity];
}

function sourceMeta(source: string): { Icon: typeof Database; label: string; className: string } {
  switch (source) {
    case "dynatrace_problem":
      return { Icon: AlertTriangle, label: "DT Problem", className: "bg-[#eef2ff] text-[#4338ca]" };
    case "dynatrace_event":
      return { Icon: GitBranch, label: "DT Event", className: "bg-[#eef2ff] text-[#4338ca]" };
    case "dynatrace_metric":
      return { Icon: Activity, label: "DT Metric", className: "bg-[#eef2ff] text-[#4338ca]" };
    case "kibana_log":
      return { Icon: FileText, label: "Kibana Log", className: "bg-[#fdf4ff] text-[#a21caf]" };
    default:
      return { Icon: Database, label: source, className: "bg-[#f3f4f6] text-[var(--text-secondary)]" };
  }
}

function isSameNode(node: StorylineNode, other: StorylineNode | undefined): boolean {
  if (!other) {
    return false;
  }
  return node.ts === other.ts && node.kind === other.kind && node.source === other.source;
}

function nodeKey(node: StorylineNode, index: number): string {
  return `${node.ts}-${node.source}-${node.kind}-${index}`;
}

function formatTimestamp(value: string | undefined): string {
  if (!value) {
    return "—";
  }
  const parsed = new Date(value);
  return Number.isNaN(parsed.valueOf()) ? value : parsed.toLocaleString();
}
