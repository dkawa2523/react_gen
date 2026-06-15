# External Data Tools

This directory is intentionally separate from the core `plasma_reactgen`
package. It is the place for future public database/API experiments, local raw
file ingestion, snapshot creation, and benchmark dataset preparation.

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
