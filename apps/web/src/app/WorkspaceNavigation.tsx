import { Layers3, MessageSquareText, Sparkles } from "lucide-react";
import type { ReactNode } from "react";

export type MainView = "chat" | "spaces";

type WorkspaceNavigationProps = {
  endAction?: ReactNode;
  onChange: (view: MainView) => void;
  value: MainView;
};

export function WorkspaceNavigation({ endAction, onChange, value }: WorkspaceNavigationProps) {
  return (
    <div className="shrink-0 px-3 pt-3">
      <div className="flex h-11 items-center gap-2 px-1">
        <span className="grid size-8 shrink-0 place-items-center rounded-[10px] bg-slate-950 text-white shadow-sm">
          <Sparkles aria-hidden="true" className="size-4" />
        </span>
        <span className="min-w-0 flex-1">
          <span className="block truncate text-sm font-semibold tracking-[-0.01em] text-slate-950">Ops Pilot</span>
          <span className="block truncate text-[11px] text-slate-500">Agent workspace</span>
        </span>
        {endAction}
      </div>

      <nav aria-label="Workspace" className="mt-3 grid gap-1">
        <NavigationItem
          active={value === "chat"}
          icon={<MessageSquareText aria-hidden="true" className="size-4" />}
          label="Chat"
          onClick={() => onChange("chat")}
        />
        <NavigationItem
          active={value === "spaces"}
          icon={<Layers3 aria-hidden="true" className="size-4" />}
          label="Spaces"
          onClick={() => onChange("spaces")}
        />
      </nav>
    </div>
  );
}

function NavigationItem({
  active,
  icon,
  label,
  onClick,
}: {
  active: boolean;
  icon: ReactNode;
  label: string;
  onClick: () => void;
}) {
  return (
    <button
      aria-current={active ? "page" : undefined}
      className={`flex h-9 w-full items-center gap-3 rounded-lg px-3 text-sm font-medium transition-colors ${
        active
          ? "bg-white text-slate-950 shadow-sm ring-1 ring-slate-200/80"
          : "text-slate-600 hover:bg-white/70 hover:text-slate-950"
      }`}
      onClick={onClick}
      type="button"
    >
      {icon}
      <span>{label}</span>
    </button>
  );
}
