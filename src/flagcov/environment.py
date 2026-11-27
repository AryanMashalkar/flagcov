"""Load a Flagsmith environment document from a file or a (self-hosted) Flagsmith API.

The environment document is what Flagsmith's server-side SDKs use for local
evaluation. It holds every flag's live state, multivariate weights, segment
rules, segment overrides and identity overrides, which is all FlagCov needs.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

DEFAULT_API_URL = "https://edge.api.flagsmith.com/api/v1/"


class EnvironmentError_(RuntimeError):
    """Raised when the environment document cannot be loaded."""


def fetch_document(server_key: str, api_url: str = DEFAULT_API_URL, timeout: float = 15) -> dict[str, Any]:
    """Fetch the environment document with a server-side environment key.

    Works against Flagsmith Cloud and self-hosted Flagsmith alike
    (``api_url`` is e.g. ``http://localhost:8000/api/v1/``).
    """
    if not server_key:
        raise EnvironmentError_("A server-side environment key (ser.xxx) is required to fetch the document.")
    url = api_url.rstrip("/") + "/environment-document/"
    request = urllib.request.Request(url, headers={"X-Environment-Key": server_key, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 (user-supplied API URL)
            return _validate(json.loads(response.read().decode("utf-8")), url)
    except urllib.error.HTTPError as exc:
        raise EnvironmentError_(f"Flagsmith returned HTTP {exc.code} for {url}. Is the key a server-side key?") from exc
    except urllib.error.URLError as exc:
        raise EnvironmentError_(f"Could not reach Flagsmith at {url}: {exc.reason}") from exc


def read_document(path: str | os.PathLike[str]) -> dict[str, Any]:
    p = Path(path)
    if not p.is_file():
        raise EnvironmentError_(f"Environment document not found: {p}")
    return _validate(json.loads(p.read_text(encoding="utf-8")), str(p))


def load_document(
    source: str | os.PathLike[str] | None = None,
    server_key: str | None = None,
    api_url: str | None = None,
) -> dict[str, Any]:
    """Load from a file path, or fetch from the API when ``source`` is None or a URL.

    Environment variables are used as fallbacks: ``FLAGSMITH_SERVER_KEY`` (or
    ``FLAGSMITH_ENVIRONMENT_KEY``) and ``FLAGSMITH_API_URL``.
    """
    if source and not str(source).startswith(("http://", "https://")):
        return read_document(source)
    key = server_key or os.environ.get("FLAGSMITH_SERVER_KEY") or os.environ.get("FLAGSMITH_ENVIRONMENT_KEY") or ""
    url = str(source) if source else (api_url or os.environ.get("FLAGSMITH_API_URL") or DEFAULT_API_URL)
    return fetch_document(key, url)


def _validate(doc: Any, where: str) -> dict[str, Any]:
    if not isinstance(doc, dict) or "feature_states" not in doc:
        raise EnvironmentError_(f"{where} is not a Flagsmith environment document (no 'feature_states').")
    doc.setdefault("project", {}).setdefault("segments", [])
    doc.setdefault("identity_overrides", [])
    return doc
