"""The external sources, and what each one can settle on its own.

The catalog is data (`external_data/sources.yaml`), so adding a database is
editing YAML rather than this file. What lives here is only the reading of it
and the one question that matters per source: can `discover` reach it now, and
if not, what does a person have to do.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import yaml

USER_AGENT = "reactgen-discover/1.0"

DEFAULT_CATALOG = Path("external_data/sources.yaml")

# What a person must do when discover cannot reach a source itself.
MANUAL_STEP = {
    "manual_export": "export from the site, then: acquire lxcat FILE --out work/",
    "api_key": "set {key_env} in the environment, then rerun",
    "bulk_download": "download the release file, then convert it to a snapshot",
}


@dataclass(frozen=True)
class Source:
    id: str
    covers: tuple[str, ...]
    access: str
    priority: int
    license: str
    applicability: str
    endpoint: str | None = None
    key_env: str | None = None

    @property
    def reachable(self) -> bool:
        """Whether discover can query this source in this environment."""

        if self.access == "api":
            return True
        if self.access == "api_key":
            return bool(self.key_env and os.environ.get(self.key_env))
        return self.access == "derived"

    @property
    def blocked_by(self) -> str | None:
        if self.reachable:
            return None
        template = MANUAL_STEP.get(self.access, "no automated route")
        return template.format(key_env=self.key_env or "")


def probe(source: Source, timeout_s: int = 15) -> str:
    """What the endpoint actually answers, rather than what the catalog claims.

    A landing page that loads is not a data file that can be fetched, so a
    reachable endpoint only downgrades to ``responds`` — never to ``api``.
    """

    if not source.endpoint:
        return "no endpoint"
    if not source.endpoint.startswith("https://"):
        return "refused, the catalog must give an https endpoint"
    request = Request(source.endpoint, headers={"User-Agent": USER_AGENT})  # noqa: S310 - checked
    try:
        with urlopen(request, timeout=timeout_s) as response:  # noqa: S310 - checked above
            return f"responds {response.status}"
    except HTTPError as error:
        return f"refused {error.code}"
    except (URLError, OSError) as error:
        return f"unreachable {type(error).__name__}"


def load(path: Path | None = None) -> list[Source]:
    document = yaml.safe_load((path or DEFAULT_CATALOG).read_text(encoding="utf-8")) or {}
    sources = [
        Source(
            id=entry["id"],
            covers=tuple(entry.get("covers") or ()),
            access=entry["access"],
            priority=int(entry.get("priority", 5)),
            license=entry.get("license", "unknown"),
            applicability=" ".join((entry.get("applicability") or "").split()),
            endpoint=entry.get("endpoint"),
            key_env=entry.get("key_env"),
        )
        for entry in document.get("sources") or []
    ]
    return sorted(sources, key=lambda item: (item.priority, item.id))


def covering(sources: list[Source], family: str) -> list[Source]:
    """Sources that describe this reaction family, best first."""

    return [item for item in sources if family in item.covers]
