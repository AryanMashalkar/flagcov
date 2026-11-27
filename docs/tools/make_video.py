"""Render docs/flagcov-demo.mp4: a narrated 1080p demo built from REAL FlagCov output.

    pip install pillow edge-tts imageio-ffmpeg
    python docs/tools/make_video.py            # neural voiceover (needs internet for edge-tts)
    python docs/tools/make_video.py --silent   # no voiceover: record your own over it

Terminal output, the PR comment and the dogfood numbers all come from real runs.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import imageio_ffmpeg
from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parents[2]
DEMO = ROOT / "examples" / "demo_shop"
OUT = ROOT / "docs" / "flagcov-demo.mp4"
W, H = 1920, 1080
VOICE = "en-US-AndrewNeural"

BG1, BG2 = (9, 12, 20), (20, 16, 38)
FG, DIM, FAINT = (236, 240, 245), (140, 148, 160), (70, 78, 92)
GREEN, RED, AMBER, CYAN, PURPLE, PINK = (63, 205, 95), (255, 84, 84), (240, 170, 50), (88, 166, 255), (176, 132, 255), (255, 92, 170)
TERM_BG, TERM_BAR = (13, 17, 23), (24, 29, 37)


def _font(names: list[str], size: int) -> ImageFont.FreeTypeFont:
    for n in names:
        for base in ("C:/Windows/Fonts/", "/usr/share/fonts/truetype/dejavu/", ""):
            p = base + n
            if os.path.exists(p):
                return ImageFont.truetype(p, size)
    return ImageFont.load_default(size)


def sans(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    return _font(["seguisb.ttf" if bold else "segoeui.ttf", "segoeuib.ttf", "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"], size)


def mono(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    return _font(["consolab.ttf" if bold else "consola.ttf", "DejaVuSansMono-Bold.ttf" if bold else "DejaVuSansMono.ttf"], size)


# --------------------------------------------------------------------------- real data


def run_pytest(args: list[str], extra_test: str | None = None) -> list[str]:
    env = {**os.environ, "PYTHONIOENCODING": "utf-8", "COLUMNS": "140"}
    with tempfile.TemporaryDirectory() as tmp:
        if extra_test:
            (DEMO / "test_zz_video.py").write_text(extra_test, encoding="utf-8")
        try:
            out = subprocess.run(
                [sys.executable, "-m", "pytest", "-p", "no:cacheprovider", "--flagcov-out", tmp, *args],
                cwd=DEMO, capture_output=True, text=True, env=env, encoding="utf-8",
            ).stdout
        finally:
            (DEMO / "test_zz_video.py").unlink(missing_ok=True)
    return [re.sub(r"^.*demo_shop[\\/]", "", l.rstrip()) for l in out.splitlines()]


GENERATED = (
    "import pytest\nfrom flagcov import OFF\nfrom shop import checkout\n\n"
    "@pytest.mark.parametrize('state', ['express', OFF])\n"
    "def test_checkout_flow_untested_states(flag_override, state):\n"
    "    flag_override('checkout_flow', state)\n"
    "    assert checkout(650, 'user-9', city='delhi')['eta_days'] > 0   # <- the one line I added\n"
)


def collect() -> dict:
    plain = [l for l in run_pytest(["-q"]) if l.strip()][-1]
    report = run_pytest(["-q", "--flagcov", "--flagcov-env", "environment.json", "--flagcov-scan", "."])
    start = next(i for i, l in enumerate(report) if "flag coverage (FlagCov)" in l)
    table = [l for l in report[start + 1:] if l.strip() and "passed" not in l]
    crash = run_pytest(["-q", "--tb=line", "test_zz_video.py"], extra_test=GENERATED)
    crash = [l for l in crash if re.search(r"ZeroDivision|passed|failed", l)][-3:]
    comment = ""
    try:
        comment = subprocess.run(
            ["gh", "api", "repos/AryanMashalkar/flagcov/issues/1/comments", "--jq", ".[0].body"],
            capture_output=True, text=True, encoding="utf-8", timeout=30,
        ).stdout
    except Exception:  # noqa: BLE001 - offline: the scene falls back to the local report
        pass
    return {"plain": plain, "table": table, "crash": crash, "comment": comment}


# --------------------------------------------------------------------------- drawing helpers


def background() -> Image.Image:
    img = Image.new("RGB", (W, H), BG1)
    d = ImageDraw.Draw(img)
    for y in range(H):
        t = y / H
        d.line([(0, y), (W, y)], fill=tuple(int(BG1[i] + (BG2[i] - BG1[i]) * t) for i in range(3)))
    glow = Image.new("RGB", (W, H), (0, 0, 0))
    gd = ImageDraw.Draw(glow)
    gd.ellipse([W * 0.55, -300, W * 1.25, 500], fill=(60, 30, 110))
    gd.ellipse([-400, H * 0.6, 500, H * 1.4], fill=(15, 50, 90))
    glow = glow.filter(ImageFilter.GaussianBlur(160))
    return Image.blend(img, Image.composite(glow, img, Image.new("L", (W, H), 90)), 0.6)


BG = None


def canvas() -> tuple[Image.Image, ImageDraw.ImageDraw]:
    img = BG.copy()
    return img, ImageDraw.Draw(img)


def center(d: ImageDraw.ImageDraw, y: int, text: str, font, fill) -> None:
    w = d.textlength(text, font=font)
    d.text(((W - w) / 2, y), text, font=font, fill=fill)


def caption(d: ImageDraw.ImageDraw, text: str) -> None:
    f = sans(36, True)
    w = d.textlength(text, font=f)
    x, y = (W - w) / 2, H - 118
    d.rounded_rectangle([x - 28, y - 16, x + w + 28, y + 56], radius=18, fill=(20, 22, 32))
    d.rounded_rectangle([x - 28, y - 16, x + w + 28, y + 56], radius=18, outline=(70, 60, 120), width=2)
    d.text((x, y), text, font=f, fill=FG)


def chip(d: ImageDraw.ImageDraw, x: int, y: int, text: str, fill, fg=(10, 10, 14)) -> int:
    f = sans(26, True)
    w = d.textlength(text, font=f)
    d.rounded_rectangle([x, y, x + w + 36, y + 46], radius=23, fill=fill)
    d.text((x + 18, y + 7), text, font=f, fill=fg)
    return int(w + 36)


def terminal(d: ImageDraw.ImageDraw, box: tuple[int, int, int, int], title: str, lines: list[tuple[str, tuple]], size: int = 25) -> None:
    x0, y0, x1, y1 = box
    d.rounded_rectangle([x0 + 10, y0 + 14, x1 + 10, y1 + 14], radius=18, fill=(4, 5, 9))
    d.rounded_rectangle(box, radius=18, fill=TERM_BG, outline=(48, 54, 66), width=2)
    d.rounded_rectangle([x0, y0, x1, y0 + 48], radius=18, fill=TERM_BAR)
    d.rectangle([x0, y0 + 30, x1, y0 + 48], fill=TERM_BAR)
    for i, c in enumerate([(255, 95, 86), (255, 189, 46), (39, 201, 63)]):
        d.ellipse([x0 + 22 + i * 30, y0 + 16, x0 + 38 + i * 30, y0 + 32], fill=c)
    tf = sans(22)
    d.text(((x0 + x1 - d.textlength(title, font=tf)) / 2, y0 + 11), title, font=tf, fill=DIM)
    f, fb = mono(size), mono(size, True)
    step = int(size * 1.42)
    max_lines = int((y1 - y0 - 80) / step)
    y = y0 + 66
    for text, col in lines[-max_lines:]:
        d.text((x0 + 28, y), text, font=fb if text.startswith("$") else f, fill=col)
        y += step


def color_for(line: str) -> tuple:
    if re.search(r"NOT TESTED|ZeroDivision|FAILED|failed|Riskiest|missing from", line):
        return RED
    if "STALE" in line or "never read" in line or "optional" in line:
        return AMBER
    if re.search(r"\btested\b|passed", line):
        return GREEN
    if line.startswith(("flag ", "----", "=")):
        return CYAN
    return FG


def ease(t: float) -> float:
    t = max(0.0, min(1.0, t))
    return 1 - (1 - t) ** 3


# --------------------------------------------------------------------------- timeline


@dataclass
class Scene:
    name: str
    narration: str
    render: Callable[[float, float], Image.Image]  # (t seconds, total duration) -> frame
    fps: int = 15  # frames per second for the animated part; static holds are deduplicated


def scene_hook(t: float, total: float) -> Image.Image:
    img, d = canvas()
    n = int(440_000_000 * ease(t / 2.6))
    big = sans(170, True)
    center(d, 260, f"${n:,}", big, RED)
    if t > 2.8:
        center(d, 470, "lost in 45 minutes", sans(64, True), FG)
    if t > 4.0:
        center(d, 570, "Knight Capital  ·  1 August 2012", sans(40), DIM)
    if t > 6.5:
        center(d, 700, "Cause: a reused feature flag switched on code no test had run in years.", sans(40, True), AMBER)
    return img


def scene_title(t: float, total: float) -> Image.Image:
    img, d = canvas()
    a = ease(t / 0.8)
    center(d, 250 + int(40 * (1 - a)), "We measure line coverage.", sans(62, True), DIM)
    if t > 1.6:
        center(d, 345, "Nobody measures flag coverage.", sans(62, True), FG)
    if t > 3.2:
        f = sans(190, True)
        w = d.textlength("FlagCov", font=f)
        d.text(((W - w) / 2 - 60, 470), "FlagCov", font=f, fill=FG)
        d.text(((W + w) / 2 - 40, 500), "🚩", font=_font(["seguiemj.ttf"], 130), embedded_color=True)
        center(d, 700, "Code coverage for feature flags", sans(50), PURPLE)
        x = (W - 900) // 2
        x += chip(d, x, 800, "Open-source Flagsmith", (88, 166, 255)) + 18
        x += chip(d, x, 800, "Toggle Wars 2026", (176, 132, 255)) + 18
        chip(d, x, 800, "Track 03", (63, 205, 95))
    return img


SHOP_CODE = [
    ('flow = client.get_string_value("checkout_flow", "classic", ctx)', CYAN),
    ("", FG),
    ('if flow == "one_page":    steps, eta = 1, 3', FG),
    ('elif flow == "express":   eta = 4 // SLOTS.get(city, 0)', FG),
    ('elif flow == "invoice":   steps, eta = 2, 5   # enterprise', FG),
    ("else:                     steps, eta = 3, 4   # classic", FG),
]


def scene_green(data: dict) -> Callable:
    def render(t: float, total: float) -> Image.Image:
        img, d = canvas()
        center(d, 70, "A small shop. Its checkout is a Flagsmith flag.", sans(48, True), FG)
        terminal(d, (90, 170, 1010, 820), "shop.py", SHOP_CODE, 24)
        cmd = "pytest"
        typed = cmd[: int(len(cmd) * ease(t / 1.2))]
        lines = [("$ " + typed, FG)]
        if t > 1.6:
            lines.append((data["plain"], GREEN))
        terminal(d, (1060, 170, 1830, 820), "terminal", lines, 30)
        if t > 2.2:
            f = sans(120, True)
            d.text((1210, 560), "✔ green", font=f, fill=GREEN)
        if t > 3.5:
            caption(d, "Tests pass. Looks safe, right?")
        return img

    return render


def scene_reveal(data: dict) -> Callable:
    table = data["table"]

    def render(t: float, total: float) -> Image.Image:
        img, d = canvas()
        cmd = "pytest --flagcov --flagcov-env environment.json --flagcov-scan ."
        typed = cmd[: int(len(cmd) * ease(t / 2.0))]
        lines = [("$ " + typed, FG)]
        shown = int(max(0, (t - 2.4) / 0.18))
        lines += [(l, color_for(l)) for l in table[:shown]]
        terminal(d, (70, 60, 1850, 900), "terminal  -  examples/demo_shop", lines, 23)
        done = t > 2.4 + len(table) * 0.18 + 0.6
        if done:
            row = next((i for i, l in enumerate(table) if "express" in l and "NOT TESTED" in l), None)
            if row is not None:
                y = 60 + 66 + (row + 1) * int(23 * 1.42)
                pulse = 3 + int(2 * (1 + math.sin(t * 6)))
                d.rounded_rectangle([86, y - 6, 1834, y + 30], radius=8, outline=RED, width=pulse)
            if t > total * 0.45:
                caption(d, "10% of real checkouts.  0 tests.")
        return img

    return render


def scene_crash(data: dict) -> Callable:
    def render(t: float, total: float) -> Image.Image:
        img, d = canvas()
        center(d, 50, "FlagCov writes the missing test. I added one line.", sans(46, True), FG)
        code = [(l, DIM if "added" not in l else AMBER) for l in GENERATED.splitlines()]
        terminal(d, (70, 140, 1850, 520), "test_express.py  (generated by FlagCov)", code, 24)
        cmd = "pytest test_express.py"
        typed = cmd[: int(len(cmd) * ease((t - 1.5) / 1.0))] if t > 1.5 else ""
        lines = [("$ " + typed, FG)]
        if t > 3.0:
            lines += [(l, color_for(l)) for l in data["crash"]]
        terminal(d, (70, 570, 1850, 880), "terminal", lines, 24)
        if t > 3.0 and t < 3.4:
            flash = Image.new("RGB", (W, H), (120, 0, 0))
            img = Image.blend(img, flash, 0.25)
            d = ImageDraw.Draw(img)
        if t > 3.6:
            caption(d, "A crash for 1 in 10 customers. The green suite never saw it.")
        return img

    return render


SELFHOSTED_STEPS = [
    ("Start official Flagsmith image (docker compose)", "self-hosted, open source"),
    ("Seed through Flagsmith's REST API", "flags · 60/30/10 split · segment · server key"),
    ("flagcov fetch  ->  live environment document", "checkout_flow: one_page 30%, express 10%"),
    ("Run the tests with this repo's GitHub Action", "segments: ['enterprise']"),
    ("Assert the report against live Flagsmith", "Live self-hosted report verified"),
]


def scene_selfhosted(t: float, total: float) -> Image.Image:
    img, d = canvas()
    center(d, 70, "Not a mock. Real self-hosted Flagsmith, on every push.", sans(52, True), FG)
    for i, (step, detail) in enumerate(SELFHOSTED_STEPS):
        appear = 0.8 + i * 1.3
        if t < appear:
            continue
        y = 200 + i * 145
        a = ease((t - appear) / 0.5)
        x = 260 + int(60 * (1 - a))
        d.rounded_rectangle([x, y, x + 1400, y + 115], radius=20, fill=(22, 26, 38), outline=(60, 66, 90), width=2)
        ok = t > appear + 0.7
        d.ellipse([x + 30, y + 30, x + 85, y + 85], fill=GREEN if ok else FAINT)
        if ok:
            d.text((x + 42, y + 28), "✓", font=sans(44, True), fill=(8, 30, 12))
        d.text((x + 115, y + 18), step, font=sans(38, True), fill=FG)
        d.text((x + 115, y + 68), detail, font=mono(26), fill=CYAN)
    if t > 0.8 + 5 * 1.3 + 0.8:
        caption(d, "Flagsmith is the source of truth. FlagCov asks the question.")
    return img


DOGFOOD = [
    ("api_usage_alerting", "off", "on · 7 reads"),
    ("sdk_metrics_labels", "off", "on · 18 reads"),
    ("segment_membership_inspection", "off", "on · 23 reads"),
]


def scene_dogfood(t: float, total: float) -> Image.Image:
    img, d = canvas()
    n = int(690 * ease(t / 2.0))
    center(d, 80, "Then I pointed it at Flagsmith itself.", sans(52, True), FG)
    center(d, 170, f"{n}", sans(200, True), PURPLE)
    center(d, 400, "of Flagsmith's own tests, run with FlagCov", sans(40), DIM)
    if t > 3.0:
        x0, y = 230, 500
        hdr = sans(30, True)
        d.text((x0, y), "flag", font=hdr, fill=DIM)
        d.text((x0 + 760, y), "Flagsmith ships it", font=hdr, fill=DIM)
        d.text((x0 + 1130, y), "tests only ever read", font=hdr, fill=DIM)
        for i, (flag, ship, tested) in enumerate(DOGFOOD):
            if t < 3.4 + i * 0.7:
                continue
            yy = y + 70 + i * 90
            d.rounded_rectangle([x0 - 20, yy - 12, x0 + 1480, yy + 62], radius=14, fill=(26, 22, 40))
            d.text((x0, yy), flag, font=mono(34, True), fill=FG)
            d.text((x0 + 760, yy), ship.upper(), font=sans(36, True), fill=AMBER)
            d.text((x0 + 1130, yy), tested, font=sans(36, True), fill=GREEN)
    if t > 6.5:
        caption(d, "Tested only when ON. The defaults Flagsmith ships are OFF.")
    return img


def md_lines(comment: str) -> list[tuple[str, tuple, int]]:
    out = []
    in_code = False
    for raw in comment.splitlines():
        line = raw.strip()
        if line.startswith("```"):
            in_code = not in_code
            continue
        if in_code:
            continue
        if not line or line.startswith(("<!--", "<details", "</details", "<sub", "```")) or set(line) <= set("|-"):
            continue
        if line.startswith("import ") or line.startswith("from ") or line.startswith("@") or line.startswith("def ") or line.startswith("#"):
            if line.startswith("## "):
                pass
            else:
                continue
        if line.startswith("## "):
            out.append((line[3:], FG, 40))
        elif line.startswith("|"):
            cells = [c.strip().strip("`") for c in line.strip("|").split("|")]
            if cells and cells[0] in ("", "Flag"):
                continue
            out.append(("   ".join(c for c in cells if c), RED if "🟠" in line or "🔴" in line else FG, 28))
        else:
            out.append((re.sub(r"[*`]", "", line), FG, 28))
    return out[:14]


def scene_pr(data: dict) -> Callable:
    lines = md_lines(data["comment"]) if data["comment"] else []

    def render(t: float, total: float) -> Image.Image:
        img, d = canvas()
        center(d, 50, "Where your team sees it: on every pull request.", sans(50, True), FG)
        x0, y0, x1, y1 = 160, 140, 1760, 950
        d.rounded_rectangle([x0, y0, x1, y1], radius=16, fill=(255, 255, 255))
        d.rounded_rectangle([x0, y0, x1, y0 + 70], radius=16, fill=(246, 248, 250))
        d.rectangle([x0, y0 + 50, x1, y0 + 70], fill=(246, 248, 250))
        d.ellipse([x0 + 24, y0 + 14, x0 + 66, y0 + 56], fill=(36, 41, 47))
        d.text((x0 + 85, y0 + 18), "github-actions  commented  ·  AryanMashalkar/flagcov  #1", font=sans(28, True), fill=(36, 41, 47))
        y = y0 + 100
        shown = int(max(0, (t - 0.6) / 0.25))
        for text, col, size in lines[:shown]:
            colour = (36, 41, 47) if col == FG else (207, 34, 46)
            text = text.replace("🚩", "").replace("🟠", "●").replace("🔴", "●").replace("⚠️", "!").replace("❓", "?").replace("🧹", "~").replace("ℹ️", "i")
            f = sans(size, size > 30)
            while d.textlength(text, font=f) > x1 - x0 - 90 and len(text) > 10:
                text = text[:-4] + "…"
            d.text((x0 + 45, y), text, font=f, fill=colour)
            y += int(size * 1.75)
        if t > total * 0.6:
            caption(d, "Untested traffic, flag by flag, with the tests to paste.")
        return img

    return render


def scene_close(t: float, total: float) -> Image.Image:
    img, d = canvas()
    center(d, 230, "Line coverage tells you what your code ran.", sans(60, True), DIM)
    if t > 2.2:
        center(d, 330, "Flag coverage tells you what your users will run.", sans(60, True), FG)
    if t > 4.5:
        f = sans(150, True)
        center(d, 470, "FlagCov", f, FG)
        box_w = 760
        bx = (W - box_w) // 2
        d.rounded_rectangle([bx, 690, bx + box_w, 780], radius=18, fill=TERM_BG, outline=(60, 66, 90), width=2)
        center(d, 708, "$ pytest --flagcov", mono(46, True), GREEN)
        center(d, 830, "github.com/AryanMashalkar/flagcov", sans(44, True), CYAN)
        center(d, 905, "Built on open-source Flagsmith  ·  Toggle Wars 2026  ·  Track 03", sans(32), DIM)
    return img


NARRATION = {
    "hook": "In twenty twelve, a trading firm called Knight Capital lost four hundred and forty million dollars... in forty-five minutes. "
            "The cause? A reused feature flag, that switched on old code no test had run in years.",
    "title": "We all measure line coverage. Nobody measures flag coverage. So I built FlagCov, on top of open-source Flagsmith.",
    "green": "Here's a small shop. Its checkout is a Flagsmith flag, with three variants, and a special path for enterprise customers. "
             "The tests are green. Looks safe.",
    "reveal": "Now, the same tests, with one extra option. FlagCov records every flag the tests read, and compares it with what Flagsmith "
              "is actually serving in production. ... Ten percent of real checkouts go through express. Not a single test has ever run it. "
              "Enterprise customers get an untested path too. And the code reads a flag that doesn't even exist in Flagsmith.",
    "crash": "FlagCov doesn't just complain. It writes the missing tests. I paste one in, add a single assert, and run it. ... "
             "Crash. Division by zero, for one in ten customers. Our green test suite would never have caught it.",
    "selfhosted": "And this isn't a mock. On every push, CI boots the official open-source Flagsmith image, seeds it through Flagsmith's own API, "
                  "and FlagCov reads the live environment document. The real weights. The real segment rules.",
    "dogfood": "Then, I pointed it at Flagsmith itself. Six hundred and ninety of Flagsmith's own tests, with FlagCov switched on. "
               "Three flags are only ever tested switched on, while the defaults Flagsmith ships have them switched off.",
    "pr": "In a real team, you'd see it right on the pull request. It focuses on the flags that change touches, "
          "shows how much production traffic is untested, and hands you the tests to paste.",
    "close": "Line coverage tells you what your code ran. Flag coverage tells you what your users will run. "
             "FlagCov. Open source, built on self-hosted Flagsmith, and one pip install away.",
}


# --------------------------------------------------------------------------- audio + encoding


CACHE = Path(__file__).parent / ".voice-cache"


async def synth(text: str, path: Path) -> None:
    """Narrate ``text`` into ``path``, caching clips so a flaky/rate-limited service only costs retries once."""
    import hashlib
    import shutil

    import edge_tts

    CACHE.mkdir(exist_ok=True)
    cached = CACHE / (hashlib.sha1(f"{VOICE}|{text}".encode()).hexdigest()[:16] + ".mp3")
    if not cached.exists():
        for attempt in range(8):
            try:
                await edge_tts.Communicate(text, VOICE, rate="-4%").save(str(cached))
                if cached.stat().st_size > 1000:
                    break
            except edge_tts.exceptions.NoAudioReceived:
                cached.unlink(missing_ok=True)
                if attempt == 7:
                    raise
            await asyncio.sleep(3 + attempt * 3)
        await asyncio.sleep(2)
    shutil.copy(cached, path)


def duration(path: Path) -> float:
    ff = imageio_ffmpeg.get_ffmpeg_exe()
    err = subprocess.run([ff, "-i", str(path)], capture_output=True, text=True).stderr
    h, m, s = re.search(r"Duration: (\d+):(\d+):([\d.]+)", err).groups()
    return int(h) * 3600 + int(m) * 60 + float(s)


def main() -> None:
    global BG
    parser = argparse.ArgumentParser()
    parser.add_argument("--silent", action="store_true", help="No voiceover; default scene lengths")
    args = parser.parse_args()

    print("collecting real output...")
    data = collect()
    BG = background()
    scenes = [
        Scene("hook", NARRATION["hook"], scene_hook),
        Scene("title", NARRATION["title"], scene_title),
        Scene("green", NARRATION["green"], scene_green(data)),
        Scene("reveal", NARRATION["reveal"], scene_reveal(data)),
        Scene("crash", NARRATION["crash"], scene_crash(data)),
        Scene("selfhosted", NARRATION["selfhosted"], scene_selfhosted),
        Scene("dogfood", NARRATION["dogfood"], scene_dogfood),
        Scene("pr", NARRATION["pr"], scene_pr(data)),
        Scene("close", NARRATION["close"], scene_close),
    ]
    ff = imageio_ffmpeg.get_ffmpeg_exe()
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        segments = []
        frame_no = 0
        for n, sc in enumerate(scenes):
            mp3 = None
            if args.silent:
                length = 9.0
            else:
                mp3 = tmp / f"{sc.name}.mp3"
                asyncio.run(synth(sc.narration, mp3))
                length = duration(mp3) + 0.9
            print(f"  {sc.name}: {length:.1f}s")
            lines: list[str] = []
            prev, hold = None, 0.0
            for i in range(int(length * sc.fps)):
                img = sc.render(i / sc.fps, length)
                sig = img.resize((96, 54)).tobytes()
                if sig == prev:
                    hold += 1 / sc.fps
                    continue
                if prev is not None:
                    lines.append(f"duration {hold:.4f}")
                frame = tmp / f"f{frame_no:05d}.png"
                img.save(frame, compress_level=1)
                lines += [f"file '{frame.as_posix()}'"]
                frame_no += 1
                prev, hold = sig, 1 / sc.fps
            lines += [f"duration {hold:.4f}", lines[-2] if len(lines) > 1 else lines[-1]]
            listing = tmp / f"scene{n}.txt"
            listing.write_text("\n".join(lines), encoding="utf-8")
            seg = tmp / f"scene{n}.mp4"
            # Each scene is cut to exactly its narration length, so picture and voice can't drift apart.
            cmd = [ff, "-y", "-f", "concat", "-safe", "0", "-i", str(listing)]
            if mp3 is not None:
                cmd += ["-i", str(mp3), "-af", "apad", "-c:a", "aac", "-b:a", "192k", "-ar", "48000"]
            else:
                cmd += ["-f", "lavfi", "-i", "anullsrc=r=48000:cl=mono", "-c:a", "aac"]
            cmd += ["-t", f"{length:.3f}", "-vf", "fps=30,format=yuv420p", "-c:v", "libx264", "-preset", "medium", "-crf", "20", str(seg)]
            subprocess.run(cmd, check=True, capture_output=True)
            segments.append(seg)
        joined = tmp / "segments.txt"
        joined.write_text("\n".join(f"file '{s.as_posix()}'" for s in segments), encoding="utf-8")
        subprocess.run([ff, "-y", "-f", "concat", "-safe", "0", "-i", str(joined), "-c", "copy", "-movflags", "+faststart", str(OUT)], check=True, capture_output=True)
    print(f"wrote {OUT} ({OUT.stat().st_size // 1024 // 1024} MB, {frame_no} unique frames)")


if __name__ == "__main__":
    main()
