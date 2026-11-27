"""The native Flagsmith Python SDK path (no OpenFeature)."""

import pytest

pytest.importorskip("flagsmith")

from flagsmith import Flagsmith  # noqa: E402
from flagsmith.offline_handlers import LocalFileHandler  # noqa: E402

from flagcov.analyze import analyze  # noqa: E402
from flagcov.recorder import instrument_flagsmith_sdk, recorder, uninstrument_flagsmith_sdk  # noqa: E402


@pytest.fixture
def sdk(demo_env_path):
    recorder.clear()
    instrument_flagsmith_sdk()
    yield Flagsmith(environment_key="ser.demo", offline_mode=True, offline_handler=LocalFileHandler(str(demo_env_path)))
    uninstrument_flagsmith_sdk()
    recorder.clear()


def test_environment_flags_are_recorded(sdk):
    flags = sdk.get_environment_flags()
    assert flags.is_feature_enabled("dark_mode") is True
    assert flags.get_feature_value("free_shipping_threshold") == 499
    got = {(r.flag, r.value, r.value_type, r.source) for r in recorder.records}
    assert got == {("dark_mode", True, "boolean", "flagsmith"), ("free_shipping_threshold", 499, "value", "flagsmith")}


def test_identity_flags_carry_traits_for_segment_checks(sdk, doc):
    flags = sdk.get_identity_flags("corp-7", traits={"plan": "enterprise"})
    assert flags.get_feature_value("checkout_flow") == "invoice"
    r = recorder.records[-1]
    assert r.targeting_key == "corp-7" and r.traits == {"plan": "enterprise"}
    seg = next(s for f in analyze(doc, recorder.records).flags for s in f.states if s.kind == "segment")
    assert seg.covered
    if seg.targeting_verified is not None:
        assert seg.targeting_verified is True


def test_uninstrument_restores_sdk(sdk):
    uninstrument_flagsmith_sdk()
    recorder.clear()
    sdk.get_environment_flags().is_feature_enabled("dark_mode")
    assert recorder.records == []
