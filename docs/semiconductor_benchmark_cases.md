# Semiconductor Benchmark Cases

The default local semiconductor benchmark suite uses three small cases:

- `ar_o2_simple`: the simplest Ar/O2 baseline for electron collisions, attachment, dissociation, ionization, ion-neutral channels, DNT readiness reporting, and missing-data planning.
- `ar_cf4_fluorocarbon`: an Ar/CF4 fluorocarbon workflow case that exercises CFx/F fragment handling, ion-neutral charge-transfer candidates, cross-section mapping, and missing-data planning.
- `sf6_o2_electronegative`: an Ar/SF6/O2 electronegative workflow case that exercises attachment-heavy chemistry, negative ions, O2 additive handling, and larger missing-data reports.

Cl2/BCl3 is not a default benchmark case in this baseline. It can be added later as a reviewed user benchmark if the required local fixture data and expectations are provided.

## Fixture Data Policy

All data under `benchmarks/fixtures/` is synthetic/minimal and exists only to validate the workflow. Do not use these values for production plasma modeling.

For scientific use, replace the fixture `internal_data/` and `cross_sections/` with reviewed internal data, licensed public snapshots, or manually reviewed literature data. The curated `registry/` is not mutated by benchmark fixtures; benchmark runs write to `benchmarks/results/`.

## Running The Suite

```powershell
python -m external_data_tools.benchmark_setup --config benchmarks/benchmark_setup.yaml --check --write-report benchmarks/results/setup_report.yaml
python -m external_data_tools.benchmark_runner benchmarks/benchmark_config_semiconductor.yaml
```

Use `--only` to run one case:

```powershell
python -m external_data_tools.benchmark_runner benchmarks/benchmark_config_semiconductor.yaml --only ar_o2_simple
```

## Case Inputs And Fixtures

Each case has:

- `benchmarks/cases/<case>/input.yaml`
- `benchmarks/fixtures/<case>/internal_data/species/species.yaml`
- `benchmarks/fixtures/<case>/internal_data/properties/properties.yaml`
- `benchmarks/fixtures/<case>/internal_data/reactions/electron.yaml`
- `benchmarks/fixtures/<case>/internal_data/reactions/ion_neutral.yaml`
- `benchmarks/fixtures/<case>/cross_sections/*.csv`
- `benchmarks/fixtures/<case>/cross_section_mapping.yaml`
- `benchmarks/expectations/<case>.yaml`

The benchmark runner performs local enrichment, imports the fixture cross-section CSVs into the prepared registry assets, applies reviewed fixture mappings, generates the network, and evaluates expectations. It does not download data and does not run external solvers.
