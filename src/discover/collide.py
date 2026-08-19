"""What two colliding partners can come out as, under one rule.

Charge transfer, dissociative charge transfer, ligand transfer, association and
collision-induced dissociation were five generators with five energy formulas.
They are one operation: take the atoms of both partners, split them into pieces
the bonds allow, recombine the pieces, and put the charge somewhere. Every one
of the five formulas falls out of a single enthalpy difference::

    Delta H = sum Hf(products) - sum Hf(reactants)
    Hf(A+) = Hf(A) + IE(A)        Hf(A-) = Hf(A) - EA(A)

Charge transfer expands to ``IE(B) - IE(A)``, mutual neutralization to
``EA(B) - IE(A)``, and Penning to ``IE(X) - E_exc`` — the same numbers the hand
written screens produced, now derived rather than restated.

Nothing is discarded for being endothermic. This list is what DNT+ is asked to
compute cross sections for, and an endothermic channel is exactly a channel
with a threshold: deleting it throws away the calculation it was pointing at.
The bound is on how far uphill to carry, not on the sign.
"""

from __future__ import annotations

from dataclasses import dataclass

from discover.fragments import _bonds as bond_splits
from discover.fragments import formula

Composition = dict[str, int]

# How many bonds an atom of each element forms. Recombination is otherwise free
# to write CF5 and C2F7, which are not species: a mechanical rule that ignores
# valence puts things in the list that cannot exist.
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
LIGANDS = frozenset({"H", "F", "Cl", "Br", "I"})


@dataclass(frozen=True)
class Partner:
    id: str
    composition: Composition
    charge: int


@dataclass(frozen=True)
class Piece:
    """One product: its formula, its charge, and whether it is registered."""

    composition: Composition
    charge: int

    @property
    def written(self) -> str:
        name = formula(self.composition)
        if self.charge > 0:
            return name + "+" * self.charge
        return name + "-" * -self.charge if self.charge < 0 else name


@dataclass(frozen=True)
class Channel:
    """One way the collision can come out, with the energy it costs."""

    products: tuple[Piece, ...]
    delta_h_eV: float | None

    @property
    def threshold_eV(self) -> float | None:
        """Where the cross section opens. Zero for anything downhill."""
        return None if self.delta_h_eV is None else max(0.0, self.delta_h_eV)


@dataclass(frozen=True)
class Energies:
    """The one table the screen needs: neutral enthalpies, and the ion steps."""

    enthalpy: dict[str, float]
    ionization: dict[str, float]
    affinity: dict[str, float]
    name_of: dict[tuple, str]  # (composition, charge) -> registered id

    def written(self, piece: Piece) -> str:
        key = (tuple(sorted(piece.composition.items())), piece.charge)
        return self.name_of.get(key, piece.written)

    def neutral(self, piece: Piece) -> str:
        key = (tuple(sorted(piece.composition.items())), 0)
        return self.name_of.get(key, formula(piece.composition))

    def of(self, piece: Piece) -> float | None:
        return enthalpy(
            self.neutral(piece),
            piece.charge,
            self.enthalpy,
            self.ionization,
            self.affinity,
        )


def channels(
    left: Partner,
    right: Partner,
    energies: Energies | None = None,
    max_leaving: int = 2,
) -> list[Channel]:
    """Every recombination of the two partners' pieces, charge placed each way.

    Both partners are split by the bonds their formula allows, the pieces are
    regrouped into two or three products, and the total charge is put on each
    product in turn. Conservation is by construction: the pieces are the atoms.
    """

    seen: set[tuple] = set()
    out = []
    total = left.charge + right.charge
    for grouping in _groupings(left.composition, right.composition, max_leaving):
        if not all(plausible(part) for part in grouping):
            continue
        for placement in _placements(grouping, total):
            key = tuple(sorted((tuple(sorted(p.composition.items())), p.charge) for p in placement))
            if key in seen:
                continue
            seen.add(key)
            out.append(Channel(tuple(placement), _delta(left, right, placement, energies)))
    return out


def _delta(
    left: Partner, right: Partner, products: list[Piece], energies: Energies | None
) -> float | None:
    """One enthalpy difference, with the terms that cancel never looked up.

    Written out, the difference is a sum over neutral skeletons plus a sum over
    the cost of charging them. Charge transfer leaves the skeletons untouched,
    so the enthalpy terms cancel exactly and only ionization energies are
    needed. Evaluating the absolute enthalpies first would demand data the
    answer does not depend on, and refuse a channel it could have settled.
    """

    if energies is None:
        return None

    skeletons: dict[str, int] = {}
    charging = 0.0
    sides = (
        (products, 1, ("", "")),
        ([_as_piece(left), _as_piece(right)], -1, (left.id, right.id)),
    )
    for pieces, sign, ids in sides:
        for index, piece in enumerate(pieces):
            # A partner recorded under its own name brings its own enthalpy, and
            # for an ion that already includes the cost of charging it. Adding
            # the ionization energy on top would count it twice, so the term is
            # only applied when the enthalpy came from the neutral skeleton.
            named = ids[index] if index < len(ids) else ""
            exact = named in energies.enthalpy
            name = named if exact else energies.neutral(piece)
            skeletons[name] = skeletons.get(name, 0) + sign
            if piece.charge and not exact:
                step = _charging(name, piece.charge, energies)
                if step is None:
                    return None
                charging += sign * step

    total = charging
    for name, count in skeletons.items():
        if not count:
            continue  # present on both sides; its enthalpy cannot matter
        value = energies.enthalpy.get(name)
        if value is None:
            return None
        total += count * value
    return total


def _charging(name: str, charge: int, energies: Energies) -> float | None:
    """What it costs to put this charge on the neutral."""

    table = energies.ionization if charge > 0 else energies.affinity
    step = table.get(name)
    return None if step is None else charge * step


def _as_piece(partner: Partner) -> Piece:
    return Piece(dict(partner.composition), partner.charge)


def _parent(partner: Partner) -> str:
    """The neutral an ion's enthalpy is built from."""

    return formula(partner.composition)


def _groupings(left: Composition, right: Composition, max_leaving: int) -> list[list[Composition]]:
    """Ways to regroup both partners' atoms, bounded by what one collision does.

    A thermal-to-few-eV encounter breaks a bond or two, so the pieces come from
    the same bond enumeration electron impact uses. Five outcomes cover the
    families: nothing moves, they stick together, either one comes apart, or
    they swap a group. Charge placement is a separate step, which is why charge
    transfer needs no rule of its own.
    """

    whole_left, whole_right = dict(left), dict(right)
    groupings: list[list[Composition]] = [
        [whole_left, whole_right],  # unchanged pieces; the charge may still move
        [_merge(whole_left, whole_right)],  # association
    ]
    left_splits = bond_splits(left, max_leaving)
    right_splits = bond_splits(right, max_leaving)

    groupings += [[heavy, light, whole_right] for heavy, light in left_splits]
    groupings += [[whole_left, heavy, light] for heavy, light in right_splits]
    for a_heavy, a_light in left_splits:
        for b_heavy, b_light in right_splits:
            groupings.append([_merge(a_heavy, b_light), _merge(b_heavy, a_light)])

    unique: dict[tuple, list[Composition]] = {}
    for grouping in groupings:
        parts = [part for part in grouping if part]
        if parts:
            unique.setdefault(_key(parts), parts)
    return list(unique.values())


def _placements(grouping: list[Composition], total: int) -> list[list[Piece]]:
    """The total charge on each product in turn."""

    if not grouping:
        return []
    out = []
    for index in range(len(grouping)):
        out.append(
            [
                Piece(dict(part), total if position == index else 0)
                for position, part in enumerate(grouping)
            ]
        )
    return out


def plausible(composition: Composition) -> bool:
    """Whether a skeleton can carry this many ligands.

    An acyclic skeleton of ``m`` central atoms offers ``m * valence - 2(m - 1)``
    places once its own bonds are counted, so CF5 and C2F7 are refused while
    SF6 and C2F6 are not. Unknown elements are left alone rather than guessed at.
    """

    ligands = sum(count for element, count in composition.items() if element in LIGANDS)
    skeleton = {e: n for e, n in composition.items() if e not in LIGANDS}
    if not skeleton:
        return sum(composition.values()) <= 2  # F2 and its kind; F3 is not a species
    if any(element not in VALENCE for element in skeleton):
        return True
    centres = sum(skeleton.values())
    capacity = sum(VALENCE[e] * n for e, n in skeleton.items()) - 2 * (centres - 1)
    return ligands <= capacity


def _merge(left: Composition, right: Composition) -> Composition:
    merged = dict(left)
    for element, count in right.items():
        merged[element] = merged.get(element, 0) + count
    return {k: v for k, v in merged.items() if v}


def _key(grouping: list[Composition]) -> tuple:
    return tuple(sorted(tuple(sorted(part.items())) for part in grouping))


def enthalpy(
    neutral_id: str,
    charge: int,
    hf: dict[str, float],
    ionization: dict[str, float],
    affinity: dict[str, float],
) -> float | None:
    """Formation enthalpy of a species, ions included.

    An ion is not a separate measurement: it is the neutral plus the cost of
    taking an electron off, or minus what binding one releases.
    """

    if neutral_id == "e":
        return 0.0
    base = hf.get(neutral_id)
    if base is None:
        return None
    if charge > 0:
        step = ionization.get(neutral_id)
        return None if step is None else base + charge * step
    if charge < 0:
        step = affinity.get(neutral_id)
        return None if step is None else base + charge * step
    return base


# What a source would call each outcome. The enumeration does not need these —
# one enthalpy difference covers them all — but the reaction list is read by
# people and consumed by `reactgen.dnt`, and both sort by process name.
def classify(left: Partner, right: Partner, channel: Channel) -> str:
    products = channel.products
    if len(products) == 1:
        return "association"
    started = {left.charge, right.charge}
    if started == {1, -1} or started == {-1, 1}:
        return "mutual_neutralization"
    if 0 in started and any(c != 0 for c in started):
        moved = _charge_moved(left, right, products)
        if len(products) == 2 and _same_skeletons(left, right, products):
            return "charge_transfer" if moved else "elastic"
        return "dissociative_charge_transfer" if moved else "reactive_scattering"
    return "reactive_scattering"


def dnt_class(channel: Channel, kind: str) -> str:
    """Which DNT+ tier has to produce this channel.

    Charge exchange with both partners intact is a long-range process the
    capture model already reaches. Anything that breaks or makes a bond needs
    the short-range potential.
    """

    if kind == "elastic":
        return "elastic"
    return (
        "long_range_charge_exchange" if kind == "charge_transfer" else "short_range_charge_exchange"
    )


def _charge_moved(left: Partner, right: Partner, products: tuple[Piece, ...]) -> bool:
    """Whether the charge ended up on a different skeleton than it started on.

    Equality, not containment. ``CF4+ + CF2 -> CF4 + CF2+`` moves the charge
    even though CF2's atoms are a subset of CF4's, and reading that as "still
    on the same partner" lost every transfer onto a smaller fragment.
    """

    charged = next((p for p in products if p.charge != 0), None)
    if charged is None:
        return False
    origin = left if left.charge != 0 else right
    return dict(charged.composition) != dict(origin.composition)


def _same_skeletons(left: Partner, right: Partner, products: tuple[Piece, ...]) -> bool:
    before = sorted(tuple(sorted(p.items())) for p in (left.composition, right.composition))
    after = sorted(tuple(sorted(p.composition.items())) for p in products)
    return before == after
