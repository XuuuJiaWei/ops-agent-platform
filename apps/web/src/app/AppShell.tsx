import {
  CopilotChat,
  CopilotChatConfigurationProvider,
} from "@copilotkit/react-core/v2";
import { LayoutDashboard, MessageSquareText, PanelLeftOpen } from "lucide-react";
import { useMemo, useState } from "react";
import { AgentNativeAppView } from "./AgentNativeAppView";
import { ThreadSidebar } from "./ThreadSidebar";
import { useConversationThreads } from "./conversationThreads";
import type { BrowserEnv } from "@/lib/env";

type AppShellProps = {
  env: BrowserEnv;
};

type SidebarView = "conversations" | "settings";
type MainView = "chat" | "app";
const viewSwitcherFrameClass = import.meta.env.DEV ? "relative z-[2147483647] ml-auto mr-14" : "relative z-40 ml-auto";

export function AppShell({ env }: AppShellProps) {
  const [activeThreadId, setActiveThreadId] = useState<string | undefined>();
  const [desktopSidebarOpen, setDesktopSidebarOpen] = useState(true);
  const [mobileSidebarOpen, setMobileSidebarOpen] = useState(false);
  const [sidebarView, setSidebarView] = useState<SidebarView>("conversations");
  const [mainView, setMainView] = useState<MainView>("chat");
  const threadsState = useConversationThreads({ agentId: env.assistantId });

  const chatKey = activeThreadId ?? "new";
  const chatLabels = useMemo(
    () => ({
      chatInputPlaceholder: "Ask me anything...",
      welcomeMessageText: "Hello! What can I do for you?",
    }),
    [],
  );

  function startNewThread() {
    const thread = threadsState.createThread();
    setActiveThreadId(thread.id);
    setSidebarView("conversations");
    setMobileSidebarOpen(false);
  }

  function selectThread(threadId: string) {
    threadsState.touchThread(threadId);
    setActiveThreadId(threadId);
    setSidebarView("conversations");
    setMobileSidebarOpen(false);
  }

  async function deleteThread(threadId: string) {
    await threadsState.deleteThread(threadId);
    if (activeThreadId === threadId) {
      setActiveThreadId(undefined);
    }
  }

  function openSidebar() {
    setDesktopSidebarOpen(true);
    setMobileSidebarOpen(true);
  }

  return (
    <CopilotChatConfigurationProvider agentId={env.assistantId} labels={chatLabels} threadId={activeThreadId}>
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
                {activeThreadId ?? "new conversation"}
              </p>
            </div>
            <div className={viewSwitcherFrameClass}>
              <ViewSwitcher value={mainView} onChange={setMainView} />
            </div>
          </header>

          <div className="min-h-0 flex-1">
            {mainView === "chat" ? <CopilotChat className="h-full" key={chatKey} /> : null}
            {/* Keep the App view mounted so its agent-state subscription stays live
                even while the Chat tab is shown; hide it instead of unmounting. */}
            <div className={mainView === "app" ? "h-full" : "hidden"}>
              <AgentNativeAppView activeThreadId={activeThreadId} env={env} />
            </div>
          </div>
        </section>
      </main>
    </CopilotChatConfigurationProvider>
  );
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
