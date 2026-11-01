# External data conversion

External-format adapters are implemented in `src/acquire`, with the `acquire`
CLI. This directory contains no separate importer implementation.

Use `acquire` to produce a local snapshot with its source declarations and
assets, `rgen ingest` to match it to saved candidates, and `rgen adopt` for
explicit Registry storage. Conversion, matching and storage preserve the
declared qualification; they do not grant scientific approval.

The current workflow and supported adapters are described in
[external data](../../external_data/README.md) and
[data sources](../../docs/data_sources.md). `rgen analyze` reads explicit local
evidence without calling acquisition adapters or accessing the network.
