# Reaction output contract

`network.reactions.yaml` and `network.reactions.csv` are the primary products
of `reactgen generate`. A normal user only selects gases in the case YAML and
runs `generate`; no source profile, workspace, mapping, or property input is
required.

The YAML record is built from an explicit field list. Internal dataclass fields
do not become public output fields automatically, so this contract changes only
through a deliberate serializer change.

The existing frontier expansion follows products through later reaction
depths. Each reaction includes `precursor_reaction_ids`, containing only
earlier-depth reactions that can produce a non-input reactant. Direct reactions
of input gases have an empty list. IDs and datasets are emitted in deterministic
order, and same-depth edges cannot form a lineage cycle.

At each depth, pair candidates come from the registry index rather than a
family-specific Cartesian product. A registered pair is selected only when
both reactants are active and at least one is in the current frontier. Family
names are registry data, not user configuration; new registered two-body
families therefore participate automatically. Inference remains opt-in and is
disabled by default.
The `unimolecular` family uses one physical reactant even though the registry
index retains a compatibility target field.

Each YAML reaction retains the existing fields and adds:

- `precursor_reaction_ids`
- `available_data.cross_sections`
- `available_data.rate_coefficients`
- `available_data.mobility`
- `threshold_eV`
- `deltaE_products_minus_reactants_eV`
- `provenance_summary`

Dataset candidates are never collapsed into one record. Channels may declare
them under `data.datasets`; legacy `data.cross_section` is normalized in memory
as one cross-section dataset without rewriting the registry.
For table representations, core generation marks a dataset available only when
its asset path resolves to a real file inside the selected base/pack registry.
The top-level summary reports counts by reaction family and separates reactions
with usable numerical data from reactions whose equations are available without it.

`mechanism_coverage.yaml` compares generated reactions with the bounded
primary-source table scopes declared in
`registry/sources/semiconductor_mechanisms.yaml`. Its `complete` flag is scoped
to those rows and is never a claim of universal plasma-chemistry completeness.

`dnt_tasks.yaml` groups ion-neutral reactions and reports required property
values, units, provenance and availability, existing datasets, channel
energetics, and `data_choice.status`. It does not run DNT+. `missing_data.yaml`
adds reaction and dataset gaps. DNT-property gaps are added only when
`outputs.dnt_inputs: true` explicitly puts DNT preparation in scope; they never
stop reaction-list generation.
Missing optional cross-section, rate-coefficient, and mobility datasets are
grouped into one informational item per ion-neutral pair.
No DNT result importer, Boltzmann solver, plasma solver, or external core API
call is part of generation.

When automatic registry-pack resolution is used, `summary.json.registry`
records the resolver mode and selected pack ID/version. A missing pack does not
block generation and is not reported as a chemistry gap; generation uses the
shared base registry. Missing input species or reusable reaction pairs remain
normal coverage findings.
