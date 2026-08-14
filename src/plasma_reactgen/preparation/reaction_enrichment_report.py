from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from plasma_reactgen.domain.models import CollisionPair

_SUMMARY_LISTS = {
    "n_reaction_pairs_imported": "reaction_pairs_imported",
    "n_reaction_channels_imported": "reaction_channels_imported",
    "n_reaction_channels_skipped": "reaction_channels_skipped",
    "n_species_seeded_from_reactions": "species_seeded_from_reactions",
    "n_unresolved_product_species": "unresolved_product_species",
    "n_unresolved_reactions": "unresolved_reactions",
}


@dataclass
class ReactionEnrichmentReport:
    payload: dict[str, Any]

    @classmethod
    def create(cls, source_profile: dict[str, Any]) -> ReactionEnrichmentReport:
        payload: dict[str, Any] = {
            "schema_version": 1,
            "source_profile": source_profile.get("name", "custom"),
            **{name: [] for name in _SUMMARY_LISTS.values()},
            "summary": dict.fromkeys(_SUMMARY_LISTS, 0),
        }
        return cls(payload)

    def imported(
        self,
        pair: CollisionPair,
        channels: list[dict[str, Any]],
    ) -> None:
        self.payload["reaction_pairs_imported"].append(pair.key)
        self.payload["reaction_channels_imported"].extend(
            {"pair": pair.key, "id": channel["id"]} for channel in channels
        )

    def skipped(
        self,
        pair: CollisionPair,
        channel_id: str,
        reason: str,
        validation: dict[str, str] | None = None,
    ) -> None:
        item: dict[str, Any] = {
            "pair": pair.key,
            "id": channel_id,
            "reason": reason,
        }
        if validation is not None:
            item["validation"] = validation
        self.payload["reaction_channels_skipped"].append(item)

    def unresolved(
        self,
        pair: CollisionPair,
        channel_id: str | None,
        reason: str,
    ) -> None:
        self.payload["unresolved_reactions"].append(
            {"pair": pair.key, "id": channel_id, "reason": reason}
        )

    def product_resolution_failed(
        self,
        pair: CollisionPair,
        channel_id: str,
        unresolved: list[dict[str, Any]],
    ) -> None:
        self.payload["unresolved_product_species"].extend(
            {
                "pair": pair.key,
                "channel": channel_id,
                "species": item.get("species"),
                "reason": item.get("reason"),
            }
            for item in unresolved
        )
        self.unresolved(pair, channel_id, unresolved[0]["reason"])

    def add_seeded(self, items: list[dict[str, Any]]) -> None:
        seeded = self.payload["species_seeded_from_reactions"]
        seeded.extend(item for item in items if item not in seeded)

    def finalize(self) -> dict[str, Any]:
        self.payload["summary"] = {
            count_name: len(self.payload[list_name])
            for count_name, list_name in _SUMMARY_LISTS.items()
        }
        return self.payload


__all__ = ["ReactionEnrichmentReport"]
