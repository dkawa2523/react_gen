# Benchmarking

`external_data_tools.benchmark_runner` runs small, local-only benchmarks that
exercise `reactgen enrich`, cross-section import/mapping, `reactgen generate`,
missing-data planning, and manual input template generation without network
access, solver execution, Graphviz, pandas, matplotlib, or curated registry
mutation.

The default benchmark config is:

```powershell
python -m external_data_tools.benchmark_runner benchmarks/benchmark_config_semiconductor.yaml
python -m external_data_tools.benchmark_runner benchmarks/benchmark_config_semiconductor.yaml --only ar_o2_simple
python -m external_data_tools.benchmark_runner benchmarks/benchmark_config_semiconductor.yaml --only ar_cf4_fluorocarbon
python -m external_data_tools.benchmark_runner benchmarks/benchmark_config_semiconductor.yaml --only sf6_o2_electronegative
```

In environments where `python` is not the active launcher, use:

```powershell
py -m external_data_tools.benchmark_runner benchmarks/benchmark_config_semiconductor.yaml
```

## Outputs

Benchmark outputs are written under `benchmarks/results/`:

- `benchmarks/results/<id>/work/` contains the enrichment workspace and
  `prepared_registry/`.
- `benchmarks/results/<id>/work/missing_plan.yaml` contains suggested local
  follow-up actions.
- `benchmarks/results/<id>/work/manual_inputs/` contains fill-in templates for
  missing data.
- `benchmarks/results/<id>/outputs/` contains generated network and DNT files.
- `benchmarks/results/<id>/benchmark_metrics.yaml` contains the collected
  metrics.
- `benchmarks/results/<id>/benchmark_report.yaml` contains command steps,
  metrics, expectations, and pass/fail status.
- `benchmarks/results/summary.yaml` summarizes all benchmarks in a run.

These generated YAML files are the source of truth for the run. Checked-in
Markdown reports and result narratives are review snapshots and may lag the
current code or fixtures.

The runner runs the configured setup check before executing benchmarks. Required
fixture data missing from `benchmarks/fixtures/` is a setup failure. Optional
external solvers are reported as disabled or skipped when no executable/adapter
is configured; registry-level benchmarks still run.

The runner clears the configured benchmark `workspace` and `output` directories
before each run. Both must be under `benchmarks/results/` for the checked-in
config.

## Metrics

The metric collector reads generated YAML files and counts species, reactions,
reaction families, DNT task readiness, missing-data items, missing-plan actions,
cross-section assets, cross-section coverage, provenance coverage, inferred
reaction fraction, imported/literature-supported reaction fraction, validation
errors, expectation score, and solver skip/ready status. It does not run DNT,
Boltzmann solvers, or live circuit/plasma solvers.

`generation_complete` must be true for a benchmark case to pass. The companion
`n_generation_truncations` metric exposes configured limits that omitted data.

Cross-section coverage counts only paths that resolve to existing files inside
the prepared registry; a path string alone is not treated as coverage.

`n_dnt_ready_pairs` is a compatibility alias for pair-property readiness. Use
`n_dnt_complete_ready_pairs` to count complete pair-and-channel inputs and
`n_dnt_ready_with_warnings_pairs` to find property-ready pairs with missing
channel fields.

## Expectations

Expectation files are simple YAML checks for required species, reaction
families, reaction types, output files, and zero failed charge/element balance.
They produce a `passed` flag and a 0-to-1 score. A failed expectation means the
benchmark output should be reviewed before treating the enriched registry as an
improvement.

The benchmark also applies an enrichment quality gate. It fails on structural
defects (unavailable configured sources, invalid property candidates,
unresolved product species or reactions, or invalid/skipped reaction channels),
while ordinary missing property values remain reported data gaps.
Even when expectations otherwise pass, truncated generation fails the case.

The bundled semiconductor suite contains `ar_o2_simple`,
`ar_cf4_fluorocarbon`, and `sf6_o2_electronegative`. These use synthetic local
fixture data only. Replace fixture source profiles, internal data, and
cross-section CSVs with reviewed local data when building a production benchmark
suite.
