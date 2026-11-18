import pytest

from wafer.builtins.folder_manager.rules import (
    RULE_COLORS,
    Condition,
    HighlightRule,
    default_rules,
    new_rule,
)
from wafer.builtins.folder_manager.stats import FolderValues
from wafer.core.logs import AppLogger
from wafer.builtins.filters import TextFilter
from wafer.plugin.query.handler import filter_registry


@pytest.fixture
def text_filter():
    filter_registry.register(TextFilter)
    return TextFilter


def test_query_entries_are_empty_when_the_bars_do_not_narrow(text_filter):
    blank = {"filter": "text", "params": {"keys": ["path"], "keywords": ""}, "op": None, "enabled": True}
    rule = HighlightRule("x", "#000", bars=[blank])
    assert rule.filter_entries() and rule.query_entries() == []
    rule.bars = [{**blank, "params": {"keys": ["path"], "keywords": "cat"}}]
    assert rule.query_entries() == rule.filter_entries()


def test_mixed_matches_folder_with_files_and_folders():
    assert default_rules()[0].matches(FolderValues(3, 9, 2, 5))
    assert not default_rules()[0].matches(FolderValues(0, 9, 2, 5))


def test_rule_without_conditions_matches_nothing():
    assert not HighlightRule("x", "#000").matches(FolderValues(1, 1, 1, 1))


def test_conditions_are_anded_and_support_all_operators():
    rule = HighlightRule(
        "x", "#000", conditions=[Condition("files", "<=", 5), Condition("all_files", "==", 9)]
    )
    assert rule.matches(FolderValues(5, 9, 0, 0))
    assert not rule.matches(FolderValues(6, 9, 0, 0))
    assert not rule.matches(FolderValues(5, 8, 0, 0))


def test_folder_only_rule_has_no_count():
    assert not HighlightRule("x", "#000", conditions=[Condition("folders", ">=", 1)]).shows_count()
    assert HighlightRule("x", "#000", conditions=[Condition("all_files", ">=", 1)]).shows_count()


def test_rule_round_trips_through_dict():
    rule = HighlightRule(
        "Big",
        "#123456",
        enabled=False,
        bars=[{"filter": "text", "params": {"q": "a"}, "op": "and", "enabled": True}],
        conditions=[Condition("all_files", ">=", 100)],
    )
    assert HighlightRule.from_dict(rule.to_dict()) == rule


def test_from_dict_tolerates_missing_optional_keys():
    rule = HighlightRule.from_dict({"name": "x", "color": "#000"})
    assert rule.enabled and rule.bars == [] and rule.conditions == []


def test_unknown_metric_is_dropped_on_load():
    rule = HighlightRule.from_dict(
        {
            "name": "x",
            "color": "#000",
            "conditions": [
                {"metric": "bogus", "op": ">=", "value": 1},
                {"metric": "files", "op": "!=", "value": 1},
                {"metric": "files", "op": ">=", "value": 2},
            ],
        }
    )
    assert rule.conditions == [Condition("files", ">=", 2)]


def test_filter_entries_skip_disabled_and_unknown_filters(text_filter):
    rule = HighlightRule(
        "x",
        "#000",
        bars=[
            {"filter": "text", "params": {"a": 1}, "op": "or", "enabled": True},
            {"filter": "text", "params": {}, "op": None, "enabled": False},
            {"filter": "nope", "params": {}, "op": None, "enabled": True},
        ],
    )
    assert rule.filter_entries() == [(text_filter, {"a": 1}, "or")]


def test_malformed_conditions_are_skipped_with_a_warning(monkeypatch):
    warnings = []
    monkeypatch.setattr(AppLogger, "warning", lambda message: warnings.append(message))
    rule = HighlightRule.from_dict(
        {
            "name": "Broken",
            "color": "#000",
            "conditions": [
                {"metric": "files", "op": ">="},
                {"metric": "files", "op": ">=", "value": "many"},
                {"metric": "files", "op": ">=", "value": 3},
            ],
        }
    )
    assert rule.conditions == [Condition("files", ">=", 3)]
    assert len(warnings) == 2 and all("Broken" in message for message in warnings)


def test_mistyped_rule_parts_are_skipped_or_rejected(monkeypatch):
    warnings = []
    monkeypatch.setattr(AppLogger, "warning", lambda message: warnings.append(message))
    rule = HighlightRule.from_dict(
        {
            "name": "Odd",
            "color": "#000",
            "bars": ["text", {"filter": "text", "params": "x"}, {"filter": "text", "params": {"keywords": "a"}}],
            "conditions": ["files", {"metric": "files", "op": ">=", "value": 1}],
        }
    )
    assert rule.bars == [{"filter": "text", "params": {"keywords": "a"}}]
    assert rule.conditions == [Condition("files", ">=", 1)]
    assert len(warnings) == 3
    assert HighlightRule.from_dict({"name": "Odd", "color": "#000", "bars": "text", "conditions": 5}).bars == []
    for bad in ({"name": 1, "color": "#000"}, {"name": "Odd", "color": None}, "rule"):
        with pytest.raises((TypeError, KeyError)):
            HighlightRule.from_dict(bad)


def test_bar_without_filter_is_skipped_with_a_warning(text_filter, monkeypatch):
    warnings = []
    monkeypatch.setattr(AppLogger, "warning", lambda message: warnings.append(message))
    rule = HighlightRule(
        "Broken",
        "#000",
        bars=[{"params": {}}, {"filter": "text", "params": {"a": 1}, "op": None, "enabled": True}],
    )
    assert rule.filter_entries() == [(text_filter, {"a": 1}, None)]
    assert len(warnings) == 1 and "Broken" in warnings[0]


def test_new_rule_takes_next_free_name_and_color():
    first = new_rule([])
    assert (first.name, first.color) == ("Rule 1", RULE_COLORS[0])
    assert first.conditions == [Condition("files", ">=", 1)]
    existing = [HighlightRule("Rule 1", RULE_COLORS[0]), HighlightRule("Rule 3", RULE_COLORS[1])]
    second = new_rule(existing)
    assert (second.name, second.color) == ("Rule 2", RULE_COLORS[2])


def test_new_rule_reuses_first_color_when_all_are_used():
    existing = [HighlightRule(f"Rule {i + 1}", color) for i, color in enumerate(RULE_COLORS)]
    assert new_rule(existing).color == RULE_COLORS[0]


def test_a_rule_needs_files_only_when_its_count_conditions_fail_at_zero():
    assert HighlightRule("A", "#000000", conditions=[Condition("files", ">=", 1), Condition("folders", "<=", 0)]).needs_files()
    assert HighlightRule("B", "#000000", conditions=[Condition("all_files", "==", 3)]).needs_files()
    assert not HighlightRule("C", "#000000", conditions=[Condition("files", "<=", 5)]).needs_files()
    assert not HighlightRule("D", "#000000", conditions=[Condition("folders", ">=", 1)]).needs_files()


def test_counts_allow_checks_only_the_count_conditions():
    rule = HighlightRule("A", "#000000", conditions=[Condition("files", ">=", 2), Condition("all_files", "<=", 10), Condition("folders", ">=", 5)])
    assert rule.counts_allow(2, 10)
    assert not rule.counts_allow(1, 10)
    assert not rule.counts_allow(2, 11)
