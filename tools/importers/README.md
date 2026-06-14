# External data importers

Importer tools are developer-side utilities for converting external public data
into local registry YAML files and local assets. They are not part of the core
generation runtime.

The core generator does not call importers during `reactgen generate`, and normal
generation must not require network access or external API availability.

## Importer contract

- Convert external data into reviewable local files under `registry/`.
- Store imported numerical assets under `registry/assets/`.
- Preserve source, provenance, license, and access date whenever available.
- Record asset paths and source information in reaction YAML entries.
- Mark imported records explicitly with `status: imported` or
  `status: literature_supported`.
- Do not overwrite curated registry files automatically.
- Do not mix inferred, imported, and curated data without explicit status labels.

## Intended workflow

```text
download or provide external data
  -> run importer
  -> inspect generated registry YAML/assets
  -> promote accepted files into registry
  -> run reactgen dev-check
  -> run normal reactgen generate
```

## Current placeholders

- `import_lxcat_placeholder.py`: command-line placeholder for a future LxCat
  importer. It does not download, parse, or write files, and it is not called by
  `reactgen generate`.
