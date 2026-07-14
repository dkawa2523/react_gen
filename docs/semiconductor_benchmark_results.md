# Semiconductor Benchmark Results

## Result Authority

This page records stable interpretation guidance and a historical qualitative
review. It deliberately does not duplicate per-case counts, coverage fractions,
scores, or pass/fail totals.

For the current run, use these generated files as the source of truth:

- `benchmarks/results/summary.yaml`
- `benchmarks/results/<case>/benchmark_metrics.yaml`
- `benchmarks/results/<case>/benchmark_report.yaml`

`benchmarks/results/semiconductor_benchmark_report.md` is a generated,
point-in-time presentation of the same YAML. Its timestamp identifies the run
it describes.

## Suite Scope

The default local-only workflow covers:

- Ar/O2 simple oxygen plasma (`ar_o2_simple`)
- Ar/CF4 fluorocarbon plasma (`ar_cf4_fluorocarbon`)
- Ar/SF6/O2 electronegative plasma (`sf6_o2_electronegative`)

Ar/O2 is the compact baseline. Ar/CF4 exercises a more connected fluorocarbon
mechanism, while Ar/SF6/O2 emphasizes attachment and negative-ion chemistry.
Together they exercise enrichment, cross-section import and mapping, network
generation, DNT export, missing-data planning, and visualization without
executing simulation software.

## Historical Snapshot Context

The qualitative observations below were reviewed against the generated
benchmark snapshot dated 2026-06-15. They are not claims about a later run.
Rerun the suite and inspect the authoritative YAML whenever code, fixtures,
source profiles, or policies change.

Run the suite with:

```powershell
python -m external_data_tools.run_semiconductor_benchmarks `
  --config benchmarks/benchmark_config_semiconductor.yaml
```

Use `py` instead of `python` when that is the active Windows launcher.

## Ar/O2 Specific Evaluation

The Ar/O2 case is intended to verify the following baseline expectations. Check
the generated case report to confirm that they still hold for the current run:

- O2 electron elastic reaction exists.
- O2 electron ionization reaction exists.
- O2 electron dissociation reaction exists.
- O2 electron attachment reaction exists.
- Ar+ + O2 ion-neutral chemistry is represented by the fixture data.
- O and O- species are present or generated.
- The benchmark output includes the synthetic fixture warning: fixture values
  and cross sections are for workflow validation only and must not be used for
  production plasma modeling.

## Reading Coverage And DNT Results

Sparse synthetic cross-section fixtures are useful for testing asset import and
linking, but their coverage is not evidence of production mechanism quality.
Use the generated missing-data plan and coverage metrics to select the next
review task.

`n_dnt_property_ready_pairs` only means the required ion/neutral pair properties
are present. It does not imply complete DNT input. Read
`n_dnt_complete_ready_pairs` and `n_dnt_ready_with_warnings_pairs` to distinguish
complete inputs from property-ready pairs that still lack channel thresholds or
energetics.

## Validity Assessment

The suite validates workflow behavior and makes data gaps reviewable. It can
show that local fixture data are prepared without mutating curated `registry/`,
that mappings refer to local assets, and that network, missing-data, DNT, and
visualization outputs are produced consistently.

It does not validate final plasma-process accuracy, electron energy
distributions, transport or rate coefficients, sheath physics, circuit
coupling, or DNT trajectories. Synthetic fixtures must be replaced with
reviewed internal data, approved local snapshots, or literature-supported data
before scientific conclusions are drawn.

## Data Review Priorities

Ar/O2:

- Replace synthetic O2 cross sections with reviewed local data.
- Review O2 transport properties and charge-transfer energetics.
- Add reviewed attachment and dissociation cross sections.

Ar/CF4:

- Import reviewed fluorocarbon cross sections.
- Review CFx fragment channels, product branching, and thermochemistry.
- Complete DNT inputs for fluorine-bearing pairs.

Ar/SF6/O2:

- Import reviewed SF6/O2 attachment and dissociation cross sections.
- Review negative-ion channels and SFx thermochemistry.
- Complete missing DNT pair properties and channel energetics.

## Release Interpretation

The benchmark workflow is suitable for repeatable local regression and review.
Release decisions still require domain review of synthetic or imported values,
reaction channels, mappings, energetics, and DNT assumptions.
