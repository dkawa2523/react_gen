# External Data

This directory is for local raw files, reviewed snapshots, and manifests created
by external data tooling. Large downloaded or generated data files are ignored by
default.

Use:

- `raw/` for downloaded or locally imported raw source files.
- `snapshots/` for reviewed local snapshots used by prepare/enrich workflows.
- `manifests/` for provenance manifests.

Do not auto-promote generated data into the curated `registry/`.

