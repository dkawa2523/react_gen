from __future__ import annotations

from pathlib import Path
from typing import Any

from plasma_reactgen.data_sources.base import PropertyProvider, SpeciesProvider


class PubChemProvider(SpeciesProvider, PropertyProvider):
    """Disabled PubChem extension point for future prepare-time enrichment."""

    available = False

    def __init__(
        self,
        *,
        enabled: bool = False,
        mode: str = "online",
        cache_dir: str | Path = "external_data/pubchem/cache",
    ):
        self.enabled = bool(enabled)
        self.mode = str(mode)
        self.cache_dir = Path(cache_dir)

    def find_species(self, query: str) -> list[dict[str, Any]]:
        return []

    def find_properties(
        self,
        species_id: str,
        names: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        return []

    def status(self) -> dict[str, Any]:
        return {
            "available": False,
            "enabled": self.enabled,
            "mode": self.mode,
            "cache_dir": str(self.cache_dir),
            "message": (
                "PubChem online enrichment is not enabled. This provider is a "
                "prepare/enrich extension point only and performs no HTTP calls."
            ),
        }
