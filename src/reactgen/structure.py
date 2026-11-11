"""Optional, local graph edits on explicitly supplied SMILES.

RDKit owns graph parsing/canonicalisation. The recipes below own only declared
Lewis bond/charge/radical changes; they do not identify spin, a minimum or a
reaction mechanism. Atomic maps survive in the returned transformation.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, replace
from functools import lru_cache
from importlib import import_module
from itertools import combinations
from typing import Any, Literal

from reactgen.balance import nuclide_correspondence
from reactgen.chemistry import candidate_state, is_atom, parse_state_id, state_id
from reactgen.model import (
    EquationKey,
    ReactionCandidate,
    ReactionKey,
    StateCandidate,
    StateKey,
    Term,
    side_key,
)


class StructureUnavailable(ValueError):
    """A graph operation needs an unavailable dependency or representation."""


@dataclass(frozen=True)
class GraphEdit:
    process: str
    products: tuple[StateCandidate, ...]
    transformation: dict


@lru_cache(maxsize=1)
def _load_chem() -> tuple[Any, str | None]:
    """Remember binary load failures as well as successful imports for this run."""
    try:
        return import_module("rdkit.Chem"), None
    except ModuleNotFoundError as error:
        if error.name is None or not (error.name.startswith("rdkit") or error.name == "numpy"):
            raise
        return None, "explicit SMILES validation and graph edits require optional RDKit"
    except ImportError as error:
        if not any(
            text in str(error).lower()
            for text in ("dll load failed", "application control", "blocked")
        ):
            raise
        return None, "optional RDKit binary dependency could not load: " + str(error)
    except OSError as error:
        if getattr(error, "winerror", None) not in {126, 193, 206, 577}:
            raise
        return None, "optional RDKit binary dependency could not load: " + str(error)


def _chem() -> Any:
    chem, failure = _load_chem()
    if failure is not None:
        raise StructureUnavailable(failure)
    return chem


def _read(smiles: str) -> Any:
    chem = _chem()
    mol = chem.MolFromSmiles(smiles, sanitize=False)
    if mol is None:
        raise ValueError("invalid SMILES structure")
    mol.UpdatePropertyCache(strict=False)
    expanded = chem.AddHs(mol)
    # Once the graph contains its hydrogen inventory, a later bond or charge
    # edit must not let sanitization infer additional hydrogen atoms.
    for atom in expanded.GetAtoms():
        atom.SetNoImplicit(True)
    return expanded


def bind_structure(state: StateCandidate, smiles: str) -> StateCandidate:
    """Bind a declared structure; an independent returned inventory must agree."""
    mol = _read(smiles)
    _check_inventory(mol, state)
    if _chem().SanitizeMol(mol, catchErrors=True):
        raise StructureUnavailable("RDKit cannot represent this declared Lewis structure")
    for atom in mol.GetAtoms():
        atom.SetAtomMapNum(0)
    canonical = _chem().MolToSmiles(mol, canonical=True)
    return _with_structure(state, "smiles:" + canonical)


def input_structure(state: StateCandidate, mapped: str | None) -> tuple[StateCandidate, str | None]:
    """Check either SMILES declaration and retain explicit ID spellings."""
    inline = state.structure
    if inline is not None and not inline.startswith("smiles:"):
        if mapped is not None:
            raise ValueError("inline and mapped input structures use different representations")
        return state, None
    if inline is None and mapped is None:
        return state, None
    try:
        if inline is None:
            return bind_structure(state, mapped or ""), None
        checked = bind_structure(state, inline.removeprefix("smiles:"))
        if mapped is not None and checked.structure != bind_structure(state, mapped).structure:
            raise ValueError("inline and mapped SMILES describe different input structures")
        return state, None
    except StructureUnavailable as error:
        if mapped is not None:
            declared = "smiles:" + mapped
            if inline is None:
                return _with_structure(state, declared), str(error)
            if inline != declared:
                raise ValueError("cannot reconcile inline and mapped input structures") from error
        return state, str(error)


def _with_structure(state: StateCandidate, structure: str) -> StateCandidate:
    identifier = state_id(
        state.composition,
        state.charge,
        state.state.kind,
        state.state.label,
        resolution=state.state.resolution,
        phase=state.phase,
        structure=structure,
    )
    return replace(state, id=identifier, structure=structure)


def _check_inventory(mol: Any, state: StateCandidate) -> None:
    """Both user and source graphs must describe their declared physical target.

    Nuclides remain in the explicit graph identity, which mapped declarations
    compare separately; the state inventory itself is element-resolved only.
    A contradictory declaration is an input error, not a nonexistent species.
    """
    composition = dict(Counter(atom.GetSymbol() for atom in mol.GetAtoms()))
    charge = sum(atom.GetFormalCharge() for atom in mol.GetAtoms())
    if composition != state.composition or charge != state.charge:
        raise ValueError("SMILES composition or charge contradicts its input state")


def _molecule(state: StateCandidate, start: int = 1) -> Any:
    if not state.structure or not state.structure.startswith("smiles:"):
        raise StructureUnavailable(
            "graph edits require explicit SMILES, not an opaque structure ID"
        )
    mol = _read(state.structure.removeprefix("smiles:"))
    _check_inventory(mol, state)
    if _chem().SanitizeMol(mol, catchErrors=True):
        raise StructureUnavailable("RDKit cannot represent this declared Lewis structure")
    for index, atom in enumerate(mol.GetAtoms(), start):
        atom.SetAtomMapNum(index)
    return mol


def _result(mol: Any, process: str, edits: list[dict], depth: int) -> GraphEdit | None:
    chem = _chem()
    mol.UpdatePropertyCache(strict=False)
    if chem.SanitizeMol(mol, catchErrors=True):
        return None
    products = []
    maps = []
    for fragment in chem.GetMolFrags(mol, asMols=True, sanitizeFrags=False):
        composition = dict(Counter(atom.GetSymbol() for atom in fragment.GetAtoms()))
        charge = sum(atom.GetFormalCharge() for atom in fragment.GetAtoms())
        mapped = chem.MolToSmiles(fragment, canonical=True)
        for atom in fragment.GetAtoms():
            atom.SetAtomMapNum(0)
        structure = "smiles:" + chem.MolToSmiles(fragment, canonical=True)
        state = candidate_state(
            composition,
            charge,
            "composition",
            resolution="lumped",
            structure=structure,
            classes=frozenset({"graph_product"}),
            depth=depth,
            introduced_by=("graph." + process,),
        )
        products.append(state)
        maps.append({"state": state.id, "mapped_smiles": mapped})
    return GraphEdit(
        process,
        tuple(products),
        {
            "kind": "graph_edit",
            "resolution": "lewis_graph",
            "edits": edits,
            "products": maps,
            "scope": "declared Lewis edit; electronic spin and energetic minimum unassigned",
        },
    )


def _from_edits(mol: Any, process: str, edits: list[dict], depth: int) -> GraphEdit | None:
    """The one bond/charge/radical edit implementation for generation and replay."""
    edited = _chem().RWMol(mol)
    indices = {atom.GetAtomMapNum(): atom.GetIdx() for atom in edited.GetAtoms()}
    for edit in edits:
        if not _replay_edit(edited, edit, indices):
            return None
    return _result(edited.GetMol(), process, edits, depth)


def fragment_edits(state: StateCandidate, depth: int) -> Iterator[GraphEdit | None]:
    """Finite homolytic cuts and donor-pair reversals in either graph encoding."""
    chem = _chem()
    mol = _molecule(state)
    mappings = [{"state": state.id, "mapped_smiles": chem.MolToSmiles(mol, canonical=True)}]
    bonds = [
        bond
        for bond in mol.GetBonds()
        if bond.GetBondType() in {chem.BondType.SINGLE, chem.BondType.DATIVE}
    ]
    for count in (1, 2):
        for selected in combinations(bonds, count):
            changes = [
                {
                    "action": "break",
                    "atoms": [bond.GetBeginAtomIdx() + 1, bond.GetEndAtomIdx() + 1],
                    "bond": str(bond.GetBondType()),
                }
                for bond in selected
            ]
            result = _from_edits(mol, "dissociation", changes, depth)
            yield (
                _mapped(result, mappings)
                if result is not None and len(result.products) in {2, 3}
                else None
            )
    for bond in bonds:
        if bond.GetBondType() != chem.BondType.SINGLE:
            continue
        a, b = bond.GetBeginAtomIdx(), bond.GetEndAtomIdx()
        for donor, acceptor in ((a, b), (b, a)):
            result = _from_edits(
                mol,
                "dissociation",
                [{"action": "coordinate_break", "atoms": [donor + 1, acceptor + 1]}],
                depth,
            )
            yield (
                _mapped(result, mappings)
                if result is not None and len(result.products) == 2
                else None
            )


def pair_edits(
    left: StateCandidate, right: StateCandidate, depth: int
) -> Iterator[GraphEdit | None]:
    """Finite local recipes over explicit graphs; no inferred spin/TS model."""
    chem = _chem()
    first = _molecule(left)
    second = _molecule(right, first.GetNumAtoms() + 1)
    combined = chem.CombineMols(first, second)
    mappings = [
        {"state": state.id, "mapped_smiles": chem.MolToSmiles(mol, canonical=True)}
        for state, mol in ((left, first), (right, second))
    ]
    split = first.GetNumAtoms()
    yield from _radical_pair_edits(combined, split, depth, mappings)
    for donor, lo, hi in ((first, split, combined.GetNumAtoms()), (second, 0, split)):
        offset = 0 if donor is first else split
        for bond in donor.GetBonds():
            a, b = bond.GetBeginAtomIdx() + offset, bond.GetEndAtomIdx() + offset
            for attacker in range(lo, hi):
                for result in _bond_attack(combined, attacker, a, b, bond.GetBondType(), depth):
                    yield _mapped(result, mappings)


def _radical_pair_edits(
    combined: Any, split: int, depth: int, mappings: list[dict]
) -> Iterator[GraphEdit | None]:
    for a in range(split):
        for b in range(split, combined.GetNumAtoms()):
            aa, bb = combined.GetAtomWithIdx(a), combined.GetAtomWithIdx(b)
            if aa.GetNumRadicalElectrons() and bb.GetNumRadicalElectrons():
                yield _mapped(_join_radicals(combined, a, b, depth), mappings)
                for result in _disproportionation(combined, a, b, depth):
                    yield _mapped(result, mappings)
                for result in _disproportionation(combined, b, a, depth):
                    yield _mapped(result, mappings)
            if _donor(aa) and _acceptor(bb):
                yield _mapped(_coordinate(combined, a, b, depth), mappings)
            if _donor(bb) and _acceptor(aa):
                yield _mapped(_coordinate(combined, b, a, depth), mappings)


def _mapped(result: GraphEdit | None, mappings: list[dict]) -> GraphEdit | None:
    return (
        None
        if result is None
        else replace(result, transformation={**result.transformation, "reactant_graphs": mappings})
    )


def _join_radicals(mol: Any, a: int, b: int, depth: int) -> GraphEdit | None:
    return _from_edits(
        mol,
        "radical_recombination",
        [{"action": "form", "atoms": [a + 1, b + 1], "bond": "SINGLE"}],
        depth,
    )


def _donor(atom: Any) -> bool:
    ceilings = {"N": 3, "O": 2, "P": 3, "S": 2, "F": 1, "Cl": 1, "Br": 1, "I": 1}
    return (
        atom.GetSymbol() in ceilings
        and atom.GetFormalCharge() <= 0
        and not atom.GetNumRadicalElectrons()
        and atom.GetTotalValence() <= ceilings[atom.GetSymbol()]
    )


def _acceptor(atom: Any) -> bool:
    return (
        atom.GetFormalCharge() > 0
        or (atom.GetSymbol() in {"B", "Al"} and atom.GetTotalValence() < 4)
        or (atom.GetSymbol() in {"Si", "Ge"} and atom.GetTotalValence() <= 4)
    )


def _coordinate(mol: Any, donor: int, acceptor: int, depth: int) -> GraphEdit | None:
    """Encode donation as a single bond and paired formal-charge changes.

    RDKit counts a dative bond at the acceptor, so neutral electron-deficient
    acceptors may exceed its valence table. The charge-separated Lewis encoding
    preserves net charge and donation direction; it is not electron transfer.
    https://www.rdkit.org/docs/RDKit_Book.html#dative-bonds
    https://www.rdkit.org/docs/RDKit_Book.html#valence-calculation-and-allowed-valences
    """
    return _from_edits(
        mol,
        "coordinate_addition",
        [
            {
                "action": "coordinate_form",
                "atoms": [donor + 1, acceptor + 1],
                "bond": "SINGLE",
                "electron_bookkeeping": "donor pair; formal donor +1, acceptor -1",
            }
        ],
        depth,
    )


def _bond_attack(
    mol: Any, attacker: int, a: int, b: int, bond_type: Any, depth: int
) -> Iterator[GraphEdit | None]:
    chem = _chem()
    active = mol.GetAtomWithIdx(attacker)
    if bond_type == chem.BondType.DOUBLE and active.GetNumRadicalElectrons():
        for near, far in ((a, b), (b, a)):
            yield _from_edits(
                mol,
                "radical_addition",
                [{"action": "pi_addition", "atoms": [attacker + 1, near + 1, far + 1]}],
                depth,
            )
    if bond_type != chem.BondType.SINGLE:
        return
    if active.GetNumRadicalElectrons() >= 2:
        yield _insertion(mol, attacker, a, b, depth)
    for centre, leaving in ((a, b), (b, a)):
        yield from _substitution(mol, attacker, centre, leaving, depth)


def _insertion(mol: Any, attacker: int, a: int, b: int, depth: int) -> GraphEdit | None:
    return _from_edits(
        mol, "insertion", [{"action": "insert", "atoms": [a + 1, attacker + 1, b + 1]}], depth
    )


def _substitution(
    mol: Any, attacker: int, centre: int, leaving: int, depth: int
) -> Iterator[GraphEdit | None]:
    active, gone = mol.GetAtomWithIdx(attacker), mol.GetAtomWithIdx(leaving)
    roles = [attacker, centre, leaving]
    if _labelled_atom_exchange(mol, roles):
        if active.GetIsotope() != gone.GetIsotope():
            yield _from_edits(
                mol,
                "isotope_exchange",
                [{"action": "isotope_exchange", "atoms": [index + 1 for index in roles]}],
                depth,
            )
        # An H atom abstracting H from an isotope-labelled hydrogen diatom
        # generates the same graph inventory as a swap (or the input pair).
        # Abstraction from other molecules makes distinct products.
        if gone.GetAtomicNum() == 1 and (
            mol.GetNumAtoms() > 3 or mol.GetAtomWithIdx(centre).GetAtomicNum() != 1
        ):
            yield _hydrogen_transfer(mol, attacker, centre, leaving, depth)
        return
    if active.GetNumRadicalElectrons():
        yield _from_edits(
            mol,
            "substitution",
            [{"action": "substitute", "atoms": [attacker + 1, centre + 1, leaving + 1]}],
            depth,
        )
        if gone.GetSymbol() == "H":
            yield _hydrogen_transfer(mol, attacker, centre, leaving, depth)
    if active.GetFormalCharge() < 0 and gone.GetDegree() == 1:
        yield _from_edits(
            mol,
            "substitution",
            [
                {
                    "action": "heterolytic_substitution",
                    "atoms": [attacker + 1, centre + 1, leaving + 1],
                }
            ],
            depth,
        )


def _hydrogen_transfer(
    mol: Any, attacker: int, centre: int, hydrogen: int, depth: int
) -> GraphEdit | None:
    return _from_edits(
        mol,
        "radical_abstraction",
        [{"action": "hydrogen_transfer", "atoms": [centre + 1, hydrogen + 1, attacker + 1]}],
        depth,
    )


def _disproportionation(
    mol: Any, receiver: int, radical: int, depth: int
) -> Iterator[GraphEdit | None]:
    """Beta-H transfer plus adjacent pi formation consumes two radical electrons."""
    chem = _chem()
    centre = mol.GetAtomWithIdx(radical)
    for beta in centre.GetNeighbors():
        beta_index = beta.GetIdx()
        if mol.GetBondBetweenAtoms(radical, beta_index).GetBondType() != chem.BondType.SINGLE:
            continue
        for hydrogen in beta.GetNeighbors():
            if hydrogen.GetSymbol() != "H":
                continue
            yield _from_edits(
                mol,
                "radical_disproportionation",
                [
                    {
                        "action": "disproportionation",
                        "atoms": [receiver + 1, hydrogen.GetIdx() + 1, beta_index + 1, radical + 1],
                    }
                ],
                depth,
            )


def validate_graph_transformation(
    reactants: tuple[StateCandidate, ...],
    products: tuple[StateCandidate, ...],
    transformation: dict,
    *,
    process: str | None = None,
) -> bool | None:
    """Replay the declared local edit, not a search over reaction recipes.

    True means these atom/charge/radical and bond changes describe these graphs.
    It says nothing about a PES, actual spin, minimum or reaction occurrence.
    """
    try:
        if process is not None and not _process_actions(process, transformation):
            return False
        return _validate_graphs(reactants, products, transformation)
    except StructureUnavailable:
        return None


def _process_actions(process: str, transformation: dict) -> bool:
    actions = {
        "dissociation": {"break", "coordinate_break"},
        "isotope_exchange": {"isotope_exchange"},
        "radical_recombination": {"form"},
        "radical_addition": {"pi_addition"},
        "coordinate_addition": {"form", "coordinate_form"},
        "insertion": {"insert"},
        "radical_abstraction": {"hydrogen_transfer"},
        "substitution": {"substitute", "heterolytic_substitution"},
        "radical_disproportionation": {"disproportionation"},
    }
    edits = transformation.get("edits")
    matches = (
        process in actions
        and isinstance(edits, list)
        and bool(edits)
        and all(isinstance(edit, dict) and edit.get("action") in actions[process] for edit in edits)
    )
    if not matches or not isinstance(edits, list):
        return False
    if process == "isotope_exchange":
        return len(edits) == 1
    if process == "radical_recombination":
        return all(edit.get("bond") == "SINGLE" for edit in edits)
    if process == "coordinate_addition":
        return all(
            edit.get("bond") == ("DATIVE" if edit["action"] == "form" else "SINGLE")
            for edit in edits
        )
    return True


def _validate_graphs(
    reactants: tuple[StateCandidate, ...],
    products: tuple[StateCandidate, ...],
    transformation: dict,
) -> bool | None:
    chem = _chem()
    inputs = transformation.get("reactant_graphs")
    outputs = transformation.get("products")
    edits = transformation.get("edits")
    if not isinstance(inputs, list) or not isinstance(outputs, list):
        return False
    if not isinstance(edits, list) or not edits:
        return False
    starts = _declared_graphs(reactants, inputs)
    ends = _declared_graphs(products, outputs)
    if starts is None or ends is None:
        return None
    if not isinstance(starts, list) or not isinstance(ends, list) or not starts:
        return False
    combined = starts[0]
    for mol in starts[1:]:
        combined = chem.CombineMols(combined, mol)
    indices = {atom.GetAtomMapNum(): atom.GetIdx() for atom in combined.GetAtoms()}
    if 0 in indices or len(indices) != combined.GetNumAtoms():
        return False
    edited = chem.RWMol(combined)
    for declaration in edits:
        if not _replay_edit(edited, declaration, indices):
            return False
    result = _result(edited.GetMol(), "replay", edits, 0)
    if result is None:
        return False
    expected = sorted(item["mapped_smiles"] for item in result.transformation["products"])
    actual = sorted(chem.MolToSmiles(mol, canonical=True) for mol in ends)
    return expected == actual


def _declared_graphs(
    states: tuple[StateCandidate, ...],
    declarations: list,
) -> list[Any] | Literal[False] | None:
    chem = _chem()
    by_id = {state.id: state for state in states if state.composition}
    if Counter(item.get("state") for item in declarations if isinstance(item, dict)) != Counter(
        state.id for state in states if state.composition
    ):
        return False
    result = []
    for declaration in declarations:
        if not isinstance(declaration, dict) or not isinstance(
            declaration.get("mapped_smiles"), str
        ):
            return False
        state = by_id[declaration["state"]]
        # The same explicit-H parser as generation preserves mapped hydrogens.
        # RDKit's default parser removes them and therefore loses edit targets.
        mol = _read(declaration["mapped_smiles"])
        if chem.SanitizeMol(mol, catchErrors=True):
            return False
        if state.structure is None:
            # An element/charge target already identifies an unlabelled atomic
            # graph. An explicit nuclide or any molecular graph needs its own
            # structural identity; neither is inferred from a formula here.
            if (
                sum(state.composition.values()) != 1
                or mol.GetNumAtoms() != 1
                or mol.GetAtomWithIdx(0).GetIsotope()
            ):
                return None
            _check_inventory(mol, state)
        else:
            if not state.structure.startswith("smiles:"):
                return None
            if _unmapped_smiles(mol) != _unmapped_smiles(_molecule(state)):
                return False
        result.append(mol)
    return result


def _unmapped_smiles(mol: Any) -> str:
    mol = _chem().Mol(mol)
    for atom in mol.GetAtoms():
        atom.SetAtomMapNum(0)
    return str(_chem().MolToSmiles(mol, canonical=True))


def structure_key(state: StateCandidate) -> str | None:
    """Canonical explicit graph identity; opaque source IDs are not interpreted."""
    if not state.structure or not state.structure.startswith("smiles:"):
        return None
    return _canonical_smiles_structure(state.key[0], state.charge, state.structure).removeprefix(
        "smiles:"
    )


@lru_cache(maxsize=4096)
def _canonical_smiles_structure(
    composition: tuple[tuple[str, int], ...], charge: int, structure: str
) -> str:
    state = candidate_state(dict(composition), charge, structure=structure)
    return "smiles:" + _unmapped_smiles(_molecule(state))


def _physical_structure(
    composition: tuple[tuple[str, int], ...], charge: int, structure: str
) -> str:
    """Only use an independently validated explicit graph as a comparison alias."""
    if not structure.startswith("smiles:"):
        return structure
    try:
        return _canonical_smiles_structure(composition, charge, structure)
    except ValueError:
        # An unavailable engine or unsupported/invalid declaration establishes
        # no graph equivalence. Input validation owns errors on user structures.
        return structure


def physical_state_key(state: StateCandidate) -> StateKey:
    """Compare explicit graphs while retaining charge, phase and level identity."""
    key = state.key
    if state.structure is None:
        return key
    return (*key[:-1], _physical_structure(key[0], state.charge, state.structure))


def physical_state_id(identifier: str) -> str:
    """Return a comparison ID without changing a source or saved identifier."""
    if ";structure=" not in identifier:
        return identifier
    state = parse_state_id(identifier)
    if state is None or state.structure is None:
        return identifier
    structure = _physical_structure(state.key[0], state.charge, state.structure)
    return _with_structure(state, structure).id if structure != state.structure else identifier


def saved_structure_alias_matches(
    source: str, target: str, *, allow_unverified: bool = True
) -> bool:
    """Check saved comparison axes and verify the alias when RDKit is available."""
    first, second = parse_state_id(source), parse_state_id(target)
    if (
        first is None
        or second is None
        or first.key[:-1] != second.key[:-1]
        or not (first.structure or "").startswith("smiles:")
        or not (second.structure or "").startswith("smiles:")
    ):
        return False
    try:
        _chem()
    except StructureUnavailable:
        # Reading archived results retains the original analysis's binding
        # when its optional graph engine is absent.
        return allow_unverified
    try:
        return _canonical_smiles_structure(first.key[0], first.charge, first.structure or "") == (
            _canonical_smiles_structure(second.key[0], second.charge, second.structure or "")
        )
    except ValueError:
        return False


def saved_supply_structure_matches(
    nominal: StateCandidate,
    mapped: str | None,
    supplied: StateCandidate,
    *,
    recorded_verification: bool,
) -> bool:
    """Check the saved feed against every declared structure without inventing an alias."""
    if mapped is None:
        return nominal.id == supplied.id
    if nominal.key[:-1] != supplied.key[:-1] or (
        nominal.structure is not None and not nominal.structure.startswith("smiles:")
    ):
        return False
    written = _with_structure(nominal, "smiles:" + mapped).id
    declarations = (written, nominal.id) if nominal.structure is not None else (written,)
    return all(
        declared == supplied.id
        or saved_structure_alias_matches(
            declared, supplied.id, allow_unverified=recorded_verification
        )
        for declared in declarations
    )


def bind_physical_state(
    state: StateCandidate, representatives: Mapping[str, StateCandidate]
) -> StateCandidate:
    """Bind a proposal to the explicit analysis spelling or canonical graph spelling."""
    identifier = physical_state_id(state.id)
    representative = representatives.get(identifier)
    if representative is not None:
        return replace(state, id=representative.id, structure=representative.structure)
    if identifier == state.id:
        return state
    return replace(state, id=identifier, structure=physical_state_key(state)[-1])


def physical_equation_key(
    equation: EquationKey, aliases: Mapping[str, str] | None = None
) -> EquationKey:
    """Compare equations over verified graph aliases, preserving full stoichiometry."""
    third_body, surface, reactants, products = equation

    def compare(side: tuple[tuple[str, float], ...]) -> tuple[tuple[str, float], ...]:
        terms = tuple(
            Term(physical_state_id(name) if aliases is None else aliases.get(name, name), count)
            for name, count in side
        )
        return side if terms == side else side_key(terms)

    return third_body, surface, compare(reactants), compare(products)


def physical_reaction_key(
    reaction: ReactionCandidate, aliases: Mapping[str, str] | None = None
) -> ReactionKey:
    """Compare a channel's participants without dropping its channel qualifiers."""
    return (*reaction.key[:5], *physical_equation_key(reaction.equation_key, aliases)[2:])


@lru_cache(maxsize=4096)
def _charge_partner_graph(
    composition: tuple[tuple[str, int], ...], charge: int, structure: str
) -> str:
    molecule = _molecule(candidate_state(dict(composition), charge, structure=structure))
    for atom in molecule.GetAtoms():
        atom.SetFormalCharge(0)
        atom.SetNumRadicalElectrons(0)
    return _unmapped_smiles(molecule)


def endpoint_structure_matches(first: StateKey, second: StateKey) -> bool:
    """Compare structures for endpoint relations, allowing a change in charge.

    Across charge stages, verify both explicit graphs and compare their nuclei,
    bonds and stereochemistry without the Lewis charge and radical assignments.
    Same-charge state identity still uses the full graph.
    """
    left, right = first[-1], second[-1]
    if left == right:
        return True
    if (
        first[1] == second[1]
        or left is None
        or right is None
        or not (left.startswith("smiles:") and right.startswith("smiles:"))
    ):
        return False
    try:
        return _charge_partner_graph(first[0], first[1], left) == _charge_partner_graph(
            second[0], second[1], right
        )
    except ValueError:
        return False


def resonant_charge_correspondence(ion: StateCandidate, neutral: StateCandidate) -> bool | None:
    """Check the same represented nuclear identity for exact resonant exchange.

    Different explicit isotopes give near-resonance, not exact symmetry
    (https://doi.org/10.1021/jp905184a). An unspecified atomic isotope is
    retained as the nominal representative only when both sides omit it.
    """
    if ion.composition != neutral.composition or ion.phase != neutral.phase:
        return False
    isotopes = nuclide_correspondence(ion, neutral)
    if isotopes is not True:
        return isotopes
    if any(state.state.resolution != "resolved" for state in (ion, neutral)):
        return None
    if is_atom(ion.composition):
        return True
    left, right = ion.structure, neutral.structure
    if left is None or right is None:
        return None
    if not (left.startswith("smiles:") and right.startswith("smiles:")):
        return None
    try:
        return _charge_partner_graph(ion.key[0], ion.charge, left) == (
            _charge_partner_graph(neutral.key[0], neutral.charge, right)
        )
    except ValueError:
        return None


def charge_target_correspondence(initial: StateCandidate, final: StateCandidate) -> bool | None:
    """Check an intact target formula, refining it with comparable nuclear identities."""
    if initial.composition != final.composition or initial.phase != final.phase:
        return False
    isotopes = nuclide_correspondence(initial, final)
    if (
        isotopes is False
        or initial.structure == final.structure
        or None in {initial.structure, final.structure}
    ):
        return isotopes
    start, end = nuclear_connectivity(initial), nuclear_connectivity(final)
    return False if start is not None and end is not None and start != end else isotopes


def nuclear_connectivity(state: StateCandidate) -> str | None:
    """Compare atom connectivity across charge stages without Lewis assignments.

    The element graph includes explicit hydrogens. Isotope conservation is
    checked separately, including when only part of the inventory is labelled.
    """
    if not state.structure or not state.structure.startswith("smiles:"):
        return None
    try:
        molecule = _molecule(state)
    except StructureUnavailable:
        return None
    chem = _chem()
    graph = chem.RWMol()
    for atom in molecule.GetAtoms():
        node = chem.Atom(atom.GetAtomicNum())
        node.SetNoImplicit(True)
        graph.AddAtom(node)
    for bond in molecule.GetBonds():
        graph.AddBond(bond.GetBeginAtomIdx(), bond.GetEndAtomIdx(), chem.BondType.SINGLE)
    return str(chem.MolToSmiles(graph, canonical=True))


def _replay_edit(mol: Any, edit: object, indices: dict[int, int]) -> bool:
    if not isinstance(edit, dict) or not isinstance(edit.get("atoms"), list):
        return False
    raw = edit["atoms"]
    if any(type(index) is not int or index not in indices for index in raw):
        return False
    atoms = [indices[index] for index in raw]
    action = edit.get("action")
    if action in {"break", "form"}:
        return _replay_bond(mol, action, atoms, edit.get("bond"))
    if action in {"coordinate_form", "coordinate_break"}:
        return _replay_coordinate(mol, atoms, forming=action == "coordinate_form")
    handlers = {
        "pi_addition": _replay_pi,
        "insert": _replay_insertion,
        "isotope_exchange": _replay_isotope_exchange,
        "substitute": _replay_substitution,
        "heterolytic_substitution": _replay_heterolytic,
        "hydrogen_transfer": _replay_hydrogen,
        "disproportionation": _replay_disproportionation,
    }
    handler = handlers.get(action) if isinstance(action, str) else None
    return handler(mol, atoms) if handler is not None else False


def _adjust(mol: Any, changes: tuple[tuple[int, int, int], ...]) -> bool:
    for index, radical, charge in changes:
        atom = mol.GetAtomWithIdx(index)
        value = atom.GetNumRadicalElectrons() + radical
        if value < 0:
            return False
        atom.SetNumRadicalElectrons(value)
        atom.SetFormalCharge(atom.GetFormalCharge() + charge)
    return True


def _replay_bond(mol: Any, action: str, atoms: list[int], kind: object) -> bool:
    chem = _chem()
    if len(atoms) != 2 or kind not in {"SINGLE", "DATIVE"}:
        return False
    a, b = atoms
    bond = mol.GetBondBetweenAtoms(a, b)
    if action == "break":
        if bond is None or str(bond.GetBondType()) != kind:
            return False
        mol.RemoveBond(a, b)
        sign = 1
    else:
        if bond is not None:
            return False
        if kind == "DATIVE" and not (
            _donor(mol.GetAtomWithIdx(a)) and _acceptor(mol.GetAtomWithIdx(b))
        ):
            return False
        mol.AddBond(a, b, chem.BondType.SINGLE if kind == "SINGLE" else chem.BondType.DATIVE)
        sign = -1
    return kind == "DATIVE" or _adjust(mol, ((a, sign, 0), (b, sign, 0)))


def _replace_bond(mol: Any, old: tuple[int, int], new: tuple[int, int]) -> bool:
    chem = _chem()
    existing = mol.GetBondBetweenAtoms(*old)
    if existing is None or existing.GetBondType() != chem.BondType.SINGLE:
        return False
    if mol.GetBondBetweenAtoms(*new) is not None:
        return False
    mol.RemoveBond(*old)
    mol.AddBond(*new, chem.BondType.SINGLE)
    return True


def _replay_coordinate(mol: Any, atoms: list[int], *, forming: bool) -> bool:
    if len(atoms) != 2:
        return False
    donor, acceptor = atoms
    bond = mol.GetBondBetweenAtoms(donor, acceptor)
    if forming:
        if bond is not None or not (
            _donor(mol.GetAtomWithIdx(donor)) and _acceptor(mol.GetAtomWithIdx(acceptor))
        ):
            return False
        mol.AddBond(donor, acceptor, _chem().BondType.SINGLE)
        return _adjust(mol, ((donor, 0, 1), (acceptor, 0, -1)))
    if bond is None or bond.GetBondType() != _chem().BondType.SINGLE:
        return False
    mol.RemoveBond(donor, acceptor)
    _adjust(mol, ((donor, 0, -1), (acceptor, 0, 1)))
    mol.UpdatePropertyCache(strict=False)
    return _donor(mol.GetAtomWithIdx(donor)) and _acceptor(mol.GetAtomWithIdx(acceptor))


def _replay_pi(mol: Any, atoms: list[int]) -> bool:
    chem = _chem()
    if len(atoms) != 3:
        return False
    attacker, near, far = atoms
    bond = mol.GetBondBetweenAtoms(near, far)
    if bond is None or bond.GetBondType() != chem.BondType.DOUBLE:
        return False
    if mol.GetBondBetweenAtoms(attacker, near) is not None:
        return False
    bond.SetBondType(chem.BondType.SINGLE)
    mol.AddBond(attacker, near, chem.BondType.SINGLE)
    return _adjust(mol, ((attacker, -1, 0), (far, 1, 0)))


def _replay_insertion(mol: Any, atoms: list[int]) -> bool:
    if len(atoms) != 3:
        return False
    a, centre, b = atoms
    if not _replace_bond(mol, (a, b), (a, centre)):
        return False
    if mol.GetBondBetweenAtoms(centre, b) is not None:
        return False
    mol.AddBond(centre, b, _chem().BondType.SINGLE)
    return _adjust(mol, ((centre, -2, 0),))


def _replay_substitution(mol: Any, atoms: list[int]) -> bool:
    if len(atoms) != 3:
        return False
    attacker, centre, leaving = atoms
    return _replace_bond(mol, (centre, leaving), (attacker, centre)) and _adjust(
        mol, ((attacker, -1, 0), (leaving, 1, 0))
    )


def _labelled_atom_exchange(mol: Any, atoms: list[int]) -> bool:
    """One radical atom replacing a terminal nucleus in a neutral molecule."""
    if len(atoms) != 3 or len(set(atoms)) != 3:
        return False
    incoming, _, leaving = (mol.GetAtomWithIdx(index) for index in atoms)
    if not (
        incoming.GetDegree() == 0
        and incoming.GetNumRadicalElectrons() == 1
        and incoming.GetAtomicNum() == leaving.GetAtomicNum()
        and incoming.GetIsotope()
        and leaving.GetIsotope()
        and leaving.GetDegree() == 1
    ):
        return False
    chem = _chem()
    return (
        len(chem.GetMolFrags(mol)) == 2
        and all(
            atom.GetIsotope()
            and not atom.GetFormalCharge()
            and atom.GetChiralTag() == chem.ChiralType.CHI_UNSPECIFIED
            and (atom.GetIdx() == atoms[0] or not atom.GetNumRadicalElectrons())
            for atom in mol.GetAtoms()
        )
        and all(bond.GetStereo() == chem.BondStereo.STEREONONE for bond in mol.GetBonds())
    )


def _replay_isotope_exchange(mol: Any, atoms: list[int]) -> bool:
    if not _labelled_atom_exchange(mol, atoms):
        return False
    incoming, _, leaving = atoms
    return mol.GetAtomWithIdx(incoming).GetIsotope() != mol.GetAtomWithIdx(
        leaving
    ).GetIsotope() and _replay_substitution(mol, atoms)


def _replay_heterolytic(mol: Any, atoms: list[int]) -> bool:
    if len(atoms) != 3:
        return False
    attacker, centre, leaving = atoms
    return _replace_bond(mol, (centre, leaving), (attacker, centre)) and _adjust(
        mol, ((attacker, 0, 1), (leaving, 0, -1))
    )


def _replay_hydrogen(mol: Any, atoms: list[int]) -> bool:
    if len(atoms) != 3:
        return False
    centre, hydrogen, attacker = atoms
    if mol.GetAtomWithIdx(hydrogen).GetSymbol() != "H":
        return False
    return _replace_bond(mol, (centre, hydrogen), (attacker, hydrogen)) and _adjust(
        mol, ((attacker, -1, 0), (centre, 1, 0))
    )


def _replay_disproportionation(mol: Any, atoms: list[int]) -> bool:
    if len(atoms) != 4:
        return False
    receiver, hydrogen, beta, radical = atoms
    if mol.GetAtomWithIdx(hydrogen).GetSymbol() != "H":
        return False
    bond = mol.GetBondBetweenAtoms(beta, radical)
    if bond is None or bond.GetBondType() != _chem().BondType.SINGLE:
        return False
    if not _replace_bond(mol, (beta, hydrogen), (receiver, hydrogen)):
        return False
    bond.SetBondType(_chem().BondType.DOUBLE)
    return _adjust(mol, ((receiver, -1, 0), (radical, -1, 0)))
