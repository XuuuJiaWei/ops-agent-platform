import { LayoutGrid, MessageSquareText, RefreshCw, Sparkles } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import useSWR from "swr";
import { getSpace, listSpaces } from "@/spaces/api";
import { SPACES_CHANGED_EVENT } from "@/spaces/events";
import { SpaceGrid } from "@/spaces/SpaceGrid";
import type { BrowserEnv } from "@/lib/env";

type AgentNativeAppViewProps = {
  activeThreadId: string | undefined;
  env: BrowserEnv;
};

export function AgentNativeAppView({ activeThreadId, env }: AgentNativeAppViewProps) {
  const storageKey = useMemo(() => `ops-agent-platform:selected-space:${env.assistantId}`, [env.assistantId]);
  const [selectedSpaceId, setSelectedSpaceId] = useState<string | undefined>(() => readSelectedSpace(storageKey));
  const summariesQuery = useSWR(["spaces", env.backendUrl], () => listSpaces(env));
  const summaries = summariesQuery.data ?? [];
  const effectiveSpaceId = selectedSpaceId && summaries.some((item) => item.id === selectedSpaceId) ? selectedSpaceId : summaries[0]?.id;
  const spaceQuery = useSWR(effectiveSpaceId ? ["space", env.backendUrl, effectiveSpaceId] : null, () => getSpace(env, effectiveSpaceId!));
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
    <div className="flex h-full min-h-0 bg-slate-50">
      <aside className="hidden w-64 shrink-0 border-r border-slate-200 bg-white lg:flex lg:flex-col">
        <div className="border-b border-slate-100 px-5 py-5">
          <div className="flex items-center gap-2 text-sm font-semibold text-slate-950">
            <span className="grid size-8 place-items-center rounded-lg bg-gradient-to-br from-blue-600 to-violet-600 text-white shadow-sm">
              <Sparkles aria-hidden="true" className="size-4" />
            </span>
            Spaces
          </div>
          <p className="mt-2 text-xs leading-5 text-slate-500">Persistent visual workspaces assembled with the agent.</p>
        </div>
        <nav aria-label="Spaces" className="min-h-0 flex-1 space-y-1 overflow-y-auto p-3">
          {summaries.map((summary) => (
            <button
              className={`flex w-full items-center gap-3 rounded-lg px-3 py-2.5 text-left transition ${
                effectiveSpaceId === summary.id ? "bg-blue-50 text-blue-800" : "text-slate-600 hover:bg-slate-50 hover:text-slate-950"
              }`}
              key={summary.id}
              onClick={() => selectSpace(summary.id)}
              type="button"
            >
              <LayoutGrid aria-hidden="true" className="size-4 shrink-0" />
              <span className="min-w-0 flex-1">
                <span className="block truncate text-sm font-medium">{summary.name}</span>
                <span className="block text-[11px] opacity-70">{summary.card_count} cards</span>
              </span>
            </button>
          ))}
        </nav>
        <div className="border-t border-slate-100 p-4 text-[11px] leading-5 text-slate-400">Spaces change when the agent completes a Space tool.</div>
      </aside>

      <section className="min-w-0 flex-1 overflow-y-auto">
        <div className="mx-auto w-full max-w-[1480px] px-4 py-5 sm:px-6 lg:px-8 lg:py-7">
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
              <h1 className="truncate text-xl font-semibold tracking-tight text-slate-950 sm:text-2xl">{space?.name ?? "Spaces"}</h1>
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
