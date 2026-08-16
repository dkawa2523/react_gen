"""NIST SRD 107 target definitions and ASCII-table parsing."""

from __future__ import annotations

from dataclasses import dataclass
from itertools import pairwise

ANGSTROM2_TO_M2 = 1.0e-20
NIST_SRD107_DOI = "https://doi.org/10.18434/T4KK5C"


@dataclass(frozen=True)
class NistBebTarget:
    species_id: str
    reaction_id: str
    download_url: str


TARGETS = {
    target.species_id: target
    for target in (
        NistBebTarget(
            species_id="CF2",
            reaction_id="e_CF2_ionization_CF2p",
            download_url=("https://physics.nist.gov/cgi-bin/Ionization/bebcsdwnload_ascii?CF2"),
        ),
        NistBebTarget(
            species_id="CF3",
            reaction_id="e_CF3_ionization_CF3p",
            download_url=("https://physics.nist.gov/cgi-bin/Ionization/bebcsdwnload_ascii?CF3"),
        ),
        NistBebTarget(
            species_id="CF4",
            reaction_id="e_CF4_ionization_parent_effective",
            download_url=("https://physics.nist.gov/cgi-bin/Ionization/bebcsdwnload_ascii?CF4"),
        ),
        NistBebTarget(
            species_id="O2",
            reaction_id="e_O2_ionization",
            download_url=("https://physics.nist.gov/cgi-bin/Ionization/bebcsdwnload_ascii?O2"),
        ),
        NistBebTarget(
            species_id="SF3",
            reaction_id="e_SF3_ionization",
            download_url=("https://physics.nist.gov/cgi-bin/Ionization/bebcsdwnload_ascii?SF3"),
        ),
        NistBebTarget(
            species_id="SF4",
            reaction_id="e_SF4_ionization",
            download_url=("https://physics.nist.gov/cgi-bin/Ionization/bebcsdwnload_ascii?SF4"),
        ),
        NistBebTarget(
            species_id="SF5",
            reaction_id="e_SF5_ionization",
            download_url=("https://physics.nist.gov/cgi-bin/Ionization/bebcsdwnload_ascii?SF5"),
        ),
        NistBebTarget(
            species_id="SF6",
            reaction_id="e_SF6_dissociative_ionization_SF5p_F",
            download_url=("https://physics.nist.gov/cgi-bin/Ionization/bebcsdwnload_ascii?SF6"),
        ),
    )
}


def parse_nist_beb_ascii(text: str) -> list[dict[str, float]]:
    """Convert an SRD 107 BEB table from eV/A^2 to eV/m^2."""

    rows: list[dict[str, float]] = []
    for line in text.splitlines():
        fields = line.split()
        if len(fields) != 2:
            continue
        try:
            energy_eV, cross_section_A2 = map(float, fields)
        except ValueError:
            continue
        if energy_eV < 0 or cross_section_A2 < 0:
            raise ValueError("NIST BEB rows must contain non-negative values")
        rows.append(
            {
                "energy_eV": energy_eV,
                "cross_section_m2": cross_section_A2 * ANGSTROM2_TO_M2,
            }
        )

    if len(rows) < 2:
        raise ValueError("NIST BEB response did not contain a numeric cross-section table")
    if any(left["energy_eV"] >= right["energy_eV"] for left, right in pairwise(rows)):
        raise ValueError("NIST BEB energies must be strictly increasing")
    return rows


def target_for(species_id: str) -> NistBebTarget:
    try:
        return TARGETS[species_id]
    except KeyError as exc:
        supported = ", ".join(TARGETS)
        raise ValueError(
            f"unsupported NIST BEB target {species_id!r}; choose from {supported}"
        ) from exc
