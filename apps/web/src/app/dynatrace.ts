// Frontend contract for the agent-native Dynatrace dashboard.
// Mirrors ops_pilot.agent.state.DynatraceDashboard (services/agent). The agent
// writes this into shared state via `render_dynatrace_dashboard`; the App view
// reads it through useAgent and renders a live projection of it.

export const DYNATRACE_DASHBOARD_STATE_KEY = "dynatrace_dashboard";

export type MetricTone = "normal" | "warning" | "danger" | "success";
export type DashboardStatus = "loading" | "ready" | "error";

export type DynatraceMetric = {
  key: string;
  label: string;
  value: string;
  unit?: string | null;
  tone?: MetricTone;
  sparkline?: number[] | null;
};

export type DynatraceProblem = {
  id: string;
  title: string;
  severity: string;
  entity?: string;
  started_at?: string;
};

export type DynatraceDashboard = {
  generated_at?: string;
  focus_entity?: string | null;
  time_window?: string;
  status?: DashboardStatus;
  metrics?: DynatraceMetric[];
  problems?: DynatraceProblem[];
  note?: string;
};

export type AgentStateWithDashboard = {
  [DYNATRACE_DASHBOARD_STATE_KEY]?: DynatraceDashboard;
};

export function readDynatraceDashboard(state: unknown): DynatraceDashboard | undefined {
  if (!state || typeof state !== "object") {
    return undefined;
  }
  const value = (state as AgentStateWithDashboard)[DYNATRACE_DASHBOARD_STATE_KEY];
  return value && typeof value === "object" ? value : undefined;
}
