from __future__ import annotations

from typing import Any, Callable

from plasma_reactgen.domain.models import GeneratedReaction


AssetExists = Callable[[str | None], bool]
DATASET_OUTPUT_KINDS = {
    "cross_sections": "cross_section",
    "rate_coefficients": "rate_coefficient",
    "mobility": "mobility",
}


def reaction_available_data(
    reaction: GeneratedReaction,
    asset_exists: AssetExists | None = None,
) -> dict[str, list[dict[str, Any]]]:
    return {
        output_name: dataset_payloads(reaction, kind, asset_exists)
        for output_name, kind in DATASET_OUTPUT_KINDS.items()
    }


def reaction_output(
    reaction: GeneratedReaction,
    asset_exists: AssetExists | None = None,
) -> dict[str, Any]:
    """Build the stable public reaction record explicitly."""

    return {
        "id": reaction.id,
        "depth": reaction.depth,
        "family": reaction.family,
        "type": reaction.type,
        "equation": reaction.equation,
        "reactants": [
            {"species": item.species, "n": item.n} for item in reaction.reactants
        ],
        "products": [
            {"species": item.species, "n": item.n} for item in reaction.products
        ],
        "source_pair_key": reaction.source_pair_key,
        "source_pair_label": reaction.source_pair_label,
        "introduced_species": list(reaction.introduced_species),
        "validation": dict(reaction.validation),
        "data_status": dict(reaction.data_status),
        "threshold_eV": reaction.threshold_eV,
        "deltaE_products_minus_reactants_eV": reaction.deltaE_products_minus_reactants_eV,
        "dnt_class": reaction.dnt_class,
        "data": reaction.data,
        "evidence": reaction.evidence,
        "provenance": reaction.provenance,
        "source_record": reaction.source_record,
        "confidence": reaction.confidence,
        "datasets": [item.to_dict() for item in reaction.datasets],
        "precursor_reaction_ids": list(reaction.precursor_reaction_ids),
        "available_data": reaction_available_data(reaction, asset_exists),
        "provenance_summary": provenance_summary(reaction),
    }


def provenance_summary(reaction: GeneratedReaction) -> dict[str, Any]:
    record = provenance_record(reaction)
    dataset_source = next(
        (
            dataset.source
            for dataset in sorted(
                reaction.datasets,
                key=lambda item: (not item.preferred, item.id),
            )
            if dataset.source is not None
        ),
        None,
    )
    summary = {
        "available": record is not None or dataset_source is not None,
        "source_type": None,
        "source_id": None,
        "citation": None,
        "confidence": reaction.confidence,
    }
    if record is not None:
        summary.update(
            {
                "source_type": record.get("source_type") or record.get("type"),
                "source_id": record.get("source_id") or record.get("id"),
                "citation": record.get("citation"),
            }
        )
    elif dataset_source is not None:
        summary.update(
            {
                "source_type": dataset_source.source_type,
                "source_id": dataset_source.source_id,
                "citation": dataset_source.citation,
            }
        )
    return summary


def provenance_record(reaction: GeneratedReaction) -> dict[str, Any] | None:
    """Return the canonical provenance record with legacy-data fallback."""

    for item in (reaction.provenance, reaction.source_record, reaction.evidence):
        if isinstance(item, dict) and item:
            return dict(item)
    if isinstance(reaction.data, dict):
        for key in ("provenance", "source_record", "evidence"):
            item = reaction.data.get(key)
            if isinstance(item, dict) and item:
                return dict(item)
    return None


def available_dataset_ids(
    reaction: GeneratedReaction,
    kind: str,
    asset_exists: AssetExists | None = None,
) -> list[str]:
    unavailable_statuses = {
        "missing",
        "path_registered_but_missing",
        "reference_only_needs_import",
        "unavailable",
    }
    if (
        kind == "cross_section"
        and reaction.family == "electron"
        and "cross_section" in reaction.data_status
        and reaction.data_status["cross_section"] != "local_file_registered"
    ):
        return []
    return sorted(
        dataset.id
        for dataset in reaction.datasets
        if dataset.kind == kind
        and dataset.status not in unavailable_statuses
        and dataset.representation != "reference_only"
        and _representation_is_available(dataset, asset_exists)
    )


def dataset_payloads(
    reaction: GeneratedReaction,
    kind: str,
    asset_exists: AssetExists | None = None,
) -> list[dict[str, Any]]:
    available = set(available_dataset_ids(reaction, kind, asset_exists))
    payloads = []
    for dataset in sorted(reaction.datasets, key=lambda item: item.id):
        if dataset.kind != kind:
            continue
        payload = dataset.to_dict()
        payload["available"] = dataset.id in available
        payloads.append(payload)
    return payloads


def _representation_is_available(dataset, asset_exists: AssetExists | None) -> bool:
    if dataset.representation != "table":
        return True
    path = dataset.asset.path if dataset.asset is not None else None
    if not path:
        return False
    if asset_exists is None:
        # Compatibility for callers working with an in-memory network.  Core
        # generate always supplies the registry resolver below.
        return True
    try:
        return bool(asset_exists(path))
    except (OSError, TypeError, ValueError):
        return False
