import json
import xml.dom.minidom

from flagcov import report as render
from flagcov.analyze import analyze
from flagcov.recorder import Record


def demo_report(doc, scan=True):
    records = [
        Record("checkout_flow", "classic", "string"),
        Record("checkout_flow", "one_page", "string"),
        Record("dark_mode", True, "boolean"),
        Record("new_search", False, "boolean"),
        Record("free_shipping_threshold", 499, "integer"),
    ]
    refs = {k: ["shop.py:1"] for k in ("checkout_flow", "dark_mode", "new_search", "free_shipping_threshold", "recommendation_v2")}
    return analyze(doc, records, refs if scan else None)


def test_terminal_lists_untested_and_headline(doc):
    text = render.terminal(demo_report(doc))
    assert "express" in text and "NOT TESTED" in text
    assert "STALE (no code reads it)" in text
    assert "Riskiest flag: checkout_flow (10%" in text
    assert "missing from Flagsmith: recommendation_v2" in text
    assert text.isascii()  # safe for Windows consoles and CI logs


def test_terminal_untested_only(doc):
    text = render.terminal(demo_report(doc), show_covered=False)
    assert "one_page" not in text


def test_markdown_pr_comment(doc):
    md = render.markdown(demo_report(doc))
    assert md.startswith("## 🚩 FlagCov")
    assert "| 🟠 | `checkout_flow` | `express` | 10% of prod traffic |" in md
    assert 'segment "enterprise" (plan == enterprise)' in md
    assert "Kill switch never tested" in md and "`legacy_promo_banner`" not in md.split("Kill switch")[1].split("\n")[0]
    assert "`recommendation_v2` (shop.py:1)" in md
    assert "```python" in md


def test_markdown_can_focus_on_changed_flags(doc):
    md = render.markdown(demo_report(doc), changed_flags={"dark_mode"})
    assert "`express`" not in md


def test_markdown_all_green(doc):
    records = [
        Record("checkout_flow", v, "string") for v in ("classic", "one_page", "express", "invoice")
    ] + [Record("dark_mode", True, "boolean"), Record("new_search", False, "boolean"),
         Record("free_shipping_threshold", 499, "integer"), Record("legacy_promo_banner", True, "boolean")]
    md = render.markdown(analyze(doc, records))
    assert "Every flag state production can serve was exercised" in md


def test_badge_is_valid_svg(doc):
    svg = render.badge(demo_report(doc))
    xml.dom.minidom.parseString(svg)
    assert "flag coverage" in svg and "%" in svg


def test_stubs_compile_and_cover_untested(doc):
    code = render.stubs(demo_report(doc))
    compile(code, "stubs.py", "exec")
    assert "flag_override('checkout_flow', state)" in code
    assert "'express'" in code and "OFF" in code
    assert "legacy_promo_banner" not in code  # stale flags get no tests


def test_stubs_nothing_to_do():
    empty = analyze({"feature_states": [], "project": {"segments": []}}, [])
    assert "Nothing to generate" in render.stubs(empty)


def test_write_all(tmp_path, doc):
    files = render.write_all(demo_report(doc), tmp_path / "out")
    assert all(p.is_file() for p in files.values())
    assert json.loads(files["json"].read_text())["unknown_flags"] == {"recommendation_v2": ["shop.py:1"]}
