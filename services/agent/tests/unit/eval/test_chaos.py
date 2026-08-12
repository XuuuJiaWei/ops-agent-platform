from __future__ import annotations

import json

import pytest

from ops_pilot.config.settings import Settings
from ops_pilot.eval import chaos


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


def test_targeted_flag_activation_is_transactional(monkeypatch) -> None:
    document = _document()
    patched: list[dict] = []
    monkeypatch.setattr(chaos, "read_flags", lambda _settings: document)
    monkeypatch.setattr(chaos, "_patch_document", lambda _settings, value: patched.append(value))

    original = chaos.set_flag(
        Settings(),
        "productCatalogFailure",
        "on",
        target={"product_id": "OLJCESPC7Z"},
    )

    active = patched[-1]["flags"]["productCatalogFailure"]
    assert original["targeting"]["if"][1:] == ["off", "off"]
    assert active["defaultVariant"] == "on"
    assert active["targeting"]["if"][1:] == ["on", "off"]


def test_plain_activation_removes_targeting_that_can_override_default(monkeypatch) -> None:
    document = _document()
    monkeypatch.setattr(chaos, "read_flags", lambda _settings: document)
    monkeypatch.setattr(chaos, "_patch_document", lambda *_args: None)

    chaos.set_flag(Settings(), "productCatalogFailure", "on")

    active = document["flags"]["productCatalogFailure"]
    assert active["defaultVariant"] == "on"
    assert "targeting" not in active


def test_restore_flag_replaces_the_complete_spec(monkeypatch) -> None:
    document = _document()
    original = document["flags"]["productCatalogFailure"].copy()
    document["flags"]["productCatalogFailure"] = {
        "defaultVariant": "on",
        "variants": {"on": True, "off": False},
    }
    monkeypatch.setattr(chaos, "read_flags", lambda _settings: document)
    monkeypatch.setattr(chaos, "_patch_document", lambda *_args: None)

    chaos.restore_flag(Settings(), "productCatalogFailure", original)

    assert document["flags"]["productCatalogFailure"] == original


def test_evaluate_flag_uses_ofrep_with_target_context(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_kubectl(_settings, *args, input_text: str | None = None, timeout_seconds=None):
        captured["args"] = args
        assert input_text is not None
        captured["body"] = json.loads(input_text)
        captured["timeout_seconds"] = timeout_seconds
        return '{"key":"productCatalogFailure","variant":"on","value":true}'

    monkeypatch.setattr(chaos, "_kubectl", fake_kubectl)

    result = chaos.evaluate_flag(
        Settings(),
        "productCatalogFailure",
        context={"product_id": "OLJCESPC7Z"},
    )

    assert result["variant"] == "on"
    assert captured["body"] == {"context": {"product_id": "OLJCESPC7Z"}}
    captured_args = captured["args"]
    assert isinstance(captured_args, tuple)
    assert "--raw" in captured_args


@pytest.mark.asyncio
async def test_wait_for_flag_variant_requires_stable_reads(monkeypatch) -> None:
    variants = iter(("off", "on", "on"))
    monkeypatch.setattr(
        chaos,
        "evaluate_flag",
        lambda *_args, **_kwargs: {"variant": next(variants)},
    )
    settings = Settings(
        chaos_flag_sync_timeout_seconds=1,
        chaos_poll_interval_seconds=0.001,
        chaos_stable_reads=2,
    )

    result = await chaos.wait_for_flag_variant(settings, "productCatalogFailure", "on")

    assert result["attempts"] == 3
    assert result["evaluation"]["variant"] == "on"
