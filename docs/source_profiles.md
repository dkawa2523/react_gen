# Source Profiles

Source profiles describe which local/offline data sources are considered during
prepare/enrich workflows. They do not change `reactgen generate`: generation
still reads only the registry directory passed with `--registry`.

Built-in profiles live under `registry/rules/source_profiles/`:

- `local_only`
- `experimental_first`
- `internal_first`

## Metadata Fields

Each profile can include these metadata lists:

```yaml
active_sources:
  - local_registry
  - local_assets
optional_sources:
  - internal_file
  - nist_snapshot
  - chemicals_optional
disabled_sources:
  - pubchem_online
  - vamdc
  - openadas
external_only_sources:
  - pubchem_fetch
  - lxcat_raw_import
  - openadas_raw_import
  - vamdc_query
```

`active_sources` are local sources that are expected to be usable by default.
`optional_sources` are allowed by the profile but may need configuration, such
as a local snapshot directory. `disabled_sources` are explicitly ignored by the
provider factory. `external_only_sources` are acquisition/conversion tools run
with `python -m external_data_tools...`; they are not imported by the core
package.

The source priority lists still control prepare/enrich ordering:

```yaml
species_identity:
  - local_registry
  - internal_species_db
properties:
  - local_registry
  - internal_property_db
  - nist_snapshot
electron_cross_sections:
  - local_assets
  - lxcat_offline
ion_neutral_reactions:
  - local_registry
  - internal_reaction_db
```

If a listed optional provider is missing configuration, enrich reports a warning
and continues unless `strict_sources: true` is set.

## Inspecting A Profile

Use:

```powershell
reactgen source-list --source-profile local_only --registry registry
reactgen source-list --source-profile experimental_first --registry registry
reactgen source-list --source-profile path/to/source_profile.yaml --registry registry
```

The command prints active, optional, disabled, and external-only sources,
missing configuration, provider counts, and license-review notes when
`external_data/source_catalog.yaml` is available.

## Enabling Internal File Data

Add the internal file providers to the priority lists and configure the local
root:

```yaml
properties:
  - local_registry
  - internal_property_db
ion_neutral_reactions:
  - local_registry
  - internal_reaction_db
internal_file:
  root: path/to/internal_data
```

Expected local layout:

```text
internal_data/
  species/species.yaml
  properties/properties.yaml
  reactions/electron.yaml
  reactions/ion_neutral.yaml
  cross_sections/index.yaml
```

## Enabling Local NIST Snapshots

Core NIST property support is local snapshot only. Core generation and
enrichment do not scrape NIST or call online services. A separate, explicitly
invoked `external_data_tools.data_admin import_nist_beb` command can populate a
site-local prepared registry with declared SRD 107 total-ionization endpoints.

```yaml
properties:
  - local_registry
  - nist_snapshot
nist_snapshot:
  root: external_data/nist
```

Users are responsible for licensing, citation, and redistribution review for
NIST-derived snapshots.

## Enabling LXCat Assets

LXCat support is local/offline only. Import raw files or simple CSV/TSV files
outside curated registry, then link reviewed assets into `prepared_registry`.

```yaml
electron_cross_sections:
  - local_assets
  - lxcat_offline
lxcat_offline:
  index: external_data/lxcat/index.yaml
```

For simple manual assets, the usual workflow is:

```powershell
reactgen import-cross-sections INPUT.csv --workspace WORKSPACE --reaction-id REACTION_ID --target TARGET
reactgen apply-cross-section-mapping mapping.yaml --workspace WORKSPACE
```

## Disabled And External-Only Sources

Disabled sources are not built by the provider factory even if a user
accidentally adds them to a priority list. External-only sources remain in
`external_data_tools/` and should be run explicitly by users. Generated external
snapshots should be reviewed before they are used by prepare/enrich.
