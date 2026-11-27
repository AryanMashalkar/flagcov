import pytest

from flagcov.scan import scan_paths, scan_text


@pytest.mark.parametrize(
    "code, key",
    [
        ('client.get_boolean_value("dark_mode", False)', "dark_mode"),
        ("client.get_string_value('checkout_flow', 'classic', ctx)", "checkout_flow"),
        ('client.get_integer_details("limit", 5)', "limit"),
        ('client.getBooleanValue("js_flag", false)', "js_flag"),
        ("await client.getStringValue(`tpl_flag`, 'x')", "tpl_flag"),
        ('flags.is_feature_enabled("py_sdk")', "py_sdk"),
        ('flags.get_feature_value("remote_cfg")', "remote_cfg"),
        ('flagsmith.hasFeature("js_sdk")', "js_sdk"),
        ('flagsmith.getValue("js_value")', "js_value"),
        ('client.GetBooleanValue(ctx, "go_flag", false, evalCtx)', None),  # Go passes ctx first: not matched
    ],
)
def test_patterns(code, key):
    found = [k for k, _ in scan_text(code)]
    assert found == ([key] if key else [])


def test_react_use_flags_list():
    found = [k for k, _ in scan_text('const flags = useFlags(["banner", \'search_v2\'], ["trait"])')]
    assert found == ["banner", "search_v2"]


def test_line_numbers():
    assert scan_text('a = 1\n\nx = c.get_boolean_value("f", False)') == [("f", 3)]


def test_scan_paths_walks_and_skips(tmp_path):
    (tmp_path / "app.py").write_text('c.get_boolean_value("one", False)\nc.get_boolean_value("one", False)')
    (tmp_path / "web").mkdir()
    (tmp_path / "web" / "a.ts").write_text('client.getStringValue("two", "x")')
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "lib.js").write_text('client.getStringValue("vendored", "x")')
    (tmp_path / "notes.txt").write_text('get_boolean_value("txt", False)')
    refs = scan_paths([tmp_path])
    assert set(refs) == {"one", "two"}
    assert len(refs["one"]) == 2 and refs["one"][0].endswith("app.py:1")


def test_scan_single_file(tmp_path):
    f = tmp_path / "x.py"
    f.write_text('c.get_string_value("solo", "")')
    assert list(scan_paths([f])) == ["solo"]


def test_comments_and_docstrings_are_ignored():
    code = '''"""
Usage:
    client.get_boolean_value("doc_flag", False)
"""
# client.get_boolean_value("commented_flag", False)
    // client.getBooleanValue("js_comment", false)
real = client.get_boolean_value("real_flag", False)
'''
    assert scan_text(code, python=True) == [("real_flag", 7)]


def test_changed_flags_from_git(tmp_path):
    import subprocess

    from flagcov.scan import changed_flags

    def git(*a):
        subprocess.run(["git", *a], cwd=tmp_path, check=True, capture_output=True)

    git("init", "-q", "-b", "main")
    git("config", "user.email", "t@example.com")
    git("config", "user.name", "t")
    (tmp_path / "shop.py").write_text('flow = c.get_string_value("checkout_flow", "x")\nSLOTS = 1\n')
    (tmp_path / "other.py").write_text('c.get_boolean_value("dark_mode", False)\n')
    git("add", ".")
    git("commit", "-qm", "base")
    git("checkout", "-qb", "feature")
    (tmp_path / "shop.py").write_text('flow = c.get_string_value("checkout_flow", "x")\nSLOTS = 2\n')
    git("commit", "-qam", "change")
    assert changed_flags("main", cwd=tmp_path) == {"checkout_flow"}
