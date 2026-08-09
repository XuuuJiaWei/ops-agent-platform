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
  readPersistedAppConfig,
  writePersistedAppConfig,
  type PersistedAppConfig,
  type PersistedThreadSource,
} from "./appConfigPersistence";
import { createConversationThreadId, useConversationThreads } from "./conversationThreads";
import type { BrowserEnv } from "@/lib/env";

type AppShellProps = {
  env: BrowserEnv;
};

type MainView = "chat" | "spaces";
const AgentNativeAppView = lazy(() =>
  import("./AgentNativeAppView").then((module) => ({ default: module.AgentNativeAppView })),
);
const viewSwitcherFrameClass = import.meta.env.DEV ? "relative z-[2147483647] ml-auto mr-14" : "relative z-40 ml-auto";
const chatMessageView = {
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
  const initialConfig = useMemo(() => normalizeInitialConfig(readPersistedAppConfig(env.assistantId)), [env.assistantId]);
  const [activeThreadId, setActiveThreadId] = useState<string>(initialConfig.activeThreadId);
  const [activeThreadSource, setActiveThreadSource] = useState<PersistedThreadSource>(initialConfig.activeThreadSource);
  const [hasExplicitThreadId, setHasExplicitThreadId] = useState(initialConfig.hasExplicitThreadId);
  const [desktopSidebarOpen, setDesktopSidebarOpen] = useState(initialConfig.desktopSidebarOpen);
  const [mobileSidebarOpen, setMobileSidebarOpen] = useState(false);
  const [mainView, setMainView] = useState<MainView>(initialConfig.mainView);
  const [spacesMounted, setSpacesMounted] = useState(initialConfig.mainView === "spaces");
  const threadsState = useConversationThreads({ agentId: env.assistantId });
  const { setThreadTitle, touchThread } = threadsState;

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
      chatInputPlaceholder: "Ask me anything...",
      welcomeMessageText: "Hello! What can I do for you?",
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

      const nextConfig = normalizeInitialConfig(readPersistedAppConfig(env.assistantId));
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
    setHasExplicitThreadId(false);
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
      setHasExplicitThreadId(false);
    }
  }

  function openSidebar() {
    setDesktopSidebarOpen(true);
    setMobileSidebarOpen(true);
  }

  function changeMainView(view: MainView) {
    setMainView(view);
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
          isDesktopOpen={desktopSidebarOpen && mainView === "chat"}
          isMobileOpen={mobileSidebarOpen && mainView === "chat"}
          onCloseDesktop={() => setDesktopSidebarOpen(false)}
          onCloseMobile={() => setMobileSidebarOpen(false)}
          onDeleteThread={deleteThread}
          onNewThread={startNewThread}
          onSelectThread={selectThread}
          onToggleMobile={() => setMobileSidebarOpen((open) => !open)}
          threadsState={threadsState}
        />

        <section className="flex min-w-0 flex-1 flex-col bg-white">
          <header className="flex h-14 shrink-0 items-center gap-3 border-b border-[var(--border-subtle)] px-3 md:px-4">
            {mainView === "chat" ? <button
              aria-label="Open sidebar"
              className={`hidden size-9 items-center justify-center rounded-md border border-[var(--border-subtle)] text-[var(--text-secondary)] hover:bg-[var(--surface-muted)] hover:text-[var(--text-primary)] ${
                desktopSidebarOpen ? "md:hidden" : "md:inline-flex"
              }`}
              onClick={openSidebar}
              title="Open sidebar"
              type="button"
            >
              <PanelLeftOpen aria-hidden="true" className="size-4" />
            </button> : null}
            <div className="min-w-0 pl-10 md:pl-0">
              <p className="truncate text-sm font-semibold text-[var(--text-primary)]">{mainView === "chat" ? "Support Desk" : "Spaces"}</p>
              <p className="truncate font-mono text-[11px] text-[var(--text-secondary)]">
                {mainView === "chat" ? (hasExplicitThreadId ? activeThreadId : "new conversation") : "agent-authored visual workspace"}
              </p>
            </div>
            <div className={viewSwitcherFrameClass}>
              <ViewSwitcher value={mainView} onChange={changeMainView} />
            </div>
          </header>

          <div className="relative min-h-0 flex-1">
            {/* Keep both views mounted and toggle visibility with `hidden` so
                neither loses state when switching tabs: the Chat keeps its
                in-progress conversation/input, and the Spaces view keeps its live
                agent-state subscription. Unmounting either (e.g. conditional
                render) discards that state. */}
            <div aria-hidden={mainView !== "chat"} className={mainView === "chat" ? "h-full" : "invisible absolute inset-0 h-full"} inert={mainView !== "chat"}>
              <CopilotChat className="h-full" messageView={chatMessageView} />
            </div>
            <ThreadLifecycleSync
              agentId={env.assistantId}
              onThreadActivity={handleThreadActivity}
              threadId={activeThreadId}
            />
            {spacesMounted ? (
              <div aria-hidden={mainView !== "spaces"} className={mainView === "spaces" ? "h-full" : "invisible absolute inset-0 h-full"} inert={mainView !== "spaces"}>
                <Suspense fallback={<div className="h-full animate-pulse bg-slate-50" />}>
                  <AgentNativeAppView activeThreadId={activeThreadId} env={env} />
                </Suspense>
              </div>
            ) : null}
          </div>
        </section>
      </main>
    </CopilotChatConfigurationProvider>
  );
}

function normalizeInitialConfig(config: PersistedAppConfig): PersistedAppConfig & { activeThreadId: string } {
  const activeThreadId = config.activeThreadId ?? createConversationThreadId();
  return {
    ...config,
    activeThreadId,
    activeThreadSource: config.activeThreadSource,
    hasExplicitThreadId: Boolean(config.activeThreadId && config.hasExplicitThreadId),
  };
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

function ViewSwitcher({ onChange, value }: { onChange: (view: MainView) => void; value: MainView }) {
  return (
    <div
      aria-label="Main view"
      className="inline-grid h-10 grid-cols-2 rounded-md border border-[var(--border-subtle)] bg-[var(--surface-muted)] p-1 shadow-sm"
      role="tablist"
    >
      <ViewSwitchButton active={value === "chat"} icon={<MessageSquareText aria-hidden="true" className="size-4" />} label="Chat" onClick={() => onChange("chat")} />
      <ViewSwitchButton active={value === "spaces"} icon={<Layers3 aria-hidden="true" className="size-4" />} label="Spaces" onClick={() => onChange("spaces")} />
    </div>
  );
}

function ViewSwitchButton({ active, icon, label, onClick }: { active: boolean; icon: React.ReactNode; label: string; onClick: () => void }) {
  return (
    <button
      aria-selected={active}
      className={`inline-flex h-8 min-w-20 items-center justify-center gap-2 rounded-md px-3 text-sm font-medium transition-colors ${
        active ? "bg-white text-[var(--text-primary)] shadow-sm" : "text-[var(--text-secondary)] hover:text-[var(--text-primary)]"
      }`}
      onClick={onClick}
      role="tab"
      title={label}
      type="button"
    >
      {icon}
      {label}
    </button>
  );
}
