from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

import pytest

from ops_pilot.config.mcp_schema import MCPConfig
from ops_pilot.config.settings import Settings
from ops_pilot.eval import chaos
from ops_pilot.eval.dataset import EvalCase, InjectSpec
from ops_pilot.mcp.status import MCPLoadStatus, MCPServerLoadStatus


@pytest.mark.asyncio
async def test_flagd_client_retries_an_early_port_forward_exit(monkeypatch) -> None:
    class Stderr:
        async def read(self) -> bytes:
            return b"TLS handshake timeout"

    class Process:
        def __init__(self, returncode: int | None) -> None:
            self.returncode = returncode
            self.stderr = Stderr()

        def terminate(self) -> None:
            self.returncode = 0

        def kill(self) -> None:
            self.returncode = 1

        async def wait(self) -> int:
            return self.returncode or 0

    class Response:
        content = b"{}"

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, Any]:
            return {"flags": {"paymentFailure": {"defaultVariant": "off"}}}

    class HttpClient:
        async def request(self, *_args, **_kwargs) -> Response:
            return Response()

        async def aclose(self) -> None:
            return None

    processes = [Process(1), Process(None)]
    starts = 0

    async def start_process(*_args, **_kwargs) -> Process:
        nonlocal starts
        process = processes[starts]
        starts += 1
        return process

    monkeypatch.setattr(chaos, "_kubeconfig_from_settings", lambda _settings: "test-kubeconfig")
    monkeypatch.setattr(chaos.asyncio, "create_subprocess_exec", start_process)
    monkeypatch.setattr(chaos.httpx, "AsyncClient", lambda **_kwargs: HttpClient())

    variants = await chaos.current_variants(Settings.model_validate({}))

    assert variants == {"paymentFailure": "off"}
    assert starts == 2


def _document() -> dict:
    return {
        "flags": {
            "productCatalogFailure": {
                "defaultVariant": "off",
                "variants": {"on": True, "off": False},
                "targeting": {
                    "if": [
                        {"==": [{"var": "product_id"}, "OLJCESPC7Z"]},
                        "off",
                        "off",
                    ]
                },
            }
        }
    }


def test_targeted_flag_activation_replaces_the_complete_runtime_rule() -> None:
    desired, original = chaos._document_with_flag(
        _document(),
        "productCatalogFailure",
        "on",
        target={"product_id": "OLJCESPC7Z"},
    )

    active = desired["flags"]["productCatalogFailure"]
    assert original["targeting"]["if"][1:] == ["off", "off"]
    assert active["defaultVariant"] == "on"
    assert active["targeting"]["if"][1:] == ["on", "off"]


def test_plain_activation_removes_targeting_that_overrides_the_default() -> None:
    desired, _ = chaos._document_with_flag(_document(), "productCatalogFailure", "on")

    active = desired["flags"]["productCatalogFailure"]
    assert active["defaultVariant"] == "on"
    assert "targeting" not in active


def test_baseline_is_a_copy_with_all_known_faults_off() -> None:
    document = _document()
    document["flags"]["productCatalogFailure"]["defaultVariant"] = "on"

    baseline = chaos._baseline_document(document)

    assert baseline["flags"]["productCatalogFailure"]["defaultVariant"] == "off"
    assert "targeting" not in baseline["flags"]["productCatalogFailure"]
    assert document["flags"]["productCatalogFailure"]["defaultVariant"] == "on"


def test_validate_flag_catalog_requires_traffic_and_case_variants() -> None:
    flags = {flag: {"defaultVariant": "off", "variants": {"off": False, "on": True}} for flag in chaos.FAULT_FLAGS}
    flags["loadGeneratorTraffic"] = {"defaultVariant": "on", "variants": {"off": False, "on": True}}
    inject = InjectSpec(flag="paymentFailure", variant="on")

    chaos.validate_flag_catalog({"flags": flags}, {"payment": inject})

    flags["loadGeneratorTraffic"]["defaultVariant"] = "off"
    with pytest.raises(chaos.ChaosError, match="loadGeneratorTraffic"):
        chaos.validate_flag_catalog({"flags": flags}, {"payment": inject})


@dataclass
class _FakeFlagd:
    variants: list[str]
    settings: Settings

    async def read(self) -> dict[str, Any]:
        return {"flags": {}}

    async def write(self, document: Mapping[str, Any]) -> None:
        del document

    async def evaluate(
        self,
        flag: str,
        context: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        del flag, context
        return {"variant": self.variants.pop(0)}


@pytest.mark.asyncio
async def test_wait_for_flag_variant_requires_stable_ofrep_reads() -> None:
    flagd = _FakeFlagd(
        variants=["off", "on", "on"],
        settings=Settings.model_validate(
            {
                "chaos_flag_sync_timeout_seconds": 1,
                "chaos_poll_interval_seconds": 0.001,
                "chaos_stable_reads": 2,
            }
        ),
    )

    result = await chaos.wait_for_flag_variant(flagd, "productCatalogFailure", "on")

    assert result["attempts"] == 3
    assert result["evaluation"]["variant"] == "on"


def _mcp_settings(*, required: bool = True) -> Settings:
    return Settings.model_validate(
        {
            "mcp": MCPConfig.from_mapping(
                {
                    "mcpServers": {
                        "kubernetes": {
                            "required": required,
                            "transport": "stdio",
                            "command": "kubernetes",
                        },
                        "prometheus": {
                            "required": required,
                            "transport": "stdio",
                            "command": "prometheus",
                        },
                    },
                }
            )
        }
    )


def _runtime() -> SimpleNamespace:
    statuses = tuple(
        MCPServerLoadStatus(name=name, required=True, transport="stdio", ok=True, tool_count=1)
        for name in ("kubernetes", "prometheus")
    )
    mcp = SimpleNamespace(
        status=MCPLoadStatus(servers=statuses),
        tool_names=("pods_list", "query"),
    )
    return SimpleNamespace(mcp=mcp)


def test_mcp_preflight_requires_every_server_to_be_required() -> None:
    with pytest.raises(chaos.ChaosError, match="required: true"):
        chaos.validate_mcp_runtime(_mcp_settings(required=False), _runtime(), [])


def test_mcp_preflight_rejects_missing_case_tool_without_calling_tools() -> None:
    case = EvalCase(
        id="payment",
        prompt="investigate",
        category="diagnosis",
        expected_tools=("search_traces",),
    )

    with pytest.raises(ValueError, match="search_traces"):
        chaos.validate_mcp_runtime(_mcp_settings(), _runtime(), [case])
