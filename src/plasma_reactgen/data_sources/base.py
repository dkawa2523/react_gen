from __future__ import annotations

from typing import Any

class SpeciesProvider:
    """Interface for prepare-time species identity candidate providers."""

    def find_species(self, query: Any) -> list[dict[str, Any]]:
        raise NotImplementedError


class PropertyProvider:
    """Interface for prepare-time species property candidate providers."""

    def find_properties(
        self,
        species_id: str,
        property_names: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        raise NotImplementedError


class ReactionProvider:
    """Interface for prepare-time reaction candidate providers."""

    def find_channels(self, pair: Any) -> list[dict[str, Any]]:
        raise NotImplementedError


class CrossSectionProvider:
    """Interface for prepare-time cross-section candidate providers."""

    def find_cross_sections(
        self,
        pair: Any,
    ) -> list[dict[str, Any]]:
        raise NotImplementedError
