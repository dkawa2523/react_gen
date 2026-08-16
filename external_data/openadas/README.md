# OpenADAS Manual Raw Files

This directory is for local OpenADAS manifests and notes. The repository does
not implement OpenADAS scraping, login/session handling, automatic downloads, or
full ADAS parsing.

Use explicit user-provided files with:

```bash
python -m external_data_tools.openadas_raw_import MANIFEST.yaml --workspace WORKSPACE
```

The first version registers raw file metadata and caches source files under
`workspace/source_cache/openadas/`. It supports ADF01 charge-exchange metadata
as optional generic ion reaction table skeletons and registers ADF07 electron
impact ionisation coefficient files as raw metadata only.

OpenADAS is useful primarily for atomic and fusion-oriented charge-exchange and
coefficient data. Semiconductor polyatomic ion-neutral chemistry will usually
need reviewed internal data, converted literature tables, or domain-specific
measurements.

Full ADAS parsing, coefficient interpolation, cross-section conversion, and
Boltzmann solver workflows are future work. Generated metadata should be
reviewed before prepare/enrich use and must not be promoted automatically into
the curated `registry/`.
