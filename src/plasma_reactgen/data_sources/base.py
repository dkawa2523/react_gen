from __future__ import annotations

from typing import Any

from plasma_reactgen.data_sources.models import (
    CrossSectionCandidate,
    PropertyCandidate,
    ReactionCandidate,
    SpeciesCandidate,
)


class SpeciesProvider:
    """Interface for prepare-time species identity candidate providers."""

    def find_species(self, query: Any) -> list[SpeciesCandidate] | list[dict[str, Any]]:
        raise NotImplementedError


class PropertyProvider:
    """Interface for prepare-time species property candidate providers."""

    def find_properties(
        self,
        species_id: str,
        property_names: list[str] | None = None,
    ) -> list[PropertyCandidate] | list[dict[str, Any]]:
        raise NotImplementedError


class ReactionProvider:
    """Interface for prepare-time reaction candidate providers."""

    def find_reactions(
        self,
        reactants: list[str],
        family: str | None = None,
    ) -> list[ReactionCandidate] | list[dict[str, Any]]:
        raise NotImplementedError

    def find_channels(self, pair: Any) -> list[ReactionCandidate] | list[dict[str, Any]]:
        raise NotImplementedError


class CrossSectionProvider:
    """Interface for prepare-time cross-section candidate providers."""

    def find_cross_sections(
        self,
        pair: Any,
    ) -> list[CrossSectionCandidate] | list[dict[str, Any]]:
        raise NotImplementedError
