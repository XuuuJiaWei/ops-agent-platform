import pytest

from ops_pilot.config.interpolation import (
    MissingEnvironmentError,
    expand_mapping,
    expand_optional,
    expand_value,
)


def test_expand_value_substitutes_from_env():
    assert expand_value("https://${HOST}/mcp", {"HOST": "example.com"}) == "https://example.com/mcp"


def test_expand_value_multiple_and_repeated_vars():
    env = {"A": "x", "B": "y"}
    assert expand_value("${A}-${B}-${A}", env) == "x-y-x"


def test_expand_value_adjacent_placeholders():
    assert expand_value("${A}${B}", {"A": "1", "B": "2"}) == "12"


def test_dollar_dollar_becomes_literal_dollar():
    assert expand_value("cost is 5$$", {}) == "cost is 5$"


def test_escaped_placeholder_is_not_looked_up():
    # $${VAR} -> literal ${VAR}, no env lookup, no missing-var error.
    assert expand_value("$${VAR}", {}) == "${VAR}"


def test_missing_var_raises_with_name():
    with pytest.raises(MissingEnvironmentError, match="OTEL_SHOOT_DOMAIN") as exc:
        expand_value("https://x.${OTEL_SHOOT_DOMAIN}/mcp", {})
    assert exc.value.missing == ("OTEL_SHOOT_DOMAIN",)


def test_missing_vars_are_sorted_and_deduped():
    with pytest.raises(MissingEnvironmentError) as exc:
        expand_value("${B}${A}${B}", {})
    assert exc.value.missing == ("A", "B")


def test_empty_string_env_counts_as_missing():
    with pytest.raises(MissingEnvironmentError, match="HOST"):
        expand_value("${HOST}", {"HOST": ""})


def test_expand_mapping_expands_each_value():
    result = expand_mapping({"Authorization": "Basic ${TOKEN}", "X": "static"}, {"TOKEN": "abc"})
    assert result == {"Authorization": "Basic abc", "X": "static"}


def test_expand_optional_passes_through_none_and_empty():
    assert expand_optional(None, {}) is None
    assert expand_optional("", {}) == ""


def test_expand_optional_expands_non_empty():
    assert expand_optional("https://${HOST}", {"HOST": "h"}) == "https://h"
