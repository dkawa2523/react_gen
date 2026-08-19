"""Turn gaps into an acquisition plan.

Each gap kind routes to the source family that can close it. The plan says what
to fetch and how it will be accepted; fetching itself stays outside this
package, under ``external_data_tools``.
"""

from __future__ import annotations

from collections import defaultdict

from reactgen.model import Gap

ROUTES = {
    "missing_cross_section": (
        "electron_cross_section",
        "LXCat (Biagi / Phelps / IST-Lisbon), Itikawa and Christophorou-Olthoff evaluations",
        "product-resolved channels, eV and m2, threshold consistent, complete set declared",
    ),
    "missing_rate_coefficient": (
        "rate_coefficient",
        "NIST Chemical Kinetics, IUPAC/JPL evaluations, primary kinetics literature",
        "temperature range preserved, SI units, plasma applicability reviewed",
    ),
    "missing_property": (
        "species_property",
        "NIST Chemistry WebBook and CCCBDB, ATcT thermochemistry",
        "value with unit, state convention, and a citable source record",
    ),
    "missing_threshold": (
        "threshold_energy",
        "spectroscopic and ionization-energy compilations",
        "consistent with the reaction energetics of the same channel",
    ),
    "incomplete_set": (
        "electron_cross_section",
        "LXCat complete sets",
        "exactly one momentum-transfer channel per target",
    ),
    "unregistered_pair": (
        "reaction_channels",
        "primary mechanism papers, QDB validated chemistry sets",
        "balanced equation with a cited source row",
    ),
    "missing_electron_chemistry": (
        "electron_channels",
        "evaluated electron-collision reviews, LXCat process lists, mechanism papers",
        "elastic, ionization, dissociation and attachment channels enumerated with "
        "products and thresholds; a balanced equation per channel",
    ),
    "input_gas": (
        "species_identity",
        "PubChem identity snapshot, then a mechanism source",
        "formula, charge and state registered before any reaction",
    ),
    "reaction_family": (
        "reaction_channels",
        "three-body kinetics evaluations; surface recombination measurements",
        "m6/s with third-body efficiencies, or gamma with material and temperature",
    ),
    "competing_datasets": (
        "review_decision",
        "no acquisition needed",
        "one dataset marked preferred with a written rationale",
    ),
    "out_of_range": (
        "review_decision",
        "no acquisition needed",
        "either accept the extrapolation explicitly or acquire in-range data",
    ),
}

PRIORITY = {"blocking": "P0", "data": "P1", "info": "P2"}


def build(gaps: list[Gap]) -> dict:
    grouped: defaultdict[tuple[str, str], list[Gap]] = defaultdict(list)
    for gap in gaps:
        target, _, _ = ROUTES.get(gap.kind, ("other", "", ""))
        grouped[(PRIORITY.get(gap.severity, "P2"), target)].append(gap)

    items = []
    for (priority, target), found in sorted(grouped.items()):
        _, source, acceptance = ROUTES.get(found[0].kind, ("other", "unrouted", "manual review"))
        items.append(
            {
                "priority": priority,
                "target": target,
                "count": len(found),
                "source": source,
                "acceptance": acceptance,
                "subjects": sorted({gap.subject for gap in found})[:20],
            }
        )
    return {"acquisition_plan": items}
