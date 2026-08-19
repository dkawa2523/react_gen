"""What each layer of judgement says about a reaction.

Four questions, in the order of how much each demands of the data:

``structure``       can these species exist, and does the equation balance?
``thermochemistry`` do the energetics leave the channel open?
``kinetics``        does it run fast enough to matter under these conditions?
``attestation``     does any source state this reaction?

They are not a filter and not a ranking. A reaction that fails ``structure``
never reaches a network at all; the other three annotate. Reading them in order
tells a reviewer how far the evidence for a reaction actually goes, which one
combined "confidence" word cannot: a channel can be thermochemically certain
and completely unattested, and that is a different thing from an attested one
whose rate nobody has measured.

Layers a run did not evaluate say ``not_run`` rather than ``unknown``, because
"nobody looked" and "we looked and cannot tell" are different answers.
"""

from __future__ import annotations

from reactgen.model import Reaction

LAYERS = ("structure", "thermochemistry", "kinetics", "attestation")

# What this repository writes when it worked a channel out for itself. Anything
# else in `source_type` came from a paper or a database, and a reaction that
# carries one is attested whether or not a separate index was handed in.
DERIVED = frozenset(
    {
        "bond_breaking",
        "formation_enthalpy",
        "dissociation_limit",
        "ionization_and_bond_energy",
        "excitation_versus_ionization_energy",
        "vibrational_manifold",
        "structural",
    }
)

# What the screens record when they decided a channel on energy alone.
SCREENED = frozenset(
    {
        "formation_enthalpy",
        "dissociation_limit",
        "ionization_and_bond_energy",
        "excitation_versus_ionization_energy",
    }
)


def verdicts(
    reaction: Reaction, listed: list[str], relevance: str | None, selected: tuple[str, ...]
) -> dict[str, str]:
    """One line per layer the run was asked for."""

    answers = {
        "structure": _structure(reaction),
        "thermochemistry": _thermochemistry(reaction),
        "kinetics": relevance or "unknown",
        "attestation": _attestation(reaction, listed),
    }
    return {name: answers[name] if name in selected else "not_run" for name in LAYERS}


def _attestation(reaction: Reaction, listed: list[str]) -> str:
    """Who states this reaction: an index handed in, or its own record.

    A curated channel already carries the paper it was read from, so requiring
    a separate index to call it attested reported two hundred and fifty DOIs as
    unattested. The index adds to that rather than replacing it.
    """

    sources = list(listed)
    own = reaction.source.get("source_id") or reaction.source.get("source_type")
    if own and reaction.source.get("source_type") not in DERIVED:
        sources.append(str(own))
    return ", ".join(dict.fromkeys(sources)) if sources else "unattested"


def _structure(reaction: Reaction) -> str:
    """Everything in a network conserved charge and elements; what differs is
    whether the species were registered or had to be proposed."""

    return "conserved, species proposed" if reaction.status == "candidate" else "conserved"


def _thermochemistry(reaction: Reaction) -> str:
    energy = reaction.delta_e_eV
    if energy is None:
        return "screened on energy" if _screened(reaction) else "unknown"
    if energy < 0:
        return f"exothermic by {abs(energy):.2f} eV"
    if energy > 0:
        return f"endothermic by {energy:.2f} eV"
    return "thermoneutral"


def _screened(reaction: Reaction) -> bool:
    return reaction.source.get("source_type", "") in SCREENED


def select(names: str | None) -> tuple[str, ...]:
    """The layers to evaluate. Unknown names are refused rather than ignored."""

    if not names:
        return LAYERS
    chosen = tuple(part.strip() for part in names.split(",") if part.strip())
    unknown = sorted(set(chosen) - set(LAYERS))
    if unknown:
        raise ValueError(f"unknown layers {unknown}; known: {list(LAYERS)}")
    return chosen
