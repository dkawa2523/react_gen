# Benchmark Report Guide

`external_data_tools.benchmark_report` converts benchmark runner outputs into a
human-readable Markdown evaluation. It is intended for the local semiconductor
benchmark suite:

- Ar/O2 simple oxygen plasma
- Ar/CF4 fluorocarbon plasma
- Ar/SF6/O2 electronegative plasma

The report evaluates mechanism readiness, data coverage, missing-data
transparency, and workflow execution. It does not claim final quantitative
plasma process accuracy.

## Command

```powershell
python -m external_data_tools.benchmark_runner benchmarks/benchmark_config_semiconductor.yaml
python -m external_data_tools.benchmark_report benchmarks/results/summary.yaml --output benchmarks/results/semiconductor_benchmark_report.md
```

On Windows environments where `python` is not the active launcher, use `py`:

```powershell
py -m external_data_tools.benchmark_report benchmarks/results/summary.yaml --output benchmarks/results/semiconductor_benchmark_report.md
```

## Status Labels

- `passed`: the workflow produced required species, reaction families, outputs,
  and zero validation or structural enrichment errors.
- `warning`: the workflow ran, but data coverage, provenance, or DNT readiness
  needs attention.
- `failed`: setup, generation, or validation failed.

Fixture and imported data still require domain review before scientific use;
this invariant limitation is stated once for the suite instead of repeated as a
status for every case.

## Evaluation Rules

`PASS_WORKFLOW` requires:

- expectation score at least `0.75`
- `validation_error_count == 0`
- `structural_enrichment_unresolved_count == 0`
- `generation_complete == true`
- at least one electron reaction
- at least one ion-neutral reaction

The structural enrichment gate counts unavailable configured sources,
non-missing-property unresolved records (for example unsupported units),
unresolved reaction channels, and invalid/skipped reaction channels. Product
species details are retained without counting the same failed channel twice.
Missing physical-property values are measured and reported, but do not by
themselves fail the workflow.

`WARNING_DATA_GAPS` is emitted for low cross-section coverage, low provenance
coverage, high inferred reaction fraction, or no DNT pair-property-ready pairs.
Cross-section coverage counts only asset paths that resolve to existing files
inside the prepared registry.

`FAIL_SETUP`, `FAIL_ENRICHMENT`, `FAIL_VALIDATION`, and `FAIL_GENERATION`
indicate missing required fixtures, structural enrichment defects,
charge/element balance errors, truncated generation, or no generated reactions.

## DNT Readiness Metrics

`n_dnt_property_ready_pairs` means the required ion/neutral pair properties are
present. Use
`n_dnt_complete_ready_pairs` for pairs whose properties and required channel
fields are complete; `n_dnt_ready_with_warnings_pairs` identifies
property-ready pairs with missing channel fields.

## Results And Snapshots

For the current run, treat per-case `benchmark_metrics.yaml` and
`benchmark_report.yaml`, together with `benchmarks/results/summary.yaml`, as the
source of truth. Markdown reports and narrative result pages checked into the
repository are review snapshots, not automatically synchronized live status.

## Interpreting The Report

Use the report to decide whether the current prepared registry is useful for
review and next-step data work. Low-pressure plasma modeling still requires
reviewed cross sections, transport/DNT parameters, reaction energetics, and
domain expert review before quantitative conclusions.
