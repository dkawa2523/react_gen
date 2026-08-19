# Acquiring the reaction list

What has to be collected before `rgen generate` can build a reaction list for a
gas, in the order it has to be collected, with what makes each item acceptable.

Numerical data — cross sections, rate coefficients — is a separate and later
concern. This plan is about the equations and the information needed to write
them down correctly.

## The unit of storage

One record per reaction, never per gas mixture. A registered `e + CF4` file
serves every case containing CF4, and generation resolves the combinations at
run time. Adding a gas is adding its own records, not a new mixture pack.

## What a reaction record needs

| field | why | where it comes from |
|---|---|---|
| reactants and products | the equation itself | mechanism literature, evaluated reviews |
| species composition and charge | element and charge balance reject a wrong equation | PubChem identity, verified against the registry formula |
| `threshold_eV` | opens the channel; checked against the reaction energetics | ionization and appearance energies |
| `type` and `dnt_class` | decides expansion and which DNT+ tier applies | the channel's own physics |
| `source_record` | a reviewer must be able to find the row again | the citation |

A record without a cross section is still a usable record. A record without a
balanced equation is not.

## Step 1 — identity (done)

```powershell
acquire pubchem external_data/identity/query.yaml --out external_data/identity
```

All 28 stable neutral species verified against PubChem: composition compared
element by element, then mass. Results in `external_data/identity/identity.yaml`.

**Composition must be compared, not just mass.** A name lookup for `CO` returns
cobalt (CID 104730, 58.93 amu). Comparing mass alone reads that as a
disagreement; comparing composition identifies it as the wrong compound.
`external_data/identity/pubchem_queries.yaml` holds the explicit query names for
the eight species whose formula is not a name PubChem resolves.

Ions, radicals and excited states have no PubChem entry and are not queried.

## Step 2 — derivable chemistry (done)

An excited state's ionization threshold is the ground-state threshold minus the
excitation energy. That is arithmetic on registered values, so it is derived
rather than acquired, and the derivation is recorded in the file:

| species | threshold | from |
|---|---:|---|
| `Ar_4s` | 4.16 eV | 15.7596 − 11.6 |
| `O2_a1Delta` | 11.0927 eV | 12.0697 − 0.977 |
| `O2_b1Sigma` | 10.4427 eV | 12.0697 − 1.627 |
| `O_1D` | 11.6511 eV | 13.618055 − 1.967 |

Each gets elastic, stepwise ionization and superelastic channels. Stepwise
ionization from metastables is a dominant electron source; leaving these species
in the network with no electron chemistry made them dead ends.

## Step 3 — the remaining worklist

Generated from the registry, not maintained by hand:

```powershell
rgen plan cases/ar_sf6_o2/case.yaml     # per case
```

`external_data/worklist/electron_channels.yaml` holds the whole backlog: **23
neutral species with no electron chemistry, 9 of them already produced by
registered chemistry**. The second group is the urgent one — those species exist
in generated networks today and cannot be processed.

### Group A — produced by registered chemistry, no way to react (9)

`SO SO2 SO2F SO2F2 SOF SOF2 SOF3 SOF4 C`

These come out of SF6/O2 chemistry. Electron-collision data for the SOxFy family
is genuinely sparse; expect primary literature rather than an evaluated review,
and expect some channels to stay unregistered with that recorded as the finding.

| target | route |
|---|---|
| SO, SO2 | evaluated electron-collision reviews for sulfur oxides |
| SOF2, SO2F2, SOF4, SOF3, SOF, SO2F | SF6/O2 discharge literature; QDB sets covering SF6/O2 |
| C | atomic carbon ionization from atomic data compilations |

### Group B — registered feedstocks with no chemistry (14)

`BCl3 C2H2 C4F8 CH4 CHF3 Cl2 Cu H2 HBr He N2 NF3 NH3 SiH4`

| target | route | note |
|---|---|---|
| He, H2, N2, CH4, Cl2 | LXCat complete sets (Biagi, Phelps, IST-Lisbon, Morgan, Hayashi) | well covered; expect a clean import |
| C4F8, NF3, CHF3 | Christophorou–Olthoff style evaluations; QDB fluorocarbon sets | product branching must be resolved |
| SiH4, NH3 | silane and ammonia plasma reviews; LXCat | deposition chemistry, many fragments |
| C2H2 | LXCat hydrocarbon sets | |
| BCl3, HBr | primary literature only | sparsest of the group |
| Cu | atomic data compilations | sputtered metal, not a feed gas |

Once an export is in hand the path is mechanical:

```powershell
acquire lxcat export.txt --out work/n2
rgen ingest work/n2/snapshot.yaml --overlay work/overlay.yaml
rgen generate cases/n2/case.yaml --overlay work/overlay.yaml
```

Matching is structural, so `E + N2 -> E + E + N2+` finds the registered reaction
whatever spelling the export uses. Anything matching zero or several reactions
lands in `review_queue.yaml` instead of being guessed at.

## What cannot be automated

There is no public API that returns the electron-impact channels of a molecule.
Channel enumeration is a reading task against evaluated reviews and mechanism
papers, and the acceptance decision — is this the same process, at these states,
in this energy range — is a judgement. What is automated is everything around
it: identity verification, structural matching, balance and energy checks, and
the worklist that says what is still missing.

## Acceptance

Every imported record passes the same gates before it counts:

- charge and element balance, or the reaction is rejected at expansion
- an endothermic channel's threshold covers its own `delta_e_eV`
- one momentum-transfer channel per target, and no lumped state tracked
  alongside the levels it stands for
- a `source_record` a reviewer can follow

Run `rgen check --registry registry` to apply them to the registry alone.
