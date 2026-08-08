import { LayoutDashboard } from "lucide-react";
import type { BrowserEnv } from "@/lib/env";

type AgentNativeAppViewProps = {
  activeThreadId: string | undefined;
  env: BrowserEnv;
};

// Placeholder for the future agent-native app surface. The earlier
// storyline/correlation panel was removed; this keeps the "App" view mounted
// (so switching tabs never unmounts the chat) while the next iteration is built.
export function AgentNativeAppView({ activeThreadId }: AgentNativeAppViewProps) {
  return (
    <div className="h-full overflow-y-auto bg-[#f7f8fa]">
      <div className="mx-auto flex w-full max-w-6xl flex-col gap-5 px-4 py-5 sm:px-6 lg:px-8">
        <section className="rounded-md border border-dashed border-[var(--border-subtle)] bg-white p-10 text-center shadow-sm">
          <LayoutDashboard aria-hidden="true" className="mx-auto size-8 text-[var(--text-secondary)]" />
          <h1 className="mt-4 text-lg font-semibold text-[var(--text-primary)]">App view</h1>
          <p className="mx-auto mt-2 max-w-md text-sm leading-6 text-[var(--text-secondary)]">
            This surface is a placeholder for upcoming agent-native panels.
          </p>
          <p className="mx-auto mt-4 font-mono text-[11px] text-[var(--text-secondary)]">
            {activeThreadId ? `thread ${activeThreadId}` : "new conversation"}
          </p>
        </section>
      </div>
    </div>
  );
}
