import {
  CopilotChat,
  CopilotChatAssistantMessage,
  CopilotChatConfigurationProvider,
  type CopilotChatAssistantMessageProps,
} from "@copilotkit/react-core/v2";
import { Layers3, MessageSquareText, PanelLeftOpen } from "lucide-react";
import { lazy, Suspense, useCallback, useEffect, useMemo, useState } from "react";
import { ThreadLifecycleSync } from "./ThreadLifecycleSync";
import { ThreadSidebar } from "./ThreadSidebar";
import {
  appConfigStorageKey,
  normalizeInitialAppConfig,
  readPersistedAppConfig,
  writePersistedAppConfig,
  type PersistedThreadSource,
} from "./appConfigPersistence";
import { useConversationThreads } from "./conversationThreads";
import type { MainView } from "./WorkspaceNavigation";
import type { BrowserEnv } from "@/lib/env";

type AppShellProps = {
  env: BrowserEnv;
};

const AgentNativeAppView = lazy(() =>
  import("./AgentNativeAppView").then((module) => ({ default: module.AgentNativeAppView })),
);
const chatMessageView = {
  className: "!bg-transparent",
  assistantMessage: Object.assign(AssistantMessageWithTerminalToolbar, {
    CopyButton: CopilotChatAssistantMessage.CopyButton,
    MarkdownRenderer: CopilotChatAssistantMessage.MarkdownRenderer,
    ReadAloudButton: CopilotChatAssistantMessage.ReadAloudButton,
    RegenerateButton: CopilotChatAssistantMessage.RegenerateButton,
    ThumbsDownButton: CopilotChatAssistantMessage.ThumbsDownButton,
    ThumbsUpButton: CopilotChatAssistantMessage.ThumbsUpButton,
    Toolbar: CopilotChatAssistantMessage.Toolbar,
    ToolbarButton: CopilotChatAssistantMessage.ToolbarButton,
  }),
};

export function AppShell({ env }: AppShellProps) {
  const initialConfig = useMemo(() => normalizeInitialAppConfig(readPersistedAppConfig(env.assistantId)), [env.assistantId]);
  const [activeThreadId, setActiveThreadId] = useState<string>(initialConfig.activeThreadId);
  const [activeThreadSource, setActiveThreadSource] = useState<PersistedThreadSource>(initialConfig.activeThreadSource);
  const [hasExplicitThreadId, setHasExplicitThreadId] = useState(initialConfig.hasExplicitThreadId);
  const [desktopSidebarOpen, setDesktopSidebarOpen] = useState(initialConfig.desktopSidebarOpen);
  const [mobileSidebarOpen, setMobileSidebarOpen] = useState(false);
  const [mainView, setMainView] = useState<MainView>(initialConfig.mainView);
  const [spacesMounted, setSpacesMounted] = useState(initialConfig.mainView === "spaces");
  const threadsState = useConversationThreads({ agentId: env.assistantId });
  const { setThreadTitle, touchThread } = threadsState;
  const activeThread = threadsState.threads.find((thread) => thread.id === activeThreadId);

  const handleThreadActivity = useCallback(
    (threadId: string, titleCandidate?: string) => {
      touchThread(threadId);
      if (titleCandidate) {
        setThreadTitle(threadId, titleCandidate);
      }
      if (threadId === activeThreadId) {
        setHasExplicitThreadId(true);
      }
    },
    [activeThreadId, setThreadTitle, touchThread],
  );

  const chatLabels = useMemo(
    () => ({
      chatInputPlaceholder: "Ask about your systems…",
      welcomeMessageText: "What would you like to investigate?",
    }),
    [],
  );

  useEffect(() => {
    writePersistedAppConfig(env.assistantId, {
      activeThreadId,
      activeThreadSource,
      desktopSidebarOpen,
      hasExplicitThreadId,
      mainView,
    });
  }, [activeThreadId, activeThreadSource, desktopSidebarOpen, env.assistantId, hasExplicitThreadId, mainView]);

  useEffect(() => {
    touchThread(activeThreadId);
  }, [activeThreadId, touchThread]);

  useEffect(() => {
    function handleStorage(event: StorageEvent) {
      if (event.key !== appConfigStorageKey(env.assistantId)) {
        return;
      }

      const nextConfig = normalizeInitialAppConfig(readPersistedAppConfig(env.assistantId));
      setActiveThreadId(nextConfig.activeThreadId);
      setActiveThreadSource(nextConfig.activeThreadSource);
      setHasExplicitThreadId(nextConfig.hasExplicitThreadId);
      setDesktopSidebarOpen(nextConfig.desktopSidebarOpen);
      setMainView(nextConfig.mainView);
      if (nextConfig.mainView === "spaces") setSpacesMounted(true);
    }

    window.addEventListener("storage", handleStorage);
    return () => window.removeEventListener("storage", handleStorage);
  }, [env.assistantId]);

  function startNewThread() {
    const thread = threadsState.startNewThread();
    setActiveThreadId(thread.id);
    setActiveThreadSource(threadsState.source);
    setHasExplicitThreadId(true);
    setMobileSidebarOpen(false);
  }

  function selectThread(threadId: string) {
    threadsState.touchThread(threadId);
    setActiveThreadId(threadId);
    setActiveThreadSource(threadsState.source);
    setHasExplicitThreadId(true);
    setMobileSidebarOpen(false);
  }

  async function deleteThread(threadId: string) {
    await threadsState.deleteThread(threadId);
    if (activeThreadId === threadId) {
      const thread = threadsState.startNewThread();
      setActiveThreadId(thread.id);
      setActiveThreadSource(threadsState.source);
      setHasExplicitThreadId(true);
    }
  }

  function openSidebar() {
    setDesktopSidebarOpen(true);
    setMobileSidebarOpen(true);
  }

  function changeMainView(view: MainView) {
    setMainView(view);
    setMobileSidebarOpen(false);
    if (view === "spaces") setSpacesMounted(true);
  }

  return (
    <CopilotChatConfigurationProvider
      agentId={env.assistantId}
      hasExplicitThreadId={hasExplicitThreadId}
      labels={chatLabels}
      threadId={activeThreadId}
    >
      <main className="flex h-dvh min-h-screen bg-[var(--surface-page)]">
        <ThreadSidebar
          activeThreadId={activeThreadId}
          activeView={mainView}
          isDesktopOpen={desktopSidebarOpen && mainView === "chat"}
          isMobileOpen={mobileSidebarOpen && mainView === "chat"}
          onCloseDesktop={() => setDesktopSidebarOpen(false)}
          onCloseMobile={() => setMobileSidebarOpen(false)}
          onDeleteThread={deleteThread}
          onNewThread={startNewThread}
          onSelectThread={selectThread}
          onToggleMobile={() => setMobileSidebarOpen((open) => !open)}
          onViewChange={changeMainView}
          threadsState={threadsState}
        />

        <section className="flex min-w-0 flex-1 flex-col bg-[var(--surface-panel)]">
          <header
            className={`h-[60px] shrink-0 items-center gap-3 border-b border-slate-200 px-3 md:px-5 ${
              mainView === "spaces" ? "flex lg:hidden" : "flex"
            }`}
          >
            {mainView === "chat" ? (
              <button
                aria-label="Open navigation"
                className={`hidden size-9 items-center justify-center rounded-lg border border-slate-200 text-slate-500 hover:bg-slate-50 hover:text-slate-950 ${
                  desktopSidebarOpen ? "md:hidden" : "md:inline-flex"
                }`}
                onClick={openSidebar}
                title="Open navigation"
                type="button"
              >
                <PanelLeftOpen aria-hidden="true" className="size-4" />
              </button>
            ) : null}
            <div className="min-w-0 pl-10 md:pl-0">
              <p className="truncate text-sm font-semibold tracking-[-0.01em] text-slate-950">
                {mainView === "chat" ? activeThread?.name || "New chat" : "Spaces"}
              </p>
              <p className="truncate text-[11px] text-slate-500">{mainView === "chat" ? "Conversation" : "Persistent visual workspaces"}</p>
            </div>
            <div className="ml-2 lg:hidden">
              <ViewSwitcher compact value={mainView} onChange={changeMainView} />
            </div>
          </header>

          <div className="relative min-h-0 flex-1">
            {/* Keep both views mounted and toggle visibility so
                neither loses state when switching tabs: the Chat keeps its
                in-progress conversation/input, and the Spaces view keeps its live
                agent-state subscription. Unmounting either (e.g. conditional
                render) discards that state. */}
            <div aria-hidden={mainView !== "chat"} className={mainView === "chat" ? "h-full" : "invisible absolute inset-0 h-full"} inert={mainView !== "chat"}>
              <CopilotChat
                className="ops-chat h-full bg-[var(--surface-chat)]"
                input="!bg-transparent"
                messageView={chatMessageView}
                scrollView="bg-[var(--surface-chat)]"
              />
            </div>
            <ThreadLifecycleSync
              agentId={env.assistantId}
              onThreadActivity={handleThreadActivity}
              threadId={activeThreadId}
            />
            {spacesMounted ? (
              <div aria-hidden={mainView !== "spaces"} className={mainView === "spaces" ? "h-full" : "invisible absolute inset-0 h-full"} inert={mainView !== "spaces"}>
                <Suspense fallback={<div className="h-full animate-pulse bg-slate-50" />}>
                  <AgentNativeAppView activeThreadId={activeThreadId} env={env} onViewChange={changeMainView} />
                </Suspense>
              </div>
            ) : null}
          </div>
        </section>
      </main>
    </CopilotChatConfigurationProvider>
  );
}

function AssistantMessageWithTerminalToolbar(props: CopilotChatAssistantMessageProps) {
  const toolbarVisible = !props.isRunning && isTerminalVisibleAssistantMessage(props);
  return <CopilotChatAssistantMessage {...props} toolbarVisible={toolbarVisible} />;
}

function isTerminalVisibleAssistantMessage({ message, messages }: CopilotChatAssistantMessageProps): boolean {
  if (!messages || messages.length === 0) {
    return true;
  }

  for (let index = messages.length - 1; index >= 0; index -= 1) {
    const candidate = messages[index];
    if (candidate.role === "tool") {
      continue;
    }
    return candidate.role === "assistant" && candidate.id === message.id;
  }

  return false;
}

function ViewSwitcher({ compact = false, onChange, value }: { compact?: boolean; onChange: (view: MainView) => void; value: MainView }) {
  return (
    <div
      aria-label="Main view"
      className="inline-grid h-9 grid-cols-2 rounded-lg border border-slate-200 bg-slate-100 p-0.5"
      role="tablist"
    >
      <ViewSwitchButton active={value === "chat"} compact={compact} icon={<MessageSquareText aria-hidden="true" className="size-4" />} label="Chat" onClick={() => onChange("chat")} />
      <ViewSwitchButton active={value === "spaces"} compact={compact} icon={<Layers3 aria-hidden="true" className="size-4" />} label="Spaces" onClick={() => onChange("spaces")} />
    </div>
  );
}

function ViewSwitchButton({ active, compact, icon, label, onClick }: { active: boolean; compact: boolean; icon: React.ReactNode; label: string; onClick: () => void }) {
  return (
    <button
      aria-selected={active}
      aria-label={label}
      className={`inline-flex h-8 items-center justify-center gap-2 rounded-md px-2 text-xs font-medium transition-colors ${compact ? "min-w-8 sm:min-w-16" : "min-w-20"} ${
        active ? "bg-white text-slate-950 shadow-sm" : "text-slate-500 hover:text-slate-950"
      }`}
      onClick={onClick}
      role="tab"
      title={label}
      type="button"
    >
      {icon}
      <span className={compact ? "hidden sm:inline" : undefined}>{label}</span>
    </button>
  );
}
