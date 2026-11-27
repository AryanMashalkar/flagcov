"""End-to-end: run pytest with --flagcov inside a temporary project (pytester)."""

import json
import shutil

import pytest

pytest.importorskip("openfeature")

IN_MEMORY_CONFTEST = """
import pytest
from openfeature import api
from openfeature.provider.in_memory_provider import InMemoryFlag, InMemoryProvider

@pytest.fixture(autouse=True, scope="session")
def provider():
    api.set_provider(InMemoryProvider({
        "checkout_flow": InMemoryFlag("classic", {"classic": "classic", "one_page": "one_page", "express": "express"}),
        "dark_mode": InMemoryFlag("on", {"on": True, "off": False}),
    }))
    yield
    api.clear_providers()
"""

TESTS = """
from openfeature import api
from flagcov import OFF

def test_classic():
    assert api.get_client().get_string_value("checkout_flow", "classic") == "classic"

def test_dark():
    assert api.get_client().get_boolean_value("dark_mode", False) is True

def test_forced_variant(flag_override):
    flag_override("checkout_flow", "one_page")
    assert api.get_client().get_string_value("checkout_flow", "classic") == "one_page"

def test_forced_off(flag_override):
    flag_override("checkout_flow", OFF)
    assert api.get_client().get_string_value("checkout_flow", "classic") == "classic"

def test_override_is_undone_after_each_test():
    assert api.get_client().get_string_value("checkout_flow", "classic") == "classic"
"""


@pytest.fixture
def project(pytester, demo_env_path):
    pytester.makeconftest(IN_MEMORY_CONFTEST)
    pytester.makepyfile(test_shop=TESTS)
    shutil.copy(demo_env_path, pytester.path / "environment.json")
    return pytester


def test_report_is_printed_and_written(project):
    result = project.runpytest_subprocess("--flagcov", "--flagcov-env", "environment.json", "-p", "no:cacheprovider")
    result.assert_outcomes(passed=5)
    result.stdout.fnmatch_lines(["*flag coverage (FlagCov)*", "*checkout_flow*express*NOT TESTED*", "*Riskiest flag*"])
    report = json.loads((project.path / ".flagcov" / "report.json").read_text())
    checkout = next(f for f in report["flags"] if f["flag"] == "checkout_flow")
    labels = {s["label"]: s["covered"] for s in checkout["states"]}
    assert labels["classic"] and labels["one_page"] and not labels["express"]
    assert labels["off (kill switch)"] is True  # forced with flagcov.OFF
    evaluations = json.loads((project.path / ".flagcov" / "evaluations.json").read_text())
    assert {e["test"] for e in evaluations} >= {"test_shop.py::test_classic", "test_shop.py::test_forced_variant"}


def test_threshold_fails_a_green_suite(project):
    result = project.runpytest_subprocess("--flagcov", "--flagcov-env", "environment.json", "--flagcov-fail-untested", "5")
    assert result.ret == pytest.ExitCode.TESTS_FAILED
    result.stdout.fnmatch_lines(["*FAIL: untested production traffic*"])


def test_threshold_passes_when_met(project):
    result = project.runpytest_subprocess("--flagcov", "--flagcov-env", "environment.json", "--flagcov-fail-under", "1")
    assert result.ret == pytest.ExitCode.OK


def test_scan_option(project):
    project.makepyfile(app='client.get_boolean_value("ghost_flag", False)')
    result = project.runpytest_subprocess("--flagcov", "--flagcov-env", "environment.json", "--flagcov-scan", "app.py")
    result.stdout.fnmatch_lines(["*missing from Flagsmith: ghost_flag*"])


def test_missing_document_still_saves_evaluations(project):
    result = project.runpytest_subprocess("--flagcov", "--flagcov-env", "nope.json")
    result.assert_outcomes(passed=5)
    result.stdout.fnmatch_lines(["*Could not load the environment document*"])
    assert (project.path / ".flagcov" / "evaluations.json").is_file()


def test_plugin_is_inert_without_the_flag(project):
    result = project.runpytest_subprocess("-p", "no:cacheprovider")
    result.assert_outcomes(passed=5)
    assert "FlagCov" not in result.stdout.str()
    assert not (project.path / ".flagcov").exists()


def test_ini_options(project):
    project.makeini("[pytest]\nflagcov_env = environment.json\n")
    result = project.runpytest_subprocess("--flagcov")
    result.stdout.fnmatch_lines(["*flag coverage (FlagCov)*"])


def test_xdist_workers_are_merged(project):
    pytest.importorskip("xdist")
    result = project.runpytest_subprocess("--flagcov", "--flagcov-env", "environment.json", "-n", "2", "-p", "no:cacheprovider")
    result.assert_outcomes(passed=5)
    result.stdout.fnmatch_lines(["*flag coverage (FlagCov)*"])
    evaluations = json.loads((project.path / ".flagcov" / "evaluations.json").read_text())
    assert {e["test"] for e in evaluations} >= {"test_shop.py::test_classic", "test_shop.py::test_dark"}
    assert not list((project.path / ".flagcov" / "workers").glob("*.json"))
