import {
  CopilotChat,
  CopilotChatAssistantMessage,
  CopilotChatConfigurationProvider,
  type CopilotChatAssistantMessageProps,
} from "@copilotkit/react-core/v2";
import { LayoutDashboard, MessageSquareText, PanelLeftOpen } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { AgentNativeAppView } from "./AgentNativeAppView";
import { LocalThreadMessagePersistence } from "./LocalThreadMessagePersistence";
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

type SidebarView = "conversations" | "settings";
type MainView = "chat" | "app";
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
  const [sidebarView, setSidebarView] = useState<SidebarView>(initialConfig.sidebarView);
  const [mainView, setMainView] = useState<MainView>(initialConfig.mainView);
  const threadsState = useConversationThreads({ agentId: env.assistantId });
  const { setThreadTitle, touchThread } = threadsState;

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
      sidebarView,
    });
  }, [activeThreadId, activeThreadSource, desktopSidebarOpen, env.assistantId, hasExplicitThreadId, mainView, sidebarView]);

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
      setSidebarView(nextConfig.sidebarView);
      setMainView(nextConfig.mainView);
    }

    window.addEventListener("storage", handleStorage);
    return () => window.removeEventListener("storage", handleStorage);
  }, [env.assistantId]);

  function startNewThread() {
    const thread = threadsState.startNewThread();
    setActiveThreadId(thread.id);
    setActiveThreadSource(threadsState.source);
    setHasExplicitThreadId(false);
    setSidebarView("conversations");
    setMobileSidebarOpen(false);
  }

  function selectThread(threadId: string) {
    threadsState.touchThread(threadId);
    setActiveThreadId(threadId);
    setActiveThreadSource(threadsState.source);
    setHasExplicitThreadId(true);
    setSidebarView("conversations");
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

  return (
    <CopilotChatConfigurationProvider
      agentId={env.assistantId}
      hasExplicitThreadId={activeThreadSource === "copilot" && hasExplicitThreadId}
      labels={chatLabels}
      threadId={activeThreadId}
    >
      <main className="flex h-dvh min-h-screen bg-[var(--surface-page)]">
        <ThreadSidebar
          activeThreadId={activeThreadId}
          env={env}
          isDesktopOpen={desktopSidebarOpen}
          isMobileOpen={mobileSidebarOpen}
          onCloseDesktop={() => setDesktopSidebarOpen(false)}
          onCloseMobile={() => setMobileSidebarOpen(false)}
          onDeleteThread={deleteThread}
          onNewThread={startNewThread}
          onSelectThread={selectThread}
          onToggleMobile={() => setMobileSidebarOpen((open) => !open)}
          onViewChange={setSidebarView}
          threadsState={threadsState}
          view={sidebarView}
        />

        <section className="flex min-w-0 flex-1 flex-col bg-white">
          <header className="flex h-14 shrink-0 items-center gap-3 border-b border-[var(--border-subtle)] px-3 md:px-4">
            <button
              aria-label="Open sidebar"
              className={`hidden size-9 items-center justify-center rounded-md border border-[var(--border-subtle)] text-[var(--text-secondary)] hover:bg-[var(--surface-muted)] hover:text-[var(--text-primary)] ${
                desktopSidebarOpen ? "md:hidden" : "md:inline-flex"
              }`}
              onClick={openSidebar}
              title="Open sidebar"
              type="button"
            >
              <PanelLeftOpen aria-hidden="true" className="size-4" />
            </button>
            <div className="min-w-0 pl-10 md:pl-0">
              <p className="truncate text-sm font-semibold text-[var(--text-primary)]">Support Desk</p>
              <p className="truncate font-mono text-[11px] text-[var(--text-secondary)]">
                {hasExplicitThreadId ? activeThreadId : "new conversation"}
              </p>
            </div>
            <div className={viewSwitcherFrameClass}>
              <ViewSwitcher value={mainView} onChange={setMainView} />
            </div>
          </header>

          <div className="min-h-0 flex-1">
            {/* Keep both views mounted and toggle visibility with `hidden` so
                neither loses state when switching tabs: the Chat keeps its
                in-progress conversation/input, and the App view keeps its live
                agent-state subscription. Unmounting either (e.g. conditional
                render) discards that state. */}
            <div className={mainView === "chat" ? "h-full" : "hidden"}>
              <CopilotChat className="h-full" messageView={chatMessageView} />
            </div>
            <LocalThreadMessagePersistence
              agentId={env.assistantId}
              enabled={activeThreadSource === "local"}
              onTitleCandidate={setThreadTitle}
              threadId={activeThreadId}
            />
            <div className={mainView === "app" ? "h-full" : "hidden"}>
              <AgentNativeAppView activeThreadId={activeThreadId} env={env} />
            </div>
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
      <ViewSwitchButton active={value === "app"} icon={<LayoutDashboard aria-hidden="true" className="size-4" />} label="App" onClick={() => onChange("app")} />
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
