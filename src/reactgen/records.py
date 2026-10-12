"""Normalized, read-only evidence records.

Registry YAML, reviewed overlays and imported snapshots meet here.  The rest of
the pipeline therefore handles one numerical-data shape and never branches on
where a record came from.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Sequence
from copy import deepcopy
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any, cast

from reactgen.model import (
    EquationKey,
    StateCandidate,
    Term,
    canonical_family,
    canonical_process,
)
from reactgen.units import energy_eV as energy_in_eV

REVIEWED_TIERS = frozenset({"curated", "reviewed"})
TRUSTED_PROPERTY_TIERS = REVIEWED_TIERS | {"derived"}
TIER_RANK = {"curated": 0, "reviewed": 1, "derived": 2, "estimated": 3, "imported": 4}


@dataclass(frozen=True)
class SourceRef:
    """Stated source identifiers, independent of scientific method or approval.

    Missing identifiers stay missing. A legacy citation never identifies its
    provider, release or original measurement by inference.
    """

    provider: str | None = None
    collection: str | None = None
    release: str | None = None
    record_id: str | None = None
    citation: str | None = None
    url: str | None = None
    source_id: str | None = None
    source_type: str | None = None

    def __post_init__(self) -> None:
        for item in fields(self):
            value = getattr(self, item.name)
            if value is not None and (not isinstance(value, str) or not value.strip()):
                raise ValueError(f"source.{item.name} must be nonempty text")

    def label(self, fallback: str | None = None) -> str | None:
        return (
            self.citation
            or self.source_id
            or self.record_id
            or self.provider
            or self.collection
            or self.source_type
            or fallback
        )


def normalized_source(value: object, default: object = None) -> SourceRef:
    """Normalize a citation or source mapping; preserve unknown fields elsewhere."""
    combined = _source_mapping(default) | _source_mapping(value)
    return SourceRef(**{item.name: combined.get(item.name) for item in fields(SourceRef)})


def _source_mapping(value: object) -> dict[str, str]:
    if value is None:
        return {}
    if isinstance(value, SourceRef):
        return {key: val for key, val in asdict(value).items() if val is not None}
    if isinstance(value, str):
        return {"citation": value} if value.strip() else {}
    if not isinstance(value, dict):
        raise ValueError("source must be text or a mapping")
    return {
        str(key): str(val)
        for key, val in value.items()
        if val is not None and isinstance(val, str | int | float) and str(val).strip()
    }


def source_information(entry: dict, default_source: object = None) -> tuple[SourceRef, object]:
    """Keep the author's declaration separate from its normalized identifiers."""
    source = entry.get("source")
    source_identifiers = source
    if "provenance" in entry and "source_declaration" in entry and isinstance(source, str):
        stated = normalized_source(entry.get("provenance"))
        if source == stated.label():
            # A portable display label is not a newly stated citation.
            source_identifiers = None
    provenance = normalized_source(
        entry.get("provenance"),
        _source_mapping(default_source) | _source_mapping(source_identifiers),
    )
    if "source_declaration" in entry:
        declaration = deepcopy(entry["source_declaration"])
    else:
        declaration = dict(entry)
    if default_source:
        if not isinstance(declaration, dict):
            declaration = {"record_declaration": declaration}
        context = deepcopy(default_source)
        if isinstance(context, SourceRef):
            context = asdict(context)
        elif isinstance(context, str):
            context = {"citation": context}
        context = cast(dict, context)
        prior = declaration.get("snapshot_source")
        if prior is not None:
            if not isinstance(prior, dict):
                prior = {"record_declaration": prior}
            context = context | prior
        declaration["snapshot_source"] = context
    return provenance, deepcopy(declaration)


def scientific_method(entry: dict, default_source: object = None) -> str:
    """Read canonical method declarations, without consulting provider names."""
    candidates = [entry.get("method")]
    for data in (entry.get("source"), entry.get("source_declaration"), default_source):
        if isinstance(data, dict):
            candidates.append(data.get("method"))
    for value in candidates:
        if value is not None:
            text = str(value).lower()
            return (
                text
                if text in {"measured", "evaluated", "calculated", "estimated", "unknown"}
                else "unknown"
            )
    return "unknown"


def review_scope(entry: dict) -> tuple[str, ...]:
    """Only explicit review scopes qualify particular claims; tiers imply none."""
    value = entry.get("review_scope")
    if value is None:
        value = []
    if not isinstance(value, list | tuple) or any(
        not isinstance(item, str) or not item.strip() for item in value
    ):
        raise ValueError("review_scope must be a list of nonempty claim names")
    return tuple(sorted(set(value)))


def review_scope_covers(scopes: tuple[str, ...], claim: str) -> bool:
    """A stated scope limits a qualification; unscoped legacy records are adapted."""
    return not scopes or claim in scopes


def scientific_declaration(value: object, source: SourceRef) -> object:
    """Compare a declaration independently of standardized acquisition context.

    This view never replaces the stored declaration. Unknown conditions,
    notes and source fields remain scientific content. Only reserved
    acquisition containers and matching, redundant snapshot identifiers are
    omitted. Known review scopes are unordered claim sets; their declaration
    order remains in storage. Other lists and inconsistent source declarations
    remain distinguishable.
    """
    content = deepcopy(value)
    if not isinstance(content, dict):
        return content
    _normalize_declaration_comparison(content, source)
    declaration = content.get("source_declaration")
    if isinstance(declaration, dict):
        _normalize_declaration_comparison(declaration, source)
    return content


def _normalize_declaration_comparison(content: dict, source: SourceRef) -> None:
    if "review_scope" in content:
        content["review_scope"] = list(review_scope(content))
    content.pop("acquisition", None)
    stated_source = content.get("source")
    if isinstance(stated_source, dict):
        stated_source.pop("acquisition", None)
    snapshot_source = content.get("snapshot_source")
    if isinstance(snapshot_source, dict):
        snapshot_source.pop("acquisition", None)
        for item in fields(SourceRef):
            if item.name in snapshot_source and snapshot_source[item.name] == getattr(
                source, item.name
            ):
                snapshot_source.pop(item.name)
        if not snapshot_source:
            content.pop("snapshot_source")


def scientific_dataset_content(dataset: NumericDataset | dict) -> dict:
    """Shared comparison view for typed datasets and saved canonical evidence.

    Acquisition declarations and paths stay in every stored record. A known
    asset checksum identifies bytes independently of their storage location;
    unknown bytes retain their path and cannot establish that equivalence.
    Typed records check the current bytes; saved result mappings compare the
    recorded observation without reading files or recomputing old results.
    """
    body = dataset_payload(dataset) if isinstance(dataset, NumericDataset) else dataset
    source = normalized_source(body.get("provenance"), body.get("source"))
    content = scientific_declaration(body, source)
    if not isinstance(content, dict):
        raise ValueError("scientific dataset must be a mapping")
    asset = content.get("asset")
    if isinstance(asset, dict):
        asset.pop("local_path", None)
        checksum = asset.get("sha256")
        known_bytes = _is_sha256(checksum)
        if isinstance(dataset, NumericDataset):
            known_bytes = dataset.asset is not None and dataset.asset.read_bytes(False) is not None
        if known_bytes:
            asset.pop("path", None)
            asset.pop("reference", None)
            declaration = content.get("source_declaration")
            if isinstance(declaration, dict):
                _asset_declaration_content(declaration, checksum)
    return content


def _is_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _asset_declaration_content(declaration: dict, checksum: object) -> None:
    """Omit only the storage fields already represented by the normalized asset."""
    asset = declaration.get("asset")
    if asset is not None:
        retained = (
            {
                key: value
                for key, value in asset.items()
                if key not in {"path", "sha256", "declared_sha256"}
            }
            if isinstance(asset, dict)
            else {}
        )
        declaration["asset"] = retained | {"content_sha256": checksum}
    nested = declaration.get("source_declaration")
    if isinstance(nested, dict):
        _asset_declaration_content(nested, checksum)


def scientific_record_id(entry: dict, fallback: str = "record") -> str:
    """Local content identity when the source supplies no scientific record ID."""
    stated = entry.get("record_id")
    if stated is not None:
        if not isinstance(stated, str) or not stated.strip():
            raise ValueError("record_id must be nonempty text")
        return stated
    body = json.dumps(entry, sort_keys=True, ensure_ascii=True, default=str)
    return f"{fallback}:{hashlib.sha256(body.encode()).hexdigest()[:20]}"


def numerical_record_id(
    entry: dict,
    default_source: object = None,
    legacy_default: str | None = None,
) -> str:
    """Separate a canonical dataset ID from a source's native record ID.

    A native record keeps one identity within its stated source namespace,
    even when its numerical declaration changes. Without a native ID, both
    the declaration and normalized source context define a local content ID.
    The snapshot container path and filename never define scientific identity.
    """
    stated = entry.get("id")
    if stated is not None:
        if not isinstance(stated, str) or not stated.strip():
            raise ValueError("dataset.id must be nonempty text")
        return stated
    source, declaration = source_information(entry, default_source)
    return _source_record_identity(entry, source, declaration, "dataset", legacy_default)


def state_record_id(
    entry: dict,
    default_source: object = None,
    *,
    preserved_record_id: bool = False,
) -> str:
    """Identify a new source declaration while preserving IDs of saved records.

    Snapshot ``record_id`` and ``source.record_id`` are native identifiers.
    Overlay and Registry adapters explicitly preserve their existing canonical
    ``record_id`` instead of interpreting it as a new source declaration.
    """
    if preserved_record_id and entry.get("record_id") is not None:
        return scientific_record_id(entry, "local-state")
    source, declaration = source_information(entry, default_source)
    return _source_record_identity(entry, source, declaration, "state")


def _source_record_identity(
    entry: dict,
    source: SourceRef,
    declaration: object,
    kind: str,
    legacy_default: str | None = None,
) -> str:
    """Shared native namespace and anonymous scientific-content identity."""
    native = entry.get("record_id")
    if native is None:
        native = source.record_id
    if native is not None:
        if not isinstance(native, str) or not native.strip():
            raise ValueError("record_id must be nonempty text")
        namespace = {
            "provider": source.provider,
            "collection": source.collection,
            "release": source.release,
            "source_id": source.source_id,
            "record_id": native,
        }
        body = json.dumps(namespace, sort_keys=True, ensure_ascii=True)
        return f"source-{kind}:{hashlib.sha256(body.encode()).hexdigest()[:20]}"
    if legacy_default is not None and not any(asdict(source).values()):
        # Preserve anonymous legacy Registry containers. A stated source is
        # never collapsed into that container's fallback ID.
        return legacy_default
    content = scientific_declaration(
        entry | {"provenance": asdict(source), "source_declaration": declaration}, source
    )
    return scientific_record_id(cast(dict, content), f"local-{kind}")


def _state_native_id(entry: dict, source: SourceRef) -> str | None:
    """Recover an original source identifier from saved, including legacy, records."""
    if source.record_id is not None:
        return source.record_id
    declaration = entry.get("source_declaration")
    native = declaration.get("record_id") if isinstance(declaration, dict) else None
    if native is not None and (not isinstance(native, str) or not native.strip()):
        raise ValueError("source declaration record_id must be nonempty text")
    return native


def scientific_record_key(entry: dict) -> tuple:
    """Match a saved state by its native namespace, or its preserved canonical ID.

    A newly namespaced source ID can match the same original record saved by
    an older adapter, without renaming the already stored canonical ID.
    """
    source = normalized_source(entry.get("provenance"), entry.get("source"))
    native = _state_native_id(entry, source)
    return (
        native or entry.get("record_id"),
        source.provider,
        source.collection,
        source.release,
        source.source_id,
    )


def state_record_content(record: StateRecord | dict) -> dict:
    """Normalize comparison defaults without replacing a stored declaration.

    Older portable records may omit newly supported property/model defaults.
    Normalize those fields at this boundary, retaining acquisition context and
    unknown fields. Identical old records are not new acquisitions merely
    because the current adapter expresses a default explicitly.
    """
    body = state_record_payload(record) if isinstance(record, StateRecord) else record
    source = normalized_source(body.get("provenance"), body.get("source"))
    native = _state_native_id(body, source)
    if native is not None and source.record_id is None:
        source = SourceRef(**(asdict(source) | {"record_id": native}))
    content = deepcopy(body)
    content["provenance"] = asdict(source)
    properties = content.get("properties")
    if isinstance(properties, dict):
        content["properties"] = {
            name: value | asdict(normalized_property(value, quantity=str(name)))
            if isinstance(value, dict)
            else value
            for name, value in properties.items()
        }
    thermo = content.get("thermo")
    if isinstance(thermo, dict):
        normalized_fit = normalized_thermo(thermo)
        if normalized_fit is None:
            raise ValueError("state thermo must normalize to a NASA7 model")
        content["thermo"] = thermo | asdict(normalized_fit)
    return _portable_payload(content)


def scientific_state_content(record: StateRecord | dict) -> dict:
    """Compare state science while retaining every acquisition in stored records.

    The canonical ID is compared separately by ``scientific_record_key``.
    Physical target, values, qualification and unknown scientific conditions
    remain in this view; only standardized acquisition context is omitted.
    """
    body = state_record_content(record)
    source = normalized_source(body.get("provenance"), body.get("source"))
    content = scientific_declaration(body, source)
    if not isinstance(content, dict):
        raise ValueError("scientific state record must be a mapping")
    content.pop("record_id", None)
    properties = content.get("properties")
    if isinstance(properties, dict):
        content["properties"] = {
            name: scientific_declaration(
                value, normalized_source(value.get("provenance"), value.get("source"))
            )
            if isinstance(value, dict)
            else value
            for name, value in properties.items()
        }
    thermo = content.get("thermo")
    if isinstance(thermo, dict):
        content["thermo"] = scientific_declaration(
            thermo, normalized_source(thermo.get("provenance"), thermo.get("source"))
        )
    return content


def validate_snapshot(document: object) -> dict:
    """Read the supported external snapshot version; unversioned input is legacy."""
    if not isinstance(document, dict) or not isinstance(document.get("records"), list):
        raise ValueError("snapshot must contain a records list")
    version = document.get("snapshot_version")
    if "snapshot_version" in document and (type(version) is not int or version != 1):
        raise ValueError(f"unsupported snapshot_version: {version!r}")
    if any(not isinstance(record, dict) for record in document["records"]):
        raise ValueError("snapshot records must be mappings")
    return document


def _record_provenance(
    record: Property
    | Thermo
    | RegistryState
    | NumericDataset
    | StateRecord
    | ReactionRecord
    | RegistryReaction,
    *,
    display_source: bool = False,
) -> None:
    """Also normalize records constructed directly by Python callers."""
    object.__setattr__(record, "review_scope", review_scope({"review_scope": record.review_scope}))
    source = record.source
    source_identifiers = source
    if (
        display_source
        and isinstance(record.provenance, SourceRef)
        and source == record.provenance.label()
    ):
        # Property/Thermo.source may already be the display label derived from
        # a provider/native ID. Reusing it must not fill an unknown citation.
        source_identifiers = None
    provenance = normalized_source(record.provenance, source_identifiers)
    object.__setattr__(record, "provenance", provenance)
    if record.source_declaration is None and source:
        object.__setattr__(record, "source_declaration", deepcopy(source))
    if display_source and source is None:
        object.__setattr__(record, "source", provenance.label())


def _validate_state_values(
    existence: str,
    energy_eV: float | None,
    lifetime_s: float | None,
    degeneracy: float | None,
    existence_source: str | None,
) -> None:
    if existence not in {"unknown", "hypothetical", "confirmed", "unbound", "transient"}:
        raise ValueError(f"unknown existence assertion: {existence}")
    if existence_source is not None and (
        not isinstance(existence_source, str) or not existence_source.strip()
    ):
        raise ValueError("state.existence_source must be nonempty text")
    for name, value in (
        ("excitation_energy_eV", energy_eV),
        ("lifetime_s", lifetime_s),
        ("degeneracy", degeneracy),
    ):
        if value is None:
            continue
        _typed_number(value, f"state.{name}")
        if not math.isfinite(value) or value < 0 or (name != "excitation_energy_eV" and value == 0):
            sign = "nonnegative" if name == "excitation_energy_eV" else "positive"
            raise ValueError(f"state.{name} must be finite and {sign}")


@dataclass(frozen=True)
class FormationReference:
    """Reference of a formation enthalpy, independent of source qualification.

    ``standard_elements`` uses each element's standard reference state at the
    stated temperature and pressure. Ion and electron conventions differ at
    finite temperature; an ion-convention reaction with a net free-electron
    contribution additionally needs its declared electron formation enthalpy.
    Missing reference fields remain missing, rather than implying 298.15 K.
    See https://webbook.nist.gov/chemistry/ion/ .
    """

    temperature_K: float | None = None
    basis: str | None = None
    standard_pressure_Pa: float | None = None
    electron_convention: str | None = None
    electron_enthalpy_eV: float | None = None

    def __post_init__(self) -> None:
        for name in ("temperature_K", "standard_pressure_Pa", "electron_enthalpy_eV"):
            value = getattr(self, name)
            _typed_number(value, f"formation_reference.{name}")
            if value is not None and (
                not math.isfinite(value)
                or (name == "temperature_K" and value < 0)
                or (name == "standard_pressure_Pa" and value <= 0)
                or (name == "electron_enthalpy_eV" and value < 0)
            ):
                raise ValueError(f"formation_reference.{name} has an invalid value")
        if self.basis is not None and (
            not isinstance(self.basis, str) or self.basis != "standard_elements"
        ):
            raise ValueError("formation_reference.basis must be standard_elements")
        if self.electron_convention is not None and (
            not isinstance(self.electron_convention, str)
            or self.electron_convention not in {"ion", "electron"}
        ):
            raise ValueError("formation_reference.electron_convention must be ion or electron")
        if (
            self.electron_enthalpy_eV is not None
            and (self.electron_convention != "ion" or self.temperature_K == 0)
            and self.electron_enthalpy_eV != 0
        ):
            raise ValueError(
                "formation_reference nonzero electron enthalpy requires a finite-T ion convention"
            )

    @property
    def complete(self) -> bool:
        """A stated elemental reference; this alone does not qualify an ion."""
        return (
            self.temperature_K is not None
            and self.basis is not None
            and self.standard_pressure_Pa is not None
        )

    def complete_for_charge(self, charge: int, *, electron_term_required: bool = False) -> bool:
        """A finite-T ion needs its convention; a neutral quantity does not."""
        return (
            self.complete
            and (charge == 0 or self.temperature_K == 0 or self.electron_convention is not None)
            and (
                not electron_term_required
                or charge == 0
                or self.temperature_K == 0
                or self.electron_convention != "ion"
                or self.electron_enthalpy_eV is not None
            )
        )


def normalized_formation_reference(value: object) -> FormationReference | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError("formation_reference must be a mapping")
    return FormationReference(
        temperature_K=normalized_number(
            value.get("temperature_K"), "formation_reference.temperature_K"
        ),
        basis=_text(value.get("basis")),
        standard_pressure_Pa=normalized_number(
            value.get("standard_pressure_Pa"), "formation_reference.standard_pressure_Pa"
        ),
        electron_convention=_text(value.get("electron_convention")),
        electron_enthalpy_eV=normalized_number(
            value.get("electron_enthalpy_eV"), "formation_reference.electron_enthalpy_eV"
        ),
    )


@dataclass(frozen=True)
class Property:
    value: float | None = None
    unit: str | None = None
    source: str | None = None
    qualifier: str | None = None
    uncertainty: Uncertainty | None = None
    tier: str = "imported"
    provenance: SourceRef = field(default_factory=SourceRef)
    source_declaration: object = None
    method: str = "unknown"
    review_scope: tuple[str, ...] = ()
    status: str = "imported"
    formation_reference: FormationReference | None = None
    definition: str | None = None

    def __post_init__(self) -> None:
        _record_provenance(self, display_source=True)
        _typed_number(self.value, "property.value")
        if self.definition is not None and (
            not isinstance(self.definition, str) or not self.definition.strip()
        ):
            raise ValueError("property.definition must be nonempty text")
        if self.uncertainty is not None and not isinstance(self.uncertainty, Uncertainty):
            raise ValueError("property.uncertainty must be an Uncertainty record")
        if self.formation_reference is not None and not isinstance(
            self.formation_reference, FormationReference
        ):
            raise ValueError("property.formation_reference must be a FormationReference record")

    @property
    def known(self) -> bool:
        return self.value is not None and math.isfinite(self.value)

    def reviewed_for(self, quantity: str) -> bool:
        """Qualify this quantity only; an empty scope preserves legacy review.

        Source qualification does not establish identity, applicability or
        physical existence. Those questions retain their separate checks.
        """
        return (
            self.tier in TRUSTED_PROPERTY_TIERS
            and self.status not in {"rejected", "conflicting"}
            and review_scope_covers(self.review_scope, quantity)
        )


def _state_properties(
    properties: dict[str, Property],
    excitation_eV: float | None,
    tier: str,
    source: str,
    review_scope: tuple[str, ...] = (),
    status: str = "imported",
) -> dict[str, Property]:
    """Give a legacy level-energy scalar its own qualification exactly once.

    An explicit Property is authoritative for its numerical qualification.
    Changing an existence assertion's tier cannot requalify this value.
    Conflicting duplicate values within a declaration are input errors.
    """

    for quantity, prop in properties.items():
        if not isinstance(prop, Property):
            raise ValueError("state.properties must contain Property records")
        validate_property_definition(prop, quantity)
    explicit = properties.get("excitation_energy_eV")
    if (
        explicit is not None
        and explicit.value is not None
        and (not math.isfinite(explicit.value) or explicit.value < 0)
    ):
        raise ValueError("excitation_energy_eV property must be finite and nonnegative")
    if excitation_eV is None:
        return properties
    if explicit is None:
        return properties | {
            "excitation_energy_eV": Property(
                excitation_eV, "eV", source, tier=tier, review_scope=review_scope, status=status
            )
        }
    converted = energy_in_eV(explicit.value, explicit.unit) if explicit.value is not None else None
    if converted is not None and not math.isclose(
        converted, excitation_eV, rel_tol=1e-9, abs_tol=1e-9
    ):
        raise ValueError("state scalar and excitation_energy_eV property disagree")
    return properties


@dataclass(frozen=True)
class Thermo:
    low: tuple[float, ...]
    high: tuple[float, ...]
    t_min: float
    t_mid: float
    t_max: float
    source: str | None = None
    tier: str = "imported"
    phase: str | None = None
    standard_pressure_Pa: float | None = None
    provenance: SourceRef = field(default_factory=SourceRef)
    source_declaration: object = None
    method: str = "unknown"
    review_scope: tuple[str, ...] = ()
    status: str = "imported"

    def __post_init__(self) -> None:
        _record_provenance(self, display_source=True)

    def coefficients(self, temperature_K: float) -> tuple[float, ...]:
        return self.low if temperature_K < self.t_mid else self.high

    def reviewed_for(self, claim: str) -> bool:
        """Model review is independent of the NASA shape and reference domain."""
        return (
            self.tier in TRUSTED_PROPERTY_TIERS
            and self.status not in {"rejected", "conflicting"}
            and review_scope_covers(self.review_scope, claim)
        )


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
    existence_source: str | None = None
    status: str | None = None
    source: dict[str, str] = field(default_factory=dict)
    provenance: SourceRef = field(default_factory=SourceRef)
    source_declaration: object = None
    method: str = "unknown"
    review_scope: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _record_provenance(self)
        _validate_state_values(
            self.existence, self.energy_eV, self.lifetime_s, self.degeneracy, self.existence_source
        )

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
    phase: str = "unknown"
    structure: str | None = None
    records: tuple[StateRecord, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "properties",
            _state_properties(
                self.properties,
                self.state.energy_eV,
                evidence_tier(self.state.status or self.status),
                f"registry:{self.id}",
                self.state.review_scope,
                self.state.status or self.status,
            ),
        )

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

    def __post_init__(self) -> None:
        _typed_number(self.minimum, "validity.minimum")
        _typed_number(self.maximum, "validity.maximum")

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
    absolute: float | None = None

    def __post_init__(self) -> None:
        for name in ("factor", "relative", "absolute"):
            _typed_number(getattr(self, name), f"uncertainty.{name}")

    def bounds(self, value: float) -> tuple[float, float] | None:
        """Return ordered bounds; invalid declarations cannot support an inference."""

        for name, declared, minimum in (
            ("factor", self.factor, 1.0),
            ("relative", self.relative, 0.0),
            ("absolute", self.absolute, 0.0),
        ):
            if declared is not None and (not math.isfinite(declared) or declared < minimum):
                raise ValueError(f"uncertainty {name} must be finite and >= {minimum:g}")
        if not math.isfinite(value):
            raise ValueError("uncertainty value must be finite")
        if self.absolute is not None:
            bounds = value - self.absolute, value + self.absolute
        elif self.factor is not None:
            bounds = value / self.factor, value * self.factor
        elif self.relative is not None:
            bounds = value * (1 - self.relative), value * (1 + self.relative)
        else:
            return None
        if not all(math.isfinite(bound) for bound in bounds):
            raise ValueError("uncertainty bounds must be finite")
        return min(bounds), max(bounds)


def normalized_property(
    entry: dict,
    default_tier: str = "imported",
    default_source: object = None,
    *,
    quantity: str | None = None,
) -> Property:
    """Preserve a value and the negative/qualified evidence around it."""

    parameters = {
        name: entry[name]
        for name in ("uncertainty_factor", "relative_uncertainty")
        if name in entry
    }
    provenance, declaration = source_information(entry, default_source)
    prop = Property(
        value=normalized_number(entry.get("value")),
        unit=_text(entry.get("unit")),
        source=entry.get("source") if isinstance(entry.get("source"), str) else provenance.label(),
        qualifier=_text(
            entry.get("qualifier")
            or (entry.get("status") if entry.get("status") in {"unbound", "transient"} else None)
        ),
        uncertainty=_uncertainty(entry.get("uncertainty"), parameters, _text(entry.get("unit"))),
        tier=_declared_tier(entry, default_tier),
        provenance=provenance,
        source_declaration=declaration,
        method=scientific_method(entry, default_source),
        review_scope=review_scope(entry),
        status=str(entry.get("status") or "imported"),
        formation_reference=normalized_formation_reference(entry.get("formation_reference")),
        definition=entry.get("definition"),
    )
    validate_property_definition(prop, quantity)
    return prop


def validate_property_definition(prop: Property, quantity: str | None) -> None:
    """Validate declared definitions for quantities currently used in judgments.

    No definition is inferred from a provider or unit. New quantities retain
    their stated definitions until a consumer defines their scientific use.
    Adiabatic and vertical IE/EA are different observables, as described in
    https://webbook.nist.gov/chemistry/ion/ . Appearance energy describes a
    fragment-ion channel and is not a definition of the parent's IE.
    """
    definitions = {
        "ionization_energy_eV": {"atomic", "adiabatic", "vertical"},
        "electron_affinity_eV": {"atomic", "adiabatic", "vertical"},
        "threshold_eV": {"channel_threshold", "appearance_energy"},
        "delta_e_eV": {"products_minus_reactants"},
    }
    allowed = definitions.get(quantity or "")
    if prop.definition is not None and allowed is not None and prop.definition not in allowed:
        raise ValueError(f"{quantity}.definition must be one of {', '.join(sorted(allowed))}")


def normalized_thermo(
    data: object, default_tier: str = "imported", default_source: object = None
) -> Thermo | None:
    """Read an explicitly declared NASA7 fit without inventing its range or phase."""

    if data is None:
        return None
    if not isinstance(data, dict):
        raise ValueError("thermo must be a NASA7 mapping")
    low, high = data.get("low"), data.get("high")
    if (
        not isinstance(low, list | tuple)
        or not isinstance(high, list | tuple)
        or len(low) != 7
        or len(high) != 7
    ):
        raise ValueError("thermo.low and thermo.high must contain seven coefficients")
    numbers = [
        normalized_number(value)
        for value in (*low, *high, data.get("t_min"), data.get("t_mid"), data.get("t_max"))
    ]
    if any(value is None or not math.isfinite(value) for value in numbers):
        raise ValueError("thermo coefficients and temperature bounds must be finite numbers")
    numeric = tuple(float(value) for value in numbers if value is not None)
    t_min, t_mid, t_max = numeric[-3:]
    if not 0 < t_min <= t_mid <= t_max or t_min == t_max:
        raise ValueError("thermo requires 0 < t_min <= t_mid <= t_max with a nonzero range")
    pressure = normalized_number(data.get("standard_pressure_Pa"))
    if pressure is not None and (not math.isfinite(pressure) or pressure <= 0):
        raise ValueError("thermo.standard_pressure_Pa must be finite and positive")
    provenance, declaration = source_information(data, default_source)
    return Thermo(
        low=numeric[:7],
        high=numeric[7:14],
        t_min=t_min,
        t_mid=t_mid,
        t_max=t_max,
        source=data.get("source") if isinstance(data.get("source"), str) else provenance.label(),
        tier=_declared_tier(data, default_tier),
        phase=_text(data.get("phase")),
        standard_pressure_Pa=pressure,
        provenance=provenance,
        source_declaration=declaration,
        method=scientific_method(data, default_source),
        review_scope=review_scope(data),
        status=str(data.get("status") or "imported"),
    )


def _declared_tier(entry: dict, default: str) -> str:
    declared = str(
        entry.get("evidence_tier") or entry.get("quality") or entry.get("tier") or ""
    ).lower()
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
    status = str(entry.get("status") or "")
    return (
        evidence_tier(status)
        if status in TIER_RANK or status == "literature_supported"
        else default
    )


def evidence_tier(status: str, source: dict[str, str] | None = None) -> str:
    """Adapt explicit legacy qualifications; a source name never qualifies data."""

    if status in {"curated", "literature_supported"}:
        return "curated"
    if status == "reviewed":
        return "reviewed"
    if status == "estimated":
        return "estimated"
    if status == "derived":
        return "derived"
    return "imported"


@dataclass(frozen=True)
class AssetReference:
    """Stored byte observation and author declaration, separate from location."""

    reference: str
    local_path: Path | None = field(default=None, compare=False, repr=False)
    sha256: str | None = None
    declared_sha256: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.reference, str) or not self.reference.strip():
            raise ValueError("asset reference must be nonempty text")
        if self.local_path is not None and not isinstance(self.local_path, Path):
            raise ValueError("asset local_path must be a Path")
        for name in ("sha256", "declared_sha256"):
            value = getattr(self, name)
            if value is not None and not isinstance(value, str):
                raise ValueError(f"asset.{name} must be text")

    @property
    def available(self) -> bool:
        return self.local_path is not None and self.local_path.is_file()

    @property
    def integrity_ok(self) -> bool:
        return self.read_bytes() is not None

    def read_bytes(self, check_declaration: bool = True) -> bytes | None:
        """Return exactly the bytes whose saved observation has been checked.

        Calculation also checks the author's checksum. Copying an invalid
        declaration may preserve its observed bytes, but never qualifies it.
        Direct Python references without a byte observation remain unusable.
        """
        if self.local_path is None or not _is_sha256(self.sha256):
            return None
        try:
            content = self.local_path.read_bytes()
        except OSError:
            return None
        if hashlib.sha256(content).hexdigest() != self.sha256:
            return None
        if check_declaration and self.declared_sha256 not in (None, self.sha256):
            return None
        return content


def asset_reference(
    value: object,
    base: Path | None = None,
    allowed_root: Path | None = None,
) -> AssetReference | None:
    if not value:
        return None
    written = value.get("path") if isinstance(value, dict) else value
    # A serialized reference separates the author's declaration from our
    # measured checksum. Never replace a failed declaration on reloading.
    if isinstance(value, dict):
        declaration = (
            value.get("declared_sha256") if "declared_sha256" in value else value.get("sha256")
        )
        declared = str(declaration) if declaration is not None else None
    else:
        declared = None
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
    checksum = (
        value.get("sha256")
        if isinstance(value, dict) and "declared_sha256" in value and "sha256" in value
        else hashlib.sha256(local.read_bytes()).hexdigest()
        if local
        else None
    )
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
    reaction_order: float | None = None
    parameter_units: dict[str, str] = field(default_factory=dict)
    reference_temperature_K: float | None = None
    provenance: SourceRef = field(default_factory=SourceRef)
    source_declaration: object = None
    method: str = "unknown"
    review_scope: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _record_provenance(self)
        if self.asset is not None and not isinstance(self.asset, AssetReference):
            raise ValueError("dataset.asset must be an AssetReference")
        if type(self.preferred) is not bool:
            raise ValueError("dataset.preferred must be a boolean")
        if not isinstance(self.params, dict):
            raise ValueError("dataset.parameters must be a mapping")
        for name, value in self.params.items():
            _typed_number(value, f"dataset.parameters.{name}", optional=False)
        _typed_number(self.reaction_order, "dataset.reaction_order")
        _typed_number(self.reference_temperature_K, "dataset.reference_temperature_K")
        if self.validity is not None and not isinstance(self.validity, Validity):
            raise ValueError("dataset.validity must be a Validity record")
        if self.uncertainty is not None and not isinstance(self.uncertainty, Uncertainty):
            raise ValueError("dataset.uncertainty must be an Uncertainty record")

    @property
    def usable(self) -> bool:
        if self.form == "reference_only":
            return False
        return (
            self.asset is not None and self.asset.integrity_ok
            if self.form == "table"
            else bool(self.params)
        )

    @property
    def reviewed(self) -> bool:
        return (
            self.tier in REVIEWED_TIERS
            and self.status not in {"rejected", "conflicting"}
            and review_scope_covers(self.review_scope, self.kind)
        )

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
    energy_properties: dict[str, Property] = field(default_factory=dict)
    third_body: str | None = None
    surface: str | None = None
    reverse: str | None = None
    datasets: list[NumericDataset] = field(default_factory=list)
    source: dict[str, str] = field(default_factory=dict)
    status: str = "draft"
    stabilization: str | None = None
    provenance: SourceRef = field(default_factory=SourceRef)
    source_declaration: object = None
    method: str = "unknown"
    review_scope: tuple[str, ...] = ()
    records: tuple[ReactionRecord, ...] = ()

    def __post_init__(self) -> None:
        _record_provenance(self)
        validate_reaction_energy_properties(self.energy_properties)

    @property
    def threshold_eV(self) -> float | None:
        return _reaction_energy_value(self.energy_properties, "threshold_eV")

    @property
    def delta_e_eV(self) -> float | None:
        return _reaction_energy_value(self.energy_properties, "delta_e_eV")


def _reaction_energy_value(properties: dict[str, Property], quantity: str) -> float | None:
    """Convert a stored declaration for inspection; this does not qualify its use."""
    prop = properties.get(quantity)
    return (
        energy_in_eV(prop.value, prop.unit) if prop is not None and prop.value is not None else None
    )


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
    existence_source: str | None = None
    members: tuple[str, ...] = ()
    record_id: str | None = None
    provenance: SourceRef = field(default_factory=SourceRef)
    source_declaration: object = None
    method: str = "unknown"
    review_scope: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _record_provenance(self)
        _validate_state_values(
            self.existence, self.energy_eV, self.lifetime_s, self.degeneracy, self.existence_source
        )
        object.__setattr__(
            self,
            "properties",
            _state_properties(
                self.properties,
                self.energy_eV,
                self.tier,
                self.label,
                self.review_scope,
                self.status,
            ),
        )

    def value(self, name: str) -> float | None:
        prop = self.properties.get(name)
        return prop.value if prop else None

    @property
    def reviewed(self) -> bool:
        """Qualification of the existence assertion, never of nested quantities."""
        return self.reviewed_for("state_existence")

    def reviewed_for(self, claim: str) -> bool:
        return (
            self.tier in REVIEWED_TIERS
            and self.status not in {"rejected", "conflicting"}
            and review_scope_covers(self.review_scope, claim)
        )

    @property
    def label(self) -> str:
        return self.provenance.label(f"{self.origin}:{self.id}") or f"{self.origin}:{self.id}"


@dataclass(frozen=True)
class ReactionRecord:
    id: str
    equation_key: EquationKey
    family: str | None
    process: str
    states: tuple[StateCandidate, ...]
    datasets: tuple[NumericDataset, ...] = ()
    energy_properties: dict[str, Property] = field(default_factory=dict)
    channel_scope: str = "product_resolved"
    status: str = "imported"
    tier: str = "imported"
    source: dict[str, str] = field(default_factory=dict)
    origin: str = "snapshot"
    stabilization: str | None = None
    provenance: SourceRef = field(default_factory=SourceRef)
    source_declaration: object = None
    method: str = "unknown"
    review_scope: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _record_provenance(self)
        validate_reaction_energy_properties(self.energy_properties)
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
        if self.stabilization is None and self.process in {"attachment", "recombination"}:
            object.__setattr__(self, "stabilization", "unspecified")

    @property
    def threshold_eV(self) -> float | None:
        """Read the channel threshold in eV without duplicating its declaration."""
        return self.energy_value("threshold_eV")

    @property
    def delta_e_eV(self) -> float | None:
        """Read the products-minus-reactants energy in eV when convertible."""
        return self.energy_value("delta_e_eV")

    def energy_value(self, quantity: str) -> float | None:
        return _reaction_energy_value(self.energy_properties, quantity)

    @property
    def reviewed(self) -> bool:
        return self.tier in REVIEWED_TIERS and self.status not in {"rejected", "conflicting"}

    def reviewed_for(self, claim: str) -> bool:
        """Explicit scopes restrict approval to the stated scientific claim.

        Unscoped legacy channel declarations retain their existing meaning.
        A numerical snapshot adapter supplies its quantity scope, so approval
        of its coefficient cannot qualify a channel or an energy declaration.
        """
        return self.reviewed and review_scope_covers(self.review_scope, claim)

    @property
    def label(self) -> str:
        return self.provenance.label(f"{self.origin}:{self.id}") or f"{self.origin}:{self.id}"


def validate_reaction_energy_properties(properties: dict[str, Property]) -> None:
    """Check independently supplied reaction quantities at their typed boundary."""
    if not isinstance(properties, dict):
        raise ValueError("reaction.energy_properties must be a mapping")
    for quantity, prop in properties.items():
        if quantity not in {"threshold_eV", "delta_e_eV"} or not isinstance(prop, Property):
            raise ValueError(
                "reaction.energy_properties requires threshold_eV/delta_e_eV Property records"
            )
        validate_property_definition(prop, quantity)
        if prop.value is not None and (
            not math.isfinite(prop.value) or (quantity == "threshold_eV" and prop.value < 0)
        ):
            raise ValueError(
                f"{quantity} must be finite"
                + (" and nonnegative" if quantity == "threshold_eV" else "")
            )


def reaction_energy_definition_compatible(prop: Property, quantity: str) -> bool:
    """Whether this declaration expresses the consumed channel energy quantity.

    A legacy unspecified definition supports only a declared-value comparison.
    Appearance energy is not an incident collision threshold. Free qualifiers
    can express limits or a different observable; no numerical limit is inferred
    from such text until an explicit interpretation is implemented.
    """
    if prop.qualifier is not None and (
        not isinstance(prop.qualifier, str) or prop.qualifier.strip()
    ):
        return False
    if quantity == "threshold_eV":
        return prop.definition in {None, "channel_threshold"}
    if quantity == "delta_e_eV":
        return prop.definition in {None, "products_minus_reactants"}
    return False


def channel_energy_status(record: ReactionRecord, quantity: str) -> str | None:
    """A rejected/conflicting enclosing declaration stops its nested quantity.

    Other parent tiers, scopes and statuses never approve or downgrade an
    independently reviewed Property. A missing quantity has no lifecycle claim.
    """
    prop = record.energy_properties.get(quantity)
    if prop is None:
        return None
    return record.status if record.status in {"rejected", "conflicting"} else prop.status


def qualified_channel_energy(record: ReactionRecord, quantity: str) -> Property | None:
    """Return the independently reviewed, compatible quantity, not its numerical use.

    Parent channel review never qualifies this Property; rejection of the
    enclosing declaration stops it. The caller must still check value, units,
    declared uncertainty and competing records.
    """
    prop = record.energy_properties.get(quantity)
    return (
        prop
        if prop is not None
        and channel_energy_status(record, quantity) not in {"rejected", "conflicting"}
        and prop.reviewed_for(quantity)
        and reaction_energy_definition_compatible(prop, quantity)
        else None
    )


def property_energy_bounds(prop: Property) -> tuple[float, float] | None:
    """Convert a finite energy and its declared interval to eV.

    With no numerical uncertainty this returns a nominal point, not a measured
    zero-width error interval. Invalid/absent numerical bounds remain unusable.
    """
    if prop.value is None or energy_in_eV(prop.value, prop.unit) is None:
        return None
    try:
        bounds = (
            prop.uncertainty.bounds(prop.value)
            if prop.uncertainty is not None
            else (prop.value, prop.value)
        )
    except ValueError:
        return None
    if bounds is None:
        return None
    lower, upper = (energy_in_eV(value, prop.unit) for value in bounds)
    return None if lower is None or upper is None else (lower, upper)


def energy_declarations_agree(properties: Sequence[Property]) -> bool:
    """Compare declared centers; tolerate only roundoff from different energy units."""
    for index, left in enumerate(properties):
        for right in properties[index + 1 :]:
            if left.value is None or right.value is None:
                return False
            if left.unit == right.unit:
                if left.value != right.value:
                    return False
                continue
            first = energy_in_eV(left.value, left.unit)
            second = energy_in_eV(right.value, right.unit)
            if first is None or second is None:
                if (left.value, left.unit) != (right.value, right.unit):
                    return False
            elif first != second and not math.isclose(first, second, rel_tol=1e-12, abs_tol=0.0):
                return False
    return True


def energy_properties_equivalent(left: Property, right: Property) -> bool:
    """Compare one scientific declaration across equivalent energy-unit copies.

    Only redundant value/unit and absolute-error declarations are normalized.
    Definitions, review, sources and additional scientific annotations remain
    meaningful. Original records and their raw declarations are never changed.
    """
    if (left.value is not None or right.value is not None) and not energy_declarations_agree(
        (left, right)
    ):
        return False
    if not _absolute_energy_errors_match(left, right):
        return False
    return _energy_property_comparison_content(left) == _energy_property_comparison_content(right)


def _absolute_energy_errors_match(left: Property, right: Property) -> bool:
    first = left.uncertainty.absolute if left.uncertainty is not None else None
    second = right.uncertainty.absolute if right.uncertainty is not None else None
    if first is None or second is None:
        return first is None and second is None
    return _energy_values_equal(first, left.unit, second, right.unit)


def _energy_property_comparison_content(prop: Property) -> dict:
    """Retain metadata after the caller has compared center and absolute error."""
    content = scientific_declaration(asdict(prop), prop.provenance)
    if not isinstance(content, dict):
        raise ValueError("energy Property comparison requires mapping content")
    if prop.value is not None and energy_in_eV(prop.value, prop.unit) is not None:
        content.pop("value", None)
        content.pop("unit", None)
    if (
        prop.uncertainty is not None
        and prop.uncertainty.absolute is not None
        and energy_in_eV(prop.uncertainty.absolute, prop.unit) is not None
    ):
        content["uncertainty"].pop("absolute", None)
    declaration = content.get("source_declaration")
    if isinstance(declaration, dict):
        _normalize_energy_declaration(declaration, prop)
        if not declaration:
            content["source_declaration"] = None
    return content


def _energy_values_equal(
    first: float, first_unit: str | None, second: float, second_unit: str | None
) -> bool:
    if first_unit == second_unit:
        return first == second
    converted_first = energy_in_eV(first, first_unit)
    converted_second = energy_in_eV(second, second_unit)
    return (
        converted_first is not None
        and converted_second is not None
        and math.isclose(converted_first, converted_second, rel_tol=1e-12, abs_tol=0.0)
    )


def _normalize_energy_declaration(declaration: dict, prop: Property) -> None:
    """Omit a repeated numeric declaration only when it matches the parsed quantity."""
    stated_unit = declaration.get("unit")
    unit = (
        stated_unit
        if isinstance(stated_unit, str)
        else (None if "unit" in declaration else prop.unit)
    )
    if prop.value is not None and _declared_energy_matches(
        declaration.get("value"), unit, prop.value, prop.unit
    ):
        declaration.pop("value", None)
        declaration.pop("unit", None)
    uncertainty = declaration.get("uncertainty")
    if (
        isinstance(uncertainty, dict)
        and prop.uncertainty is not None
        and prop.uncertainty.absolute is not None
        and _declared_energy_matches(
            uncertainty.get("absolute"),
            uncertainty.get("unit")
            if isinstance(uncertainty.get("unit"), str)
            else (None if "unit" in uncertainty else unit),
            prop.uncertainty.absolute,
            prop.unit,
        )
    ):
        uncertainty.pop("absolute", None)
        uncertainty.pop("unit", None)
        if not uncertainty:
            declaration.pop("uncertainty", None)
    nested = declaration.get("source_declaration")
    if isinstance(nested, dict):
        _normalize_energy_declaration(nested, prop)


def _declared_energy_matches(
    value: object, unit: str | None, parsed: float, parsed_unit: str | None
) -> bool:
    try:
        number = normalized_number(value)
    except ValueError:
        # Original source annotations need not follow the normalized value schema.
        return False
    return number is not None and _energy_values_equal(number, unit, parsed, parsed_unit)


def normalized_reaction_energy_properties(
    record: dict, default_source: object = None
) -> dict[str, Property]:
    """Adapt legacy scalar declarations once; keep explicit quantity review separate.

    Old channel scalars preserve their existing channel qualification and raw
    declaration, but receive no inferred definition or uncertainty. Explicit
    quantity records carry their own tier, status, review scope and method.
    Duplicated scalar/quantity values must agree after unit conversion.
    """
    entries = record.get("energy_properties")
    if entries is None:
        entries = {}
    if not isinstance(entries, dict) or any(
        not isinstance(value, dict) for value in entries.values()
    ):
        raise ValueError("reaction.energy_properties must be a mapping of property records")
    provenance, _ = source_information(record, default_source)
    source = _source_mapping(default_source) | _source_mapping(record.get("source"))
    status = str(record.get("status") or "imported")
    properties = {
        str(name): normalized_property(
            entry,
            # A portable Property has already resolved its source context.
            # Reloading it must not invent a link to the enclosing channel.
            default_source=None
            if "provenance" in entry and "source_declaration" in entry
            else source,
            quantity=str(name),
        )
        for name, entry in entries.items()
    }
    for quantity, external in (
        ("threshold_eV", "threshold_eV"),
        ("delta_e_eV", "deltaE_products_minus_reactants_eV"),
    ):
        value = normalized_number(record.get(external), external)
        if value is None:
            continue
        explicit = properties.get(quantity)
        if explicit is not None:
            converted = (
                energy_in_eV(explicit.value, explicit.unit) if explicit.value is not None else None
            )
            if converted is None or not math.isclose(converted, value, rel_tol=1e-9, abs_tol=1e-9):
                raise ValueError(f"reaction scalar and {quantity} property disagree")
            continue
        properties[quantity] = Property(
            value=value,
            unit="eV",
            source=provenance.label(),
            tier=_declared_tier(record, evidence_tier(status, source)),
            provenance=provenance,
            source_declaration={"legacy_scalar": external, "value": value, "unit": "eV"},
            method=scientific_method(record, default_source),
            review_scope=review_scope(record),
            status=status,
        )
    validate_reaction_energy_properties(properties)
    return properties


def reaction_has_numeric_declaration(record: dict) -> bool:
    """A quantity record must be stated, rather than inferred from a channel claim."""
    return any(
        name in record
        for name in (
            "kind",
            "form",
            "representation",
            "parameters",
            "params",
            "asset",
            "data",
            "value",
            "unit",
        )
    )


def normalized_reaction_record(
    record: dict,
    equation_key: EquationKey,
    states: tuple[StateCandidate, ...],
    default_source: object = None,
    *,
    origin: str = "snapshot",
    datasets: tuple[NumericDataset, ...] = (),
    preserved_record_id: bool = False,
) -> ReactionRecord:
    """Normalize a channel declaration independently of its numerical datasets.

    The caller identifies the physical equation; approval is retained only for
    its declared claims. New source IDs occupy a reaction-record namespace,
    distinct from coefficient records. Portable overlays preserve that ID.
    """
    provenance, declaration = source_information(record, default_source)
    source = _source_mapping(default_source) | _source_mapping(record.get("source"))
    status = str(record.get("status") or "imported")
    scopes = review_scope(record)
    if not scopes and reaction_has_numeric_declaration(record):
        scopes = (
            str(record.get("kind") or (datasets[0].kind if datasets else "rate_coefficient")),
        )
    if preserved_record_id:
        identifier = record.get("id")
        if not isinstance(identifier, str) or not identifier.strip():
            raise ValueError("reaction record id must be nonempty text")
    elif record.get("id") is not None:
        identifier = f"reaction-record:{numerical_record_id(record, default_source)}"
    else:
        identity = deepcopy(record) | {"review_scope": list(scopes)}
        _reaction_quantity_declaration_content(identity)
        claim_declaration = deepcopy(declaration)
        if isinstance(claim_declaration, dict):
            _reaction_quantity_declaration_content(claim_declaration)
        identifier = _source_record_identity(identity, provenance, claim_declaration, "reaction")
    family = record.get("family")
    return ReactionRecord(
        id=identifier,
        equation_key=equation_key,
        family=canonical_family(str(family)) if family is not None else None,
        process=str(record.get("type") or "attested"),
        states=states,
        datasets=datasets,
        energy_properties=normalized_reaction_energy_properties(
            record | {"review_scope": list(scopes)}, default_source
        ),
        channel_scope=str(record.get("channel_scope") or "product_resolved"),
        status=status,
        tier=_declared_tier(record, evidence_tier(status, source)),
        source=source,
        origin=origin,
        stabilization=record.get("stabilization"),
        provenance=provenance,
        source_declaration=declaration,
        method=scientific_method(record, default_source),
        review_scope=scopes,
    )


def reaction_record_payload(record: ReactionRecord) -> dict:
    """One portable scientific declaration for overlays and Registry channels.

    Numerical records normally travel in their quantity collection so saving a
    channel claim does not duplicate or change numerical qualification.
    """
    third_body, surface, reactants, products = record.equation_key
    left = " + ".join(str(Term(name, count)) for name, count in reactants)
    right = " + ".join(str(Term(name, count)) for name, count in products)
    if third_body is not None:
        left, right = f"{left} + {third_body}", f"{right} + {third_body}"
    payload = {
        "id": record.id,
        "reaction": f"{left} -> {right}",
        "family": record.family,
        "type": record.process,
        "third_body": third_body,
        "surface": surface,
        "stabilization": record.stabilization,
        "channel_scope": record.channel_scope,
        "energy_properties": {
            name: asdict(prop) for name, prop in record.energy_properties.items()
        },
        "status": record.status,
        "evidence_tier": record.tier,
        "source": record.source,
        "provenance": asdict(record.provenance),
        "source_declaration": deepcopy(record.source_declaration),
        "method": record.method,
        "review_scope": list(record.review_scope),
    }
    return _portable_payload({name: value for name, value in payload.items() if value is not None})


def scientific_reaction_content(record: ReactionRecord | dict) -> dict:
    """Compare reaction claims; independent numerical datasets compare themselves."""
    payload = reaction_record_payload(record) if isinstance(record, ReactionRecord) else record
    source = normalized_source(payload.get("provenance"), payload.get("source"))
    content = scientific_declaration(payload, source)
    if not isinstance(content, dict):
        raise ValueError("scientific reaction record must be a mapping")
    properties = normalized_reaction_energy_properties(payload)
    content["energy_properties"] = {
        name: scientific_declaration(asdict(prop), prop.provenance)
        for name, prop in properties.items()
    }
    # Old portable scalar records compare through the same external adapter.
    # Their author's declaration remains intact in source_declaration.
    content.pop("threshold_eV", None)
    content.pop("deltaE_products_minus_reactants_eV", None)
    _reaction_quantity_declaration_content(content)
    return content


def _reaction_quantity_declaration_content(content: dict) -> None:
    """A mixed input retains its original quantity declaration only for provenance."""
    content.pop("datasets", None)
    if reaction_has_numeric_declaration(content):
        for name in (
            "kind",
            "form",
            "representation",
            "parameters",
            "params",
            "asset",
            "data",
            "value",
            "unit",
            "independent_variable",
            "observable",
            "reaction_order",
            "parameter_units",
            "reference_temperature_K",
            "validity",
            "uncertainty",
            "preferred",
        ):
            content.pop(name, None)
    declaration = content.get("source_declaration")
    if isinstance(declaration, dict):
        _reaction_quantity_declaration_content(declaration)


def normalized_state_record(
    record: dict,
    candidate: StateCandidate,
    default_source: object = None,
    *,
    origin: str = "snapshot",
    preserved_record_id: bool = False,
) -> StateRecord:
    """Normalize one independent scientific declaration for an identified state.

    ``id`` identifies the physical target for existing callers; ``record_id``
    identifies this declaration. Neither properties nor a NASA fit assert that
    the state exists. Identification is supplied by the calling input adapter.
    """
    provenance, declaration = source_information(record, default_source)
    if not preserved_record_id and record.get("record_id") is not None:
        native = record["record_id"]
        if not isinstance(native, str) or not native.strip():
            raise ValueError("record_id must be nonempty text")
        if provenance.record_id not in {None, native}:
            raise ValueError("state record_id contradicts source.record_id")
        provenance = SourceRef(**(asdict(provenance) | {"record_id": native}))
    source = _source_mapping(default_source) | _source_mapping(record.get("source"))
    status = str(record.get("status") or "imported")
    tier = _declared_tier(record, evidence_tier(status, source))
    entries = record.get("properties") or {}
    if not isinstance(entries, dict) or any(
        not isinstance(item, dict) for item in entries.values()
    ):
        raise ValueError("state record properties must be a mapping of property records")
    properties = {
        str(name): normalized_property(entry, default_source=source, quantity=str(name))
        for name, entry in entries.items()
    }
    name = record.get("property")
    fit = record.get("thermo") or (record.get("value") if name == "thermo" else None)
    if name and name != "thermo":
        properties[str(name)] = normalized_property(record, tier, source, quantity=str(name))
    excitation = normalized_number(record.get("excitation_energy_eV"))
    if excitation is not None and "excitation_energy_eV" not in properties:
        properties["excitation_energy_eV"] = normalized_property(
            record | {"value": excitation, "unit": "eV"}, tier, source
        )
    return StateRecord(
        id=str(record.get("species") or candidate.id),
        candidate=candidate,
        record_id=state_record_id(record, default_source, preserved_record_id=preserved_record_id),
        properties=properties,
        thermo=normalized_thermo(fit, default_source=source),
        existence=str(record.get("existence") or "unknown"),
        existence_source=record.get("existence_source"),
        status=status,
        tier=tier,
        source=source,
        provenance=provenance,
        source_declaration=declaration,
        method=scientific_method(record, default_source),
        review_scope=review_scope(record),
        origin=origin,
        energy_eV=excitation,
        configuration=record.get("configuration"),
        term=record.get("term"),
        j=None if record.get("J") is None else str(record["J"]),
        parity=record.get("parity"),
        degeneracy=normalized_number(record.get("degeneracy")),
        lifetime_s=normalized_number(record.get("lifetime_s")),
        members=tuple(record.get("members") or ()),
    )


def state_record_payload(record: StateRecord) -> dict:
    """Portable declaration, shared by overlay and Registry record arrays."""
    state = record.candidate.state
    payload = {
        "species": record.candidate.id,
        "record_id": record.record_id,
        "phase": record.candidate.phase,
        "structure": record.candidate.structure,
        "state": {"kind": state.kind, "label": state.label, "resolution": state.resolution},
        "properties": {name: asdict(prop) for name, prop in record.properties.items()},
        "thermo": asdict(record.thermo) if record.thermo is not None else None,
        "existence": record.existence,
        "existence_source": record.existence_source,
        "configuration": record.configuration,
        "term": record.term,
        "J": record.j,
        "parity": record.parity,
        "degeneracy": record.degeneracy,
        "lifetime_s": record.lifetime_s,
        "excitation_energy_eV": record.energy_eV,
        "members": list(record.members),
        "status": record.status,
        "evidence_tier": record.tier,
        "source": record.source,
        "provenance": asdict(record.provenance),
        "source_declaration": deepcopy(record.source_declaration),
        "method": record.method,
        "review_scope": list(record.review_scope),
    }
    return _portable_payload({name: value for name, value in payload.items() if value is not None})


def _portable_payload(value: Any) -> Any:
    """Use YAML sequence shapes consistently before comparing or persisting records."""
    if isinstance(value, dict):
        return {key: _portable_payload(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_portable_payload(item) for item in value]
    return value


def normalized_dataset(
    record: dict,
    *,
    base: Path | None = None,
    default_id: str | None = None,
    default_kind: str = "rate_coefficient",
    default_source: dict[str, str] | None = None,
    allowed_asset_root: Path | None = None,
) -> NumericDataset:
    """Normalize either a Registry Dataset or one snapshot/overlay mapping."""

    source = _source_mapping(default_source) | _source_mapping(record.get("source"))
    provenance, declaration = source_information(record, default_source)
    status = str(record.get("status") or "imported")
    form = str(record.get("form") or record.get("representation") or "reference_only")
    parameters = record.get("parameters", record.get("params"))
    if parameters is None:
        parameters = {}
    if not isinstance(parameters, dict):
        raise ValueError("dataset.parameters must be a mapping")
    kind = str(record.get("kind") or default_kind)
    observable = _text(record.get("observable")) or {
        "rate_coefficient": "reaction_rate",
        "sticking_coefficient": "sticking_probability",
    }.get(kind)
    asset = asset_reference(record.get("asset"), base, allowed_asset_root)
    identity = record
    if (
        record.get("id") is None
        and provenance.record_id is None
        and asset is not None
        and asset.read_bytes(False) is not None
    ):
        identity = deepcopy(record)
        _asset_declaration_content(identity, asset.sha256)
        identity["asset"]["declared_sha256"] = asset.declared_sha256
    return NumericDataset(
        id=numerical_record_id(identity, default_source, default_id),
        kind=kind,
        form=form,
        unit=_text(record.get("unit")),
        independent_variable=_text(record.get("independent_variable")),
        observable=observable,
        channel_scope=str(record.get("channel_scope") or "product_resolved"),
        params={
            key: number
            for key, value in parameters.items()
            if key != "source_unit"
            and (number := normalized_number(value, f"dataset.parameters.{key}")) is not None
        },
        asset=asset,
        validity=_validity(record.get("validity"), _text(record.get("independent_variable"))),
        uncertainty=_uncertainty(record.get("uncertainty"), parameters, _text(record.get("unit"))),
        source=source,
        status=status,
        tier=_declared_tier(record, evidence_tier(status, source)),
        preferred=record.get("preferred", False),
        reaction_order=normalized_number(record.get("reaction_order"), "dataset.reaction_order"),
        parameter_units=(
            {"source_value": str(parameters["source_unit"])}
            if parameters.get("source_unit")
            else {}
        )
        | _strings(record.get("parameter_units") or {}),
        reference_temperature_K=normalized_number(
            record.get("reference_temperature_K"), "dataset.reference_temperature_K"
        ),
        provenance=provenance,
        source_declaration=declaration,
        method=scientific_method(record, default_source),
        review_scope=review_scope(record),
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
        "provenance": asdict(dataset.provenance),
        "source_declaration": deepcopy(dataset.source_declaration),
        "method": dataset.method,
        "review_scope": list(dataset.review_scope),
        "status": dataset.status,
        "tier": dataset.tier,
        "preferred": dataset.preferred,
        "reaction_order": dataset.reaction_order,
        "parameter_units": dataset.parameter_units,
        "reference_temperature_K": dataset.reference_temperature_K,
    }


def _validity(data: object, independent_variable: str | None = None) -> Validity | None:
    if data is None:
        return None
    if not isinstance(data, dict):
        raise ValueError("validity must be a mapping")
    unit = _text(data.get("unit"))
    default_quantity = independent_variable or {
        "K": "unspecified_temperature",
        "Td": "reduced_field",
        "eV": "collision_energy",
    }.get(unit or "", "unspecified")
    return Validity(
        quantity=str(data.get("quantity") or default_quantity),
        minimum=normalized_number(data.get("minimum"), "validity.minimum"),
        maximum=normalized_number(data.get("maximum"), "validity.maximum"),
        unit=unit,
    )


def _uncertainty(
    data: object, parameters: dict, parent_unit: str | None = None
) -> Uncertainty | None:
    if data is None:
        factor = normalized_number(parameters.get("uncertainty_factor"))
        relative = normalized_number(parameters.get("relative_uncertainty"))
        return Uncertainty(factor, relative) if factor is not None or relative is not None else None
    if not isinstance(data, dict):
        raise ValueError("uncertainty must be a mapping")
    absolute, conversion = _absolute_uncertainty(data, parent_unit)
    note = "; ".join(text for text in (_text(data.get("note")), conversion) if text) or None
    return Uncertainty(
        factor=normalized_number(data.get("factor")),
        relative=normalized_number(data.get("relative")),
        note=note,
        absolute=absolute,
    )


def _absolute_uncertainty(data: dict, parent_unit: str | None) -> tuple[float | None, str | None]:
    """Absolute bounds use the parent value's unit in the normalized record."""
    absolute = normalized_number(data.get("absolute"))
    declared_unit = _text(data.get("unit"))
    if absolute is None or declared_unit is None or declared_unit == parent_unit:
        return absolute, None
    converted = energy_in_eV(absolute, declared_unit)
    parent_scale = energy_in_eV(1.0, parent_unit)
    if converted is None or parent_scale is None:
        raise ValueError("absolute uncertainty unit cannot be converted to the parent value unit")
    normalized = converted / parent_scale
    return normalized, (
        f"absolute uncertainty {absolute!r} {declared_unit} converted to "
        f"{normalized!r} {parent_unit} using energy-per-particle unit conversion"
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
    return {
        "factor": value.factor,
        "relative": value.relative,
        "note": value.note,
        "absolute": value.absolute,
    }


def _strings(data: dict) -> dict[str, str]:
    return {str(key): str(value) for key, value in data.items() if value is not None}


def _text(value: object) -> str | None:
    return None if value is None else str(value)


def _typed_number(value: object, name: str, *, optional: bool = True) -> None:
    """Internal records require numbers; invalid physical values remain inspectable."""
    if value is None and optional:
        return
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError(f"{name} must be a number" + (" or null" if optional else ""))


def normalized_number(value: object, name: str = "value") -> float | None:
    """Accept explicit numeric text at an external boundary, never malformed omissions.

    Nonfinite numeric declarations are retained for numerical invalidity checks
    and result round trips; bools and nonnumeric text are format errors.
    """
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int | float | str):
        raise ValueError(f"{name} must be numeric or null")
    try:
        return float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{name} must be numeric or null") from None
