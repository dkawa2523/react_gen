"""Which species is the ion, the anion, or the ground state of which.

Every screen needs the same handful of questions answered — what neutral does
this ion come from, what ion does this neutral become, what does this excited
state fall back to — and they are all the same lookup: find the species with
this composition and that charge, in that state.

Kept apart from the screens so each of those reads as its own physics.
"""

from __future__ import annotations

from dataclasses import dataclass

from reactgen.model import Species

Composition = dict[str, int]


def _key(composition: Composition, charge: int) -> tuple:
    return (tuple(sorted(composition.items())), charge)


@dataclass
class Relations:
    """The species table, indexed the way a screen asks about it."""

    species: dict[str, Species]

    def _find(self, composition: Composition, charge: int, ground: bool = False) -> str | None:
        """The species with this formula and charge, preferring the ground state.

        Several states share a formula, and answering with whichever was loaded
        last would name ``O_1D`` where ``O`` was meant. ``ground`` makes it the
        only acceptable answer rather than merely the preferred one.
        """

        fallback = None
        for item in self.species.values():
            if _key(item.composition, item.charge) != _key(composition, charge):
                continue
            if item.state.kind == "ground":
                return item.id
            fallback = item.id
        return None if ground else fallback

    def charge_of(self, species_id: str) -> int | None:
        item = self.species.get(species_id)
        return None if item is None else item.charge

    def neutral_of(self, species_id: str) -> str | None:
        """The neutral an ion came from, whichever sign it carries.

        Answers for ions only. A neutral asked about itself would let a caller
        treat it as an ion, and the reaction it then wrote would not balance.
        """

        item = self.species.get(species_id)
        if item is None or item.charge == 0:
            return None
        return self._find(dict(item.composition), 0)

    def cation_of(self, species_id: str) -> str | None:
        """The singly charged ion of a neutral, if one is registered."""

        item = self.species.get(species_id)
        return None if item is None else self._find(dict(item.composition), 1)

    def ground_of(self, species_id: str) -> str | None:
        """What an excited state falls back to."""

        item = self.species.get(species_id)
        return None if item is None else self._find(dict(item.composition), item.charge, True)

    def has_excited(self, species_id: str) -> bool:
        """Whether the registry already resolves this species into levels.

        Where it does, a lumped ``Ar*`` beside a registered ``Ar_4s`` would put
        the same physics in the list twice under two granularities.
        """

        item = self.species.get(species_id)
        if item is None:
            return False
        return any(
            other.state.kind != "ground"
            and _key(other.composition, other.charge) == _key(item.composition, item.charge)
            for other in self.species.values()
        )

    def cations(self) -> dict[str, str]:
        """Ground-state neutrals onto their ions.

        Excited states are left out: ionizing a metastable gives the
        ground-state ion, so naming one after the metastable would invent a
        species like ``Ar_4s+`` that does not exist.
        """

        return {
            item.id: ion
            for item in self.species.values()
            if item.is_neutral
            and item.state.kind == "ground"
            and (ion := self._find(dict(item.composition), 1))
        }

    def by_charge(self, names: set[str], charge: int) -> list[str]:
        return sorted(name for name in names if self.charge_of(name) == charge)
