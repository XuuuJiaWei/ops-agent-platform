import * as DropdownMenu from "@radix-ui/react-dropdown-menu";
import { Archive, ChevronLeft, Ellipsis, Menu, MessageSquarePlus, RefreshCw, Trash2 } from "lucide-react";
import type { ConversationThread, ConversationThreadsState } from "./conversationThreads";
import { WorkspaceNavigation, type MainView } from "./WorkspaceNavigation";

type ThreadSidebarProps = {
  activeThreadId: string | undefined;
  activeView: MainView;
  isDesktopOpen: boolean;
  isMobileOpen: boolean;
  onCloseDesktop: () => void;
  onCloseMobile: () => void;
  onDeleteThread: (threadId: string) => Promise<void>;
  onNewThread: () => void;
  onSelectThread: (threadId: string) => void;
  onToggleMobile: () => void;
  onViewChange: (view: MainView) => void;
  threadsState: ConversationThreadsState;
};

export function ThreadSidebar({
  activeThreadId,
  activeView,
  isDesktopOpen,
  isMobileOpen,
  onCloseDesktop,
  onCloseMobile,
  onDeleteThread,
  onNewThread,
  onSelectThread,
  onToggleMobile,
  onViewChange,
  threadsState,
}: ThreadSidebarProps) {
  function closeFromHeader() {
    if (typeof window !== "undefined" && window.matchMedia("(min-width: 768px)").matches) {
      onCloseDesktop();
      return;
    }
    onCloseMobile();
  }

  return (
    <>
      {activeView === "chat" ? (
        <button
          aria-label="Open navigation"
          className="fixed left-3 top-3 z-30 inline-flex size-9 items-center justify-center rounded-lg border border-slate-200 bg-white text-slate-600 shadow-sm md:hidden"
          onClick={onToggleMobile}
          title="Open navigation"
          type="button"
        >
          <Menu aria-hidden="true" className="size-4" />
        </button>
      ) : null}
      <button
        aria-label="Close navigation"
        className={`fixed inset-0 z-20 bg-slate-950/25 backdrop-blur-[1px] transition-opacity md:hidden ${isMobileOpen ? "opacity-100" : "pointer-events-none opacity-0"}`}
        onClick={onCloseMobile}
        tabIndex={isMobileOpen ? 0 : -1}
        type="button"
      />
      <aside
        aria-label="Chat navigation"
        className={`fixed inset-y-0 left-0 z-30 flex w-72 max-w-[88vw] flex-col border-r border-slate-200 bg-slate-50 shadow-xl transition-transform md:static md:z-auto md:max-w-none md:translate-x-0 md:shadow-none ${
          isMobileOpen ? "translate-x-0" : "-translate-x-full"
        } ${isDesktopOpen ? "md:flex" : "md:hidden"}`}
      >
        <WorkspaceNavigation
          endAction={
            <button
              aria-label="Collapse navigation"
              className="inline-flex size-8 items-center justify-center rounded-lg text-slate-500 hover:bg-white hover:text-slate-950"
              onClick={closeFromHeader}
              title="Collapse navigation"
              type="button"
            >
              <ChevronLeft aria-hidden="true" className="size-4" />
            </button>
          }
          onChange={onViewChange}
          value={activeView}
        />

        <div className="mx-3 my-4 h-px bg-slate-200" />
        <ConversationPanel
          activeThreadId={activeThreadId}
          onDeleteThread={onDeleteThread}
          onNewThread={onNewThread}
          onSelectThread={onSelectThread}
          threadsState={threadsState}
        />
      </aside>
    </>
  );
}

type ConversationPanelProps = {
  activeThreadId: string | undefined;
  onNewThread: () => void;
  onDeleteThread: (threadId: string) => Promise<void>;
  onSelectThread: (threadId: string) => void;
  threadsState: ConversationThreadsState;
};

function ConversationPanel({ activeThreadId, onDeleteThread, onNewThread, onSelectThread, threadsState }: ConversationPanelProps) {
  const { archiveThread, error, fetchMoreThreads, hasMoreThreads, isFetchingMoreThreads, isLoading, refetchThreads, threads } = threadsState;

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="shrink-0 px-3">
        <button
          className="inline-flex h-10 w-full items-center justify-center gap-2 rounded-lg bg-slate-950 px-3 text-sm font-medium text-white shadow-sm transition hover:bg-slate-800"
          onClick={onNewThread}
          type="button"
        >
          <MessageSquarePlus aria-hidden="true" className="size-4" />
          New chat
        </button>
      </div>

      <div className="mt-5 flex shrink-0 items-center justify-between px-4 pb-2">
        <h2 className="text-[11px] font-semibold uppercase tracking-[0.08em] text-slate-500">Recent</h2>
        <button
          aria-label="Refresh conversations"
          className="inline-flex size-7 items-center justify-center rounded-md text-slate-400 hover:bg-white hover:text-slate-900"
          onClick={refetchThreads}
          title="Refresh conversations"
          type="button"
        >
          <RefreshCw aria-hidden="true" className="size-3.5" />
        </button>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto px-2 pb-3 [scrollbar-width:thin]">
        {isLoading ? <EmptyRow label="Loading chats…" /> : null}
        {!isLoading && error ? (
          <div className="mx-1 rounded-lg border border-red-200 bg-white p-3 text-sm text-slate-600">
            <p className="mb-2 text-red-700">Chats are temporarily unavailable.</p>
            <button className="inline-flex h-8 items-center gap-2 rounded-md border border-slate-200 px-2 text-xs font-medium" onClick={refetchThreads} type="button">
              <RefreshCw aria-hidden="true" className="size-3" />
              Try again
            </button>
          </div>
        ) : null}
        {!isLoading && !error && threads.length === 0 ? <EmptyRow label="Start a chat to see it here." /> : null}
        <ol className="space-y-1">
          {threads.map((thread) => (
            <ThreadRow
              active={thread.id === activeThreadId}
              key={thread.id}
              onArchive={() => void archiveThread(thread.id)}
              onDelete={() => void onDeleteThread(thread.id)}
              onSelect={() => onSelectThread(thread.id)}
              thread={thread}
            />
          ))}
        </ol>
      </div>

      {hasMoreThreads ? (
        <div className="shrink-0 px-3 pb-3">
          <button
            className="inline-flex h-9 w-full items-center justify-center gap-2 rounded-lg border border-slate-200 bg-white text-sm text-slate-600 hover:bg-slate-100 hover:text-slate-950"
            disabled={isFetchingMoreThreads}
            onClick={fetchMoreThreads}
            type="button"
          >
            <RefreshCw aria-hidden="true" className={`size-4 ${isFetchingMoreThreads ? "animate-spin" : ""}`} />
            Load more
          </button>
        </div>
      ) : null}
    </div>
  );
}

type ThreadRowProps = {
  active: boolean;
  onArchive: () => void;
  onDelete: () => void;
  onSelect: () => void;
  thread: ConversationThread;
};

function ThreadRow({ active, onArchive, onDelete, onSelect, thread }: ThreadRowProps) {
  const name = thread.name || "Untitled chat";

  return (
    <li className={`group relative rounded-lg transition-colors ${active ? "bg-white shadow-sm ring-1 ring-slate-200/80" : "hover:bg-white/70"}`}>
      {active ? <span aria-hidden="true" className="absolute inset-y-2 left-0 w-0.5 rounded-r bg-blue-600" /> : null}
      <button className="flex min-h-12 w-full min-w-0 items-center gap-2 px-3 pr-10 text-left" onClick={onSelect} type="button">
        <span className="min-w-0 flex-1 truncate text-[13px] font-medium text-slate-800">{name}</span>
        <time className="shrink-0 text-[11px] tabular-nums text-slate-400">{formatRelativeTime(thread.lastRunAt ?? thread.updatedAt)}</time>
      </button>
      <ThreadActions name={name} onArchive={onArchive} onDelete={onDelete} />
    </li>
  );
}

function ThreadActions({ name, onArchive, onDelete }: { name: string; onArchive: () => void; onDelete: () => void }) {
  return (
    <DropdownMenu.Root>
      <DropdownMenu.Trigger asChild>
        <button
          aria-label={`Actions for ${name}`}
          className="absolute right-1.5 top-1/2 inline-flex size-8 -translate-y-1/2 items-center justify-center rounded-md bg-inherit text-slate-400 opacity-0 transition hover:bg-slate-100 hover:text-slate-900 focus:opacity-100 group-hover:opacity-100 data-[state=open]:bg-slate-100 data-[state=open]:opacity-100"
          type="button"
        >
          <Ellipsis aria-hidden="true" className="size-4" />
        </button>
      </DropdownMenu.Trigger>
      <DropdownMenu.Portal>
        <DropdownMenu.Content
          align="start"
          className="z-50 min-w-40 rounded-lg border border-slate-200 bg-white p-1 text-sm text-slate-700 shadow-xl"
          side="right"
          sideOffset={6}
        >
          <DropdownMenu.Item className="flex cursor-default select-none items-center gap-2 rounded-md px-2.5 py-2 outline-none data-[highlighted]:bg-slate-100 data-[highlighted]:text-slate-950" onSelect={onArchive}>
            <Archive aria-hidden="true" className="size-4" />
            Archive
          </DropdownMenu.Item>
          <DropdownMenu.Separator className="my-1 h-px bg-slate-100" />
          <DropdownMenu.Item className="flex cursor-default select-none items-center gap-2 rounded-md px-2.5 py-2 text-red-700 outline-none data-[highlighted]:bg-red-50" onSelect={onDelete}>
            <Trash2 aria-hidden="true" className="size-4" />
            Delete
          </DropdownMenu.Item>
        </DropdownMenu.Content>
      </DropdownMenu.Portal>
    </DropdownMenu.Root>
  );
}

function EmptyRow({ label }: { label: string }) {
  return <p className="mx-1 rounded-lg border border-dashed border-slate-200 bg-white/60 px-3 py-3 text-xs leading-5 text-slate-500">{label}</p>;
}

function formatRelativeTime(value: Date | number | string | null | undefined): string {
  if (!value) return "now";

  const date = new Date(value);
  if (Number.isNaN(date.valueOf())) return "now";

  const diffMs = Date.now() - date.valueOf();
  const minutes = Math.max(0, Math.round(diffMs / 60000));
  if (minutes < 1) return "now";
  if (minutes < 60) return `${minutes}m`;

  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours}h`;
  return `${Math.round(hours / 24)}d`;
}
