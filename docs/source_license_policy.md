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
- LXCat, UMIST, WebBook and CollisionDB conversion retain raw input and its
  SHA-256 with the snapshot. Other converters retain the source declarations they obtained;
  metadata not provided by an adapter remains unknown rather than invented.
- Keep restricted or confidential raw data, snapshots, and assets in suitable
  local storage. Do not add them to a public repository, distribute a result
  containing them, or bundle them in a release without checking the relevant
  rights. The catalog is not an access-control mechanism.
- Optional acquisition packages remain optional dependencies in
  `pyproject.toml`, separate from the core analysis runtime.

## Source-specific access and distribution

The following source statements were checked on 2026-10-13. Apply the terms to
the actual collection and record; neither the converter nor catalog grants rights.

| Source | Current handling |
|---|---|
| [CollisionDB licence](https://db-amdis.org/collisiondb/licence/) | Data and metadata are CC BY 4.0 unless explicitly stated otherwise. Retain attribution to the original authors, their references/DOIs, licence notices and modification information. Check any record-specific exception. |
| [LXCat redistribution policy](https://us.lxcat.net/instructions/redistribution.php) | Third-party redistribution is not generally authorised. Direct users to retrieve the data from LXCat and preserve contributor references. Inclusion in a commercial package requires the policy's explicit contributor permission and LXCat notification; a converter does not supply them. |
| [WebBook](https://webbook.nist.gov/chemistry/) and [NIST SRD policy](https://www.nist.gov/open/copyright-fair-use-and-licensing-statements-srd-data-software-and-technical-series-publications) | WebBook is SRD 69 and carries compilation copyright. Public browsing is not blanket redistribution permission. Check the relevant SRD and upstream collection terms before bundling saved pages or data. |
| Local or licensed files | Retain the actual owner, terms and source description. A local path, package licence or user-defined provider does not change the rights of the underlying observations. |

`acquire webbook SPECIES.yaml --out WORK` explicitly retrieves pages by CAS or
WebBook ID. `--page PAGE.html` converts a saved page for one target without network
access. `acquire collisiondb DATASET.txt --out WORK` converts a saved downloaded
JSON-header/two-column integral cross section; it does not download the whole DB.
Supported quantities, units, state mappings and frame requirements are defined
in the [data dictionary](data_dictionary.md) and [source workflow](data_sources.md).
Retrieval and format acceptance do not establish scientific applicability or approval.

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

Native IDs belong to their stated provider/collection/release namespace. A CAS
number or WebBook URI identifies a species, not an individual determination.
WebBook's converter-generated `derived_row_key` and its rule stay in
`source_declaration`; they do not become native `source.record_id` values.
Where the source supplies no quantity record ID, the common scientific-content
ID is used. CollisionDB's actual `qid` remains its native dataset ID.

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
compatibility rule. Reaction threshold and products-minus-reactants energy are
already independent typed Properties with their own definitions, qualifications
and scopes; the parent channel cannot approve them implicitly.

`data_selection.quantities` ranks or restricts the three numerical quantities,
formation enthalpy, IE, EA, excitation energy and thermochemical models by
method, provider, collection or record. `data_selection.targets` overrides a
quantity policy for one canonical target ID. These requests preserve identity,
definitions, reference conditions, qualifications and applicability checks;
they cannot exchange different observables or rate-law orders by source rank.
Existence and reaction-energy evidence selection are outside these policies.
The method `estimated` describes value generation and does not by itself supply
qualification or missing assumptions.

`rgen records RESULT --target TARGET [--quantity QUANTITY]` shows selectable IDs,
content and qualifications compactly; `--detail` includes complete raw
declarations. Listing a saved record does not qualify it or recompute a conclusion.
Multiple imports retain independent records and unresolved source inputs.
The version 1 review queue stores source/snapshot/kind per input, distinguishes
this import's review count from all pending inputs, and removes only a matching
input later accepted by ingest. Edited scientific declarations are not silently
treated as resolution of older inputs. Overlay and queue are saved together and
restored after an ordinary IO failure; incomplete recovery retains named backups.

WebBook retains unconfirmed precursor states and source structures instead of
assigning isomer-specific data to a formula-only target. Heavy-particle
CollisionDB files require their source's `com` or `target` energy frame;
user-selected axes do not supply a missing frame. Fit-generated tables retain
their calculated origin and declared domain, without promoting fit error to
measurement uncertainty. NASA9/Shomate, EEDF integration and surface-flux
conversion remain unimplemented; acquiring their input does not implement them.

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

## 1.0 property-source review (2026-11-01)

The working Registry's property records were checked as individual numerical values and
derived scalar estimates in this project's per-species representation. The
Registry does not contain WebBook/CCCBDB/ASD page archives, their database tables,
spectral plots, or the chemicals/mendeleev/PYroMat programs. A record's scientific
qualification is unchanged by this rights review.

Individual scientific facts and the protected expression or arrangement of a
compilation require different treatment. The
[U.S. Copyright Office](https://www.copyright.gov/help/faq/faq-protect.html)
distinguishes facts from their expression. NIST's own
[SRD workshop report, section 8.1](https://nvlpubs.nist.gov/nistpubs/SpecialPublications/NIST.SP.1225.pdf)
likewise distinguishes numerical scientific data from database presentation,
arrangement and metadata. These sources support reviewing the actual material
being distributed; they are not a new licence for arbitrary database exports.

| Local material | Verified source terms and required handling |
|---|---|
| WebBook-derived mass, ionization/affinity/formation values, e.g. CF4 and CF2 | [WebBook is SRD 69](https://webbook.nist.gov/chemistry/), not a generic non-SRD NIST work. Its [contact notice](https://webbook.nist.gov/chemistry/contact/) reserves compilation rights. Keep the source and original quantity references. Independent factual entries are distinct from copying its pages, table organisation, explanatory text or spectra. No blanket licence for the WebBook compilation was obtained. |
| CCCBDB experimental polarizability/dipole values, e.g. BCl3, C2H2, CF4 and CH4 | [CCCBDB identifies itself as SRD 101, release 22](https://cccbdb.nist.gov/). Keep the named determination, units and source reference; the local values are per-species facts, not a copy of its compilation. The general NIST non-SRD redistribution grant is not the basis for redistributing this SRD. |
| ASD levels, ionization energies and existence references, e.g. Ar, O, N ions | [ASD identifies SRD 78 and version 5.12](https://www.nist.gov/pml/atomic-spectra-database-contents); [Basic Atomic Spectroscopic Data](https://www.nist.gov/pml/handbook-basic-atomic-spectroscopic-data) is the separate SRD 108. Retain the actual database/version and primary references already present. Do not turn the generic citation “NIST Atomic Data” into an invented precise provenance. |
| chemicals thermochemistry, dipoles, collision radii and effective vibrational estimates | [chemicals v1.5.2](https://raw.githubusercontent.com/CalebBell/chemicals/v1.5.2/LICENSE.txt) is MIT; its copyright and permission notice are retained in [chemicals-LICENSE.txt](../registry/data_notes/chemicals-LICENSE.txt). The package uses several upstream databanks. The original Registry entries often omit the selected table and package release; a matching value today does not prove which historical table supplied it. Retain the existing citation and distinguish factual scalar reuse from copying an upstream table. New acquisitions retain their selected thermochemistry table and release. |
| mendeleev atomic mass, IE, EA and polarizability values | Both the [mendeleev v1.2.0 package](https://raw.githubusercontent.com/lmmentel/mendeleev/v1.2.0/LICENSE) and the separate [mendeleev-data v1.2.0 repository](https://github.com/lmmentel/mendeleev-data/tree/v1.2.0) are MIT. This provides a data-repository grant, beyond a software-only label. Retain [package notice](../registry/data_notes/mendeleev-LICENSE.txt), [data notice](../registry/data_notes/mendeleev-data-LICENSE.txt), original literature citations and transformations such as polarizability unit conversion. These checked versions do not retroactively supply an absent acquisition version. |
| PYroMat ideal-gas enthalpy values for CF, CFO and FO | The installed 2.2.6 package and [official source licence](https://raw.githubusercontent.com/chmarti1/PYroMat/master/LICENSE.txt) are GPLv3. Registry contains three scalar evaluations at 300 K, with no program or PYroMat coefficient files. GPLv3 section 2 distinguishes executing the program from output that itself constitutes a covered work. Do not label these numerical outputs, or this whole project, GPL merely because PYroMat evaluated them. If its program or protected database material is bundled later, its own source/notice obligations must be satisfied. Keep the existing program/source citation and evaluated temperature. |

The corresponding [NIST source notice](../registry/data_notes/NIST-SRD-NOTICE.txt)
preserves compilation attribution and explains the limited material included.
The [official NIST policy](https://www.nist.gov/open/copyright-fair-use-and-licensing-statements-srd-data-software-and-technical-series-publications)
separates SRD from its worldwide non-SRD data grant. Do not claim that all NIST
data are public domain, or that preserving a notice obtains a compilation
redistribution licence. Conversely, a compilation copyright notice does not by
itself make every cited numerical fact a prohibited copy.

No provider was contacted or new permission obtained in this review. Restrictions
for bulk/contractual database products, source pages, spectra, original papers or
future imported assets must be checked for that proposed distribution. The
present scalar review does not clear those different materials.

The former `tests/fixtures/cccbdb_polarizability.html` contained an excerpt of
source table markup. It was preserved outside the release tree, then replaced
by independently authored minimal HTML with invented values and references.
The fixture covers navigation, row shape, missing cells and sub/sup tags; its
tests validate the adapter, not physical measurements. The source distribution
does not ship the former excerpt. Registry values and scientific qualification
were not changed by this cleanup.
