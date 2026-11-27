import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from flagcov.cli import main
from flagcov.environment import EnvironmentError_, load_document
from flagcov.recorder import Record, Recorder


@pytest.fixture
def fake_flagsmith(doc):
    """A local stand-in for a self-hosted Flagsmith API serving the environment document."""
    seen = {}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            seen["path"], seen["key"] = self.path, self.headers.get("X-Environment-Key")
            if self.headers.get("X-Environment-Key") != "ser.good":
                self.send_response(403)
                self.end_headers()
                return
            body = json.dumps(doc).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}/api/v1/", seen
    server.shutdown()


def test_fetch_from_api(fake_flagsmith):
    url, seen = fake_flagsmith
    doc = load_document(None, "ser.good", url)
    assert doc["name"] == "Production"
    assert seen == {"path": "/api/v1/environment-document/", "key": "ser.good"}


def test_fetch_bad_key(fake_flagsmith):
    url, _ = fake_flagsmith
    with pytest.raises(EnvironmentError_, match="HTTP 403"):
        load_document(None, "ser.bad", url)


def test_env_vars_are_used(fake_flagsmith, monkeypatch):
    url, _ = fake_flagsmith
    monkeypatch.setenv("FLAGSMITH_SERVER_KEY", "ser.good")
    monkeypatch.setenv("FLAGSMITH_API_URL", url)
    assert load_document()["name"] == "Production"


def test_missing_key_and_bad_files(tmp_path):
    with pytest.raises(EnvironmentError_, match="server-side environment key"):
        load_document(None, "", "http://127.0.0.1:9/api/v1/")
    with pytest.raises(EnvironmentError_, match="not found"):
        load_document(tmp_path / "nope.json")
    bad = tmp_path / "bad.json"
    bad.write_text('{"hello": 1}')
    with pytest.raises(EnvironmentError_, match="not a Flagsmith environment document"):
        load_document(bad)


def test_unreachable_api():
    with pytest.raises(EnvironmentError_, match="Could not reach"):
        load_document(None, "ser.x", "http://127.0.0.1:9/api/v1/")


def test_cli_fetch_then_report(fake_flagsmith, tmp_path, capsys):
    url, _ = fake_flagsmith
    env = tmp_path / "env.json"
    assert main(["fetch", "--api-url", url, "--key", "ser.good", "-o", str(env)]) == 0
    evals = tmp_path / "evaluations.json"
    rec = Recorder()
    rec.add(Record("checkout_flow", "classic", "string"))
    rec.dump(evals)
    capsys.readouterr()
    assert main(["report", "--env", str(env), "--evaluations", str(evals), "--format", "md"]) == 0
    assert "FlagCov" in capsys.readouterr().out
    assert main(["report", "--env", str(env), "--evaluations", str(evals), "--fail-untested", "50"]) == 2


@pytest.mark.parametrize("fmt", ["table", "json", "stubs"])
def test_cli_formats(demo_env_path, tmp_path, capsys, fmt):
    assert main(["report", "--env", str(demo_env_path), "--evaluations", str(tmp_path / "none.json"), "--format", fmt, "--out", str(tmp_path / "o")]) == 0
    out = capsys.readouterr().out
    if fmt == "json":
        assert json.loads(out)["records"] == 0
    assert (tmp_path / "o" / "badge.svg").is_file()


def test_cli_scan(tmp_path, capsys):
    (tmp_path / "a.py").write_text('c.get_boolean_value("x_flag", False)')
    assert main(["scan", str(tmp_path)]) == 0
    assert "x_flag" in capsys.readouterr().out
    assert main(["scan", str(tmp_path), "--json"]) == 0
    assert "x_flag" in json.loads(capsys.readouterr().out)


def test_cli_reports_errors(tmp_path, capsys):
    assert main(["report", "--env", str(tmp_path / "missing.json")]) == 1
    assert "not found" in capsys.readouterr().err


def test_recorder_roundtrip(tmp_path):
    rec = Recorder()
    rec.current_test = "t::x"
    rec.add(Record("f", 1.5, "float", traits={"plan": "pro"}))
    rec.dump(tmp_path / "r.json")
    loaded = Recorder.load(tmp_path / "r.json")
    assert loaded[0].flag == "f" and loaded[0].test == "t::x" and loaded[0].traits == {"plan": "pro"}
