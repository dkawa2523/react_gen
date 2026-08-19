"""DNT+ inputs, graded by the model each pair can actually run.

The pairs come from the *species* in the network, not from the reactions found
in it. This is what DNT+ is for: no database states ion-neutral cross sections
for most of these pairs, so a pair with no known channel is precisely one to
point a calculation at. Every ion-neutral encounter scatters elastically and
captures at the Langevin rate whatever chemistry does or does not follow, and
that transport is what a plasma model needs for mobility and ion energy.

Readiness is not one boolean. A pair whose long-range parameters are known can
run the capture and charge-exchange model today; the inelastic and reactive
channels additionally need a short-range potential. Reporting one combined flag
hides the first result behind the second, so each tier is reported separately.

The index lists every pair and is the work order. Full input documents are
written only for pairs that some tier can already run, because a directory of
several thousand blocked stubs hides the ones that are ready.
"""

from __future__ import annotations

from dataclasses import asdict

from reactgen.case import Case
from reactgen.model import ELECTRON, Network, Reaction
from reactgen.physics import ion_neutral_pair, reduced_mass_amu
from reactgen.registry import Registry

LONG_RANGE_REQUIRED = ("mass_amu", "polarizability_A3", "dipole_moment_D")
FULL_REQUIRED = ("collision_radius_A",)

TARGET_PROPERTIES = (
    *LONG_RANGE_REQUIRED,
    *FULL_REQUIRED,
    "quadrupole_moment_DA",
    "polarizability_anisotropy_A3",
    "rotational_constant_cm1",
)

# Channel classes each tier can produce.
LONG_RANGE_CLASSES = {"elastic", "long_range_charge_exchange"}


def build(case: Case, network: Network, registry: Registry) -> tuple[list[dict], dict]:
    """One input document per ion-neutral pair, plus the index summary."""

    channels: dict[tuple[str, str], list[Reaction]] = {}
    for reaction in network.reactions:
        if reaction.family != "ion_neutral":
            continue
        found = ion_neutral_pair(reaction, network.species)
        if found:
            channels.setdefault(found, []).append(reaction)

    documents = [
        _pair(ion, neutral, channels.get((ion, neutral), []), case, network, registry)
        for ion, neutral in _every_pair(network)
    ]
    return documents, _index(documents)


def _every_pair(network: Network) -> list[tuple[str, str]]:
    """Each ion against each neutral the network holds."""

    ions = sorted(
        item.id for item in network.species.values() if item.charge != 0 and item.id != ELECTRON
    )
    neutrals = sorted(item.id for item in network.species.values() if item.is_neutral)
    return [(ion, neutral) for ion in ions for neutral in neutrals]


def _pair(
    ion_id: str,
    neutral_id: str,
    reactions: list[Reaction],
    case: Case,
    network: Network,
    registry: Registry,
) -> dict:
    ion, neutral = network.species[ion_id], network.species[neutral_id]
    potential = registry.potentials.get(("ion_neutral", ion_id, neutral_id), {})
    # Structural, not read off a reaction: `Ar+ + Ar -> Ar + Ar+` changes nothing
    # chemically, so it is often absent from the list while being the largest
    # ion-neutral cross section in the discharge.
    resonant = ion.composition == neutral.composition
    readiness = _readiness(ion, neutral, potential, reactions, resonant)

    return {
        "pair": f"{_slug(ion_id)}__{_slug(neutral_id)}",
        "models": _models(neutral.value("dipole_moment_D"), resonant),
        "readiness": readiness,
        "runnable": [tier for tier, state in readiness.items() if state["status"] == "ready"],
        "projectile": {"id": ion_id, "charge": ion.charge, "mass_amu": ion.value("mass_amu")},
        "target": {"id": neutral_id, **{n: neutral.value(n) for n in TARGET_PROPERTIES}},
        "reduced_mass_amu": reduced_mass_amu(ion, neutral),
        "long_range": {
            "model": "ion_dipole" if neutral.value("dipole_moment_D") else "ion_induced_dipole",
            "polarizability_A3": neutral.value("polarizability_A3"),
            "dipole_moment_D": neutral.value("dipole_moment_D"),
        },
        "short_range": potential.get("short_range"),
        "energy_grid": asdict(case.dnt),
        "conditions": {k: v for k, v in asdict(case.conditions).items() if v is not None},
        "channels": [
            {
                "reaction_id": reaction.id,
                "equation": reaction.equation,
                "dnt_class": reaction.dnt_class,
                "tier": _tier_of(reaction),
                "threshold_eV": reaction.threshold_eV,
                "delta_e_eV": reaction.delta_e_eV,
            }
            for reaction in reactions
        ],
    }


def _readiness(ion, neutral, potential: dict, reactions: list[Reaction], resonant: bool) -> dict:
    """Status per model tier, each with only the fields that tier needs."""

    missing_long = [name for name in LONG_RANGE_REQUIRED if neutral.value(name) is None]
    if ion.value("mass_amu") is None:
        missing_long.append("projectile.mass_amu")

    missing_full = [name for name in FULL_REQUIRED if neutral.value(name) is None]
    if not potential.get("short_range"):
        missing_full.append("short_range_potential")
    missing_full += [
        f"threshold_eV of {reaction.id}"
        for reaction in reactions
        if _tier_of(reaction) == "full" and reaction.threshold_eV is None
    ]

    tiers = {
        "long_range": _state(missing_long),
        "full": _state(missing_long + missing_full),
    }
    if resonant:
        tiers["analytic_resonant"] = _state(
            [] if ion.value("mass_amu") and neutral.value("mass_amu") else ["mass_amu"]
        )
    return tiers


def _state(missing: list[str]) -> dict:
    return {"status": "ready" if not missing else "blocked", "missing": sorted(set(missing))}


def _tier_of(reaction: Reaction) -> str:
    """Which model tier has to produce this channel."""

    return "long_range" if reaction.dnt_class in LONG_RANGE_CLASSES else "full"


def _models(dipole: float | None, resonant: bool) -> list[str]:
    models = ["analytic_resonant_charge_exchange"] if resonant else []
    if dipole is None:
        return [*models, "unknown"]
    return [*models, "dnt_plus_dm" if abs(dipole) > 0 else "dnt_plus"]


def _index(documents: list[dict]) -> dict:
    """The work order: every pair, whether it can run, and what nobody states.

    ``no_known_channel`` is the count that matters most here. Those pairs are
    the reason DNT+ is in the workflow at all — nothing to import, so the
    numbers have to be computed.
    """

    tiers = ("long_range", "full", "analytic_resonant")
    unstated = [d for d in documents if not d["channels"]]
    return {
        "summary": {
            tier: f"{sum(1 for d in documents if tier in d['runnable'])}/{len(documents)}"
            for tier in tiers
        },
        "pairs_total": len(documents),
        "no_known_channel": len(unstated),
        "resonant": sum(1 for d in documents if "analytic_resonant" in d["readiness"]),
        "note": (
            "every ion-neutral pair in the network, whether or not a reaction is "
            "known for it: elastic scattering and capture happen regardless. A pair "
            "ready for long_range can be run now; full adds inelastic channels"
        ),
        "pairs": [
            {
                "pair": document["pair"],
                "runnable": document["runnable"],
                "known_channels": len(document["channels"]),
                "blocked_by": sorted(
                    {item for state in document["readiness"].values() for item in state["missing"]}
                ),
            }
            for document in documents
        ],
    }


def _slug(species_id: str) -> str:
    return species_id.replace("+", "_p").replace("-", "_m").replace("(", "").replace(")", "")
