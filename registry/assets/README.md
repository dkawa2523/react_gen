# Registry assets

This registry snapshot intentionally does **not** include digitized electron-collision cross-section tables.
Reaction YAML files contain public source references with `status: needs_import` and `path: null`.

To use an acquired LXCat table, first save an analysis result and match the
converted snapshot to its candidates:

```powershell
rgen analyze Ar --evidence registry --out result
rgen needs result
acquire lxcat export.txt --out work/lxcat
rgen ingest work/lxcat/snapshot.yaml --result result --overlay work/overlay.yaml
rgen analyze Ar --evidence registry --evidence work/overlay.yaml --out result
rgen needs result
```

Keep the generated `snapshot.yaml` and its `assets/` files together. Inspect
`work/review_queue.yaml` for ambiguous identities or incompatible channels.
Matching a table does not approve its scientific quality or establish a rate
coefficient; an electron cross section still needs an applicable EEDF integral.

After reviewing the source, units, state and channel assignment, applicable
conditions, and redistribution rights, inspect an explicit adoption with
`rgen adopt work/overlay.yaml --registry registry --dry-run`. Only remove
`--dry-run` when adopting the reviewed data. Analysis and ingestion do not write
to Registry. See the [Registry guide](../../docs/registry_data_guide.md) for
dataset records and the [source policy](../../docs/source_license_policy.md)
for licensing and review.
