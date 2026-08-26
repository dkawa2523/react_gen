# Changelog

## 0.5.0 - 2026-08-24

- Define the three canonical YAML files and all tabular CSV views as the stable
  output specification. Treat SVG, PNG, and HTML as non-normative derived views.
  Remove the derived root-state `missing` column, repeated screening-rule columns,
  and empty state tables from reaction-only assessment layers.
- Add a maintained output reference covering every public CSV column, state symbol,
  state axis, reaction family/process, assessment value, screening rule, summary,
  visualization, YAML capability, and common interpretation pitfall.
- Normalize displayed participant order across YAML, CSV, and network views: incident
  electrons first, heavy ions before neutral targets, activated neutrals before stable
  neutrals, and product electrons last. Canonical stoichiometry and reaction IDs are unchanged.
- Add exhaustive electron, ion, neutral, and surface family reaction CSV views at
  the case root, in every assessment layer, and in every cumulative screening stage.
  Empty families retain headers, and the unsplit `reactions.csv` remains canonical.
- Separate state excitation, resolution, lifetime/radiative class, canonical label,
  display symbol, and formula structure scope in YAML/CSV/network views. Expose
  lumped/resolved alternative representations instead of leaving overlapping state
  models implicit.
- Correct the curated argon 4s record to a mixed metastable/resonant umbrella. Match
  it exactly to `Ar(4s)` and only compatibly to `Ar(m)`/`Ar(r)`; compatible evidence
  no longer populates candidate-specific numerical property columns.
- Replace the wide metadata-heavy CSV views with compact human-readable
  `states.csv` and `reactions.csv` tables.
- Group the five assessment views under `assessments/<layer>/`; each layer has
  an exhaustive `reactions.csv` view, the three state-applicable layers also have
  `states.csv`, and all layers retain exact verdict
  counts in `summary.csv`, a
  normalized verdict-count SVG, and a verdict-colored hierarchical generation
  network. The network uses shared state nodes and directed reaction junctions
  so multi-reactant and multi-product channels remain explicit hyperedges.
- Add `assessments/statistics.csv` and `statistics.svg` for cross-layer verdict
  comparison and cumulative pass-only reaction readiness. Add `composition.svg`
  for complete-set charge, state-kind, reaction-family, and generation-depth
  counts.
- Add per-layer `family_summary.csv` and `reaction_family.svg` views. Use one
  edge width throughout the network, encode reaction family by color and verdict
  by line pattern. Replace sampled and paginated SVG networks with one offline
  `assessments/network.html` per case. It stores every reaction once and provides
  assessment/screening views, search, filters, in-page pagination, exact counts,
  a selected-reaction hyperedge, and clickable state-neighborhood networks.
  Neighborhoods classify connected reactions by net stoichiometric change into
  producers, consumers, and zero-net participants with independent pagination.
  Add a complete reaction-state stoichiometric matrix as the default explorer
  view and as one high-resolution `assessments/network.png` per case. Every
  reaction occupies exactly one column; no candidate is sampled or projected
  into ambiguous species-species edges. The PNG embeds counts, scope, and a
  reaction-ID digest for auditability.
- Add a target-selectable `Hierarchical pathways` explorer view and one
  `assessments/pathways.png` example per case. Path layers use minimum
  all-reactants-reachable hypergraph steps rather than candidate generation
  depth. Alternative producers, target consumers, and target-preserving
  reactions remain explicitly counted and inspectable; the view is labelled as
  reachability rather than kinetic dominance. Keep the overview to state names,
  roles, short reaction numbers/types, direction, and family colour; move exact
  equations, IDs, and assessments to click-through detail.
- Add three cumulative pass-only screening views from State + Consistency
  through Thermochemistry and a final Kinetics OR Reaction evidence gate.
  Each stage exports separate retained-state and retained-reaction CSV files,
  exact step retention counts, a retention chart, and a filtered reaction network.
  The final reaction CSV preserves both original verdicts, the combined OR verdict,
  and the accepting source.
- Remove the redundant `selected.csv`, the `layers/` directory, JSON-valued CSV
  cells, and repeated run metadata. The three YAML files remain the canonical
  machine-readable bundle.
- Use compact scientific state notation (`Ar(m)`, `Ar(r)`, `CF4*`, `O2(v)`,
  and resolved term symbols) and add a plain-language English `reaction_type`
  beside every displayed reaction equation. Add `state_meaning` to state CSV
  views and a collapsed notation guide plus state hover text to the explorer.

## 0.4.3 - 2026-08-24

- Keep `@ground` and other explicit state markers only in canonical machine IDs;
  show familiar names such as `Ar+`, `Ar(metastable)`, and `O2(vibrational)` in
  the leading CSV columns.
- Render reaction equations with human-readable species names while retaining
  deterministic IDs and the exact canonical equation in later columns.

## 0.4.2 - 2026-08-24

- Put state identity, formula, reaction equation, process, verdicts, and policy
  selection first in CSV views; move reproducibility metadata and nested detail
  to later columns.
- Restore compact per-assessment views as `layers/consistency.csv`, `state.csv`,
  `thermochemistry.csv`, `reaction_evidence.csv`, and `kinetics.csv` without
  restoring the legacy graphs, duplicated passed-only files, or summaries.
- Expose unambiguous state properties, elemental counts, and common reaction
  energy values as ordinary columns while keeping full evidence in YAML.

## 0.4.1 - 2026-08-24

- Add optional flat `states.csv`, `reactions.csv`, and `selected.csv` views via
  `rgen generate --csv`; the three YAML files remain the canonical ingest bundle.
- Include policy selection, exclusion reasons, all assessment verdicts, evidence
  references, and numerical-readiness fields in the CSV views.
- Keep the output directory stable and atomically replace each completed file,
  avoiding temporary-directory ACLs that hid generated files from Windows users.

## 0.4.0 - 2026-08-23

- Canonicalize source and generated reaction families/processes before channel
  keys are built. Three-body `recombination`, `association`, and the former
  generated name now resolve to one `neutral/three_body_association` channel.
- Reject non-finite and nonphysical pressure, temperature, density, field, and
  geometry conditions as case-input errors.
- Add a formula-level `reactive_candidate` role for odd-electron species,
  non-noble atoms, and valence-deficient homoleptic fragments such as CF2 and
  SiH2 without claiming a spin state.
- Bound neutral-pair expansion to feed, fragment, excited, and reactive
  candidates, preserving closure for the representative semiconductor mixtures.
- Require property-level evidence quality when electron affinity decides anion
  existence, and do not export unreviewed reaction enthalpy/Gibbs values as
  numerically ready values.
- Reject thermochemical `fail` from exploratory and strict simulation policies;
  thermochemical `unknown` remains visible and usable where policy permits.
- Require an explicit reviewed lumped-state record rather than treating one
  resolved member as proof that a lumped manifold is simulation-ready.
- Publish bundle schema version 4 because canonical channel names change
  deterministic reaction IDs.

## 0.3.0 - 2026-08-23

- Identify reaction channels by equation, family, and physical process so equal
  stoichiometry no longer merges elastic, charge-exchange, and other channels.
- Add numerical observables and require process, observable, unit, axis, scope,
  and applicability compatibility before a dataset is declared usable.
- Restrict formula-derived bond operations to atoms, diatomics, and homoleptic
  central-ligand formulas; keep general formulas on non-bond-specific templates.
- Treat charged noble-gas ligand products as complexes and prevent automatic
  creation of an unbound neutral ground-state parent.
- Rename the first assessment from Structure to Consistency, stop treating a
  feed declaration as state-existence evidence, and reject hard failures from
  the acquisition queue.
- Require a reviewed direct forward rate and an explicitly reversible thermal
  process before declaring a reverse rate derivable; exclude electron impact,
  mutual neutralization, and dissociative channels.
- Track evidence quality per property, thermochemical record, and numerical
  dataset so an estimated auxiliary property cannot downgrade reviewed thermo,
  and imported values cannot silently become reviewed evidence.
- Make PubChem identity acquisition reject ambiguous multi-record matches and
  include process metadata in snapshot-to-bundle matching.
- Remove the duplicate discovery policy and publish schema version 3.

## 0.2.0 - 2026-08-23

- Replace Registry-first expansion with deterministic formula-driven electron,
  ion, and neutral candidate templates.
- Separate mechanical candidates from read-only Registry, overlay, and snapshot
  evidence; Registry availability no longer changes the mechanical set.
- Add five independent four-valued assessments and purpose-specific ID selection.
- Normalize Registry, overlay, and snapshot evidence once, then use indexed state
  and equation matching instead of scanning the Registry for every candidate.
- Distinguish cross-section, direct-rate, reaction-enthalpy, electron-energy-loss,
  equilibrium, and reverse-rate readiness.
- Share one conservation implementation between Registry checks and candidate
  assessment, and remove implicit property derivation from Registry loading.
- Replace the legacy bundle with `states.yaml`, `reactions.yaml`, and
  `selected.yaml`; publish all three by one directory swap and provide one public
  bundle schema.
- Match acquired data to generated canonical bundle indexes and reserve Registry
  writes for explicit `rgen adopt`.
- Remove the `discover` executable/package, DNT/ranking/coverage/graph/layer
  generation, legacy outputs, and checked-in generated case bundles.
- Replace the stale implementation-specific quality baseline with direct Ruff,
  mypy, pytest, import-boundary, and case-generation gates.
- Require neutral formula gas inputs; remove fraction, DNT-grid, status, and
  process-selection case fields.
- Separate generation roles from electronic open-shell character, restrict bond
  operations to formulas with a bounded structural interpretation, and prevent
  neutral noble-gas bonding during composition operations.
- Preserve unbound/transient and qualified property evidence; reject unbound
  parent anions and energetically impossible Penning channels, and report
  charge-transfer energy defects where IE/EA data exist.
- Stop deriving excited-state NASA polynomials and electron-reaction reverse
  rates from a ground-state gas-temperature equilibrium assumption.
- Validate numerical table contents before declaring kinetics ready.

## 0.1.0 - 2026-07-14

- Generate deterministic, registry-driven multistep reaction lists with depth
  and precursor lineage.
- Associate multiple cross-section, rate-coefficient, and mobility datasets
  with registered reaction channels while reading the legacy cross-section form.
- Report DNT-relevant ion-neutral properties and existing datasets without
  executing DNT.
- Resolve versioned registry packs from input gases and retain explicit
  `--registry` behavior.
- Separate normal generation from registry-maintenance commands and keep
  generated workspaces out of source control.
