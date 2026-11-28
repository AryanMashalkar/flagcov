"""Seed a fresh self-hosted Flagsmith with the FlagCov demo shop's flags.

    python seed.py --api-url http://localhost:8000/api/v1/ --out .selfhosted.env

Creates (through Flagsmith's own REST API, no database access):
  * a local admin user (random password, written only to the --out file)
  * organisation "FlagCov Demo" / project "Demo Shop" / environment "Production"
  * dark_mode (on), new_search (off), free_shipping_threshold (499),
    legacy_promo_banner (on), checkout_flow (classic 60% / one_page 30% / express 10%)
  * segment "enterprise" (plan == enterprise) overriding checkout_flow to "invoice"
  * a server-side environment key, used by FlagCov to fetch the environment document

Standard library only, so it runs anywhere Python 3.10+ does.
"""

from __future__ import annotations

import argparse
import json
import secrets
import sys
import time
import urllib.error
import urllib.request

EMAIL = "flagcov-admin@example.com"


class Api:
    def __init__(self, base: str) -> None:
        self.base = base.rstrip("/") + "/"
        self.token: str | None = None

    def call(self, method: str, path: str, body: dict | None = None, ok: tuple[int, ...] = (200, 201)) -> dict:
        data = None if body is None else json.dumps(body).encode()
        req = urllib.request.Request(self.base + path.lstrip("/"), data=data, method=method)
        req.add_header("Content-Type", "application/json")
        req.add_header("Accept", "application/json")
        if self.token:
            req.add_header("Authorization", f"Token {self.token}")
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                text = resp.read().decode() or "{}"
                return json.loads(text)
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode(errors="replace")[:500]
            if exc.code in ok:
                return json.loads(detail or "{}")
            raise SystemExit(f"{method} {path} -> HTTP {exc.code}: {detail}") from None


def wait_until_up(api_url: str, timeout: float = 300) -> None:
    root = api_url.split("/api/")[0]
    deadline = time.time() + timeout
    while time.time() < deadline:
        for probe in ("/health/liveness/", "/health", "/api/v1/"):
            try:
                with urllib.request.urlopen(root + probe, timeout=5) as resp:
                    if resp.status < 500:
                        print(f"Flagsmith is up ({root}{probe})")
                        return
            except Exception:  # noqa: BLE001 - keep polling
                pass
        time.sleep(3)
    raise SystemExit(f"Flagsmith did not come up at {root} within {timeout:.0f}s")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--api-url", default="http://localhost:8000/api/v1/")
    parser.add_argument("--out", default=".selfhosted.env")
    args = parser.parse_args()

    wait_until_up(args.api_url)
    api = Api(args.api_url)
    password = "Fc!" + secrets.token_urlsafe(18)

    # 1. Admin user: sign up (first user on a fresh instance), then log in for a token.
    api.call(
        "POST",
        "auth/users/",
        {"email": EMAIL, "password": password, "re_password": password, "first_name": "Flag", "last_name": "Cov", "sign_up_type": "NO_INVITE"},
    )
    api.token = api.call("POST", "auth/login/", {"email": EMAIL, "password": password})["key"]

    # 2. Organisation / project / environment
    org = api.call("POST", "organisations/", {"name": "FlagCov Demo"})["id"]
    project = api.call("POST", "projects/", {"name": "Demo Shop", "organisation": org})["id"]
    env = api.call("POST", "environments/", {"name": "Production", "project": project})
    env_key = env["api_key"]

    # 3. Flags
    def feature(name: str, enabled: bool, value: object = None) -> int:
        body: dict = {"name": name, "default_enabled": enabled}
        if value is not None:
            body["initial_value"] = value
        return api.call("POST", f"projects/{project}/features/", body)["id"]

    feature("dark_mode", True)
    feature("new_search", False)
    feature("free_shipping_threshold", True, 499)
    feature("legacy_promo_banner", True)
    checkout = feature("checkout_flow", True, "classic")
    for key, weight in (("one_page", 30), ("express", 10)):
        api.call(
            "POST",
            f"projects/{project}/features/{checkout}/mv-options/",
            {"feature": checkout, "type": "unicode", "string_value": key, "key": key, "default_percentage_allocation": weight},
        )

    # 4. Segment + segment override
    segment = api.call(
        "POST",
        f"projects/{project}/segments/",
        {
            "name": "enterprise",
            "project": project,
            "rules": [{"type": "ALL", "conditions": [], "rules": [
                {"type": "ANY", "rules": [], "conditions": [{"operator": "EQUAL", "property": "plan", "value": "enterprise"}]}
            ]}],
        },
    )["id"]
    api.call(
        "POST",
        f"environments/{env_key}/features/{checkout}/create-segment-override/",
        {"feature_segment": {"segment": segment}, "enabled": True, "feature_state_value": {"type": "unicode", "string_value": "invoice"}},
    )

    # 5. Server-side key for the environment document
    server_key = api.call("POST", f"environments/{env_key}/api-keys/", {"name": "flagcov"})["key"]

    with open(args.out, "w", encoding="utf-8") as fh:
        fh.write(
            f"FLAGSMITH_API_URL={args.api_url}\nFLAGSMITH_SERVER_KEY={server_key}\nFLAGSMITH_CLIENT_KEY={env_key}\n"
            f"FLAGSMITH_ADMIN_EMAIL={EMAIL}\nFLAGSMITH_ADMIN_PASSWORD={password}\n"
            f"FLAGSMITH_PROJECT_ID={project}\nFLAGSMITH_CHECKOUT_FEATURE_ID={checkout}\nFLAGSMITH_SEGMENT_ID={segment}\n"
        )
    print(f"Seeded project 'Demo Shop' (environment {env_key}). Keys written to {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
