import pytest

from flagcov.analyze import FlagState, analyze, matches
from flagcov.recorder import Record


def rec(flag, value, value_type="string", **kw):
    return Record(flag=flag, value=value, value_type=value_type, **kw)


def state(report, flag, label):
    f = next(f for f in report.flags if f.flag == flag)
    return next(s for s in f.states if s.label == label)


# ----------------------------------------------------------------- matching rules

def test_string_value_matches_its_state():
    s = FlagState("f", "variant", True, "express", weight=10)
    assert matches(s, rec("f", "express"))
    assert not matches(s, rec("f", "classic"))
    assert not matches(s, rec("other", "express"))


def test_numbers_and_floats_normalise():
    s = FlagState("f", "default", True, 499, weight=100)
    assert matches(s, rec("f", 499, "integer"))
    assert matches(s, rec("f", 499.0, "float"))
    assert matches(s, rec("f", "499", "value"))


def test_boolean_read_covers_a_simple_on_flag_but_not_a_variant():
    on = FlagState("f", "default", True, None, weight=100)
    variant = FlagState("f", "variant", True, "express", weight=10)
    assert matches(on, rec("f", True, "boolean"))
    assert not matches(variant, rec("f", True, "boolean"))


def test_boolean_read_of_multivariate_control_does_not_count():
    control = FlagState("f", "default", True, "classic", weight=60)
    assert not matches(control, rec("f", True, "boolean"))


def test_false_covers_kill_switch_and_disabled_state():
    assert matches(FlagState("f", "kill_switch", False, None), rec("f", False, "boolean"))
    assert matches(FlagState("f", "default", False, None, weight=100), rec("f", False, "boolean"))
    assert not matches(FlagState("f", "kill_switch", False, None), rec("f", True, "boolean"))


def test_disabled_value_flag_is_covered_by_the_code_default():
    kill = FlagState("f", "kill_switch", False, None)
    assert matches(kill, rec("f", "classic", default_value="classic"))
    assert matches(kill, rec("f", "classic", reason="DISABLED"))
    # a served variant that happens to equal the default is not the disabled path
    assert not matches(kill, rec("f", "classic", default_value="classic", variant="control"))


def test_identity_override_needs_the_right_identity():
    s = FlagState("f", "identity", True, "express", identifier="qa-anna")
    assert matches(s, rec("f", "express", targeting_key="qa-anna"))
    assert not matches(s, rec("f", "express", targeting_key="someone-else"))


# ----------------------------------------------------------------- full analysis

def demo_records():
    return [
        rec("checkout_flow", "classic", targeting_key="u1", traits={"plan": "free"}, test="t::a"),
        rec("checkout_flow", "one_page", targeting_key="u2", traits={"plan": "free"}, test="t::a"),
        rec("free_shipping_threshold", 499, "integer"),
        rec("dark_mode", True, "boolean"),
        rec("new_search", False, "boolean"),
    ]


def test_demo_report_numbers(doc):
    report = analyze(doc, demo_records())
    assert state(report, "checkout_flow", "express").covered is False
    assert state(report, "checkout_flow", "classic").covered is True
    assert state(report, "checkout_flow", "classic").tests == ["t::a"]
    checkout = next(f for f in report.flags if f.flag == "checkout_flow")
    assert checkout.untested_traffic == 10
    assert [s.segment for s in checkout.untested_rules] == ["enterprise"]
    # legacy_promo_banner was never read: 100% of its traffic is untested (no scan given)
    assert report.untested_traffic == 100
    assert report.never_evaluated == ["legacy_promo_banner"]


def test_state_coverage_excludes_optional_kill_switches(doc):
    report = analyze(doc, demo_records())
    required = report.required_states
    assert all(s.kind != "kill_switch" for s in required)
    covered = sum(s.covered for s in required)
    assert report.state_coverage == pytest.approx(100 * covered / len(required))


def test_scan_marks_unreferenced_flags_stale_and_finds_unknown(doc):
    referenced = {"checkout_flow": ["shop.py:1"], "dark_mode": ["shop.py:2"], "new_search": ["x"], "free_shipping_threshold": ["x"], "recommendation_v2": ["shop.py:9"]}
    report = analyze(doc, demo_records(), referenced)
    assert report.unknown_flags == {"recommendation_v2": ["shop.py:9"]}
    assert report.unreferenced_flags == ["legacy_promo_banner"]
    banner = next(f for f in report.flags if f.flag == "legacy_promo_banner")
    assert banner.stale and banner.untested_traffic == 0
    assert report.untested_traffic == 10  # worst live flag is now checkout_flow
    assert len(report.live_flags) == 4 and len(report.fully_tested) == 3


def test_segment_targeting_verified_with_flagsmith_engine(doc):
    pytest.importorskip("flag_engine")
    records = demo_records() + [rec("checkout_flow", "invoice", targeting_key="corp-1", traits={"plan": "enterprise"})]
    seg = state(analyze(doc, records), "checkout_flow", "invoice")
    assert seg.covered and seg.targeting_verified is True


def test_segment_value_forced_without_matching_traits_is_not_verified(doc):
    pytest.importorskip("flag_engine")
    records = demo_records() + [rec("checkout_flow", "invoice", targeting_key="u9", traits={"plan": "free"}, variant="flagcov-override")]
    seg = state(analyze(doc, records), "checkout_flow", "invoice")
    assert seg.covered and seg.targeting_verified is False


def test_everything_tested_gives_full_marks(doc):
    records = demo_records() + [
        rec("checkout_flow", "express"),
        rec("checkout_flow", "invoice", targeting_key="c", traits={"plan": "enterprise"}),
        rec("legacy_promo_banner", True, "boolean"),
    ]
    report = analyze(doc, records)
    assert report.state_coverage == 100
    assert report.untested_traffic == 0
    assert len(report.fully_tested) == len(report.live_flags)


def test_empty_document_and_no_records():
    report = analyze({"feature_states": [], "project": {"segments": []}}, [])
    assert report.state_coverage == 100 and report.untested_traffic == 0 and report.worst_flag is None


def test_to_dict_is_json_serialisable(doc):
    import json

    data = analyze(doc, demo_records()).to_dict()
    json.dumps(data)
    assert data["flags"][0]["states"][0]["where"]
