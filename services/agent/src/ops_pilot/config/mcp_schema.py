"""Schema and loader for deployment-level MCP server configuration."""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ops_pilot.config.interpolation import expand_mapping, expand_optional
from ops_pilot.config.paths import REPO_ROOT, resolve_repo_path

SUPPORTED_TRANSPORTS = {"stdio", "http", "streamable_http", "sse"}


class MCPConfigError(ValueError):
    """Raised when MCP configuration is malformed."""


@dataclass(frozen=True)
class MCPServerConfig:
    name: str
    transport: str
    required: bool = False
    command: str | None = None
    args: tuple[str, ...] = field(default_factory=tuple)
    cwd: str | None = None
    url: str | None = None
    headers: Mapping[str, str] = field(default_factory=dict)
    env: Mapping[str, str] = field(default_factory=dict)
    timeout: float | None = None
    allow_tools: tuple[str, ...] = field(default_factory=tuple)
    hitl_tools: tuple[str, ...] = field(default_factory=tuple)
    retry_tools: tuple[str, ...] = field(default_factory=tuple)

    @classmethod
    def from_mapping(cls, name: str, data: Mapping[str, Any], env: Mapping[str, str]) -> MCPServerConfig:
        transport = str(data.get("transport", "stdio")).strip()
        if transport not in SUPPORTED_TRANSPORTS:
            raise MCPConfigError(
                f"MCP server '{name}' uses unsupported transport '{transport}'. "
                f"Expected one of: {', '.join(sorted(SUPPORTED_TRANSPORTS))}."
            )

        args = data.get("args", [])
        if args is None:
            args = []
        if not isinstance(args, list) or not all(isinstance(arg, str) for arg in args):
            raise MCPConfigError(f"MCP server '{name}' field 'args' must be a list of strings.")

        timeout = data.get("timeout")
        parsed_timeout = float(timeout) if timeout not in (None, "") else None
        # Whitelist: only data/endpoint fields are interpolated. command/args/cwd
        # are process-spec fields and are left verbatim by construction.
        config = cls(
            name=name,
            transport=transport,
            required=bool(data.get("required", False)),
            command=_optional_string(data.get("command")),
            args=tuple(args),
            cwd=_optional_string(data.get("cwd")),
            url=expand_optional(_optional_string(data.get("url")), env),
            headers=expand_mapping(_string_mapping(name, "headers", data.get("headers", {})), env),
            env=expand_mapping(_string_mapping(name, "env", data.get("env", {})), env),
            timeout=parsed_timeout,
            allow_tools=_string_list(name, "allow_tools", data.get("allow_tools", ())),
            hitl_tools=_string_list(name, "hitl_tools", data.get("hitl_tools", ())),
            retry_tools=_string_list(name, "retry_tools", data.get("retry_tools", ())),
        )
        config.validate()
        return config

    def validate(self) -> None:
        if self.transport == "stdio" and not self.command:
            raise MCPConfigError(f"MCP stdio server '{self.name}' requires a command.")
        if self.transport in {"http", "streamable_http", "sse"} and not self.url:
            raise MCPConfigError(f"MCP {self.transport} server '{self.name}' requires a url.")

    def to_client_connection(self) -> dict[str, Any]:
        connection: dict[str, Any] = {"transport": self.transport}
        if self.command:
            connection["command"] = self.command
        if self.args:
            connection["args"] = list(self.args)
        if self.cwd:
            connection["cwd"] = str(_resolve_cwd(self.cwd))
        if self.url:
            connection["url"] = self.url
        if self.headers:
            connection["headers"] = dict(self.headers)
        if self.env:
            connection["env"] = dict(self.env)
        return connection

    def to_langchain_config(self) -> dict[str, Any]:
        return self.to_client_connection()


@dataclass(frozen=True)
class MCPConfig:
    servers: tuple[MCPServerConfig, ...] = field(default_factory=tuple)

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any], env: Mapping[str, str] | None = None) -> MCPConfig:
        if env is None:
            env = os.environ
        raw_servers = data.get("mcpServers", data.get("servers", {}))
        if not isinstance(raw_servers, Mapping):
            raise MCPConfigError("MCP config field 'mcpServers' must be an object.")
        return cls(
            servers=tuple(
                MCPServerConfig.from_mapping(str(name), server_data, env) for name, server_data in raw_servers.items()
            )
        )

    @classmethod
    def load(cls, path: Path) -> MCPConfig:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise MCPConfigError(f"MCP config file not found: {path}") from exc
        except json.JSONDecodeError as exc:
            raise MCPConfigError(f"MCP config file is not valid JSON: {path}: {exc}") from exc
        if not isinstance(data, Mapping):
            raise MCPConfigError("MCP config root must be a JSON object.")
        return cls.from_mapping(data)

    @classmethod
    def from_file(cls, path_value: str | Path | None) -> MCPConfig:
        path = resolve_repo_path(path_value)
        if path is None:
            return cls()
        return cls.load(path)

    def required_names(self) -> set[str]:
        return {server.name for server in self.servers if server.required}

    def hitl_tool_names(self) -> set[str]:
        """Union of tool names that require human-in-the-loop approval."""

        names: set[str] = set()
        for server in self.servers:
            names.update(server.hitl_tools)
        return names

    def to_langchain_config(self) -> dict[str, dict[str, Any]]:
        return {server.name: server.to_client_connection() for server in self.servers}


def _optional_string(value: Any) -> str | None:
    if value in (None, ""):
        return None
    if not isinstance(value, str):
        raise MCPConfigError("Expected a string value.")
    return value


def _resolve_cwd(value: str) -> Path:
    raw = Path(value).expanduser()
    if raw.is_absolute():
        return raw.resolve()
    return (REPO_ROOT / raw).resolve()


def _string_mapping(name: str, field_name: str, value: Any) -> Mapping[str, str]:
    if value in (None, ""):
        return {}
    if not isinstance(value, Mapping):
        raise MCPConfigError(f"MCP server '{name}' field '{field_name}' must be an object.")
    parsed: dict[str, str] = {}
    for key, item in value.items():
        if not isinstance(key, str) or not isinstance(item, str):
            raise MCPConfigError(f"MCP server '{name}' field '{field_name}' must contain only string keys/values.")
        parsed[key] = item
    return parsed


def _string_list(name: str, field_name: str, value: Any) -> tuple[str, ...]:
    if value in (None, ""):
        return ()
    if not isinstance(value, list | tuple) or not all(isinstance(item, str) for item in value):
        raise MCPConfigError(f"MCP server '{name}' field '{field_name}' must be a list of strings.")
    return tuple(value)
