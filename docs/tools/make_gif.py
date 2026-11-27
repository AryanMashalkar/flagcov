"""Render docs/demo.gif from REAL FlagCov runs on the demo shop (no mock-ups).

    pip install pillow
    python docs/tools/make_gif.py

Every line in the GIF is captured from an actual command run in examples/demo_shop.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[2]
DEMO = ROOT / "examples" / "demo_shop"
OUT = ROOT / "docs" / "demo.gif"

W, H = 1180, 620
PAD, LINE = 22, 23
BG, FG, DIM = (13, 17, 23), (230, 237, 243), (125, 133, 144)
GREEN, RED, AMBER, CYAN, PURPLE = (63, 185, 80), (248, 81, 73), (210, 153, 34), (88, 166, 255), (188, 140, 255)


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    candidates = (
        ["C:/Windows/Fonts/consolab.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf"]
        if bold
        else ["C:/Windows/Fonts/consola.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf", "/System/Library/Fonts/Menlo.ttc"]
    )
    for c in candidates:
        if os.path.exists(c):
            return ImageFont.truetype(c, size)
    return ImageFont.load_default()


MONO, BOLD, CAPTION = font(16), font(16, True), font(19, True)


def run(args: list[str], extra_test: str | None = None) -> list[str]:
    env = {**os.environ, "PYTHONIOENCODING": "utf-8", "COLUMNS": "120"}
    with tempfile.TemporaryDirectory() as tmp:
        if extra_test:
            (DEMO / "test_zz_flagcov_generated.py").write_text(extra_test, encoding="utf-8")
        try:
            out = subprocess.run(
                [sys.executable, "-m", "pytest", "-p", "no:cacheprovider", "--flagcov-out", tmp, *args],
                cwd=DEMO, capture_output=True, text=True, env=env, encoding="utf-8",
            ).stdout
        finally:
            (DEMO / "test_zz_flagcov_generated.py").unlink(missing_ok=True)
    return [l.rstrip() for l in out.splitlines()]


def color_for(line: str) -> tuple[int, int, int]:
    if re.search(r"NOT TESTED|ZeroDivisionError|FAILED|failed|Riskiest|missing from", line):
        return RED
    if "STALE" in line or "never read" in line or "optional" in line:
        return AMBER
    if re.search(r"\btested\b|passed", line):
        return GREEN
    if line.startswith(("=", "flag ", "----")) or "FlagCov" in line:
        return CYAN
    return FG


def frame(lines: list[tuple[str, tuple[int, int, int]]], caption: str) -> Image.Image:
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([0, 0, W - 1, 34], radius=0, fill=(22, 27, 34))
    for i, c in enumerate([(255, 95, 86), (255, 189, 46), (39, 201, 63)]):
        d.ellipse([16 + i * 22, 11, 28 + i * 22, 23], fill=c)
    d.text((W // 2 - 120, 9), "flagcov  -  demo shop", font=MONO, fill=DIM)
    visible = lines[-int((H - 34 - 70) / LINE):]
    y = 34 + PAD
    for text, col in visible:
        d.text((PAD, y), text, font=BOLD if text.startswith("$") else MONO, fill=col)
        y += LINE
    d.rectangle([0, H - 56, W, H], fill=(22, 27, 34))
    d.text((PAD, H - 43), caption, font=CAPTION, fill=PURPLE)
    return img


def main() -> None:
    plain = [l for l in run(["-q"]) if l.strip()][-1:]
    report = run(["-q", "--flagcov", "--flagcov-env", "environment.json", "--flagcov-scan", "."])
    start = next(i for i, l in enumerate(report) if "flag coverage (FlagCov)" in l)
    table = [l for l in report[start:] if l.strip()]
    generated = (
        "import pytest\nfrom flagcov import OFF\nfrom shop import checkout\n\n"
        "@pytest.mark.parametrize('state', ['express', OFF])\n"
        "def test_checkout_flow_untested_states(flag_override, state):\n"
        "    flag_override('checkout_flow', state)\n"
        "    assert checkout(cart_total=650, user_id='user-9', city='delhi')['eta_days'] > 0\n"
    )
    crash = run(["-q", "--tb=line", "test_zz_flagcov_generated.py"], extra_test=generated)
    crash = [re.sub(r"^.*demo_shop[\\/]", "", l) for l in crash if re.search(r"ZeroDivision|passed|failed", l)][-3:]

    frames: list[Image.Image] = []
    durations: list[int] = []
    shown: list[tuple[str, tuple[int, int, int]]] = []

    def add(caption: str, ms: int) -> None:
        frames.append(frame(list(shown), caption))
        durations.append(ms)

    def type_cmd(cmd: str, caption: str) -> None:
        shown.append(("$ ", FG))
        for i in range(0, len(cmd) + 1, 4):
            shown[-1] = ("$ " + cmd[:i], FG)
            add(caption, 45)
        shown[-1] = ("$ " + cmd, FG)
        add(caption, 400)

    c1 = "Your test suite is green..."
    type_cmd("pytest", c1)
    for l in plain:
        shown.append((l, GREEN))
    add(c1, 1600)

    c2 = "...but Flagsmith sends 10% of checkouts down a path no test has ever run."
    shown.append(("", FG))
    type_cmd("pytest --flagcov --flagcov-env environment.json --flagcov-scan .", c2)
    for l in table:
        shown.append((l, color_for(l)))
        add(c2, 110)
    add(c2, 4200)

    c3 = "FlagCov writes the missing test. Add one assert and it finds a crash."
    shown.clear()
    type_cmd("pytest test_express.py   # FlagCov's generated test + one assert", c3)
    for l in generated.splitlines():
        shown.append(("    " + l, DIM))
    add(c3, 1500)
    for l in crash:
        shown.append((l, color_for(l)))
        add(c3, 500)
    add(c3, 4500)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    frames[0].save(OUT, save_all=True, append_images=frames[1:], duration=durations, loop=0, optimize=True)
    print(f"wrote {OUT} ({len(frames)} frames, {OUT.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
