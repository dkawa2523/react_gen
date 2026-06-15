# Run Semiconductor Benchmarks

Use `external_data_tools.run_semiconductor_benchmarks` to run the complete
local semiconductor benchmark workflow:

1. setup check
2. enrichment
3. cross-section import and mapping
4. generation and DNT input export
5. missing-data planning
6. manual input template generation
7. visualization output
8. final Markdown benchmark report

The default cases are:

- `ar_o2_simple`: Ar/O2, the baseline minimal oxygen plasma case
- `ar_cf4_fluorocarbon`: Ar/CF4 fluorocarbon plasma
- `sf6_o2_electronegative`: Ar/SF6/O2 electronegative plasma

No network access or external solver executable is required. Optional solvers are
reported as skipped when no executable paths are configured.

## Commands

Run all three cases:

```powershell
python -m external_data_tools.run_semiconductor_benchmarks
```

Run with an explicit config:

```powershell
python -m external_data_tools.run_semiconductor_benchmarks --config benchmarks/benchmark_config_semiconductor.yaml
```

Run only Ar/O2:

```powershell
python -m external_data_tools.run_semiconductor_benchmarks --only ar_o2_simple
```

Run the other individual cases:

```powershell
python -m external_data_tools.run_semiconductor_benchmarks --only ar_cf4_fluorocarbon
python -m external_data_tools.run_semiconductor_benchmarks --only sf6_o2_electronegative
```

Use strict mode to fail on expectation score below `0.75` or validation errors:

```powershell
python -m external_data_tools.run_semiconductor_benchmarks --strict
```

On Windows environments where `python` is not the active launcher, use `py`.

## Inspecting Results

The command prints paths to:

- `benchmarks/results/setup_report.yaml`
- `benchmarks/results/summary.yaml`
- per-case `benchmark_report.yaml`
- per-case `work/missing_plan.yaml`
- per-case `work/manual_inputs/`
- per-case `outputs/visualizations/`
- `benchmarks/results/semiconductor_benchmark_report.md`

Graphviz is optional. DOT files and dependency-free SVG statistics are written
without requiring Graphviz; rendered network SVG/PNG files appear only when the
`dot` executable is available.

## Replacing Synthetic Fixtures

The checked-in fixtures are synthetic/minimal workflow data. For real modeling,
replace files under `benchmarks/fixtures/<case>/internal_data/` and
`benchmarks/fixtures/<case>/cross_sections/` with reviewed internal data,
licensed local snapshots, or reviewed literature-derived files. Keep provenance
in `source_record` fields and rerun the benchmark.

## Configuring Solvers Later

External solvers are not bundled. To use them later, copy or edit
`benchmarks/external_solvers.example.yaml`, set executable paths, and make a
benchmark config point to that solver config. Missing optional solvers do not
fail registry-level benchmark runs.
