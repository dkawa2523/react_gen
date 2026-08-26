"""Normalized, read-only evidence records.

Registry YAML, reviewed overlays and imported snapshots meet here.  The rest of
the pipeline therefore handles one numerical-data shape and never branches on
where a record came from.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path

from reactgen.model import (
    EquationKey,
    StateCandidate,
    Term,
    canonical_family,
    canonical_process,
)

REVIEWED_TIERS = frozenset({"curated", "reviewed"})
TIER_RANK = {"curated": 0, "reviewed": 1, "derived": 2, "estimated": 3, "imported": 4}


@dataclass(frozen=True)
class Property:
    value: float | None = None
    unit: str | None = None
    source: str | None = None
    qualifier: str | None = None
    uncertainty: Uncertainty | None = None
    tier: str = "imported"

    @property
    def known(self) -> bool:
        return self.value is not None


@dataclass(frozen=True)
class Thermo:
    low: tuple[float, ...]
    high: tuple[float, ...]
    t_min: float
    t_mid: float
    t_max: float
    source: str | None = None
    tier: str = "imported"

    def coefficients(self, temperature_K: float) -> tuple[float, ...]:
        return self.low if temperature_K < self.t_mid else self.high


@dataclass(frozen=True)
class RegistryState:
    kind: str = "ground"
    label: str = ""
    energy_eV: float | None = None
    resolution: str = "resolved"
    members: tuple[str, ...] = ()
    existence: str = "unknown"
    configuration: str | None = None
    term: str | None = None
    j: str | None = None
    parity: str | None = None
    degeneracy: float | None = None
    lifetime_s: float | None = None

    @property
    def manifold(self) -> str:
        return "vibrational" if self.label == "vibrational" else "electronic"


@dataclass(frozen=True)
class Species:
    id: str
    composition: dict[str, int]
    charge: int
    classes: frozenset[str]
    state: RegistryState = RegistryState()
    properties: dict[str, Property] = field(default_factory=dict)
    thermo: Thermo | None = None
    status: str = "draft"

    def value(self, name: str) -> float | None:
        prop = self.properties.get(name)
        return prop.value if prop else None

    @property
    def is_neutral(self) -> bool:
        return self.charge == 0 and self.id != "e"


@dataclass(frozen=True)
class Validity:
    quantity: str
    minimum: float | None = None
    maximum: float | None = None
    unit: str | None = None

    def covers(self, value: float | None) -> bool | None:
        if value is None or (self.minimum is None and self.maximum is None):
            return None
        below = self.minimum is not None and value < self.minimum
        above = self.maximum is not None and value > self.maximum
        return not (below or above)


@dataclass(frozen=True)
class Uncertainty:
    factor: float | None = None
    relative: float | None = None
    note: str | None = None

    def bounds(self, value: float) -> tuple[float, float] | None:
        if self.factor:
            return (value / self.factor, value * self.factor)
        if self.relative:
            return (value * (1 - self.relative), value * (1 + self.relative))
        return None


def normalized_property(entry: dict, default_tier: str = "imported") -> Property:
    """Preserve a value and the negative/qualified evidence around it."""

    parameters = {key: value for key, value in entry.items() if _number(value) is not None}
    return Property(
        value=_number(entry.get("value")),
        unit=_text(entry.get("unit")),
        source=_text(entry.get("source")),
        qualifier=_text(entry.get("qualifier") or entry.get("status")),
        uncertainty=_uncertainty(entry.get("uncertainty"), parameters),
        tier=_declared_tier(entry, default_tier),
    )


def _declared_tier(entry: dict, default: str) -> str:
    declared = str(entry.get("evidence_tier") or entry.get("quality") or "").lower()
    if declared in TIER_RANK:
        return declared
    if "estimate" in declared or "fit" in declared:
        return "estimated"
    if declared.startswith("curated"):
        return "curated"
    if declared in {"reviewed", "literature_supported", "evaluated"}:
        return "reviewed"
    if declared == "derived":
        return "derived"
    return default


def evidence_tier(status: str, source: dict[str, str] | None = None) -> str:
    """Map source-specific status words onto the five evidence tiers."""

    source_type = (source or {}).get("source_type", "").lower()
    if status in {"curated", "literature_supported"}:
        return "curated"
    if status == "reviewed":
        return "reviewed"
    if status == "estimated" or "estimated" in source_type:
        return "estimated"
    if status == "derived" or "derived" in source_type:
        return "derived"
    return "imported"


def source_label(source: dict[str, str], fallback: str) -> str:
    return (
        source.get("citation") or source.get("source_id") or source.get("source_type") or fallback
    )


@dataclass(frozen=True)
class AssetReference:
    """Stable public reference plus the local file used during this run."""

    reference: str
    local_path: Path | None = field(default=None, compare=False, repr=False)
    sha256: str | None = None
    declared_sha256: str | None = None

    @property
    def available(self) -> bool:
        return self.local_path is not None and self.local_path.is_file()

    @property
    def integrity_ok(self) -> bool:
        return self.declared_sha256 is None or self.declared_sha256 == self.sha256


def asset_reference(
    value: object,
    base: Path | None = None,
    allowed_root: Path | None = None,
) -> AssetReference | None:
    if not value:
        return None
    written = value.get("path") if isinstance(value, dict) else value
    declared = str(value.get("sha256")) if isinstance(value, dict) and value.get("sha256") else None
    if not written:
        return None
    reference = str(written).replace("\\", "/")
    path = Path(str(written))
    if not path.is_absolute() and base is not None:
        path = (base / path).resolve()
    elif path.is_absolute():
        path = path.resolve()
    local = path if path.is_file() else None
    if local is not None and allowed_root is not None:
        root = allowed_root.resolve()
        if local != root and root not in local.parents:
            local = None
    checksum = hashlib.sha256(local.read_bytes()).hexdigest() if local else None
    return AssetReference(reference, local, checksum, declared)


@dataclass(frozen=True)
class NumericDataset:
    id: str
    kind: str
    form: str
    unit: str | None = None
    independent_variable: str | None = None
    observable: str | None = None
    channel_scope: str = "product_resolved"
    params: dict[str, float] = field(default_factory=dict)
    asset: AssetReference | None = None
    validity: Validity | None = None
    uncertainty: Uncertainty | None = None
    source: dict[str, str] = field(default_factory=dict)
    status: str = "imported"
    tier: str = "imported"
    preferred: bool = False

    @property
    def usable(self) -> bool:
        if self.form == "reference_only":
            return False
        return (
            self.asset is not None and self.asset.available
            if self.form == "table"
            else bool(self.params)
        )

    @property
    def reviewed(self) -> bool:
        return self.tier in REVIEWED_TIERS

    @property
    def estimated(self) -> bool:
        return self.tier == "estimated"


@dataclass
class RegistryReaction:
    id: str
    family: str
    type: str
    reactants: list[Term]
    products: list[Term]
    threshold_eV: float | None = None
    delta_e_eV: float | None = None
    third_body: str | None = None
    surface: str | None = None
    reverse: str | None = None
    datasets: list[NumericDataset] = field(default_factory=list)
    source: dict[str, str] = field(default_factory=dict)
    status: str = "draft"


@dataclass(frozen=True)
class Material:
    id: str
    name: str
    notes: str = ""


@dataclass(frozen=True)
class StateRecord:
    id: str
    candidate: StateCandidate
    properties: dict[str, Property] = field(default_factory=dict)
    thermo: Thermo | None = None
    energy_eV: float | None = None
    existence: str = "unknown"
    configuration: str | None = None
    term: str | None = None
    j: str | None = None
    parity: str | None = None
    degeneracy: float | None = None
    lifetime_s: float | None = None
    status: str = "imported"
    tier: str = "imported"
    source: dict[str, str] = field(default_factory=dict)
    origin: str = "snapshot"

    def value(self, name: str) -> float | None:
        prop = self.properties.get(name)
        return prop.value if prop else None

    @property
    def reviewed(self) -> bool:
        return self.tier in REVIEWED_TIERS

    @property
    def label(self) -> str:
        return source_label(self.source, f"{self.origin}:{self.id}")


@dataclass(frozen=True)
class ReactionRecord:
    id: str
    equation_key: EquationKey
    family: str | None
    process: str
    states: tuple[StateCandidate, ...]
    datasets: tuple[NumericDataset, ...] = ()
    threshold_eV: float | None = None
    delta_e_eV: float | None = None
    channel_scope: str = "product_resolved"
    status: str = "imported"
    tier: str = "imported"
    source: dict[str, str] = field(default_factory=dict)
    origin: str = "snapshot"

    def __post_init__(self) -> None:
        raw_family = self.family or ""
        object.__setattr__(
            self,
            "family",
            canonical_family(raw_family) if self.family is not None else None,
        )
        object.__setattr__(
            self,
            "process",
            canonical_process(
                self.process,
                family=raw_family,
                third_body=self.equation_key[0],
                surface=self.equation_key[1],
            ),
        )

    @property
    def reviewed(self) -> bool:
        return self.tier in REVIEWED_TIERS

    @property
    def label(self) -> str:
        return source_label(self.source, f"{self.origin}:{self.id}")


def normalized_dataset(
    record: dict,
    *,
    base: Path | None = None,
    default_id: str = "dataset",
    default_kind: str = "rate_coefficient",
    default_source: dict[str, str] | None = None,
    allowed_asset_root: Path | None = None,
) -> NumericDataset:
    """Normalize either a Registry Dataset or one snapshot/overlay mapping."""

    source = dict(default_source or {}) | _strings(record.get("source") or {})
    status = str(record.get("status") or "imported")
    form = str(record.get("form") or record.get("representation") or "reference_only")
    parameters = record.get("parameters") or record.get("params") or {}
    kind = str(record.get("kind") or default_kind)
    observable = _text(record.get("observable")) or {
        "rate_coefficient": "reaction_rate",
        "sticking_coefficient": "sticking_probability",
    }.get(kind)
    return NumericDataset(
        id=str(record.get("id") or default_id),
        kind=kind,
        form=form,
        unit=_text(record.get("unit")),
        independent_variable=_text(record.get("independent_variable")),
        observable=observable,
        channel_scope=str(record.get("channel_scope") or "product_resolved"),
        params={
            key: float(value) for key, value in parameters.items() if _number(value) is not None
        },
        asset=asset_reference(record.get("asset"), base, allowed_asset_root),
        validity=_validity(record.get("validity")),
        uncertainty=_uncertainty(record.get("uncertainty"), parameters),
        source=source,
        status=status,
        tier=evidence_tier(status, source),
        preferred=bool(record.get("preferred")),
    )


def dataset_payload(dataset: NumericDataset) -> dict:
    """Public/overlay representation shared by export, ingest and adopt."""

    return {
        "id": dataset.id,
        "kind": dataset.kind,
        "form": dataset.form,
        "unit": dataset.unit,
        "independent_variable": dataset.independent_variable,
        "observable": dataset.observable,
        "channel_scope": dataset.channel_scope,
        "parameters": dataset.params,
        "asset": (
            {
                "path": dataset.asset.reference,
                "sha256": dataset.asset.sha256,
                "declared_sha256": dataset.asset.declared_sha256,
            }
            if dataset.asset
            else None
        ),
        "validity": _validity_payload(dataset.validity),
        "uncertainty": _uncertainty_payload(dataset.uncertainty),
        "source": dataset.source,
        "status": dataset.status,
        "tier": dataset.tier,
        "preferred": dataset.preferred,
    }


def _validity(data: object) -> Validity | None:
    if not isinstance(data, dict):
        return None
    unit = _text(data.get("unit"))
    default_quantity = {
        "K": "gas_temperature",
        "Td": "reduced_field",
        "eV": "collision_energy",
    }.get(unit or "", "gas_temperature")
    return Validity(
        quantity=str(data.get("quantity") or default_quantity),
        minimum=_number(data.get("minimum")),
        maximum=_number(data.get("maximum")),
        unit=unit,
    )


def _uncertainty(data: object, parameters: dict) -> Uncertainty | None:
    if not isinstance(data, dict):
        factor = _number(parameters.get("uncertainty_factor"))
        relative = _number(parameters.get("relative_uncertainty"))
        return Uncertainty(factor, relative) if factor or relative else None
    return Uncertainty(
        factor=_number(data.get("factor")),
        relative=_number(data.get("relative")),
        note=_text(data.get("note")),
    )


def _validity_payload(value: Validity | None) -> dict | None:
    if value is None:
        return None
    return {
        "quantity": value.quantity,
        "minimum": value.minimum,
        "maximum": value.maximum,
        "unit": value.unit,
    }


def _uncertainty_payload(value: Uncertainty | None) -> dict | None:
    if value is None:
        return None
    return {"factor": value.factor, "relative": value.relative, "note": value.note}


def _strings(data: dict) -> dict[str, str]:
    return {str(key): str(value) for key, value in data.items() if value is not None}


def _text(value: object) -> str | None:
    return None if value is None else str(value)


def _number(value: object) -> float | None:
    try:
        return None if value is None or isinstance(value, bool) else float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
