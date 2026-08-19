"""Download the release file a source names in the catalog.

The URL is data, not code: a source that publishes a direct file records it as
``file:`` and this fetches it. That is all `bulk_download` ever needed.

What it must not do is trust a 200. A site that serves a single-page app
answers every path with its own HTML, so a fetch that only checked the status
would write a web page into the registry and call it data. The body is checked
against the format the catalog declares, and a mismatch is refused.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

USER_AGENT = "reactgen-acquire/1.0"
TIMEOUT_S = 120
HTML_MARKERS = (b"<!doctype html", b"<html", b"<!DOCTYPE HTML")

# A line the real file has and a web page does not.
LOOKS_LIKE = {
    "umist": lambda body: b":" in body and body.split(b"\n")[0].split(b":")[0].strip().isdigit(),
    "lxcat": lambda body: b"PROCESS:" in body or b"COLUMNS:" in body,
    "csv": lambda body: b"," in body.split(b"\n")[0],
}


@dataclass(frozen=True)
class Fetched:
    url: str
    body: bytes | None = None
    sha256: str | None = None
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.body is not None


def fetch(url: str, expect: str | None = None) -> Fetched:
    """Retrieve one file and check it is the format the catalog promised."""

    if not url.startswith("https://"):
        return Fetched(url, error="the catalog must give an https url")
    request = Request(url, headers={"User-Agent": USER_AGENT})  # noqa: S310 - checked above
    try:
        with urlopen(request, timeout=TIMEOUT_S) as response:  # noqa: S310 - checked above
            body = response.read()
    except (HTTPError, URLError, OSError) as error:
        return Fetched(url, error=f"{type(error).__name__}: {error}")

    problem = _wrong_content(body, expect)
    if problem:
        return Fetched(url, error=problem)
    return Fetched(url, body, hashlib.sha256(body).hexdigest()[:16])


def _wrong_content(body: bytes, expect: str | None) -> str | None:
    head = body[:400].lower()
    if any(marker.lower() in head for marker in HTML_MARKERS):
        return "the server answered with a web page, not the release file"
    looks_right = LOOKS_LIKE.get(expect or "")
    if looks_right and not looks_right(body[:4000]):
        return f"the body does not look like {expect}"
    return None
