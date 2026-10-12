# Changelog

## 0.7.4 - 2026-10-12

- Name every public assessment and save its individual scope, concrete missing
  prerequisites and participant references. Keep binding, observed support,
  computed quantities and reaction occurrence distinct.
- Store reaction energies as independently qualified Properties. Preserve their
  definitions and uncertainties; normalize legacy external scalars once without
  retaining parallel internal values or inheriting new quantity approval.
- Compare compatible energy declarations within their stated scopes, preserve
  unknown molecular definitions, and localize physical-target mismatches.
- Show saved values, conditions and next work in CLI and HTML. Keep source
  choice, disagreements and internal generation history inspectable.
- Deduplicate explicit prerequisites and preserve dependent conclusions. Add
  CSV format 3 for individual scopes, requirements, references and selections;
  continue to verify historical formats 1 and 2 without reassessment.

## 0.7.3 - 2026-10-12

- Share electron-binding logic between state support and attachment. Keep
  contradictory positive affinity and unbound declarations unresolved; exclude
  the conflicting quantity without interpreting short lifetime as unbinding.
- Require explicit compatible formation references before subtracting formation
  enthalpies, including finite-temperature ion/electron conventions. Preserve
  incomplete declarations and independent NASA or ionization results.
- Make evidence catalogs isolated snapshots, rebuild indexes for explicit
  updates, and fingerprint actual in-memory scientific contents as well as files.
- Summarize shortage findings by responsibility, proposition and saved outcome;
  retain every affected target with `needs --detail`. Expose judgment propositions,
  scopes, explanations and input responsibilities in CSV format 2. Continue to
  verify and rebuild historical format 1 tables without reassessment.
- Review current NASA/JPL source tables and keep unresolved product manifolds
  separate from exact fine-structure levels. Source data does not complete a
  predictive mechanism.

## 0.7.2 - 2026-10-12

- Preserve saved observed asset hashes independently of author declarations.
  Validate the same bytes used for numerical table evaluation, including files
  changed after loading. Compare verified asset content independently of its
  storage path while retaining original declarations and acquisition locations.
- Keep exact physical identity when reviewed existence assertions disagree.
  Report the existence conflict as unknown without suppressing independently
  qualified properties or thermochemical models. Preserve actual identity
  ambiguity and rejected-record restrictions.
- Localize reaction energy conflicts to the quantities used by each proposition.
  Retain independent threshold, binding and Penning conclusions, and keep
  conflicting declarations and separately available calculated values visible.
- Keep schema 5 and the existing analysis inputs. Earlier saved results remain
  historical results; reading them does not rerun scientific assessments.

## 0.7.1 - 2026-10-12

- Apply review scopes and rejected/conflicting status to state existence,
  individual properties and thermochemical models at file and Python boundaries.
- Share scientific source-ID namespaces across states, reactions and datasets;
  preserve reacquisition declarations and reject one scientific ID assigned to
  different physical targets.
- Round-trip independent reaction assertions through snapshots, overlays and
  Registry records without creating empty numerical datasets or guessing an
  unknown process from a matching formula.

## 0.7.0 - 2026-10-12

- Add source-independent proposition names for state support, anion binding,
  thermochemical representation availability and reaction energy checks. Match
  corresponding ground states by composition, charge, phase, structure and
  uniqueness; check elastic identities before asserting zero internal energy.
- Preserve independent state declarations, properties and NASA fits through
  snapshot ingestion, `state_records` overlays and Registry `records`. Separate
  scientific record IDs from target IDs; retain original source declarations,
  provider/collection/release identifiers, scientific method and review scope.
- Compare NASA fits by physical contents, keeping both source records. Keep
  quantity conflicts local, and do not turn a numeric-only overlay into channel
  existence evidence or an unknown anion placeholder into negative evidence.
- Restrict explicit reaction review scopes to channel assertions, threshold or
  delta-energy claims. Numerical snapshots default to their quantity scope, so
  coefficient approval does not qualify accompanying channel or energy claims.
  Retain unscoped legacy channel declarations under their existing rules.
- Retain every channel for Registry pairs spanning multiple files. Reject
  repeated channel IDs with both file locations instead of overwriting records.
- Namespace native numerical record IDs with their stated source, including
  snapshot-level provenance. Preserve explicit canonical IDs and detect changed
  contents of one native record as a conflict. Apply numerical review scopes
  to the dataset's own quantity.
  UMIST conversion retains native fit IDs for the common generator rather than
  assigning a global ID from the row number without its release.
- Add quantity-specific `data_selection` for rate coefficients, cross sections
  and sticking probabilities: prefer or restrict methods, providers and
  collections, or pin a dataset ID. Assess records before selection and preserve
  pending applicability conditions, alternate values and ID conflicts. Property,
  NASA and existence-evidence selection remain unsupported input errors.
- Add optional proposition, selection and disagreement fields to schema 5.
  Validate selected records and requests during result reads while preserving
  compatibility with earlier schema 5 results. Legacy dataset `preferred` is
  used only without a request for that quantity and is scheduled for removal in
  0.8.
- Preserve ASD level annotations and source rows; withhold unsupported absolute
  energy and lifetime claims. Store PyroMat h(T) as enthalpy with its reference
  information, rather than claiming formation enthalpy.
- Parse UMIST RATE12/RATE22 fit layouts explicitly, retaining method, accuracy,
  notes and raw rows. Reject malformed rows with locations and retain unresolved
  additive rates as references. Do not infer LXCat product scope or an elastic
  total/momentum-transfer observable; reject incomplete process blocks.
- Consolidate source access and provided quantities in one local source catalog.
  Preserve raw conversion inputs, full download hashes and acquisition metadata.
  Acquisition, matching, adoption and scientific review remain separate actions.
- Keep reacquisition context separate from scientific numerical identity and
  conflict checks. Preserve distinct acquisition declarations without overwriting
  the original record, and keep unknown physical conditions in comparisons.

## 0.6.0 - 2026-10-11

- Replace policy selection and cumulative screening with one offline `analyze`
  pipeline and schema-5 `result.yaml`. CSV, needs and figures derive from that
  result. Inputs are targets, explicit physical conditions and computation limits.
- Separate candidate grammar, exact state/channel identity, proposition-specific
  judgments and numerical data use. Missing evidence stays unknown; numerical
  defects do not assert that a phenomenon is absent. Preserve phase, structure,
  resolution, stabilization, source qualifications and asset integrity.
- Close the bounded mechanical grammar independently of generation history;
  report limits and mechanical/attested completion separately.
- Compare rates only within the same observable, dimensions and order. Preserve
  missing conditions, nonoverlapping applicability domains and explicit model
  selection requirements; finite comparison points do not prove equivalence.
- Match stabilization through both ingest paths; retain acquisition phase and
  estimated quality. Preflight and stage adoption, restore changes after I/O
  failures, and retain recovery backups when restoration itself fails.
- Distinguish an unselected judgment from an unknown verdict in HTML. Partition
  matrices above 8000 reactions without dropping columns and publish the index
  after all page images are saved.
- Review selected existing records against primary or official sources, retaining
  unresolved measurement conditions and model scope. See the scientific review.
- Reject duplicate YAML keys and malformed numeric/boolean declarations; keep
  independent state assertions, attributes and property qualifications through
  ingest and adoption using the same full physical identity as analysis.
- Apply property uncertainty intervals consistently to IE, EA and Penning;
  retain alternative rate laws with unresolved applicability conditions.
- Validate CSV hashes against canonical content and numerical-use conclusions
  against their selected dataset. Use the available safe LibYAML implementation
  without dropping validation; expose a small result I/O benchmark tool.
- Reject LXCat column-unit mismatches and malformed table rows before conversion,
  preserving parsed numeric precision in CSV assets.
- Select process patterns within their declared reaction family. Check heavy
  unimolecular dissociation and two-entity association without inferring an
  inducer, stabilization, elementary mechanism or numerical rate.
- Repair source-backed association classifications and review Pateau coefficient
  dimensions and Son's 700 K model values. Retain source applicability gaps;
  review selected oxygen identities, individual energy properties and the O2
  NASA7 fit without promoting unrelated data.
- Select thermochemical records only for the reaction participants, eliminating
  repeated selection of unrelated states while preserving all conclusions.
- Retain loss and formula-level measurements without promoting them to
  state-resolved product rates; require review of unresolved product branching.
- Remove obsolete internal paths and old tracked output examples, update acquisition
  documentation and CI artifacts. `generate`, old policies and schema-4 bundles
  are no longer accepted by normal processing. Use `tools/migrate_v4.py` with a
  new destination to preserve old inputs/evidence and recompute judgments; this
  one-time tool is scheduled for removal in 0.8.

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
