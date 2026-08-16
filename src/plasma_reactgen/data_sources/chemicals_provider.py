"""Provider facades for the optional chemicals package."""

from __future__ import annotations

from typing import Any

from plasma_reactgen.data_sources.chemicals_adapter import (
    ChemicalsModules,
    load_chemicals_modules,
    search_chemical,
)
from plasma_reactgen.data_sources.chemicals_records import (
    j_per_mol_to_ev,
    kj_per_mol_to_ev,
    property_candidates,
    species_candidate,
)


class ChemicalsSpeciesProvider:
    def __init__(self, provider_name: str = "chemicals_optional") -> None:
        self.provider_name = provider_name

    def find_species(self, query: str) -> list[dict[str, Any]]:
        modules = load_chemicals_modules()
        chemical = search_chemical(modules, query) if modules.available else None
        return (
            [species_candidate(chemical, query, self.provider_name)] if chemical is not None else []
        )

    def status(self) -> dict[str, Any]:
        return _provider_status(load_chemicals_modules(), self.provider_name)


class ChemicalsPropertyProvider:
    def __init__(self, provider_name: str = "chemicals_optional") -> None:
        self.provider_name = provider_name
        self.notes: list[str] = []

    def find_properties(
        self,
        species_id: str,
        names: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        self.notes = []
        modules = load_chemicals_modules()
        chemical = search_chemical(modules, species_id) if modules.available else None
        if chemical is None:
            return []
        candidates, self.notes = property_candidates(
            chemical,
            modules,
            species_id,
            names,
            self.provider_name,
        )
        return candidates

    def status(self) -> dict[str, Any]:
        return _provider_status(
            load_chemicals_modules(),
            self.provider_name,
            notes=self.notes,
        )


def _provider_status(
    modules: ChemicalsModules,
    provider_name: str,
    *,
    notes: list[str] | None = None,
) -> dict[str, Any]:
    status = {
        "available": modules.available,
        "source": "chemicals",
        "reason": modules.reason,
        "provider_name": provider_name,
    }
    if notes is not None:
        status["notes"] = list(notes)
    return status


__all__ = [
    "ChemicalsPropertyProvider",
    "ChemicalsSpeciesProvider",
    "j_per_mol_to_ev",
    "kj_per_mol_to_ev",
]
