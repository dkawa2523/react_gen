"""Small, deterministic chemistry grammar used by candidate generation.

The functions in this module know formulas, bounded bond breaking and a simple
valence ceiling.  They intentionally know nothing about Registry records,
thermochemistry or kinetics.
"""

from __future__ import annotations

from reactgen import naming
from reactgen.model import ELECTRON, CandidateState, StateCandidate

Composition = dict[str, int]

NOBLE_GASES = frozenset({"He", "Ne", "Ar", "Kr", "Xe"})
DIATOMIC_ELEMENTS = frozenset({"H", "N", "O", "F", "Cl", "Br", "I"})
LIGANDS = frozenset({"H", "F", "Cl", "Br", "I"})
TERMINAL_ELEMENTS = LIGANDS | {"O"}
TERMINAL_BOND_ORDER = dict.fromkeys(LIGANDS, 1) | {"O": 2}

# Generation needs electron parity, not a path-dependent ``radical`` label.
# This compact periodic order covers every element accepted by naming.py.
PERIODIC_ORDER = (
    "H",
    "He",
    "Li",
    "Be",
    "B",
    "C",
    "N",
    "O",
    "F",
    "Ne",
    "Na",
    "Mg",
    "Al",
    "Si",
    "P",
    "S",
    "Cl",
    "Ar",
    "K",
    "Ca",
    "Sc",
    "Ti",
    "V",
    "Cr",
    "Mn",
    "Fe",
    "Co",
    "Ni",
    "Cu",
    "Zn",
    "Ga",
    "Ge",
    "As",
    "Se",
    "Br",
    "Kr",
    "Rb",
    "Sr",
    "Y",
    "Zr",
    "Nb",
    "Mo",
    "Tc",
    "Ru",
    "Rh",
    "Pd",
    "Ag",
    "Cd",
    "In",
    "Sn",
    "Sb",
    "Te",
    "I",
    "Xe",
    "Cs",
    "Ba",
    "La",
    "Ce",
    "Pr",
    "Nd",
    "Pm",
    "Sm",
    "Eu",
    "Gd",
    "Tb",
    "Dy",
    "Ho",
    "Er",
    "Tm",
    "Yb",
    "Lu",
    "Hf",
    "Ta",
    "W",
    "Re",
    "Os",
    "Ir",
    "Pt",
    "Au",
    "Hg",
    "Tl",
    "Pb",
    "Bi",
)
ATOMIC_NUMBER = {element: number for number, element in enumerate(PERIODIC_ORDER, 1)}

# Even-electron open-shell ground states that matter to the supported plasma
# feeds and their primary fragments.  Odd-electron species need no table.
KNOWN_OPEN_SHELL = frozenset({"C", "O", "Si", "S", "Ge", "Se", "O2"})
KNOWN_CLOSED_SHELL = NOBLE_GASES | frozenset({"H2", "N2", "F2", "Cl2", "Br2", "I2"})

VALENCE = {
    "H": 1,
    "F": 1,
    "Cl": 1,
    "Br": 1,
    "I": 1,
    "O": 2,
    "S": 6,
    "Se": 2,
    "N": 3,
    "P": 5,
    "B": 3,
    "C": 4,
    "Si": 4,
    "Ge": 4,
    "He": 0,
    "Ne": 0,
    "Ar": 0,
    "Kr": 0,
    "Xe": 0,
}

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
    magnitude = "" if abs(charge) == 1 else str(abs(charge))
    return f"{base}{magnitude}{sign}"


def state_id(
    composition: Composition,
    charge: int,
    kind: str = "ground",
    label: str = "",
) -> str:
    if not composition and charge == -1:
        return ELECTRON
    state_name = label or kind
    return f"{charged_formula(composition, charge)}@{state_name}"


def candidate_state(
    composition: Composition,
    charge: int,
    kind: str = "ground",
    *,
    label: str = "",
    resolution: str = "lumped",
    classes: frozenset[str] = frozenset(),
    origin: str = "mechanical",
    depth: int = 0,
    introduced_by: tuple[str, ...] = (),
) -> StateCandidate:
    return StateCandidate(
        id=state_id(composition, charge, kind, label),
        composition=dict(composition),
        charge=charge,
        state=CandidateState(kind, resolution, label),
        classes=classes,
        origin=origin,
        depth=depth,
        introduced_by=introduced_by,
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
    if state_text == "ground":
        return candidate_state(parsed.composition, parsed.charge, "ground", resolution="resolved")
    if state_text in {"vibrational", "electronic", "metastable", "resonant"}:
        return candidate_state(parsed.composition, parsed.charge, state_text, resolution="lumped")
    return candidate_state(
        parsed.composition,
        parsed.charge,
        "resolved",
        label=naming.normalize_state(state_text) or state_text,
        resolution="resolved",
    )


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


def neutral_reactive_candidate(composition: Composition) -> bool:
    """Formula-level reactivity used to expand neutral collision candidates.

    This is deliberately not a spin-state claim. Odd electron count, a
    non-noble atom, or unused valence in an unambiguous AXn formula is enough to
    keep a species such as CF2 or SiH2 active in the mechanical frontier. More
    detailed electronic-state and kinetic questions remain evidence judgements.
    """

    if is_atom(composition):
        return not is_noble(composition)
    count = electron_count(composition)
    if count is not None and count % 2:
        return True
    pair = _central_ligand_pair(composition)
    if pair is None:
        return False
    centre, ligand = pair
    capacity = VALENCE.get(centre)
    occupied = composition[ligand] * TERMINAL_BOND_ORDER[ligand]
    return capacity is not None and occupied < capacity


def is_noble_ligand_complex(composition: Composition) -> bool:
    """Whether a diatomic composition is meaningful only as a charged complex."""

    return (
        sum(composition.values()) == 2
        and len(composition) == 2
        and any(element in NOBLE_GASES for element in composition)
        and any(element in LIGANDS for element in composition)
    )


def electron_count(composition: Composition, charge: int = 0) -> int | None:
    if any(element not in ATOMIC_NUMBER for element in composition):
        return None
    return sum(ATOMIC_NUMBER[element] * count for element, count in composition.items()) - charge


def electronic_character(composition: Composition, charge: int = 0) -> str:
    """Return only what formula-level electron bookkeeping can establish.

    Odd electron count proves an open shell.  Even count alone does not prove a
    closed shell, so only a few elementary ground states are asserted here.
    Everything else stays unknown for the State evidence layer.
    """

    count = electron_count(composition, charge)
    if count is None:
        return "unknown"
    if count % 2:
        return "open_shell"
    written = formula(composition)
    if written in KNOWN_OPEN_SHELL:
        return "open_shell"
    if written in KNOWN_CLOSED_SHELL:
        return "closed_shell"
    return "unknown"


def bond_splits(
    composition: Composition,
    max_leaving: int = 2,
) -> list[tuple[Composition, Composition]]:
    """Bounded ligand loss from a molecular formula."""

    kind = formula_scope(composition)
    if kind == "atom" or kind == "formula_only":
        return []
    if kind == "diatomic":
        elements = list(composition)
        if len(elements) == 1:
            element = elements[0]
            return [({element: 1}, {element: 1})]
        leaving = max(elements, key=lambda item: ELECTRONEGATIVITY.get(item, 2.0))
        heavy_element = next(item for item in elements if item != leaving)
        return [({heavy_element: 1}, {leaving: 1})]
    ligand = _central_ligand(composition)
    if ligand is None:
        return []
    found = []
    for count in range(1, min(max_leaving, composition[ligand]) + 1):
        core = {**composition, ligand: composition[ligand] - count}
        core = {element: number for element, number in core.items() if number}
        if core:
            found.append((core, {ligand: count}))
    return found


def leaving_products(composition: Composition) -> list[Composition]:
    """A two-atom leaving group may be a real homonuclear molecule."""

    ((element, count),) = composition.items()
    if count == 2 and element in DIATOMIC_ELEMENTS:
        return [dict(composition)]
    return [{element: 1} for _ in range(count)]


def merge(left: Composition, right: Composition) -> Composition:
    merged = dict(left)
    for element, count in right.items():
        merged[element] = merged.get(element, 0) + count
    return {element: count for element, count in merged.items() if count}


def subtract(left: Composition, right: Composition) -> Composition | None:
    result = dict(left)
    for element, count in right.items():
        remaining = result.get(element, 0) - count
        if remaining < 0:
            return None
        if remaining:
            result[element] = remaining
        else:
            result.pop(element, None)
    return result or None


def plausible(composition: Composition, *, charged_noble: bool = False) -> bool:
    """A small valence ceiling; unknown central elements are not guessed."""

    if charged_noble and sum(composition.values()) == 2:
        noble = [element for element in composition if element in NOBLE_GASES]
        ligand = [element for element in composition if element not in NOBLE_GASES]
        if len(noble) == len(ligand) == 1 and ligand[0] in LIGANDS:
            return True
    if any(element in NOBLE_GASES for element in composition) and sum(composition.values()) > 1:
        return False
    if len(composition) == 1:
        return sum(composition.values()) <= 2
    ligands = sum(count for element, count in composition.items() if element in LIGANDS)
    skeleton = {element: count for element, count in composition.items() if element not in LIGANDS}
    if not skeleton:
        return sum(composition.values()) <= 2
    if any(element not in VALENCE for element in skeleton):
        return True
    centres = sum(skeleton.values())
    capacity = sum(VALENCE[element] * count for element, count in skeleton.items())
    capacity -= 2 * (centres - 1)
    return ligands <= capacity


def ligand_transfers(
    donor: Composition,
    acceptor: Composition,
    *,
    charged_acceptor: bool = False,
) -> list[tuple[Composition, Composition]]:
    """Move one ligand from donor to acceptor without association or growth."""

    if (is_noble(acceptor) and not charged_acceptor) or formula_scope(donor) == "formula_only":
        return []
    products = []
    largest_reactant = max(sum(donor.values()), sum(acceptor.values()))
    for remainder, leaving in bond_splits(donor, 1):
        moved = merge(acceptor, leaving)
        swapped = remainder == acceptor and moved == donor
        if (
            not swapped
            and sum(moved.values()) <= largest_reactant
            and plausible(remainder)
            and plausible(moved, charged_noble=charged_acceptor)
        ):
            products.append((remainder, moved))
    return products


def bond_exchanges(
    left: Composition,
    right: Composition,
) -> list[tuple[Composition, Composition]]:
    """Exchange one bounded leaving group between two collision partners."""

    products = []
    left_size = sum(left.values())
    right_size = sum(right.values())
    for left_core, left_group in bond_splits(left, 1):
        for right_core, right_group in bond_splits(right, 1):
            left_product = merge(left_core, right_group)
            right_product = merge(right_core, left_group)
            unchanged = left_product == left and right_product == right
            if (
                not unchanged
                and sum(left_product.values()) <= left_size
                and sum(right_product.values()) <= right_size
                and plausible(left_product)
                and plausible(right_product)
            ):
                products.append((left_product, right_product))
    return products
