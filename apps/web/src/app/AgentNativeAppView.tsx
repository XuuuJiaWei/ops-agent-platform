import { LayoutGrid, MessageSquareText, RefreshCw } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import useSWR from "swr";
import { getSpace, listSpaces } from "@/spaces/api";
import { SPACES_CHANGED_EVENT } from "@/spaces/events";
import { SpaceGrid } from "@/spaces/SpaceGrid";
import type { BrowserEnv } from "@/lib/env";
import { WorkspaceNavigation, type MainView } from "./WorkspaceNavigation";

type AgentNativeAppViewProps = {
  activeThreadId: string | undefined;
  env: BrowserEnv;
  onViewChange: (view: MainView) => void;
};

export function AgentNativeAppView({ activeThreadId, env, onViewChange }: AgentNativeAppViewProps) {
  const storageKey = useMemo(() => `ops-agent-platform:selected-space:${env.assistantId}`, [env.assistantId]);
  const [selectedSpaceId, setSelectedSpaceId] = useState<string | undefined>(() => readSelectedSpace(storageKey));
  const summariesQuery = useSWR(["spaces", env.backendUrl], () => listSpaces(env));
  const summaries = summariesQuery.data ?? [];
  const effectiveSpaceId = selectedSpaceId && summaries.some((item) => item.id === selectedSpaceId) ? selectedSpaceId : summaries[0]?.id;
  const spaceQuery = useSWR(
    effectiveSpaceId ? ["space", env.backendUrl, effectiveSpaceId] : null,
    () => getSpace(env, effectiveSpaceId!),
    {
      // Poll while the open space has any live (data-bound) cards so resolver
      // refreshes surface without a manual reload; static-only spaces don't poll.
      refreshInterval: (latest) => (latest?.cards.some((card) => card.binding != null) ? 15_000 : 0),
    },
  );
  const space = spaceQuery.data;
  const mutateSpaces = summariesQuery.mutate;
  const mutateSpace = spaceQuery.mutate;
  const loading = summariesQuery.isLoading || spaceQuery.isLoading;
  const validating = summariesQuery.isValidating || spaceQuery.isValidating;
  const queryError = summariesQuery.error ?? spaceQuery.error;
  const error = queryError instanceof Error ? queryError.message : queryError ? "Unable to load Spaces" : undefined;

  const refresh = useCallback(async () => {
    await Promise.all([mutateSpaces(), mutateSpace()]);
  }, [mutateSpace, mutateSpaces]);

  useEffect(() => {
    const handleSpacesChanged = () => void refresh();
    window.addEventListener(SPACES_CHANGED_EVENT, handleSpacesChanged);
    return () => window.removeEventListener(SPACES_CHANGED_EVENT, handleSpacesChanged);
  }, [refresh]);

  function selectSpace(spaceId: string) {
    writeSelectedSpace(storageKey, spaceId);
    setSelectedSpaceId(spaceId);
  }

  return (
    <div className="flex h-full min-h-0 bg-[var(--surface-page)]">
      <aside className="hidden w-72 shrink-0 border-r border-slate-200 bg-slate-50 lg:flex lg:flex-col">
        <WorkspaceNavigation onChange={onViewChange} value="spaces" />
        <div className="mx-3 my-4 h-px bg-slate-200" />
        <div className="flex items-center justify-between px-4 pb-2">
          <h2 className="text-[11px] font-semibold uppercase tracking-[0.08em] text-slate-500">Your spaces</h2>
          <span className="text-[11px] tabular-nums text-slate-400">{summaries.length}</span>
        </div>
        <nav aria-label="Spaces" className="min-h-0 flex-1 space-y-1 overflow-y-auto px-2 pb-3 [scrollbar-width:thin]">
          {summaries.map((summary) => (
            <button
              className={`relative flex w-full items-center gap-3 rounded-lg px-3 py-2.5 text-left transition ${
                effectiveSpaceId === summary.id ? "bg-white text-slate-950 shadow-sm ring-1 ring-slate-200/80" : "text-slate-600 hover:bg-white/70 hover:text-slate-950"
              }`}
              key={summary.id}
              onClick={() => selectSpace(summary.id)}
              type="button"
            >
              {effectiveSpaceId === summary.id ? <span aria-hidden="true" className="absolute inset-y-2 left-0 w-0.5 rounded-r bg-blue-600" /> : null}
              <LayoutGrid aria-hidden="true" className="size-4 shrink-0 text-slate-400" />
              <span className="min-w-0 flex-1">
                <span className="block truncate text-sm font-medium">{summary.name}</span>
                <span className="block text-[11px] text-slate-400">{summary.card_count} {summary.card_count === 1 ? "card" : "cards"}</span>
              </span>
            </button>
          ))}
        </nav>
        <div className="border-t border-slate-200 px-4 py-3 text-[11px] leading-5 text-slate-400">The agent keeps Spaces up to date as it works.</div>
      </aside>

      <section className="min-w-0 flex-1 overflow-y-auto">
        <div className="mx-auto w-full max-w-[1360px] px-4 py-5 sm:px-6 lg:px-8 lg:py-8">
          <div className="mb-6 flex items-start justify-between gap-4">
            <div className="min-w-0">
              <div className="mb-3 flex gap-2 overflow-x-auto lg:hidden">
                {summaries.map((summary) => (
                  <button
                    className={`shrink-0 rounded-full border px-3 py-1.5 text-xs font-medium ${
                      effectiveSpaceId === summary.id ? "border-blue-200 bg-blue-50 text-blue-800" : "border-slate-200 bg-white text-slate-600"
                    }`}
                    key={summary.id}
                    onClick={() => selectSpace(summary.id)}
                    type="button"
                  >
                    {summary.name}
                  </button>
                ))}
              </div>
              <h1 className="truncate text-xl font-semibold tracking-[-0.02em] text-slate-950 sm:text-2xl">{space?.name ?? "Spaces"}</h1>
              <p className="mt-1 text-sm text-slate-500">
                {space?.description ?? (summaries.length ? "Select a visual workspace" : "Create your first visual workspace with the agent")}
              </p>
              {space ? <p className="mt-2 text-xs text-slate-400">Updated {formatUpdatedAt(space.updated_at)} · version {space.version}</p> : null}
            </div>
            <button
              aria-label="Refresh Spaces"
              className="inline-flex size-9 shrink-0 items-center justify-center rounded-lg border border-slate-200 bg-white text-slate-500 shadow-sm hover:bg-slate-50 hover:text-slate-900"
              onClick={() => void refresh()}
              title="Refresh Spaces"
              type="button"
            >
              <RefreshCw aria-hidden="true" className={`size-4 ${validating ? "animate-spin" : ""}`} />
            </button>
          </div>

          {error ? <ErrorState message={error} onRetry={refresh} /> : null}
          {!error && loading && !space ? <LoadingState /> : null}
          {!error && !loading && summaries.length === 0 ? <EmptyState activeThreadId={activeThreadId} /> : null}
          {!error && space && space.cards.length === 0 ? <EmptySpaceState /> : null}
          {!error && space && space.cards.length > 0 ? <SpaceGrid cards={space.cards} /> : null}
        </div>
      </section>
    </div>
  );
}

function EmptyState({ activeThreadId }: { activeThreadId: string | undefined }) {
  return (
    <div className="grid min-h-[420px] place-items-center rounded-2xl border border-dashed border-slate-300 bg-white p-8 text-center">
      <div className="max-w-md">
        <span className="mx-auto grid size-12 place-items-center rounded-xl bg-blue-50 text-blue-700"><LayoutGrid aria-hidden="true" className="size-5" /></span>
        <h2 className="mt-4 text-base font-semibold text-slate-950">No Spaces yet</h2>
        <p className="mt-2 text-sm leading-6 text-slate-500">Open Chat and ask the agent to create a Space, then add KPI, chart, table, detail, or list cards.</p>
        <div className="mt-5 inline-flex items-center gap-2 rounded-full border border-slate-200 bg-slate-50 px-3 py-1.5 text-xs text-slate-500">
          <MessageSquareText aria-hidden="true" className="size-3.5" />
          {activeThreadId ? "Current conversation is ready" : "Start a conversation"}
        </div>
      </div>
    </div>
  );
}

function EmptySpaceState() {
  return (
    <div className="rounded-2xl border border-dashed border-slate-300 bg-white px-6 py-16 text-center">
      <h2 className="text-sm font-semibold text-slate-900">This Space is ready for cards</h2>
      <p className="mt-2 text-sm text-slate-500">Ask the agent to add a visualization to this Space.</p>
    </div>
  );
}

function LoadingState() {
  return <div className="h-72 animate-pulse rounded-2xl border border-slate-200 bg-white" />;
}

function ErrorState({ message, onRetry }: { message: string; onRetry: () => void }) {
  return (
    <div className="rounded-xl border border-red-200 bg-red-50 p-5 text-sm text-red-800">
      <p>{message}</p>
      <button className="mt-3 font-medium underline underline-offset-4" onClick={onRetry} type="button">Try again</button>
    </div>
  );
}

function formatUpdatedAt(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.valueOf())) return "recently";
  return new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" }).format(date);
}

function readSelectedSpace(storageKey: string): string | undefined {
  try {
    return localStorage.getItem(`${storageKey}:v1`) ?? undefined;
  } catch {
    return undefined;
  }
}

function writeSelectedSpace(storageKey: string, spaceId: string) {
  try {
    localStorage.setItem(`${storageKey}:v1`, spaceId);
  } catch {
    // Space selection persistence is best effort only.
  }
}
