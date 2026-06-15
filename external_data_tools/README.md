# External Data Tools

This directory is intentionally separate from the core `plasma_reactgen`
package. It is the place for public database/API experiments, local raw file
ingestion, snapshot creation, and benchmark dataset preparation.

The core runtime and `reactgen generate` must remain deterministic and
local-registry-only. Do not put online API clients, download logic, scraping, or
heavy optional dependencies under `src/plasma_reactgen`.

Future external tools may access public databases or local files, but their
outputs should be written as local files under `external_data/`, `workspaces/`,
or `benchmarks/`. Generated snapshots should be reviewed before they are used by
prepare/enrich workflows, and generated data must not be auto-promoted into the
curated `registry/`.

Optional dependencies for future external tools belong in
`requirements-external.txt`, not in the core project dependencies.

## Current Tools

Implemented tools include:

- external source setup checks for NIST/ATcT/Chemicals/PubChem/LXCat workflows
- explicit URL download manifests with dry-run support
- PubChem identity snapshot fetch/normalize
- NIST snapshot planning and validation
- LXCat/manual raw cross-section import
- OpenADAS raw file registration
- VAMDC raw query capture
- KIDA/UMIST-like local network conversion
- Argonne/ATcT-style thermochemistry snapshot planning and validation
- chemical identity fetch/normalize skeletons for optional providers such as
  ChEBI, ChemSpider, OPSIN, and NCI/Cactus

Some tools can access online resources when explicitly invoked by the user.
Tests do not use real network access. Generated raw files and snapshots must be
reviewed before they are used by prepare/enrich workflows.

## Source Setup

Use `source_setup` to check the configured external source environment, install
the optional `chemicals` package only when explicitly requested, and run
user-provided explicit URL downloads only when policy allows it:

```bash
python -m external_data_tools.source_setup --config external_data/source_access_profiles.yaml --check
python -m external_data_tools.source_setup --config external_data/source_access_profiles.yaml --install-chemicals
python -m external_data_tools.source_setup --config external_data/source_access_profiles.yaml --download-explicit-data
```

The default profile keeps network downloads disabled. NIST, Argonne/ATcT, and
LXCat data require local snapshots/assets or explicit user-provided URLs after
license and citation review. PubChem API access is limited to the external
identity snapshot fetcher; the core runtime does not call PubChem.

## Explicit URL Downloads

`external_data_tools.http_client` provides a small stdlib-only helper for
downloading explicit URLs supplied by a user-managed manifest. It sets a
User-Agent, applies a timeout, records SHA-256 hashes, and writes a YAML report
for provenance. It is not imported by the core package.

Dry-run:

```bash
python -m external_data_tools.download_manifest downloads.yaml --output-root external_data/raw --dry-run
```

Real run:

```bash
python -m external_data_tools.download_manifest downloads.yaml --output-root external_data/raw
```

The manifest format is:

```yaml
schema_version: 1
downloads:
  - id: cf4_example
    url: https://example.org/path/to/file.csv
    output: lxcat/cf4_example.csv
    source_name: example_source
    license_note: review upstream license before redistribution
    citation: citation text
```

This utility is only for explicit URLs. Site-specific terms of use, login
requirements, citation, licensing, and redistribution constraints are the
user's responsibility. Automatic scraping, site crawling, hidden API discovery,
and database-specific clients are not implemented here.
