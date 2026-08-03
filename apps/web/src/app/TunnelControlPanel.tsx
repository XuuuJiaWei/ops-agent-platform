import { PlugZap, RefreshCw, Save, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";
import type { BrowserEnv } from "@/lib/env";

type TunnelStatus = {
  connected: boolean;
  pending: number;
  sessions: string[];
};

type TunnelStatusResponse = {
  tunnels?: Record<string, TunnelStatus>;
};

type LocalBridgeStatus = {
  running: boolean;
  connected: boolean;
  last_error?: string | null;
};

type LocalBridgeStatusResponse = {
  bridges?: Record<string, LocalBridgeStatus>;
};

type MCPServerLoadStatus = {
  name: string;
  ok: boolean;
  tool_count: number;
  error?: string | null;
};

type AgentConfigResponse = {
  generation: number;
  dynamic_mcp?: {
    tool_count: number;
    servers: MCPServerLoadStatus[];
  };
};

type TunnelControlPanelProps = {
  env: BrowserEnv;
};

type MCPSource = "command" | "config";

const DEFAULT_TUNNEL_ID = "local-dev";
const DEFAULT_MCP_COMMAND = "python /path/to/mcp_server.py";
const DEFAULT_MCP_CONFIG_PATH = "/path/to/.mcp.json";
const DEFAULT_MCP_SERVER_NAME = "kibana";
const TUNNEL_ID_STORAGE_KEY = "ops-agent-platform:mcp-tunnel:id";
const MCP_COMMAND_STORAGE_KEY = "ops-agent-platform:mcp-tunnel:command";
const MCP_SOURCE_STORAGE_KEY = "ops-agent-platform:mcp-tunnel:source";
const MCP_CONFIG_PATH_STORAGE_KEY = "ops-agent-platform:mcp-tunnel:config-path";
const MCP_SERVER_NAME_STORAGE_KEY = "ops-agent-platform:mcp-tunnel:server-name";

export function TunnelControlPanel({ env }: TunnelControlPanelProps) {
  const [tunnelId, setTunnelId] = useState(() => readLocalStorage(TUNNEL_ID_STORAGE_KEY, DEFAULT_TUNNEL_ID));
  const [mcpSource, setMcpSource] = useState<MCPSource>(() => readMcpSource());
  const [mcpCommand, setMcpCommand] = useState(() => readLocalStorage(MCP_COMMAND_STORAGE_KEY, DEFAULT_MCP_COMMAND));
  const [mcpConfigPath, setMcpConfigPath] = useState(() => readLocalStorage(MCP_CONFIG_PATH_STORAGE_KEY, DEFAULT_MCP_CONFIG_PATH));
  const [mcpServerName, setMcpServerName] = useState(() => readLocalStorage(MCP_SERVER_NAME_STORAGE_KEY, DEFAULT_MCP_SERVER_NAME));
  const [token, setToken] = useState("");
  const [statuses, setStatuses] = useState<Record<string, TunnelStatus>>({});
  const [bridges, setBridges] = useState<Record<string, LocalBridgeStatus>>({});
  const [agentConfig, setAgentConfig] = useState<AgentConfigResponse | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [isApplying, setIsApplying] = useState(false);
  const [isRemoving, setIsRemoving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [applyError, setApplyError] = useState<string | null>(null);

  const selectedStatus = statuses[tunnelId];
  const selectedBridge = bridges[tunnelId];
  const selectedAgentServer = agentConfig?.dynamic_mcp?.servers.find((server) => server.name === tunnelId);

  async function refreshStatus() {
    setIsLoading(true);
    setError(null);
    try {
      const [response, agentResponse, bridgeResponse] = await Promise.all([
        fetch("/dev/mcp-tunnels", { cache: "no-store" }),
        fetch("/dev/mcp-tunnels/agent-config", { cache: "no-store" }),
        fetch("/dev/mcp-tunnels/local-bridges", { cache: "no-store" }),
      ]);
      if (!response.ok) {
        throw new Error(`Tunnel status failed: ${response.status} ${response.statusText}`);
      }
      if (!agentResponse.ok) {
        throw new Error(`Agent config status failed: ${agentResponse.status} ${agentResponse.statusText}`);
      }
      if (!bridgeResponse.ok) {
        throw new Error(`Local bridge status failed: ${bridgeResponse.status} ${bridgeResponse.statusText}`);
      }
      const payload = (await response.json()) as TunnelStatusResponse;
      const agentPayload = (await agentResponse.json()) as AgentConfigResponse;
      const bridgePayload = (await bridgeResponse.json()) as LocalBridgeStatusResponse;
      setStatuses(payload.tunnels ?? {});
      setBridges(bridgePayload.bridges ?? {});
      setAgentConfig(agentPayload);
    } catch (statusError) {
      setError(statusError instanceof Error ? statusError.message : String(statusError));
      setStatuses({});
      setBridges({});
      setAgentConfig(null);
    } finally {
      setIsLoading(false);
    }
  }

  async function applyAgentConfig() {
    setIsApplying(true);
    setApplyError(null);
    try {
      const response = await fetch(`/dev/mcp-tunnels/${encodeURIComponent(tunnelId)}/agent-config`, {
        body: JSON.stringify(buildApplyPayload({ env, mcpCommand, mcpConfigPath, mcpServerName, mcpSource, token })),
        headers: { "Content-Type": "application/json" },
        method: "PUT",
      });
      if (!response.ok) {
        throw new Error(await responseText(response));
      }
      setAgentConfig((await response.json()) as AgentConfigResponse);
      await refreshStatus();
    } catch (configError) {
      setApplyError(configError instanceof Error ? configError.message : String(configError));
    } finally {
      setIsApplying(false);
    }
  }

  async function removeAgentConfig() {
    setIsRemoving(true);
    setApplyError(null);
    try {
      const response = await fetch(`/dev/mcp-tunnels/${encodeURIComponent(tunnelId)}/agent-config`, {
        method: "DELETE",
      });
      if (!response.ok) {
        throw new Error(await responseText(response));
      }
      setAgentConfig((await response.json()) as AgentConfigResponse);
      await refreshStatus();
    } catch (configError) {
      setApplyError(configError instanceof Error ? configError.message : String(configError));
    } finally {
      setIsRemoving(false);
    }
  }

  useEffect(() => {
    const initial = window.setTimeout(() => void refreshStatus(), 0);
    const timer = window.setInterval(() => void refreshStatus(), 5000);
    return () => {
      window.clearTimeout(initial);
      window.clearInterval(timer);
    };
  }, []);

  useEffect(() => {
    writeLocalStorage(TUNNEL_ID_STORAGE_KEY, tunnelId);
  }, [tunnelId]);

  useEffect(() => {
    writeLocalStorage(MCP_SOURCE_STORAGE_KEY, mcpSource);
  }, [mcpSource]);

  useEffect(() => {
    writeLocalStorage(MCP_COMMAND_STORAGE_KEY, mcpCommand);
  }, [mcpCommand]);

  useEffect(() => {
    writeLocalStorage(MCP_CONFIG_PATH_STORAGE_KEY, mcpConfigPath);
  }, [mcpConfigPath]);

  useEffect(() => {
    writeLocalStorage(MCP_SERVER_NAME_STORAGE_KEY, mcpServerName);
  }, [mcpServerName]);

  return (
    <section className="mb-5">
      <SectionTitle />
      <div className="rounded-md border border-[#e3e3e3] bg-white p-3">
        <div className="mb-3 grid grid-cols-[1fr_auto] items-center gap-3">
          <div className="min-w-0">
            <p className="text-xs text-[#666666]">Status</p>
            <p className={`mt-1 font-mono text-[11px] ${selectedStatus?.connected ? "text-[var(--success)]" : "text-[var(--warning)]"}`}>
              {selectedStatus?.connected ? "connected" : "not connected"}
              {selectedStatus ? ` · ${selectedStatus.sessions.length} sessions · ${selectedStatus.pending} pending` : ""}
            </p>
            {selectedBridge ? (
              <p className={`mt-1 font-mono text-[11px] ${selectedBridge.connected ? "text-[var(--success)]" : "text-[#666666]"}`}>
                bridge {selectedBridge.running ? "running" : "stopped"}
                {selectedBridge.connected ? " · ready" : ""}
              </p>
            ) : null}
            <p className={`mt-1 font-mono text-[11px] ${selectedAgentServer?.ok ? "text-[var(--success)]" : "text-[#666666]"}`}>
              {selectedAgentServer?.ok
                ? `agent applied · ${selectedAgentServer.tool_count} tools · gen ${agentConfig?.generation ?? 0}`
                : "agent not applied"}
            </p>
          </div>
          <div className="flex items-center gap-1.5">
            <button
              aria-label="Apply MCP profile"
              className="inline-flex size-8 items-center justify-center rounded-md border border-[#dddddd] text-[#5f5f5f] hover:bg-[#f4f4f4] hover:text-[#111111] disabled:opacity-60"
              disabled={isApplying || !tunnelId.trim()}
              onClick={applyAgentConfig}
              title="Apply MCP profile"
              type="button"
            >
              <Save aria-hidden="true" className={`size-4 ${isApplying ? "animate-pulse" : ""}`} />
            </button>
            <button
              aria-label="Remove tunnel from agent"
              className="inline-flex size-8 items-center justify-center rounded-md border border-[#dddddd] text-[#5f5f5f] hover:bg-[#f4f4f4] hover:text-[#111111] disabled:opacity-60"
              disabled={isRemoving || !selectedAgentServer}
              onClick={removeAgentConfig}
              title="Remove tunnel from agent"
              type="button"
            >
              <Trash2 aria-hidden="true" className={`size-4 ${isRemoving ? "animate-pulse" : ""}`} />
            </button>
            <button
              aria-label="Refresh tunnel status"
              className="inline-flex size-8 items-center justify-center rounded-md border border-[#dddddd] text-[#5f5f5f] hover:bg-[#f4f4f4] hover:text-[#111111] disabled:opacity-60"
              disabled={isLoading}
              onClick={refreshStatus}
              title="Refresh tunnel status"
              type="button"
            >
              <RefreshCw aria-hidden="true" className={`size-4 ${isLoading ? "animate-spin" : ""}`} />
            </button>
          </div>
        </div>

        {error ? <p className="mb-3 rounded-md bg-[#fff7ed] px-2 py-1.5 text-xs text-[var(--warning)]">{error}</p> : null}
        {applyError ? <p className="mb-3 rounded-md bg-[#fff7ed] px-2 py-1.5 text-xs text-[var(--warning)]">{applyError}</p> : null}
        {selectedAgentServer?.error ? (
          <p className="mb-3 rounded-md bg-[#fff7ed] px-2 py-1.5 text-xs text-[var(--warning)]">{selectedAgentServer.error}</p>
        ) : null}
        {selectedBridge?.last_error ? (
          <p className="mb-3 rounded-md bg-[#fff7ed] px-2 py-1.5 text-xs text-[var(--warning)]">{selectedBridge.last_error}</p>
        ) : null}

        <TunnelInput label="Tunnel ID" value={tunnelId} onChange={setTunnelId} />
        <TunnelInput label="Backend URL" value={env.backendUrl} readOnly />
        <TunnelInput label="Token" value={token} onChange={setToken} placeholder="Optional bearer token" type="password" />
        <SourceControl value={mcpSource} onChange={setMcpSource} />
        {mcpSource === "command" ? (
          <TunnelTextArea label="Stdio command" value={mcpCommand} onChange={setMcpCommand} />
        ) : (
          <>
            <TunnelInput label="MCP config path" value={mcpConfigPath} onChange={setMcpConfigPath} />
            <TunnelInput label="MCP server" value={mcpServerName} onChange={setMcpServerName} />
          </>
        )}
      </div>
    </section>
  );
}

function SourceControl({ onChange, value }: { onChange: (value: MCPSource) => void; value: MCPSource }) {
  return (
    <div className="mb-3">
      <p className="mb-1 text-xs text-[#666666]">Source</p>
      <div className="grid grid-cols-2 rounded-md border border-[#dcdcdc] bg-[#fbfbfb] p-0.5">
        <button
          className={`h-8 rounded-[4px] text-xs ${value === "command" ? "bg-white text-[#111111] shadow-sm" : "text-[#666666]"}`}
          onClick={() => onChange("command")}
          type="button"
        >
          Command
        </button>
        <button
          className={`h-8 rounded-[4px] text-xs ${value === "config" ? "bg-white text-[#111111] shadow-sm" : "text-[#666666]"}`}
          onClick={() => onChange("config")}
          type="button"
        >
          Config file
        </button>
      </div>
    </div>
  );
}

function SectionTitle() {
  return (
    <h3 className="mb-2 flex items-center gap-2 text-xs font-semibold uppercase text-[#666666]">
      <PlugZap aria-hidden="true" className="size-4" />
      MCP Tunnel
    </h3>
  );
}

function TunnelInput({
  label,
  onChange,
  placeholder,
  readOnly,
  type = "text",
  value,
}: {
  label: string;
  onChange?: (value: string) => void;
  placeholder?: string;
  readOnly?: boolean;
  type?: "password" | "text";
  value: string;
}) {
  return (
    <label className="mb-3 block">
      <span className="text-xs text-[#666666]">{label}</span>
      <input
        className="mt-1 h-9 w-full rounded-md border border-[#dcdcdc] bg-[#fbfbfb] px-2 font-mono text-[11px] text-[#202020] outline-none focus:border-[var(--accent)] read-only:text-[#666666]"
        onChange={(event) => onChange?.(event.target.value)}
        placeholder={placeholder}
        readOnly={readOnly}
        type={type}
        value={value}
      />
    </label>
  );
}

function TunnelTextArea({ label, onChange, value }: { label: string; onChange: (value: string) => void; value: string }) {
  return (
    <label className="mb-3 block">
      <span className="text-xs text-[#666666]">{label}</span>
      <textarea
        className="mt-1 min-h-20 w-full resize-y rounded-md border border-[#dcdcdc] bg-[#fbfbfb] px-2 py-2 font-mono text-[11px] leading-5 text-[#202020] outline-none focus:border-[var(--accent)]"
        onChange={(event) => onChange(event.target.value)}
        value={value}
      />
    </label>
  );
}

function buildApplyPayload({
  env,
  mcpCommand,
  mcpConfigPath,
  mcpServerName,
  mcpSource,
  token,
}: {
  env: BrowserEnv;
  mcpCommand: string;
  mcpConfigPath: string;
  mcpServerName: string;
  mcpSource: MCPSource;
  token: string;
}) {
  return {
    connect_timeout: 15,
    mcp_command: mcpSource === "command" ? mcpCommand : undefined,
    mcp_config: mcpSource === "config" ? mcpConfigPath : undefined,
    mcp_server: mcpSource === "config" ? mcpServerName.trim() || undefined : undefined,
    server_url: env.backendUrl,
    token: token.trim() || undefined,
  };
}

async function responseText(response: Response): Promise<string> {
  try {
    const payload = (await response.json()) as { detail?: unknown };
    if (payload.detail) {
      return typeof payload.detail === "string" ? payload.detail : JSON.stringify(payload.detail);
    }
  } catch {
    // Fall through to the protocol status below.
  }
  return `${response.status} ${response.statusText}`;
}

function readLocalStorage(key: string, fallback: string): string {
  try {
    const value = window.localStorage.getItem(key);
    return value && value.trim() ? value : fallback;
  } catch {
    return fallback;
  }
}

function readMcpSource(): MCPSource {
  return readLocalStorage(MCP_SOURCE_STORAGE_KEY, "command") === "config" ? "config" : "command";
}

function writeLocalStorage(key: string, value: string): void {
  try {
    window.localStorage.setItem(key, value);
  } catch {
    // Local persistence is best effort only.
  }
}
