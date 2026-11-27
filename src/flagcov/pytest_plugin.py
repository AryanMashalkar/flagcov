"""pytest plugin: ``pytest --flagcov --flagcov-env environment.json``."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from flagcov.analyze import analyze
from flagcov.environment import EnvironmentError_, load_document
from flagcov.override import OFF, FlagOverrides
from flagcov.recorder import install_openfeature_hook, instrument_flagsmith_sdk, recorder


def pytest_addoption(parser: pytest.Parser) -> None:
    group = parser.getgroup("flagcov", "feature flag coverage (FlagCov)")
    group.addoption("--flagcov", action="store_true", default=False, help="Record flag evaluations and report flag coverage.")
    group.addoption("--flagcov-env", default=None, help="Environment document: a JSON file, or a Flagsmith API URL (self-hosted or cloud).")
    group.addoption("--flagcov-key", default=None, help="Server-side environment key used to fetch the document (or FLAGSMITH_SERVER_KEY).")
    group.addoption("--flagcov-api-url", default=None, help="Flagsmith API URL, e.g. http://localhost:8000/api/v1/ (or FLAGSMITH_API_URL).")
    group.addoption("--flagcov-out", default=".flagcov", help="Directory for report.json, report.md, badge.svg, stubs.py (default: .flagcov).")
    group.addoption("--flagcov-scan", action="append", default=None, help="Source path to scan for flag keys (repeatable). Finds flags missing from Flagsmith and flags never read.")
    group.addoption("--flagcov-fail-untested", type=float, default=None, help="Fail if any flag sends more than this percent of its production traffic to untested code.")
    group.addoption("--flagcov-fail-under", type=float, default=None, help="Fail if flag state coverage is below this percent.")
    parser.addini("flagcov_env", "Default environment document for --flagcov", default=None)
    parser.addini("flagcov_scan", "Default source paths to scan for flag keys", type="paths", default=[])


def pytest_configure(config: pytest.Config) -> None:
    if config.getoption("flagcov"):
        config.pluginmanager.register(FlagCovSession(config), "flagcov-session")


class FlagCovSession:
    def __init__(self, config: pytest.Config) -> None:
        self.config = config
        self.report = None
        self.error: str | None = None
        recorder.clear()
        if getattr(config, "workerinput", None) is None:  # controller / normal run: drop stale worker files
            out = Path(config.getoption("flagcov_out"))
            if not out.is_absolute():
                out = Path(config.invocation_params.dir) / out
            for stale in (out / "workers").glob("evaluations-*.json"):
                stale.unlink()
        self.openfeature = install_openfeature_hook()
        self.flagsmith = instrument_flagsmith_sdk()

    @pytest.hookimpl(tryfirst=True)
    def pytest_runtest_setup(self, item: pytest.Item) -> None:
        recorder.current_test = item.nodeid

    def pytest_runtest_teardown(self) -> None:
        recorder.current_test = None

    def pytest_sessionfinish(self, session: pytest.Session, exitstatus: int) -> None:
        opt = self.config.getoption
        out = Path(opt("flagcov_out"))
        if not out.is_absolute():
            out = Path(self.config.invocation_params.dir) / out

        # pytest-xdist: each worker saves its own evaluations; the controller merges them.
        worker = getattr(self.config, "workerinput", None)
        if worker is not None:
            recorder.dump(out / "workers" / f"evaluations-{worker.get('workerid', 'gw')}.json")
            return
        workers_dir = out / "workers"
        if workers_dir.is_dir():
            for part in sorted(workers_dir.glob("evaluations-*.json")):
                for record in recorder.load(part):
                    recorder.add(record)
                part.unlink()
        recorder.dump(out / "evaluations.json")

        source = opt("flagcov_env") or self.config.getini("flagcov_env") or None
        try:
            doc = load_document(source, opt("flagcov_key"), opt("flagcov_api_url"))
        except EnvironmentError_ as exc:
            self.error = str(exc)
            return

        referenced = None
        scan_paths = opt("flagcov_scan") or [str(p) for p in self.config.getini("flagcov_scan")]
        if scan_paths:
            from flagcov.scan import scan_paths as do_scan

            referenced = do_scan(scan_paths)

        self.report = analyze(doc, recorder.records, referenced)
        from flagcov import report as render

        render.write_all(self.report, out)

        failed = []
        if opt("flagcov_fail_untested") is not None and self.report.untested_traffic > opt("flagcov_fail_untested"):
            failed.append(f"untested production traffic {self.report.untested_traffic:.1f}% > {opt('flagcov_fail_untested')}%")
        if opt("flagcov_fail_under") is not None and self.report.state_coverage < opt("flagcov_fail_under"):
            failed.append(f"flag state coverage {self.report.state_coverage:.1f}% < {opt('flagcov_fail_under')}%")
        self.failures = failed
        if failed and session.exitstatus == 0:
            session.exitstatus = pytest.ExitCode.TESTS_FAILED

    def pytest_terminal_summary(self, terminalreporter: Any) -> None:
        from flagcov import report as render

        if getattr(self.config, "workerinput", None) is not None:
            return
        tr = terminalreporter
        tr.section("flag coverage (FlagCov)")
        if not self.openfeature and not self.flagsmith:
            tr.write_line("Neither openfeature-sdk nor flagsmith is installed: nothing was recorded.", yellow=True)
        if self.error:
            tr.write_line(f"Could not load the environment document: {self.error}", red=True)
            tr.write_line(f"{len(recorder.records)} evaluations were still saved to {self.config.getoption('flagcov_out')}/evaluations.json")
            return
        if self.report is None:
            return
        for line in render.terminal(self.report).splitlines():
            tr.write_line(line)
        for failure in getattr(self, "failures", []):
            tr.write_line(f"FAIL: {failure}", red=True, bold=True)


@pytest.fixture
def flag_override():
    """Force flags for one test: ``flag_override("checkout_flow", "one_page")``.

    Pass ``flagcov.OFF`` to simulate the flag being switched off.
    """
    overrides = FlagOverrides()
    yield overrides.set
    overrides.restore()


__all__ = ["OFF", "flag_override"]
