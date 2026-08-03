from ops_pilot.tools.dynatrace_dashboard import build_dashboard_snapshot


def test_build_dashboard_snapshot_normalizes_metrics_and_problems():
    snapshot = build_dashboard_snapshot(
        focus_entity="checkout-service",
        time_window="last 2h",
        metrics=[
            {"key": "err", "label": "Error rate", "value": "4.2", "unit": "%", "tone": "danger"},
            {"id": "rt", "name": "Response time", "value": 320, "sparkline": [1, "2", 3.5, "x"]},
        ],
        problems=[
            {
                "id": "P-1",
                "title": "High error rate",
                "severity": "AVAILABILITY",
                "entity": "checkout",
            },
        ],
        note="Elevated errors after deploy.",
    )

    assert snapshot["status"] == "ready"
    assert snapshot["focus_entity"] == "checkout-service"
    assert snapshot["time_window"] == "last 2h"
    assert snapshot["note"] == "Elevated errors after deploy."
    assert "generated_at" in snapshot

    metrics = snapshot["metrics"]
    assert len(metrics) == 2
    assert metrics[0] == {
        "key": "err",
        "label": "Error rate",
        "value": "4.2",
        "tone": "danger",
        "unit": "%",
    }
    # id/name fallbacks + sparkline coercion (non-numeric dropped)
    assert metrics[1]["key"] == "rt"
    assert metrics[1]["label"] == "Response time"
    assert metrics[1]["value"] == "320"
    assert metrics[1]["sparkline"] == [1.0, 2.0, 3.5]

    problems = snapshot["problems"]
    assert len(problems) == 1
    assert problems[0]["id"] == "P-1"
    assert problems[0]["severity"] == "AVAILABILITY"
    assert problems[0]["tone"] == "danger"  # critical severity marker


def test_build_dashboard_snapshot_drops_malformed_and_defaults_tone():
    snapshot = build_dashboard_snapshot(
        focus_entity=None,
        time_window="last 24h",
        metrics=[
            {"label": "missing key and value"},
            {"key": "ok", "label": "OK", "value": "99.9", "tone": "bogus"},
            "not-a-dict",
        ],
        problems=[
            {"title": "missing id"},
            {"id": "P-2", "title": "Latency spike"},
        ],
    )

    assert snapshot["focus_entity"] is None
    metrics = snapshot["metrics"]
    assert len(metrics) == 1
    assert metrics[0]["key"] == "ok"
    assert metrics[0]["tone"] == "normal"  # invalid tone falls back
    assert "sparkline" not in metrics[0]
    assert "unit" not in metrics[0]

    problems = snapshot["problems"]
    assert len(problems) == 1
    assert problems[0]["id"] == "P-2"
    assert problems[0]["severity"] == "UNKNOWN"  # default when absent
    assert problems[0]["tone"] == "warning"  # non-critical severity


def test_build_dashboard_snapshot_handles_empty_inputs():
    snapshot = build_dashboard_snapshot(
        focus_entity="svc",
        time_window="last 1h",
        metrics=None,
        problems=None,
    )
    assert snapshot["metrics"] == []
    assert snapshot["problems"] == []
    assert "note" not in snapshot
