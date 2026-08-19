# plasma-reactgen

Input gases and process conditions in; a reviewed reaction list, the species
property table, and the numerical datasets a plasma model needs out.

Three packages, 4,643 lines. See [design](docs/core_design.md).

```powershell
rgen generate cases/ar_sf6_o2/case.yaml       # reaction list + species + datasets
rgen check    --registry registry             # validate the registry alone
rgen plan     cases/ar_sf6_o2/case.yaml       # what to acquire, grouped by source
rgen ingest   snapshot.yaml --overlay work/overlay.yaml
```

Acquisition is a separate package, because it may open a network connection and
the generator may not:

```powershell
acquire lxcat export.txt --out work/ar       # LXCat export -> snapshot
acquire pubchem species.yaml --out external_data/identity
rgen ingest work/ar/snapshot.yaml --overlay work/overlay.yaml
rgen generate cases/ar_cf4/case.yaml --overlay work/overlay.yaml
```

Proposing chemistry the registry does not have is a third, optional package:

```powershell
discover sources                             # which database covers what
discover channels --gas SF6 --out work/sf6   # candidates: registered, listed, or new
discover pairs --out work/            # ion-neutral channels open by thermochemistry
```

## What it does

- Expands input gases into every reachable registered reaction, following
  products through later depths until the frontier closes, with charge and
  element balance enforced on each one.
- Applies the process conditions: Arrhenius rates at the gas temperature, cross
  sections convolved at the electron temperature, sticking coefficients turned
  into wall loss frequencies by the chamber geometry, and every dataset checked
  against its declared validity range.
- Ranks reactions by an upper bound on their frequency, against the residence
  time when one is given, and writes a reduced list with the provably negligible
  ones removed.
- Reports what is missing in one list, and what is out of scope because the
  registry holds no data of that kind at all.
- Writes the datasets a model consumes: cross-section tables, rate coefficients
  evaluated at the conditions, and DNT+ inputs graded by the model tier each
  pair can actually run.

Proposing chemistry the registry does not have is a third, optional package:

```powershell
discover sources                             # which database covers what
discover channels --gas SF6 --out work/sf6   # candidates: registered, listed, or new
discover pairs --out work/            # ion-neutral channels open by thermochemistry
```

## What it does not do

Solve a Boltzmann equation, run DNT+ or a plasma model, or fetch data during
generation. `generate` reads local files only and is reproducible; `lock.yaml`
records the registry fingerprint and dataset checksums it consumed.

## Install and test

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[quality]"
python -m pytest
python -m nox -s quality-pr
```

## Registry

Species, reactions, materials and mechanism scopes are readable YAML under
[registry/](registry/). Reaction families are directory names, so adding
`registry/reactions/three_body/*.yaml` makes those reactions appear with no code
change. See [registry data guide](docs/registry_data_guide.md).

The shared registry currently covers Ar, O2, CF4 and SF6 chemistry: 75 species
and 246 registered pairs, with the bounded Son (2014) and Pateau (2014)
mechanisms complete against their declared tables. Numerical data is the open
work — run `rgen plan` on a case to see what to acquire and how it is accepted.

## Documentation

- [Design](docs/core_design.md)
- [Registry data guide](docs/registry_data_guide.md)
- [Source and license policy](docs/source_license_policy.md)
- [Data sources](docs/data_sources.md)
- [Shared registry coverage](docs/shared_registry_coverage.md)
- [技術レポート](docs/plasma_reactgen_technical_report.md)
