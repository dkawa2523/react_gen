"""Write the output bundle.

::

    species.yaml              every state with property values, thermo and sources
    species.csv               one row per state: composition, then every property
    species_sources.csv       the same values long-form, each with where it came from
    species_thermo.csv        NASA polynomial coefficients, one row per state
    reactions.yaml / .csv     the list with lineage, rate, relevance and datasets
    coverage.yaml             how much of each declared literature mechanism is present
    gaps.yaml                 everything still missing, in one list
    summary.yaml              counts, coverage, completeness, mechanism id
    network.dot               Graphviz view
    datasets/rates.yaml       coefficients evaluated at the case conditions
    datasets/cross_sections/  electron tables, copied local, plus an index
    datasets/dnt/             one DNT+ input per ion-neutral pair, plus an index
"""

from __future__ import annotations

import csv
import shutil
from dataclasses import asdict
from pathlib import Path

import yaml

from reactgen import coverage, dnt, graph, known, layers, rank
from reactgen.case import Case
from reactgen.model import Dataset, Gap, Network, Reaction
from reactgen.physics import Rate, applicability, energy_cost_eV, feasibility, rate_of
from reactgen.registry import Registry


def write(
    outdir: Path,
    case: Case,
    network: Network,
    registry: Registry,
    gaps: list[Gap],
    mechanism_id: str,
    listed: known.Index | None = None,
    selected: tuple[str, ...] = layers.LAYERS,
) -> None:
    """Write the bundle. ``listed`` labels each reaction with who states it.

    A label, not a gate. Screening decided which channels exist; a source
    naming the same equation is confirmation to record beside it, and its
    silence is not evidence against a channel the energetics allow.
    """

    outdir.mkdir(parents=True, exist_ok=True)
    rates = {
        r.id: rate_of(r, network.species, case.conditions, registry.table)
        for r in network.reactions
    }
    ranking = rank.annotate(network, rates, case.conditions)
    records = [
        _reaction(r, case, network, rates[r.id], ranking[r.id], listed, selected)
        for r in network.reactions
    ]

    _yaml(outdir / "species.yaml", _species_doc(case, network))
    _yaml(outdir / "reactions.yaml", _reactions_doc(case, records))
    _yaml(outdir / "reduced.yaml", _reduced_doc(case, records))
    _yaml(outdir / "coverage.yaml", coverage.build(case, network, registry.root))
    _yaml(outdir / "gaps.yaml", _gaps_doc(case, gaps))
    _yaml(outdir / "summary.yaml", _summary_doc(case, network, gaps, ranking, mechanism_id))
    _reactions_csv(outdir / "reactions.csv", records)
    _species_csv(outdir / "species.csv", network)
    _species_sources_csv(outdir / "species_sources.csv", network)
    _species_thermo_csv(outdir / "species_thermo.csv", network)
    graph.write(outdir / "reaction_network.dot", network)
    graph.write(outdir / "species_lineage.dot", network, lineage=True)

    datasets = outdir / "datasets"
    _yaml(datasets / "rates.yaml", _rates_doc(case, network, rates, ranking))
    _cross_sections(datasets / "cross_sections", network, registry)
    _dnt_inputs(datasets / "dnt", case, network, registry)


# --------------------------------------------------------------------------- species


def _species_doc(case: Case, network: Network) -> dict:
    return {
        "case": case.name,
        "species": [
            {
                "id": species.id,
                "charge": species.charge,
                "composition": species.composition,
                "classes": sorted(species.classes),
                "state": {
                    "kind": species.state.kind,
                    "label": species.state.label,
                    "energy_eV": species.state.energy_eV,
                    "resolution": species.state.resolution,
                    "members": list(species.state.members),
                },
                "depth": network.depth.get(species.id, 0),
                "introduced_by": sorted(set(network.origin.get(species.id, []))) or ["input_gas"],
                "properties": {
                    name: {"value": prop.value, "unit": prop.unit, "source": prop.source}
                    for name, prop in sorted(species.properties.items())
                },
                "thermo": None if species.thermo is None else asdict(species.thermo),
                "status": species.status,
            }
            for species in sorted(network.species.values(), key=lambda s: s.id)
        ],
    }


# --------------------------------------------------------------------------- reactions


def _reactions_doc(case: Case, records: list[dict]) -> dict:
    return {
        "case": case.name,
        "conditions": _conditions(case),
        "note": "relevance is a one-sided upper bound; nothing has been removed here",
        "reactions": records,
    }


def _reduced_doc(case: Case, records: list[dict]) -> dict:
    """The same list with provably negligible reactions taken out."""

    kept = [item for item in records if item["relevance"] != "negligible"]
    dropped = [item["id"] for item in records if item["relevance"] == "negligible"]
    basis = records[0]["relevance_basis"] if records else "none"
    return {
        "case": case.name,
        "conditions": _conditions(case),
        "criterion": f"upper-bound frequency more than 6 decades below the {basis}",
        "kept": len(kept),
        "dropped": len(dropped),
        "dropped_ids": dropped,
        "reactions": kept,
    }


def _reaction(
    reaction: Reaction,
    case: Case,
    network: Network,
    rate: Rate | None,
    ranked: dict,
    listed: known.Index | None = None,
    selected: tuple[str, ...] = layers.LAYERS,
) -> dict:
    attested = sorted({f.source for f in listed.lists(reaction.equation)}) if listed else []
    return {
        "id": reaction.id,
        "equation": reaction.equation,
        "listed_by": attested,
        "evidence": layers.verdicts(reaction, attested, ranked.get("relevance"), selected),
        "family": reaction.family,
        "type": reaction.type,
        "depth": reaction.depth,
        "reactants": [{"species": t.species, "n": t.n} for t in reaction.reactants],
        "products": [{"species": t.species, "n": t.n} for t in reaction.products],
        "third_body": reaction.third_body,
        "surface": reaction.surface,
        "threshold_eV": reaction.threshold_eV,
        "delta_e_eV": reaction.delta_e_eV,
        "electron_energy_cost_eV": energy_cost_eV(reaction),
        "thermodynamics": feasibility(reaction, network.species, case.conditions),
        "reverse": reaction.reverse,
        "precursors": reaction.precursors,
        "consume": reaction.rate_form,
        "rate": None if rate is None else asdict(rate),
        **ranked,
        "datasets": [_dataset(item, case) for item in reaction.datasets],
        "status": reaction.status,
        "source": reaction.source,
    }


def _dataset(dataset: Dataset, case: Case) -> dict:
    return {
        "id": dataset.id,
        "kind": dataset.kind,
        "form": dataset.form,
        "unit": dataset.unit,
        "usable": dataset.usable,
        "preferred": dataset.preferred,
        "applicability": applicability(dataset, case.conditions),
        "uncertainty": None if dataset.uncertainty is None else asdict(dataset.uncertainty),
        "asset": dataset.asset,
        "source": dataset.source,
    }


CSV_COLUMNS = [
    "id",
    "equation",
    "family",
    "type",
    "depth",
    "consume",
    "threshold_eV",
    "electron_energy_cost_eV",
    "rate_value",
    "rate_unit",
    "rate_basis",
    "reverse_rate",
    "frequency_upper_bound_s-1",
    "relevance",
    "delta_g_eV",
    "status",
    "source",
]


def _reactions_csv(path: Path, records: list[dict]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(CSV_COLUMNS)
        for item in records:
            rate = item["rate"] or {}
            thermodynamics = item["thermodynamics"] or {}
            writer.writerow(
                [
                    item["id"],
                    item["equation"],
                    item["family"],
                    item["type"],
                    item["depth"],
                    item["consume"],
                    item["threshold_eV"],
                    item["electron_energy_cost_eV"],
                    rate.get("value", ""),
                    rate.get("unit", ""),
                    rate.get("basis", ""),
                    rate.get("reverse") or "",
                    item["frequency_upper_bound_s-1"] or "",
                    item["relevance"],
                    thermodynamics.get("delta_g_eV", ""),
                    item["status"],
                    item["source"].get("citation", ""),
                ]
            )


# The scalar properties a state list is asked for, in the order a reader wants
# them: what the species is, then how it moves, then what it costs to make.
SPECIES_PROPERTIES = (
    "mass_amu",
    "polarizability_A3",
    "dipole_moment_D",
    "collision_radius_A",
    "well_depth_K",
    "enthalpy_formation_eV",
    "entropy_J_mol_K",
    "ionization_energy_eV",
    "electron_affinity_eV",
    "vibrational_quantum_eV",
)


def _species_csv(path: Path, network: Network) -> None:
    """One row per state, with a column per element actually present.

    The element columns are built from the bundle rather than fixed, because the
    registry spans eighteen elements and any one case uses three or four; a
    fixed header would be mostly empty columns. `formula` keeps the composition
    readable in one field for anything that reads the file by eye.
    """

    listed = sorted(network.species.values(), key=lambda item: item.id)
    elements = sorted({element for item in listed for element in item.composition})
    header = (
        ["id", "formula", "charge", "state_kind", "state_label", "state_energy_eV", "depth"]
        + [f"n_{element}" for element in elements]
        + list(SPECIES_PROPERTIES)
        + ["has_thermo", "status", "missing"]
    )
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(header)
        for item in listed:
            values = {name: item.value(name) for name in SPECIES_PROPERTIES}
            writer.writerow(
                [
                    item.id,
                    _formula(item.composition),
                    item.charge,
                    item.state.kind,
                    item.state.label,
                    item.state.energy_eV,
                    network.depth.get(item.id, 0),
                ]
                + [item.composition.get(element, 0) for element in elements]
                + ["" if value is None else value for value in values.values()]
                + [
                    "yes" if item.thermo else "no",
                    item.status,
                    " ".join(name for name, value in values.items() if value is None),
                ]
            )


def _species_sources_csv(path: Path, network: Network) -> None:
    """Every property value long-form, so provenance survives the flattening.

    Without this the wide table cannot be read: a dipole moment of zero is
    either a measurement, a symmetry argument or an untouched default, and a
    single number column says which one it is only by losing the distinction.
    """

    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["id", "property", "value", "unit", "source"])
        for item in sorted(network.species.values(), key=lambda entry: entry.id):
            for name, prop in sorted(item.properties.items()):
                if prop.value is not None:
                    writer.writerow([item.id, name, prop.value, prop.unit or "", prop.source or ""])
            if item.thermo is not None:
                writer.writerow([item.id, "nasa7", "", "", item.thermo.source or ""])


def _species_thermo_csv(path: Path, network: Network) -> None:
    """NASA 7-coefficient polynomials, kept out of the wide table.

    Fifteen numeric columns would swamp the ten properties beside them, and a
    polynomial is read by a program rather than by eye.
    """

    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            ["id", "t_min", "t_mid", "t_max"]
            + [f"a{n}_low" for n in range(1, 8)]
            + [f"a{n}_high" for n in range(1, 8)]
            + ["source"]
        )
        for item in sorted(network.species.values(), key=lambda entry: entry.id):
            fit = item.thermo
            if fit is None:
                continue
            writer.writerow(
                [item.id, fit.t_min, fit.t_mid, fit.t_max, *fit.low, *fit.high, fit.source or ""]
            )


def _formula(composition: dict[str, int]) -> str:
    return "".join(
        element if count == 1 else f"{element}{count}"
        for element, count in sorted(composition.items())
    )


# --------------------------------------------------------------------------- datasets


def _rates_doc(case: Case, network: Network, rates: dict, ranking: dict) -> dict:
    return {
        "case": case.name,
        "conditions": _conditions(case),
        "note": "langevin_estimate values are capture upper bounds, not measurements",
        "rates": [
            {
                "reaction_id": reaction.id,
                "equation": reaction.equation,
                "family": reaction.family,
                "third_body": reaction.third_body,
                **asdict(rates[reaction.id]),
                **ranking[reaction.id],
            }
            for reaction in network.reactions
            if rates[reaction.id] is not None
        ],
    }


def _cross_sections(outdir: Path, network: Network, registry: Registry) -> None:
    outdir.mkdir(parents=True, exist_ok=True)
    index = []
    for reaction in network.reactions:
        if reaction.rate_form != "cross_section":
            continue
        dataset = reaction.best("cross_section")
        source = registry.asset_path(dataset.asset) if dataset else None
        if source is None:
            index.append({"reaction_id": reaction.id, "file": None, "status": "needs_import"})
            continue
        target = outdir / f"{reaction.id}.csv"
        shutil.copyfile(source, target)
        index.append({"reaction_id": reaction.id, "file": target.name, "status": "available"})
    _yaml(outdir / "index.yaml", {"cross_sections": index})


def _dnt_inputs(outdir: Path, case: Case, network: Network, registry: Registry) -> None:
    """The index is the work order; a document is written per runnable pair.

    Every pair the network holds is listed in the index, blocked ones included.
    Writing a full input for each would bury the runnable ones under thousands
    of stubs, so only pairs some tier can actually run get a file.
    """

    outdir.mkdir(parents=True, exist_ok=True)
    documents, index = dnt.build(case, network, registry)
    for document in documents:
        if document["runnable"]:
            _yaml(outdir / f"{document['pair']}.yaml", document)
    _yaml(outdir / "index.yaml", index)


# --------------------------------------------------------------------------- reports


def _gaps_doc(case: Case, gaps: list[Gap]) -> dict:
    return {"case": case.name, "counts": _counts(gaps), "gaps": [asdict(gap) for gap in gaps]}


def _summary_doc(
    case: Case, network: Network, gaps: list[Gap], ranking: dict, mechanism_id: str
) -> dict:
    needed = {
        form: [r for r in network.reactions if r.rate_form == form]
        for form in {r.rate_form for r in network.reactions}
    }
    relevance: dict[str, int] = {}
    for ranked in ranking.values():
        relevance[ranked["relevance"]] = relevance.get(ranked["relevance"], 0) + 1
    return {
        "mechanism_id": mechanism_id,
        "case": case.name,
        "gases": list(case.gases),
        "conditions": _conditions(case),
        "species": len(network.species),
        "reactions": len(network.reactions),
        "by_family": network.by_family(),
        "max_depth": max((r.depth for r in network.reactions), default=0),
        "complete": not network.truncated,
        "truncated_by": network.truncated,
        "data_coverage": {
            form: f"{sum(1 for r in group if r.best(form))}/{len(group)}"
            for form, group in sorted(needed.items())
        },
        "relevance": dict(sorted(relevance.items())),
        "gaps": _counts(gaps),
    }


def _counts(gaps: list[Gap]) -> dict[str, int]:
    return {
        severity: sum(gap.severity == severity for gap in gaps)
        for severity in ("blocking", "data", "info")
    }


def _conditions(case: Case) -> dict:
    return {k: v for k, v in asdict(case.conditions).items() if v is not None}


def _yaml(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(payload, sort_keys=False, allow_unicode=True, default_flow_style=False),
        encoding="utf-8",
    )
