// Frontend contract for the agent-native Dynatrace dashboard.
//
// NOTE: The backend A2UI tool that populated this state was removed as a
// product decision — this view is retained for future exploration but has no
// live data source right now, so AgentNativeAppView renders its empty state.
// If/when a backend emitter is reintroduced, it must write the
// `dynatrace_dashboard` state key in the shape defined below.

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
  tone?: MetricTone;
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
