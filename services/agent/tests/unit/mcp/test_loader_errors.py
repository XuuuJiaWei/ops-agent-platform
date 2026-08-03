from ops_pilot.mcp.loader import _safe_error


def test_safe_error_unwraps_exception_groups() -> None:
    error = ExceptionGroup(
        "unhandled errors in a TaskGroup",
        [RuntimeError("Tunnel 'local-dev' is not connected.")],
    )

    assert _safe_error(error) == "Tunnel 'local-dev' is not connected."
