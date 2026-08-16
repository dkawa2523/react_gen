# Argonne/ATcT-Style Thermochemistry Snapshots

This directory is for manually prepared or internally approved local
thermochemistry snapshots. In this repository, "Argonne/ATcT" means a local
snapshot source family for high-quality thermochemistry and active
thermochemical-table-style values.

The repository does not scrape websites, call online services, or assume public
bulk redistribution rights. Users are responsible for licensing, citation,
internal-use permissions, temperature conventions, uncertainties, and source
review.

Use the external tools to plan and validate local snapshots:

```bash
python -m external_data_tools.argonne_atct_snapshot_plan WORKSPACE_OR_OUTPUTS --output external_data/argonne_atct/required_thermochemistry.yaml
python -m external_data_tools.argonne_atct_snapshot_validate external_data/argonne_atct/species_thermochemistry.yaml
```

Validated snapshots can be used by prepare/enrich workflows as local property
providers. Reaction energetics candidates such as
`deltaE_products_minus_reactants_eV` should be reviewed for sign convention and
source consistency before final DNT use. Curated `registry/` files must not be
mutated automatically.
