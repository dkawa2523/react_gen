# Electron cross-section assets

This directory contains no numerical tables. The currently bundled H(1s)
electron-ionization curve is `../electron/iaea_D108105.csv`; its source, rights
notice and limited scope are described in [Registry assets](../README.md).

For additional curves, use the supported `acquire` adapter to create a snapshot,
`rgen ingest` to match it to saved candidates, and explicit `rgen adopt` for
Registry storage. See [the source workflow](../../../docs/data_sources.md).
These operations preserve source qualifications and do not approve the data
or perform the distribution integral needed for a rate coefficient.
