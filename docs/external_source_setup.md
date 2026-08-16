# External Source Setup

`external_data_tools.source_setup` checks and prepares optional external source
inputs without changing the core `plasma_reactgen` package. It is the common
entry point for NIST/ATcT local snapshots, optional Chemicals installation,
PubChem identity snapshots, and LXCat manual/raw imports.

The core command `reactgen generate` remains deterministic and local-registry
only. Online/API/download work belongs under `external_data_tools/`, and the
outputs must be reviewed before prepare/enrich uses them.

## Commands

Install dependencies used only by the external-data commands:

```powershell
python -m pip install -e ".[external-data]"
```

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

Create DB-specific collection manifests for any requested gases:

```powershell
python -m external_data_tools.data_admin plan_data_acquisition `
  --seed-gases Ar O2 CF4 SF6 `
  --registry registry `
  --output-dir external_data/acquisition_work
```

The gases in this command are the current query scope, not a pre-built mixture
pack. The persistent inputs remain individual species, reaction channels,
properties, and numerical datasets in the shared registry.
The plan also writes `qdb_chemistry_requests.yaml`, selecting relevant entries
from the complete reviewed QDB semiconductor chemistry inventory.

After reviewing QDB terms and selecting a chemistry ID:

```powershell
$env:QDB_API_KEY = "..."
python -m external_data_tools.qdb_chemistry `
  --chemistry-id 31 `
  --output external_data/raw/qdb/C31.txt
```

Setup reports use schema version 2. Requested actions are recorded once under
`mode`; the summary contains outcomes only. OpenADAS and LXCat import reports
also use schema version 2 and omit the former constant
`registry_mutated: false` field. These tools receive only workspace/prepared
registry destinations, so curated-registry safety is structural rather than a
repeated diagnostic value.

## Source Policies

- NIST properties: local snapshot or explicit user URL only. The separate
  `import_nist_beb` maintainer command accesses only eight declared SRD 107
  ASCII endpoints and writes site-local total-ionization assets; generation
  never performs a NIST query.
- Evaluated O2 cross sections: `import_oxygen_cross_sections` downloads the
  official 2026 JPCRD dataset only when explicitly invoked. It writes
  process-resolved SI assets, including separate a1Delta and b1Sigma excitation
  data, to a prepared registry and records the CC BY-NC license, source hashes,
  conversion, worksheet, and validity range.
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
- KIDA/UMIST: the explicit `external_data_tools.umist_rate22` command can fetch
  the official Rate22 release as a checksummed site-local file. Conversion reads
  native `.rates` or reviewed CSV/TSV, filters by the acquisition pair manifest,
  and preserves alpha/beta/gamma and the temperature range in a separate
  rate-candidate snapshot. It does not establish semiconductor-plasma applicability.
- VAMDC: explicit reviewed TAP endpoint and query manifest only. Cached XSAMS
  can be reduced to a species/state/process inventory, but registry mapping is
  never automatic.
- OpenADAS: manually downloaded local files only. ADF files and their mappings
  remain site-local and require source-specific license review.
- QDB: explicit chemistry ID and environment-only API key. Responses remain
  site-local, the key is redacted, and reaction/state/dataset mappings require
  license and scientific review before registry import.

## Review Before Use

External snapshots and imported assets should keep source records, citation
notes, SHA-256 hashes when available, and license notes. They should enter
`reactgen enrich` as local snapshots/assets and should never be auto-promoted
into curated `registry/`.
