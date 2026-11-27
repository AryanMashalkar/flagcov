"""Screenshot the REAL public GitHub pages that prove FlagCov works, for the demo video.

    pip install playwright && python -m playwright install chromium
    python docs/tools/capture_proof.py

Writes docs/proof/*.png: the live PR comment, the self-hosted Flagsmith CI run, and the
dogfood run on Flagsmith's own tests. Nothing is mocked: these are github.com pages.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "docs" / "proof"
REPO = "AryanMashalkar/flagcov"


def latest_run(workflow: str) -> int:
    out = subprocess.run(
        ["gh", "run", "list", "-R", REPO, "--workflow", workflow, "--status", "success", "--limit", "1", "--json", "databaseId"],
        capture_output=True, text=True, check=True,
    ).stdout
    return json.loads(out)[0]["databaseId"]


def shoot_summary(page, name: str) -> None:
    """Screenshot the job summary block FlagCov wrote (GitHub renders it as markdown)."""
    page.mouse.wheel(0, 4000)
    page.wait_for_timeout(1500)
    block = page.locator(".markdown-body").filter(has_text="FlagCov").first
    try:
        block.wait_for(timeout=15000)
        block.scroll_into_view_if_needed()
        block.screenshot(path=str(OUT / f"{name}.png"))
    except Exception as exc:  # noqa: BLE001
        print(f"no job summary found for {name}: {exc.__class__.__name__}")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    e2e, dogfood = latest_run("selfhosted-e2e.yml"), latest_run("dogfood-flagsmith.yml")
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1500, "height": 860}, device_scale_factor=1.25, color_scheme="dark")

        # 1. The FlagCov comment on PR #1
        page.goto(f"https://github.com/{REPO}/pull/1", wait_until="networkidle")
        comment = page.locator(".timeline-comment, .js-comment-container").filter(has_text="FlagCov: feature flag coverage").first
        comment.scroll_into_view_if_needed()
        comment.screenshot(path=str(OUT / "pr-comment.png"))

        # 2. Self-hosted Flagsmith end-to-end run: green job + the job summary FlagCov wrote
        page.goto(f"https://github.com/{REPO}/actions/runs/{e2e}", wait_until="networkidle")
        page.screenshot(path=str(OUT / "selfhosted-run.png"))
        shoot_summary(page, "selfhosted-summary")

        # 3. Dogfood run on Flagsmith's own tests: the report in the job summary
        page.goto(f"https://github.com/{REPO}/actions/runs/{dogfood}", wait_until="networkidle")
        page.screenshot(path=str(OUT / "dogfood-run.png"))
        shoot_summary(page, "dogfood-summary")
        browser.close()
    for f in sorted(OUT.glob("*.png")):
        print(f.name)


if __name__ == "__main__":
    main()
