# Source and license policy

The project separates acquisition, local evidence loading, scientific review,
numerical selection, and explicit Registry adoption. Access to a database,
successful parsing, and permission to redistribute its contents answer different
questions. None of them establishes that a scientific record applies to a
particular state, channel, or calculation.

## Source catalog

`external_data/source_catalog.yaml` is the single local catalog, at schema version
3. Each entry describes a `source_id`, provided quantities, an access route,
available converters, an endpoint, and rights that require checking. A direct
release download may additionally declare `file`, `format`, and `format_version`.
`acquire sources` displays this information without accessing the network.

The catalog describes capabilities and review items. It does not grant a license,
approve scientific records, set a default scientific status, or rank databases.
Providers in user evidence do not require catalog registration. An unlisted
provider still requires adequate source information and compliance with its
actual terms.

The previous access profile and fetch catalog have been consolidated into this
file. `acquire fetch --catalog PATH` continues to read a custom download catalog,
including its legacy `id` field. Old catalog `priority` values are not analysis
selection rules.

## Acquisition and storage

- `rgen analyze` reads explicit local Registry, snapshot, and overlay data. It
  does not download data, call source APIs, or require optional acquisition
  packages.
- Network retrieval belongs to an explicit acquisition command. `acquire fetch`
  downloads the HTTPS file URL declared by the selected catalog entry and checks
  the expected content format. A successful content check is not a complete
  source-format or scientific validation.
- Retain applicable source and upstream terms, attribution requirements, and
  redistribution restrictions. A public endpoint or an open-source package
  license does not establish the redistribution rights of every underlying
  dataset. Check the contributing database or node as well as an aggregator.
- Record the requested and final URL, retrieval time, original full SHA-256,
  format, and format version where acquisition supplies them. Preserve original
  files and source declarations when making repairs or conversions.
- LXCat and UMIST file conversion stores a raw copy and its SHA-256 with the
  snapshot. Other converters retain the source declarations they obtained;
  metadata not provided by an adapter remains unknown rather than invented.
- Keep restricted or confidential raw data, snapshots, and assets in suitable
  local storage. Do not add them to a public repository, distribute a result
  containing them, or bundle them in a release without checking the relevant
  rights. The catalog is not an access-control mechanism.
- Optional acquisition packages remain optional dependencies in
  `pyproject.toml`, separate from the core analysis runtime.

## Scientific qualification and selection

Records retain `provenance` (provider, collection, release, native record ID,
citation, and URL where known) and `source_declaration` (the original scientific
declaration). `method`, evidence `tier`, and declared `review_scope` are separate
fields. A provider name does not determine a measurement method or evidence
quality; scientific review does not change license terms.

An adjacent `acquisition.yaml` is carried into `acquisition.source_manifest` only
when its file name and complete SHA-256 match the converted input. The same
context is retained in scientific source declarations through ingest and adopt.
Source paths remain within that original manifest, separate from the snapshot's
new raw path. A same-file hash conflict or malformed declaration fails before
conversion writes. A manifest for another file is not adopted. Provider,
collection, and release are retained only when explicitly declared.

Mechanically imported records remain `imported` until an appropriate review or
documented derivation supplies their qualification. Acquisition, matching,
Registry membership, and adoption do not promote them automatically. Review
must address the claim actually used: identity, existence, a numerical property,
an energy relation, or applicability to a calculation. Reviewing one claim does
not approve the others.

Reaction records check `channel_assertion`, `threshold_eV`, and `delta_e_eV`
against their stated review scope. A numerical snapshot with no explicit scope
is limited to its numerical kind; coefficient review does not approve its
channel or threshold. Unscoped legacy independent channel declarations retain a
compatibility rule. Separately typed energy claims and complete claim-level
selection remain unfinished.

`data_selection` can rank or restrict rate coefficients, cross sections, and
sticking coefficients by explicitly declared method, provider, collection, or
record. It does not bypass numerical quality or applicability checks. Records
and unresolved disagreements remain inspectable. The method `estimated` is a
description of how a value was obtained; its qualification and assumptions must
also be stated. Property, thermochemical-model, and existence-evidence selection
are not yet supported by this input.

## Registry adoption and distribution

Inspect the source, target identity, quantity, applicable conditions, scientific
qualification, and usage rights before a record is used for a declared purpose
or distributed. `rgen adopt OVERLAY --registry PATH --dry-run` describes the
proposed persistent changes. Running it without `--dry-run` is the explicit
storage operation; it retains the record's original qualification and is not a
scientific approval step.

Before distributing a Registry, snapshot, asset, or analysis result, verify that
the retained source information identifies the relevant terms and attribution,
that the proposed distribution is permitted, and that transformations or repairs
are traceable to the original. When terms are unknown, preserve that uncertainty
and resolve it with the source before redistribution. Catalog review items are
guidance for this check, not blanket permission or a substitute for the source's
current terms.
