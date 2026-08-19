# Design

Three packages, 4,643 lines. `reactgen` turns input gases and process conditions
into a reaction list and the datasets a plasma model needs. `acquire` turns
foreign data files into something `reactgen` can ingest. They never import each
other, and `import-linter` enforces that along with the layering below.

## reactgen

Read in this order. Each module owns one thing and imports only from the ones
below it.

| module | owns | lines |
|---|---|---:|
| `model.py` | value types. No I/O, no policy. | 255 |
| `case.py` | gases, process conditions, geometry, surfaces, limits, DNT grid | 121 |
| `naming.py` | identify a species written in someone else's notation | 205 |
| `registry.py` | reading registry YAML, the species index, the import overlay | 428 |
| `balance.py` | charge and element conservation | 53 |
| `thermo.py` | NASA polynomials, Gibbs energy, the reverse rate | 96 |
| `expand.py` | growing the network from the input gases | 166 |
| `physics.py` | quantities derived from registered values | 227 |
| `rank.py` | how fast each reaction could possibly run | 84 |
| `audit.py` | is the reaction list itself sound | 229 |
| `quality.py` | is the numerical data behind it usable | 190 |
| `coverage.py` | how much of each declared literature mechanism is present | 78 |
| `dnt.py` | DNT+ inputs, graded by the model each pair can run | 168 |
| `ingest.py` | matching a data snapshot onto registered reactions | 192 |
| `lock.py` | pinning the data a run used | 89 |
| `plan.py` | routing gaps to acquisition sources | 89 |
| `export.py` | writing the output bundle | 344 |
| `cli.py` | four commands | 98 |

```powershell
rgen generate cases/ar_sf6_o2/case.yaml       # the bundle
rgen check    --registry registry             # validate the registry alone
rgen plan     cases/ar_sf6_o2/case.yaml       # what to acquire, by source
rgen ingest   snapshot.yaml --overlay work/overlay.yaml
```

`generate` exits non-zero on a blocking gap, so it works as a CI gate.

## acquire

| module | owns | lines |
|---|---|---:|
| `lxcat.py` | parse an LXCat export into per-process cross sections | 122 |
| `umist.py` | parse a UMIST RATE release into SI Arrhenius records | 108 |
| `pubchem.py` | fetch and verify species identity | 147 |
| `snapshot.py` | write the snapshot and its table assets | 55 |
| `cli.py` | three commands | 118 |

```powershell
acquire lxcat export.txt --out work/ar
acquire umist rate22.rates --out work/umist
acquire pubchem species.yaml --out external_data/identity
rgen ingest work/ar/snapshot.yaml --overlay work/overlay.yaml
rgen generate cases/ar_cf4/case.yaml --overlay work/overlay.yaml
```

`pubchem` is the only code in the repository that opens a network connection,
and it fetches identity only — never a reaction.

## discover — optional

Proposes the channels a species could have when the registry has none, and says
which database could confirm each. Nothing imports it, and every channel it
writes carries `status: candidate`, which no case accepts.

| module | owns | lines |
|---|---|---:|
| `fragments.py` | enumerate channels from the formula, under conservation | 108 |
| `sources.py` | which database covers what, and whether it is reachable now | 82 |
| `evidence.py` | ask the reachable sources whether a candidate is real | 74 |
| `cli.py` | three commands | 198 |

```powershell
discover sources                                  # coverage and access per database
discover channels --gas SF6 --out work/sf6        # propose, then route
```

Two constraints keep the enumeration physical: the ligand leaves singly or in a
pair, and one bond breaks at a time. So `SiH4` yields SiH3+H and SiH2+H2 and
never `H4`. A fragment the registry does not have is named from its formula and
listed under `register_first`, because bootstrapping a new gas means finding its
species and its channels together.

Ion-neutral chemistry is the family with almost no queryable database, and the
one that needs none: `A+ + B -> A + B+` is exothermic exactly when B is easier
to ionize, so `discover pairs` settles it from ionization energies alone and
`reactgen.physics` supplies the Langevin rate that follows.

| module | owns | lines |
|---|---|---:|
| `screen.py` | which ion-neutral channels are thermodynamically open | 68 |
| `known.py` | which equations a source lists, reading no number | 110 |
| `view.py` | the four registry projections discovery needs | 68 |

Three questions are kept apart, because they have different answers and
different sources:

| question | field | who can answer |
|---|---|---|
| does this *species* exist | `species_evidence` | PubChem and other compound databases |
| does this *reaction* exist | `listed_by` | anything that states the equation: the registry, UMIST, LXCat, a mechanism table |
| what is its coefficient | `parameters` | the same sources, read for their numbers |

`known.py` reads equations only. That is what makes a source usable for
existence even when its numbers are not: UMIST rates are astrochemical and do
not transfer, but a UMIST row still states that the reaction happens. The
registry is the strongest listing of all — each of its reactions was read from a
mechanism paper and reviewed — so a candidate matching one is `already
registered` rather than new work.

The catalog is data (`external_data/sources.yaml`), so adding a database is
editing YAML. Each entry declares what it covers, how it is reached — `api`,
`api_key`, `bulk_download`, `manual_export`, `derived` — and the physical caveat
a reviewer must weigh. When several describe one reaction, `priority` orders
them; a candidate is only as confirmed as its least confirmed term.

Only PubChem answers without a credential or a manual export, and it answers
about species, never reactions. A radical has no PubChem entry by design, so
that reads `unavailable`, not `not_found`.

## Input

```yaml
name: ar_sf6_o2
gases: [Ar, SF6, O2]

conditions:
  pressure_Pa: 4.0
  gas_temperature_K: 400.0
  electron_temperature_eV: 3.0     # convolves cross sections into rates
  electron_density_m3: 5.0e16      # lets electron reactions be ranked
  reduced_field_Td: 50.0
  volume_m3: 0.021                 # geometry turns a sticking coefficient
  surface_area_m2: 0.52            #   into a wall loss frequency
  residence_time_s: 0.05           # the physical reference for relevance

surfaces: [SiO2, Y2O3]
dnt: {energy_max_eV: 300.0, points: 300}
accept_status: [curated, literature_supported]
```

## Output

```
outputs/
  species.yaml              property values, units, sources, thermo, state resolution
  reactions.yaml            lineage, rate, reverse rate, energy cost, Delta G, relevance
  reduced.yaml              the same list with provably negligible reactions removed
  reactions.csv             flat
  coverage.yaml             rows of each declared literature mechanism
  gaps.yaml                 one list of everything still missing
  summary.yaml              counts, data coverage by rate form, relevance, mechanism id
  lock.yaml                 dataset ids and checksums this run consumed
  datasets/
    rates.yaml              coefficients evaluated at the case conditions
    cross_sections/         electron tables copied local, plus index.yaml
    dnt/                    one DNT+ input per pair, graded by tier, plus index.yaml
```

## Registry

```
registry/species/*.yaml               one species, optionally with a NASA polynomial
registry/reactions/<family>/*.yaml    one collision pair
registry/materials/*.yaml             one surface material
registry/sources/*.yaml               declared literature mechanism scopes
registry/assets/**                    numerical tables
```

Families are directory names, not code. Three read extra fields:

- `three_body` — the channel carries `third_body: M`; the rate is in m⁶/s.
- `surface` — the pair target is a material id and the channel carries a
  `sticking_coefficient`. Charge balance is skipped: the wall absorbs it.
- `ion_neutral` — `pair.potential.short_range` feeds the DNT+ full tier.

A lumped state declares the levels it stands for, and tracking both is blocking:

```yaml
state: {kind: excited, resolution: lumped, members: [Ar_1s5, Ar_1s4, Ar_1s3, Ar_1s2]}
```

## Identifying a species someone else named

Every database spells a species differently. `naming.py` parses a written name
into what it *asserts* — composition, charge, and a state label if it names one —
and matches structurally. Folding the string cannot do this: `O2*` and
`O2(a1Dg)` differ in meaning, not spelling.

| decidable by rule | not decidable by rule |
|---|---|
| charge: `Ar+` `Ar^+` `Ar_p` `Ar(+)` `AR 1+` `Ar+2` | which level `1s5`, `3P2` and `4s` name |
| subscript vs charge: `SF5-` is SF5 with charge −1 | whether `O2*` means a¹Δ or b¹Σ |
| electron: `e` `e-` `E` `e^-` `ELECTRON` | |
| all-caps formulas: `AR` → `Ar` | |
| Greek: `a1Dg` = `a1Delta_g` = `A1DELTAG` | |

The right column lives in each species' `aliases`, because no rule relates a
Paschen label to a term symbol. A name matching several registered species
returns `ambiguous` with the candidates listed — `O2*` gives
`[O2, O2_a1Delta, O2_b1Sigma]` — and `rgen ingest` queues that record for a
person rather than picking one.

## Conservation and thermodynamics

| law | where | when |
|---|---|---|
| charge | `balance.py` | every reaction, at expansion. Failure rejects it. |
| elements | `balance.py` | every reaction, at expansion. Failure rejects it. |
| energy | `audit.py` | threshold must cover an endothermic `delta_e_eV`. Blocking. |
| entropy | `thermo.py` | Gibbs energy per reaction, and the reverse rate |

`delta_e_eV` is E(products) − E(reactants), so a positive value is endothermic.
Thermodynamics annotates; it never removes a registered reaction.

## Relevance

Each reaction is evaluated as if its partner were the entire gas, which no
partner ever is, so the frequency is an upper bound. What that bound is compared
against decides how much it means:

- **residence time** — physical. Chemistry three decades slower than gas
  exchange contributes under 0.1% and is marked `negligible`.
- **fastest reaction** — ordering only. The bar for `negligible` is six decades.

The basis is reported on every reaction. `reduced.yaml` drops only `negligible`.

## Two kinds of finding

Splitting the checks by what they need is what keeps either half readable.

| | asks | needs data | runs on |
|---|---|---|---|
| `audit.py` | is this reaction list sound? | no | registry alone, or a network |
| `quality.py` | is the data behind it usable? | yes | a network and its conditions |

`rgen check` runs `audit` only, so a registry with no numbers at all still gets a
full structural verdict. `quality` returns nothing for a capability the registry
has no data of — one `out_of_scope` note instead of a backlog.

## Design rules

**One report.** Every problem is a `Gap(kind, subject, detail, severity)` in one
list. Adding a check means appending a `Gap`.

**Values are never invented.** Missing stays `None` and becomes a gap. Four
values are derived and each says so in its output: molecular mass from the
formula, the Langevin capture rate, the Maxwellian rate from a cross-section
table, and the reverse rate from detailed balance.

**Generation stays offline.** `acquire` may reach the network; `reactgen` may
not. `lock.yaml` records the registry fingerprint and dataset checksums a run
consumed, so drift is detectable.

**Imports never touch the curated registry.** `rgen ingest` writes an overlay
that `generate --overlay` merges in memory, and queues anything ambiguous.
