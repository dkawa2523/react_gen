# External Source Setup

`external_data_tools.source_setup` checks and prepares optional external source
inputs without changing the core `plasma_reactgen` package. It is the common
entry point for NIST/ATcT local snapshots, optional Chemicals installation,
PubChem identity snapshots, and LXCat manual/raw imports.

The core command `reactgen generate` remains deterministic and local-registry
only. Online/API/download work belongs under `external_data_tools/`, and the
outputs must be reviewed before prepare/enrich uses them.

## Commands

Check the configured source environment:

```powershell
python -m external_data_tools.source_setup --config external_data/source_access_profiles.yaml --check
```

Install the optional `chemicals` Python package:

```powershell
python -m external_data_tools.source_setup --config external_data/source_access_profiles.yaml --install-chemicals
```

Download explicit user-provided URLs only when the profile policy allows it:

```powershell
python -m external_data_tools.source_setup --config external_data/source_access_profiles.yaml --download-explicit-data
```

The setup report is written to
`external_data/manifests/source_setup_report.yaml` by default.

## Source Policies

- NIST: local snapshot or explicit user URL only. No scraping or automatic NIST
  web query is implemented.
- Argonne/ATcT: local thermochemistry snapshot or explicit user URL only.
  Review license, citation, and redistribution terms before sharing snapshots.
- Chemicals: optional Python package. It is installed only when the user passes
  `--install-chemicals`, and the core provider remains lazy if the package is
  absent.
- PubChem: use `external_data_tools.pubchem_fetch` for identity, formula,
  synonym, and identifier snapshots. Do not use PubChem as a plasma reaction or
  cross-section database.
- LXCat: manual download or explicit URL only. No login/session automation,
  crawler, or scraper is implemented.

## Review Before Use

External snapshots and imported assets should keep source records, citation
notes, SHA-256 hashes when available, and license notes. They should enter
`reactgen enrich` as local snapshots/assets and should never be auto-promoted
into curated `registry/`.
