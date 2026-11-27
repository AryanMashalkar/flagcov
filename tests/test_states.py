import pytest

from flagcov.analyze import describe_rules, extract_states


def by_kind(states, kind):
    return [s for s in states if s.kind == kind]


def test_multivariate_weights_come_from_the_document(doc):
    states = extract_states(doc)["checkout_flow"]
    population = {s.label: s.weight for s in states if s.kind in ("default", "variant")}
    assert population == {"classic": 60.0, "one_page": 30.0, "express": 10.0}


def test_variant_keys_are_kept(doc):
    states = extract_states(doc)["checkout_flow"]
    assert {s.variant_key for s in by_kind(states, "variant")} == {"one_page", "express"}
    assert by_kind(states, "default")[0].variant_key == "control"


def test_boolean_flag_has_one_live_state_and_a_kill_switch(doc):
    states = extract_states(doc)["dark_mode"]
    assert [(s.kind, s.label, s.weight) for s in states] == [("default", "on", 100.0), ("kill_switch", "off (kill switch)", None)]


def test_disabled_flag_has_no_kill_switch(doc):
    states = extract_states(doc)["new_search"]
    assert [(s.kind, s.label) for s in states] == [("default", "off")]


def test_remote_config_value(doc):
    default = by_kind(extract_states(doc)["free_shipping_threshold"], "default")[0]
    assert default.value == 499 and default.label == "499"


def test_segment_override_is_a_state_with_a_readable_rule(doc):
    seg = by_kind(extract_states(doc)["checkout_flow"], "segment")[0]
    assert seg.segment == "enterprise"
    assert seg.value == "invoice"
    assert seg.rule == "plan == enterprise"
    assert seg.weight is None  # segments never get a made-up traffic percentage
    assert seg.where == 'segment "enterprise" (plan == enterprise)'


def test_identity_overrides(doc):
    doc["identity_overrides"] = [
        {"identifier": "qa-anna", "identity_features": [{"feature": {"id": 3, "name": "checkout_flow"}, "enabled": True, "feature_state_value": "express"}]}
    ]
    ident = by_kind(extract_states(doc)["checkout_flow"], "identity")
    assert len(ident) == 1 and ident[0].identifier == "qa-anna" and ident[0].value == "express"


def test_segment_only_feature_is_still_listed(doc):
    doc["project"]["segments"][0]["feature_states"].append(
        {"feature": {"id": 99, "name": "beta_only"}, "enabled": True, "feature_state_value": "x"}
    )
    assert "beta_only" in extract_states(doc)


def test_duplicate_states_are_merged(doc):
    doc["feature_states"].append(dict(doc["feature_states"][0]))
    assert len(extract_states(doc)["dark_mode"]) == 2


def test_weights_never_go_negative(doc):
    for v in doc["feature_states"][2]["multivariate_feature_state_values"]:
        v["percentage_allocation"] = 70
    default = by_kind(extract_states(doc)["checkout_flow"], "default")[0]
    assert default.weight == 0


@pytest.mark.parametrize(
    "rules, expected",
    [
        ([], "always"),
        ([{"type": "ALL", "conditions": [{"operator": "EQUAL", "property_": "plan", "value": "pro"}]}], "plan == pro"),
        (
            [{"type": "ANY", "conditions": [
                {"operator": "EQUAL", "property_": "country", "value": "IN"},
                {"operator": "GREATER_THAN", "property_": "age", "value": "30"},
            ]}],
            "country == IN OR age > 30",
        ),
        ([{"type": "NONE", "conditions": [{"operator": "IS_SET", "property_": "banned"}]}], "NOT (banned is set)"),
        ([{"type": "ALL", "conditions": [{"operator": "PERCENTAGE_SPLIT", "value": "25"}]}], "25% of identities"),
        (
            [{"type": "ALL", "conditions": [], "rules": [
                {"type": "ANY", "conditions": [
                    {"operator": "EQUAL", "property_": "a", "value": "1"},
                    {"operator": "EQUAL", "property_": "b", "value": "2"},
                ]}]}],
            "(a == 1 OR b == 2)",
        ),
    ],
)
def test_describe_rules(rules, expected):
    assert describe_rules(rules) == expected
