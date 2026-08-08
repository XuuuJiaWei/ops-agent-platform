import {
  Archive,
  ChevronLeft,
  CircleAlert,
  Database,
  Menu,
  MessageSquarePlus,
  RefreshCw,
  SlidersHorizontal,
  Trash2,
  Unplug,
  Wrench,
} from "lucide-react";
import type { ReactNode } from "react";
import type { ConversationThread, ConversationThreadsState } from "./conversationThreads";

type ThreadSidebarProps = {
  activeThreadId: string | undefined;
  isDesktopOpen: boolean;
  isMobileOpen: boolean;
  onCloseDesktop: () => void;
  onCloseMobile: () => void;
  onDeleteThread: (threadId: string) => Promise<void>;
  onNewThread: () => void;
  onSelectThread: (threadId: string) => void;
  onToggleMobile: () => void;
  threadsState: ConversationThreadsState;
};

export function ThreadSidebar({
  activeThreadId,
  isDesktopOpen,
  isMobileOpen,
  onCloseDesktop,
  onCloseMobile,
  onDeleteThread,
  onNewThread,
  onSelectThread,
  onToggleMobile,
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
      <button
        aria-label="Open conversations"
        className="fixed left-4 top-4 z-30 inline-flex size-10 items-center justify-center rounded-md border border-[#dedede] bg-white text-[#4d4d4d] shadow-sm md:hidden"
        onClick={onToggleMobile}
        title="Open conversations"
        type="button"
      >
        <Menu aria-hidden="true" className="size-5" />
      </button>
      <div
        aria-hidden={!isMobileOpen}
        className={`fixed inset-0 z-20 bg-black/20 transition-opacity md:hidden ${isMobileOpen ? "opacity-100" : "pointer-events-none opacity-0"}`}
        onClick={onCloseMobile}
      />
      <aside
        className={`fixed inset-y-0 left-0 z-30 flex w-[340px] max-w-[88vw] flex-col border-r border-[#e5e5e5] bg-[#fbfbfb] shadow-xl transition-transform md:static md:z-auto md:max-w-none md:translate-x-0 md:shadow-none ${
          isMobileOpen ? "translate-x-0" : "-translate-x-full"
        } ${
          isDesktopOpen ? "md:flex" : "md:hidden"
        }`}
      >
        <header className="flex h-14 shrink-0 items-center justify-end px-4">
          <button
            aria-label="Collapse conversations"
            className="inline-flex size-8 items-center justify-center rounded-md text-[#5f5f5f] hover:bg-[#eeeeee] hover:text-[#111111]"
            onClick={closeFromHeader}
            title="Collapse conversations"
            type="button"
          >
            <ChevronLeft aria-hidden="true" className="size-5" />
          </button>
        </header>

        <ConversationPanel
          activeThreadId={activeThreadId}
          onNewThread={onNewThread}
          onDeleteThread={onDeleteThread}
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

function ConversationPanel({
  activeThreadId,
  onDeleteThread,
  onNewThread,
  onSelectThread,
  threadsState,
}: ConversationPanelProps) {
  const {
    archiveThread,
    error,
    fetchMoreThreads,
    hasMoreThreads,
    isFetchingMoreThreads,
    isLoading,
    refetchThreads,
    threads,
  } = threadsState;

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="shrink-0 px-4 pb-5">
        <button
          className="inline-flex h-10 items-center gap-3 rounded-md px-1 text-[15px] font-semibold text-[#202020] hover:text-black"
          onClick={onNewThread}
          type="button"
        >
          <MessageSquarePlus aria-hidden="true" className="size-5" />
          New Conversation
        </button>
      </div>

      <div className="flex shrink-0 items-center justify-between px-4 pb-4">
        <h2 className="text-xs font-semibold text-[#626262]">Open conversations</h2>
        <button
          aria-label="Filter conversations"
          className="inline-flex size-8 items-center justify-center rounded-md text-[#626262] hover:bg-[#eeeeee] hover:text-[#111111]"
          title="Filter conversations"
          type="button"
        >
          <SlidersHorizontal aria-hidden="true" className="size-4" />
        </button>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto px-2 pb-2">
        {isLoading ? <EmptyRow label="Loading conversations" /> : null}
        {!isLoading && error ? (
          <div className="mx-2 rounded-md border border-[#ececec] bg-white p-3 text-sm text-[#606060]">
            <p className="mb-2 text-[#b42318]">Conversation store unavailable</p>
            <button className="inline-flex h-8 items-center gap-2 rounded-md border border-[#dddddd] px-2 text-xs" onClick={refetchThreads} type="button">
              <RefreshCw aria-hidden="true" className="size-3" />
              Retry
            </button>
          </div>
        ) : null}
        {!isLoading && !error && threads.length === 0 ? <EmptyRow label="No conversations yet" /> : null}
        <ol className="space-y-2">
          {threads.map((thread, index) => (
            <ThreadRow
              active={thread.id === activeThreadId}
              index={index}
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
        <div className="shrink-0 px-4 py-2">
          <button
            className="inline-flex h-9 w-full items-center justify-center gap-2 rounded-md border border-[#dfdfdf] bg-white text-sm text-[#606060] hover:bg-[#f1f1f1] hover:text-[#222222]"
            disabled={isFetchingMoreThreads}
            onClick={fetchMoreThreads}
            type="button"
          >
            <RefreshCw aria-hidden="true" className={`size-4 ${isFetchingMoreThreads ? "animate-spin" : ""}`} />
            Load More
          </button>
        </div>
      ) : null}
    </div>
  );
}

type ThreadRowProps = {
  active: boolean;
  index: number;
  onArchive: () => void;
  onDelete: () => void;
  onSelect: () => void;
  thread: ConversationThread;
};

const rowAccents = [
  { bg: "#fff2f2", color: "#ef4444", icon: CircleAlert },
  { bg: "#fff8e6", color: "#f59e0b", icon: Database },
  { bg: "#eef6ff", color: "#3b82f6", icon: Wrench },
  { bg: "#f3efff", color: "#8b5cf6", icon: Unplug },
];

function ThreadRow({ active, index, onArchive, onDelete, onSelect, thread }: ThreadRowProps) {
  const accent = rowAccents[index % rowAccents.length];
  const Icon = accent.icon;
  const name = thread.name || "Untitled conversation";

  return (
    <li
      className={`group grid grid-cols-[1fr_auto] items-center rounded-md transition-colors ${
        active ? "bg-[#eee7ff]" : "hover:bg-[#f0f0f0]"
      }`}
    >
      <button className="grid min-w-0 grid-cols-[2rem_1fr] gap-2 px-3 py-3 text-left" onClick={onSelect} type="button">
        <span className="grid size-6 place-items-center rounded-md" style={{ background: accent.bg, color: accent.color }}>
          <Icon aria-hidden="true" className="size-4" />
        </span>
        <span className="min-w-0">
          <span className="block truncate text-sm font-semibold text-[#202020]">{name}</span>
          <span className="mt-0.5 flex min-w-0 items-center gap-2 text-xs text-[#676767]">
            <span className="truncate">{makeThreadSubtitle(name)}</span>
            <time className="shrink-0">{formatRelativeTime(thread.lastRunAt ?? thread.updatedAt)}</time>
          </span>
        </span>
      </button>
      <div className="flex pr-2 opacity-0 transition-opacity group-hover:opacity-100 group-focus-within:opacity-100">
        <IconButton label="Archive conversation" onClick={onArchive}>
          <Archive aria-hidden="true" className="size-4" />
        </IconButton>
        <IconButton label="Delete conversation" onClick={onDelete} danger>
          <Trash2 aria-hidden="true" className="size-4" />
        </IconButton>
      </div>
    </li>
  );
}

type IconButtonProps = {
  children: ReactNode;
  danger?: boolean;
  label: string;
  onClick: () => void;
};

function IconButton({ children, danger, label, onClick }: IconButtonProps) {
  return (
    <button
      aria-label={label}
      className={`inline-flex size-8 items-center justify-center rounded-md hover:bg-white ${danger ? "text-[#b42318]" : "text-[#5f5f5f]"}`}
      onClick={onClick}
      title={label}
      type="button"
    >
      {children}
    </button>
  );
}

function EmptyRow({ label }: { label: string }) {
  return <p className="mx-2 rounded-md border border-[#ececec] bg-white px-3 py-2 text-sm text-[#666666]">{label}</p>;
}

function makeThreadSubtitle(name: string): string {
  const words = name.split(/\s+/).filter(Boolean);
  return words.slice(0, 3).join(" ") || "Conversation";
}

function formatRelativeTime(value: Date | number | string | null | undefined): string {
  if (!value) {
    return "now";
  }

  const date = new Date(value);
  if (Number.isNaN(date.valueOf())) {
    return "now";
  }

  const diffMs = Date.now() - date.valueOf();
  const minutes = Math.max(0, Math.round(diffMs / 60000));
  if (minutes < 1) {
    return "now";
  }
  if (minutes < 60) {
    return `${minutes}m`;
  }
  const hours = Math.round(minutes / 60);
  if (hours < 24) {
    return `${hours}h`;
  }
  return `${Math.round(hours / 24)}d`;
}
