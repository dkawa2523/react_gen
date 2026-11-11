"""Small, deterministic chemistry grammar used by candidate generation.

The functions in this module know formulas and finite inventory partitions.
They do not infer a molecular structure, reactivity or valence from a formula,
and know nothing about Registry records, thermochemistry or kinetics.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Iterator
from itertools import product
from urllib.parse import quote, unquote

from reactgen import naming
from reactgen.model import (
    ELECTRON,
    CandidateState,
    EquationKey,
    ReactionCandidate,
    StateCandidate,
    Term,
    canonical_family,
    canonical_process,
    reaction_id,
    side_key,
    validate_stoichiometric_terms,
)

Composition = dict[str, int]


def parse_equation(text: str) -> tuple[EquationKey, tuple[StateCandidate, ...]] | None:
    """Identify an explicitly written equation without asserting a channel exists."""
    left, separator, right = text.partition("->")
    if not separator:
        return None
    reactants, products = _parse_equation_side(left), _parse_equation_side(right)
    if reactants is None or products is None:
        return None
    left_terms, left_states, left_third = reactants
    right_terms, right_states, right_third = products
    if left_third != right_third:
        return None
    return (
        ("M" if left_third or right_third else None, None, left_terms, right_terms),
        tuple({state.id: state for state in (*left_states, *right_states)}.values()),
    )


def _parse_equation_side(
    text: str,
) -> tuple[tuple[tuple[str, float], ...], tuple[StateCandidate, ...], bool] | None:
    terms: list[Term] = []
    states: dict[str, StateCandidate] = {}
    third_body = False
    for piece in re.split(r"\s+\+\s+", text.strip()):
        token = piece.strip()
        if not token:
            continue
        count_text, separator, name = token.rpartition(" ")
        try:
            count = float(count_text) if separator else 1.0
        except ValueError:
            count, written = 1.0, token
        else:
            written = name if separator else token
        if written == "M":
            try:
                validate_stoichiometric_terms(((written, count),))
            except ValueError:
                return None
            if count != 1 or third_body:
                return None
            third_body = True
            continue
        state = parse_state_id(written)
        if state is None:
            return None
        terms.append(Term(state.id, count))
        states[state.id] = state
    try:
        validate_stoichiometric_terms(terms)
    except ValueError:
        return None
    return side_key(terms), tuple(states.values()), third_body


NOBLE_GASES = frozenset({"He", "Ne", "Ar", "Kr", "Xe"})
LIGANDS = frozenset({"H", "F", "Cl", "Br", "I"})
TERMINAL_ELEMENTS = LIGANDS | {"O"}


ELECTRONEGATIVITY = {
    "Cu": 1.90,
    "Si": 1.90,
    "B": 2.04,
    "H": 2.20,
    "P": 2.19,
    "C": 2.55,
    "S": 2.58,
    "I": 2.66,
    "Br": 2.96,
    "N": 3.04,
    "Cl": 3.16,
    "O": 3.44,
    "F": 3.98,
}


def formula(composition: Composition) -> str:
    order = sorted(
        composition,
        key=lambda element: (ELECTRONEGATIVITY.get(element, 2.0), element),
    )
    return "".join(
        f"{element}{composition[element] if composition[element] > 1 else ''}" for element in order
    )


def charged_formula(composition: Composition, charge: int) -> str:
    base = formula(composition)
    if charge == 0:
        return base
    sign = "+" if charge > 0 else "-"
    # A bare trailing digit belongs to the chemical formula (Ar2+ is Ar2
    # with charge +1).  Separate multivalent charge from the atom count.
    magnitude = "" if abs(charge) == 1 else f"^{abs(charge)}"
    return f"{base}{magnitude}{sign}"


def state_id(
    composition: Composition,
    charge: int,
    kind: str = "ground",
    label: str = "",
    *,
    resolution: str | None = None,
    phase: str = "gas",
    structure: str | None = None,
) -> str:
    if not composition and charge == -1:
        return ELECTRON
    state_name = label or kind
    default_kind, default_resolution, default_label = _state_defaults(state_name)
    identity = ""
    if kind != default_kind:
        identity += f";kind={quote(kind, safe='')}"
    resolution = resolution or _state_defaults(kind)[1]
    if resolution != default_resolution:
        identity += f";resolution={quote(resolution, safe='')}"
    if label != default_label:
        identity += f";label={quote(label, safe='')}"
    if phase != "gas":
        identity += f";phase={quote(phase, safe='')}"
    if structure is not None:
        identity += f";structure={quote(structure, safe='')}"
    return f"{charged_formula(composition, charge)}@{quote(state_name, safe='')}{identity}"


def candidate_state(
    composition: Composition,
    charge: int,
    kind: str = "ground",
    *,
    label: str = "",
    resolution: str | None = None,
    classes: frozenset[str] = frozenset(),
    origin: str = "mechanical",
    depth: int = 0,
    introduced_by: tuple[str, ...] = (),
    phase: str = "gas",
    structure: str | None = None,
) -> StateCandidate:
    resolution = resolution or _state_defaults(kind)[1]
    return StateCandidate(
        id=state_id(
            composition,
            charge,
            kind,
            label,
            resolution=resolution,
            phase=phase,
            structure=structure,
        ),
        composition=dict(composition),
        charge=charge,
        state=CandidateState(kind, resolution, label),
        classes=classes,
        origin=origin,
        depth=depth,
        introduced_by=introduced_by,
        phase=phase,
        structure=structure,
    )


def parse_state_id(written: str) -> StateCandidate | None:
    """Read either a canonical ``formula@state`` id or a chemical name."""

    if written.strip().lower() in naming.ELECTRON_NAMES:
        return electron_state()
    formula_text, separator, state_text = written.partition("@")
    parsed = naming.parse(formula_text if separator else written)
    if not parsed.composition:
        return None
    if not separator:
        if parsed.state:
            return candidate_state(
                parsed.composition,
                parsed.charge,
                "resolved",
                label=naming.normalize_state(parsed.state) or "",
                resolution="resolved",
            )
        if parsed.excited:
            return candidate_state(parsed.composition, parsed.charge, "electronic")
        return candidate_state(parsed.composition, parsed.charge, "ground", resolution="resolved")
    identity = _parse_identity_suffix(state_text)
    if identity is None:
        return None
    state_text, tags = identity
    kind, resolution, label = _state_defaults(state_text)
    resolution = tags.get("resolution", resolution)
    if resolution not in {"resolved", "lumped"}:
        return None
    return candidate_state(
        parsed.composition,
        parsed.charge,
        tags.get("kind", kind),
        label=tags.get("label", label),
        resolution=resolution,
        phase=tags.get("phase", "gas"),
        structure=tags.get("structure"),
    )


def declared_state_target(
    written: str, declaration: dict, *, default_phase: str = "unknown"
) -> StateCandidate | None:
    """Identify a formula/state declaration without choosing evidence or quantities.

    Identity suffixes and separately declared fields must agree. The calling
    source adapter states its phase scope; an unspecified snapshot phase stays
    unknown. A source query is not a physical target declaration.
    """
    candidate = parse_state_id(written)
    if candidate is None:
        return None
    _validate_target_declaration(candidate, declaration)
    phase = declaration.get("phase")
    if phase is None:
        phase = candidate.phase if ";phase=" in written else default_phase
    structure = declaration.get("structure", candidate.structure)
    for name, value in (("phase", phase), ("structure", structure)):
        if value is not None and (not isinstance(value, str) or not value.strip()):
            raise ValueError(f"state declaration {name} must be nonempty text")
        if f";{name}=" in written and value != getattr(candidate, name):
            raise ValueError(f"state declaration {name} contradicts its physical target")
    return candidate_state(
        candidate.composition,
        candidate.charge,
        candidate.state.kind,
        label=candidate.state.label,
        resolution=candidate.state.resolution,
        phase=phase,
        structure=structure,
    )


def _validate_target_declaration(candidate: StateCandidate, declaration: dict) -> None:
    composition = declaration.get("composition")
    if composition is not None and (
        not isinstance(composition, dict)
        or any(type(value) is not int or value <= 0 for value in composition.values())
        or composition != candidate.composition
    ):
        raise ValueError("state declaration composition contradicts its physical target")
    charge = declaration.get("charge")
    if charge is not None and (type(charge) is not int or charge != candidate.charge):
        raise ValueError("state declaration charge contradicts its physical target")
    state = declaration.get("state")
    if state is not None and (
        not isinstance(state, dict)
        or set(state) - {"kind", "resolution", "label"}
        or any(getattr(candidate.state, name, None) != value for name, value in state.items())
    ):
        raise ValueError("state declaration contradicts its physical target")


def _state_defaults(name: str) -> tuple[str, str, str]:
    if name == "ground":
        return "ground", "resolved", ""
    if name in {"vibrational", "electronic", "metastable", "resonant"}:
        return name, "lumped", ""
    return "resolved", "resolved", name


def _parse_identity_suffix(text: str) -> tuple[str, dict[str, str]] | None:
    """Read canonical identity tags without treating them as state labels."""
    state, *fields = text.split(";")
    values: dict[str, str] = {}
    for field in fields:
        key, equals, value = field.partition("=")
        if (
            not equals
            or (not value and key != "label")
            or key not in {"kind", "resolution", "label", "phase", "structure"}
            or key in values
        ):
            return None
        values[key] = unquote(value)
    return unquote(state), values


def electron_state() -> StateCandidate:
    return StateCandidate(
        id=ELECTRON,
        composition={},
        charge=-1,
        state=CandidateState("electron", "resolved", "electron"),
        classes=frozenset({"electron"}),
        origin="mechanical",
        depth=0,
        introduced_by=("input",),
    )


def is_atom(composition: Composition) -> bool:
    return sum(composition.values()) == 1


def is_noble(composition: Composition) -> bool:
    return is_atom(composition) and next(iter(composition)) in NOBLE_GASES


def formula_scope(composition: Composition) -> str:
    """Small structural scope in which bond operations have a clear meaning."""

    atoms = sum(composition.values())
    if atoms == 0:
        return "particle"
    if atoms == 1:
        return "atom"
    if atoms == 2:
        return "diatomic"
    if _central_ligand(composition) is not None:
        return "central_ligand"
    return "formula_only"


def _central_ligand(composition: Composition) -> str | None:
    """Terminal element for an unambiguous homoleptic ``AXn`` formula."""

    pair = _central_ligand_pair(composition)
    return pair[1] if pair is not None else None


def _central_ligand_pair(composition: Composition) -> tuple[str, str] | None:
    if len(composition) != 2:
        return None
    centres = [element for element, count in composition.items() if count == 1]
    if len(centres) != 1:
        return None
    ligand = next(element for element in composition if element != centres[0])
    return (centres[0], ligand) if ligand in TERMINAL_ELEMENTS else None


def merge(left: Composition, right: Composition) -> Composition:
    merged = dict(left)
    for element, count in right.items():
        merged[element] = merged.get(element, 0) + count
    return {element: count for element, count in merged.items() if count}


def composition_groups(composition: Composition, max_atoms: int) -> Iterator[Composition]:
    """Enumerate bounded nonempty inventory groups, without asserting a bond."""
    elements = sorted(composition)
    for counts in product(*(range(composition[element] + 1) for element in elements)):
        if 0 < sum(counts) <= max_atoms:
            yield {
                element: count for element, count in zip(elements, counts, strict=False) if count
            }


def subtract(composition: Composition, group: Composition) -> Composition:
    """Subtract a contained inventory; negative counts are an implementation error."""
    result = dict(composition)
    for element, count in group.items():
        if result.get(element, 0) < count:
            raise ValueError("group is not contained in the parent inventory")
        result[element] -= count
    return {element: count for element, count in result.items() if count}


def composition_partitions(
    composition: Composition, fragments: int = 2
) -> Iterator[tuple[Composition, ...]]:
    """Lazy unordered partitions into nonempty inventories, not bond cleavage.

    Each element count is distributed directly, so identical atoms do not
    create factorially many duplicate atom-labelled partitions.
    """
    if fragments not in {2, 3}:
        raise ValueError("the candidate grammar supports two or three fragments")
    if sum(composition.values()) < fragments:
        return
    elements = sorted(composition)
    buckets: list[Composition] = [{} for _ in range(fragments)]

    def distribute(index: int) -> Iterator[tuple[Composition, ...]]:
        if index == len(elements):
            keys = [tuple(sorted(bucket.items())) for bucket in buckets]
            if all(keys) and keys == sorted(keys):
                yield tuple(dict(bucket) for bucket in buckets)
            return
        element = elements[index]
        for allocation in _allocations(composition[element], fragments):
            for bucket, count in zip(buckets, allocation, strict=False):
                if count:
                    bucket[element] = count
                else:
                    bucket.pop(element, None)
            yield from distribute(index + 1)

    yield from distribute(0)


def _allocations(count: int, buckets: int) -> Iterator[tuple[int, ...]]:
    if buckets == 1:
        yield (count,)
    else:
        for first in range(count + 1):
            for rest in _allocations(count - first, buckets - 1):
                yield (first, *rest)


def reaction_declaration_matches(
    declaration: dict[str, str | None],
    target: ReactionCandidate,
    *,
    comparison: Callable[[EquationKey], EquationKey] | None = None,
) -> bool:
    """Compare explicit target assertions; never interpret a source's free-text declaration.

    Missing fields make no assertion. An enclosing channel supplies the context,
    while every explicitly stated equation, process or physical condition must agree.
    This only identifies the quantity's target; it does not approve the reaction.
    """
    if "reaction_id" in declaration and declaration["reaction_id"] != reaction_id(target.key):
        return False
    if written := declaration.get("reaction"):
        parsed = parse_equation(written)
        if parsed is None:
            return False
        parsed_equation = parsed[0]
        equation = (parsed_equation[0], target.surface, parsed_equation[2], parsed_equation[3])
        if equation != target.equation_key and (
            comparison is None or comparison(equation) != comparison(target.equation_key)
        ):
            return False
    if (family := declaration.get("family")) and canonical_family(family) != target.family:
        return False
    if (process := declaration.get("type")) and canonical_process(
        process,
        family=declaration.get("family") or "",
        third_body=target.third_body,
        surface=target.surface,
    ) != target.process:
        return False
    if "stabilization" in declaration:
        stabilization = declaration["stabilization"]
        stabilization = stabilization or (
            "unspecified" if target.process in {"attachment", "recombination"} else None
        )
        if stabilization != target.stabilization:
            return False
    return all(
        name not in declaration or declaration[name] == getattr(target, name)
        for name in ("third_body", "surface")
    )


def electron_partition_process(
    parent_charge: int, outgoing: float, fragment_charges: Iterable[int]
) -> str:
    """Classify a charge-balanced split with one incident and up to two outgoing electrons.

    The positive/negative fragment pair of a neutral parent with one outgoing
    electron has its own class. IUPAC Orange Book, section 12.3.1.
    """
    if outgoing == 0:
        return "dissociative_recombination" if parent_charge > 0 else "dissociative_attachment"
    if outgoing == 2:
        return "dissociative_detachment" if parent_charge < 0 else "dissociative_ionization"
    return "ion_pair_formation" if parent_charge == 0 and any(fragment_charges) else "dissociation"


def reaction_family(equation: EquationKey) -> str:
    """Identify a collision family from canonical participants, not auxiliary records."""
    if equation[1] is not None:
        return "surface"
    identifiers = {name for name, _count in equation[2]}
    if ELECTRON in identifiers:
        return "electron"
    reactants = [parse_state_id(identifier) for identifier in identifiers]
    if any(state is None for state in reactants):
        raise ValueError("reaction family requires identified canonical participant states")
    return "ion" if any(state is not None and state.charge for state in reactants) else "neutral"
