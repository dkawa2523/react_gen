# Registry assets

This registry snapshot intentionally does **not** include digitized electron-collision cross-section tables.
Reaction YAML files contain public source references with `status: needs_import` and `path: null`.

Recommended next step:

1. Import LxCat / literature cross-section tables into `registry/assets/electron_cs/...`.
2. Update each `data.cross_section.path` in `registry/reactions/electron/*.yaml`.
3. Re-run `reactgen generate` and confirm `missing_data.csv` no longer reports missing cross-section paths.
