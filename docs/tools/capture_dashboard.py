"""Screenshot the REAL self-hosted Flagsmith dashboard (run in CI right after seed.py).

    python docs/tools/capture_dashboard.py --env .selfhosted.env --out dashboard-shots

Logs in with the throwaway admin that seed.py created on a disposable CI instance,
then captures the flags list, the checkout_flow flag (60/30/10 split) and the
enterprise segment. Every step also saves a debug screenshot, so a selector change
in a future Flagsmith release is easy to diagnose from the artifact.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from playwright.sync_api import Page, sync_playwright

BASE = "http://localhost:8000"


def read_env(path: str) -> dict[str, str]:
    out = {}
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip()
    return out


def snap(page: Page, out: Path, name: str, full: bool = False) -> None:
    page.wait_for_timeout(1200)
    page.screenshot(path=str(out / f"{name}.png"), full_page=full)
    print("saved", name)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--env", default=".selfhosted.env")
    ap.add_argument("--out", default="dashboard-shots")
    args = ap.parse_args()
    env = read_env(args.env)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    project, env_key = env["FLAGSMITH_PROJECT_ID"], env["FLAGSMITH_CLIENT_KEY"]

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1600, "height": 960}, device_scale_factor=2, color_scheme="dark")

        # Log in
        page.goto(f"{BASE}/login", wait_until="networkidle")
        snap(page, out, "debug-01-login")
        page.locator("input[type=email], input[name=email], input[id*=email i]").first.fill(env["FLAGSMITH_ADMIN_EMAIL"])
        page.locator("input[type=password]").first.fill(env["FLAGSMITH_ADMIN_PASSWORD"])
        page.keyboard.press("Enter")
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(3000)
        snap(page, out, "debug-02-after-login")

        # Flags list for the Production environment
        page.goto(f"{BASE}/project/{project}/environment/{env_key}/features", wait_until="networkidle")
        page.wait_for_timeout(3000)
        snap(page, out, "flags-list")

        # Open checkout_flow (multivariate 60/30/10)
        try:
            page.get_by_text("checkout_flow", exact=True).first.click(timeout=15000)
            page.wait_for_timeout(3000)
            snap(page, out, "checkout-flow")
            for tab in ("Segment Overrides", "Segment overrides"):
                loc = page.get_by_text(tab, exact=True)
                if loc.count():
                    loc.first.click()
                    page.wait_for_timeout(2500)
                    snap(page, out, "checkout-flow-segment-overrides")
                    break
            page.keyboard.press("Escape")
        except Exception as exc:  # noqa: BLE001
            print("checkout_flow modal failed:", type(exc).__name__)
            snap(page, out, "debug-03-checkout-failed")

        # Segments page
        page.goto(f"{BASE}/project/{project}/segments", wait_until="networkidle")
        page.wait_for_timeout(3000)
        snap(page, out, "segments")
        try:
            page.get_by_text("enterprise", exact=True).first.click(timeout=15000)
            page.wait_for_timeout(3000)
            snap(page, out, "segment-enterprise")
        except Exception as exc:  # noqa: BLE001
            print("segment modal failed:", type(exc).__name__)
        browser.close()


if __name__ == "__main__":
    main()
