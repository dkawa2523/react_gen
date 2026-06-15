# Semiconductor Benchmark Results

## Executive Summary

The corrected semiconductor benchmark suite uses three default local-only workflow cases:

- Ar/O2 simple oxygen plasma (`ar_o2_simple`)
- Ar/CF4 fluorocarbon plasma (`ar_cf4_fluorocarbon`)
- Ar/SF6/O2 electronegative plasma (`sf6_o2_electronegative`)

Ar/O2 is the simplest baseline case. It exercises oxygen electron-impact channels, a small ion-neutral set, DNT readiness reporting, cross-section mapping, missing-data planning, and visualization outputs without requiring any external solver.

The benchmark runner completed the registry-level workflow for all three cases. External solvers are optional; they were disabled in the checked setup because no executable paths are configured. That is expected for local registry-level benchmark runs and is not a benchmark failure.

## Environment And Command Summary

Commands requested:

```powershell
python -m pytest
python -m external_data_tools.run_semiconductor_benchmarks --config benchmarks/benchmark_config_semiconductor.yaml
```

On this Windows environment, `python` resolves to the Microsoft Store alias, so the requested commands did not start Python. The workflow was then run with the available launcher:

```powershell
$env:PYTHONPATH='src'
py -m external_data_tools.run_semiconductor_benchmarks --config benchmarks/benchmark_config_semiconductor.yaml
```

Benchmark inputs:

- Registry path: `registry`
- Benchmark config: `benchmarks/benchmark_config_semiconductor.yaml`
- Setup config: `benchmarks/benchmark_setup.yaml`
- Source profiles:
  - `benchmarks/fixtures/ar_o2_simple/source_profile.yaml`
  - `benchmarks/fixtures/ar_cf4_fluorocarbon/source_profile.yaml`
  - `benchmarks/fixtures/sf6_o2_electronegative/source_profile.yaml`

Output directories:

- `benchmarks/results/ar_o2_simple/work`
- `benchmarks/results/ar_o2_simple/outputs`
- `benchmarks/results/ar_cf4_fluorocarbon/work`
- `benchmarks/results/ar_cf4_fluorocarbon/outputs`
- `benchmarks/results/sf6_o2_electronegative/work`
- `benchmarks/results/sf6_o2_electronegative/outputs`

Test status at the time of this report: benchmark workflow ran successfully with `py`; final test status is recorded in the implementation summary for this prompt.

## Case-By-Case Results

| Case | Species | Reactions | Electron | Ion-neutral | Expectation score | Cross-section coverage | DNT ready pairs | Missing data items | Provenance coverage | Imported/literature fraction | Validation errors | Solver status |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| Ar/O2 simple oxygen plasma | 6 | 11 | 7 | 4 | 1.00 | 0.14 | 2 | 7 | 0.55 | 0.55 | 0 | disabled |
| Ar/CF4 fluorocarbon plasma | 12 | 43 | 17 | 26 | 1.00 | 0.06 | 10 | 19 | 0.02 | 0.02 | 0 | disabled |
| Ar/SF6/O2 electronegative plasma | 12 | 20 | 12 | 8 | 1.00 | 0.17 | 4 | 12 | 0.55 | 0.55 | 0 | disabled |

Plot links:

- Ar/O2: `benchmarks/results/ar_o2_simple/outputs/visualizations/statistics/`
- Ar/CF4: `benchmarks/results/ar_cf4_fluorocarbon/outputs/visualizations/statistics/`
- Ar/SF6/O2: `benchmarks/results/sf6_o2_electronegative/outputs/visualizations/statistics/`

Graphviz DOT files were written under each case's `outputs/visualizations/network/` directory. Rendered network SVG/PNG files are optional and require Graphviz `dot` to be installed.

## Ar/O2 Specific Evaluation

The Ar/O2 baseline confirms the simplest oxygen workflow is operational:

- O2 electron elastic reaction exists.
- O2 electron ionization reaction exists.
- O2 electron dissociation reaction exists.
- O2 electron attachment reaction exists.
- Ar+ + O2 ion-neutral reaction exists from the fixture data.
- O and O- species are present or generated.
- Charge and element balance validation passes with `validation_error_count: 0`.
- The benchmark output includes the synthetic fixture warning: fixture values and cross sections are for workflow validation only and must not be used for production plasma modeling.

## Graph Evaluation

Reaction counts increase from the compact Ar/O2 baseline to the more connected Ar/CF4 fluorocarbon case, then settle into a smaller but attachment-heavy Ar/SF6/O2 electronegative case:

- Ar/O2: 11 reactions, including 7 electron and 4 ion-neutral reactions.
- Ar/CF4: 43 reactions, including 17 electron and 26 ion-neutral reactions.
- Ar/SF6/O2: 20 reactions, including 12 electron and 8 ion-neutral reactions.

Missing-data counts remain visible and actionable:

- Ar/O2: 7 missing items.
- Ar/CF4: 19 missing items.
- Ar/SF6/O2: 12 missing items.

Cross-section coverage is intentionally low because each fixture provides only a minimal synthetic cross-section asset:

- Ar/O2: 0.14 coverage.
- Ar/CF4: 0.06 coverage.
- Ar/SF6/O2: 0.17 coverage.

DNT readiness is present for all cases but does not imply final transport accuracy:

- Ar/O2: 2 DNT-ready pairs.
- Ar/CF4: 10 DNT-ready pairs, with 2 pairs still missing DNT properties.
- Ar/SF6/O2: 4 DNT-ready pairs.

All three cases achieved an expectation score of 1.00 and had zero validation errors.

## Validity Assessment

This benchmark validates workflow readiness and data coverage. It proves that local fixture data can enrich a prepared registry, import cross-section assets, map those assets to channels, generate reaction-network outputs, plan missing data, create manual fill-in templates, and produce visualization artifacts.

It does not validate final plasma process accuracy. It does not validate quantitative electron energy distributions, transport coefficients, rate coefficients, sheath physics, circuit coupling, or DNT trajectory results unless live solvers and reviewed input data are configured separately.

Synthetic fixtures are not production data. They must be replaced by reviewed internal data, reviewed public snapshots, or approved literature values before scientific conclusions are drawn.

## Data Gaps And Next Actions

Ar/O2:

- Replace the synthetic O2 cross section with reviewed LXCat or internal data.
- Fill or review O2 polarizability, dipole moment, and collision radius values.
- Review Ar+ + O2 charge-transfer energetics.
- Add real O2 attachment and dissociation cross sections.

Ar/CF4:

- Import reviewed fluorocarbon cross sections.
- Review CFx fragment channels and product branching.
- Fill thermochemistry and DNT data for CFx and fluorine-bearing species.

Ar/SF6/O2:

- Import reviewed SF6/O2 attachment and dissociation cross sections.
- Review negative-ion channels.
- Fill missing DNT properties and SFx thermochemistry.

## Live Solver Status

| Solver | Enabled | Executable path | Adapter | Result |
| --- | --- | --- | --- | --- |
| BOLSIG+ | false | null | export_only | disabled |
| LoKI-B | false | null | export_only | disabled |
| ZDPlasKin | false | null | export_only | disabled |
| ThunderBoltz | false | null | export_only | disabled |
| ngspice | false | null | ngspice_basic | disabled |

Missing or disabled solver executables are setup issues, not registry benchmark failures. The registry-level benchmark can complete without live solvers. Quantitative transport validation needs reviewed cross sections and configured solver adapters.

## Pass Warning Fail Summary

- Passed workflow cases: 3
- Warning cases: 3
- Failed cases: 0
- Skipped optional solver checks: 5 solver families disabled by configuration

Warnings are expected for this baseline because fixture cross sections are synthetic and sparse, live solvers are not configured, and several data gaps intentionally remain visible for manual review.

## Release Readiness Conclusion

Ready now:

- The corrected three-case semiconductor benchmark suite runs locally.
- Required fixture data is present.
- Curated `registry/` is not mutated by the benchmark workflow.
- `enrich`, cross-section import, mapping, `generate`, missing-data planning, manual template generation, metrics, and benchmark reporting work together.
- The Ar/O2 case is a practical minimal baseline for future regression checks.

Requires domain review:

- Synthetic fixture values.
- Imported reaction channels.
- Cross-section mappings.
- Ion-neutral energetics.
- DNT-ready pair assumptions.

Requires real data replacement:

- Synthetic cross-section CSVs.
- Sparse fluorocarbon and electronegative chemistry fixtures.
- Any fixture property marked as imported, estimated, or benchmark-only.

Requires solver setup:

- Any quantitative live-solver validation.
- BOLSIG+/LoKI-B transport checks.
- ZDPlasKin chemistry execution.
- ThunderBoltz swarm validation.
- ngspice circuit coupling checks.
