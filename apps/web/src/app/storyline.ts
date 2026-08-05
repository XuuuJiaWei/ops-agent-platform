// Frontend contract for the agent-native multi-source fault storyline panel.
//
// Mirrors the backend Storyline / StorylineNode data structures defined in
// docs/design/multi-source-storyline-correlation.md §3.1. The correlation
// workflow (Dynatrace problems/events/metrics + Kibana logs, aligned in one
// time window) writes the `storyline` shared-state key in the shape below;
// AgentNativeAppView reads it via CopilotKit shared state and renders the
// timeline. Until a backend emitter populates the key, the panel renders its
// empty state.

export const STORYLINE_STATE_KEY = "storyline";

// Origin of a signal on the timeline. Kept as a string union so the backend
// can add sources without breaking the reader (unknown values fall back to a
// neutral rendering).
export type StorylineSource =
  | "dynatrace_problem"
  | "dynatrace_event"
  | "dynatrace_metric"
  | "kibana_log";

export type StorylineSeverity = "info" | "warn" | "error" | "critical";

// Causal position of a node in the narrative.
export type StorylineRole = "trigger" | "propagation" | "symptom" | "context";

export type StorylineStatus = "loading" | "ready" | "error";

export type StorylineNode = {
  ts: number; // UTC epoch ms — unified time base across both sources.
  source: StorylineSource | string;
  kind: string; // e.g. "LongJAVAGCTime" / "KubeHpaMaxedOut" / "log.ERROR".
  title: string;
  entity_id?: string | null;
  entity_name?: string | null;
  severity?: StorylineSeverity | string;
  role?: StorylineRole | string;
  // Raw evidence (problemId / eventId / correlationId / log line / trace.id …).
  evidence?: Record<string, unknown> | null;
  deep_link?: string | null; // Back-link into Dynatrace / Kibana UI.
};

export type Storyline = {
  status?: StorylineStatus;
  // Actual aligned window [from_ms, to_ms] in UTC epoch ms.
  window?: [number, number] | null;
  entities?: string[];
  nodes?: StorylineNode[];
  root_cause?: StorylineNode | null;
  narrative?: string;
  confidence?: number | null; // 0–1 correlation / root-cause confidence.
  // Explicitly declared missing sources — "No silent caps": never let the
  // panel imply full coverage when a source had no data / no permission.
  gaps?: string[];
  generated_at?: string;
};

export type AgentStateWithStoryline = {
  [STORYLINE_STATE_KEY]?: Storyline;
};

export function readStoryline(state: unknown): Storyline | undefined {
  if (!state || typeof state !== "object") {
    return undefined;
  }
  const value = (state as AgentStateWithStoryline)[STORYLINE_STATE_KEY];
  return value && typeof value === "object" ? value : undefined;
}

// ---- Presentation helpers (pure, unit-testable) ---------------------------

export function normalizeSeverity(severity: string | undefined): StorylineSeverity {
  switch (severity) {
    case "critical":
    case "error":
    case "warn":
    case "info":
      return severity;
    default:
      return "info";
  }
}

export function normalizeRole(role: string | undefined): StorylineRole {
  switch (role) {
    case "trigger":
    case "propagation":
    case "symptom":
    case "context":
      return role;
    default:
      return "context";
  }
}

// Sort nodes ascending by timestamp without mutating the input array.
export function sortNodesByTime(nodes: StorylineNode[]): StorylineNode[] {
  return [...nodes].sort((a, b) => a.ts - b.ts);
}

export function formatEpochMs(ts: number | undefined): string {
  if (ts === undefined || ts === null || Number.isNaN(ts)) {
    return "—";
  }
  const parsed = new Date(ts);
  return Number.isNaN(parsed.valueOf()) ? String(ts) : parsed.toLocaleTimeString();
}

export function formatWindow(window: [number, number] | null | undefined): string {
  if (!window || window.length !== 2) {
    return "—";
  }
  const [from, to] = window;
  const fromDate = new Date(from);
  const toDate = new Date(to);
  if (Number.isNaN(fromDate.valueOf()) || Number.isNaN(toDate.valueOf())) {
    return "—";
  }
  return `${fromDate.toLocaleString()} → ${toDate.toLocaleTimeString()}`;
}

export function formatConfidence(confidence: number | null | undefined): string {
  if (confidence === undefined || confidence === null || Number.isNaN(confidence)) {
    return "—";
  }
  return `${Math.round(confidence * 100)}%`;
}
