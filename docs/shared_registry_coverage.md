# Shared reaction-registry coverage

The registry stores species and reusable reactions, never a predefined gas mixture.
Input gases seed the active species set and generation follows every reachable,
registered reaction until the frontier closes. `expansion.max_depth` is optional and
should be used only for an intentionally truncated diagnostic run.

```text
input gases -> reachable registered reactions -> products -> repeat to closure
```

## Completed bounded mechanisms

Coverage is measured against declared rows in primary literature, rather than against
an unbounded claim that every possible plasma reaction is known.

| Mechanism | Declared gas-phase scope | Registry result |
|---|---|---:|
| Son et al. (2014), CF4/Ar/O2 | Table 1, R1-R60 volume chemistry | 60/60 |
| Pateau et al. (2014), SF6 | Tables II-III, R1-R50 mass-balance chemistry | 50/50 |
| Pateau et al. (2014), SF6/O2 | Table VII, R119-R138 cross chemistry | 20/20 |

The registry includes electron dissociation, ionization and attachment; CFx/F/O/COx
neutral chemistry; SFx/F recombination; SFx/O oxidation; 63 explicitly enumerated
negative-ion detachment reactions; 56 explicitly enumerated mutual-neutralization
reactions; and the unary `SOF4 -> SOF3 + F` reaction. Every emitted reaction is checked
for registered species, charge balance, and element balance.

`mechanism_coverage.yaml` is written for each generation. A complete entry means only
that all rows within that entry's declared scope are represented. It does not mean that
all semiconductor gases, surfaces, states, or numerical data are complete.

R138 is included as a reaction equation but has no numerical coefficient. The primary
table and later transcriptions do not give a sufficiently consistent exponent/unit for
safe numerical use. The equation is therefore available to the chemical list while the
coefficient remains an explicit acquisition gap.

## Reaction list versus numerical data

`network.reactions.yaml` and `.csv` are the primary chemical-list outputs. Reaction
equations do not require a local cross section, rate coefficient, DNT input, or solver
result. The YAML summary separately reports reactions with and without usable numerical
datasets.

DNT task inventory is retained for compatibility, but DNT gaps are not part of normal
reaction-list diagnostics. They become warnings only when `outputs.dnt_inputs: true` is
requested.

## Broader semiconductor feedstocks

The following feedstock identities are registered so they can be passed to generation
and acquisition planning: H2, N2, C4F8, SiH4, NH3, Cu, Cl2, BCl3, CH4, C2H2, He, CHF3,
HBr, and NF3. A feedstock without an electron-reaction file produces an explicit
`chemical_reaction_list` error; an empty result is never presented as a complete
chemistry.

`external_data/qdb_semiconductor_chemistries.yaml` inventories all 29 chemistry sets in
QDB Table 7 (November 2016), including validated SF6/O2, CF4/O2, C4F8,
Ar/O2/C4F8, SF6/CF4/O2, and SF6/CF4/N2/H2 sets and acquisition targets for
Ar/NF3, Cl2/O2/Ar, Ar/BCl3/Cl2, and silane/ammonia deposition chemistry.

Licensed QDB responses can be cached without exposing the API key:

```powershell
$env:QDB_API_KEY = "..."
python -m external_data_tools.qdb_chemistry `
  --chemistry-id 31 `
  --output external_data/raw/qdb/C31.txt
```

The response and checksum metadata remain site-local and are not auto-promoted. Each
reaction, state, dataset, unit, source, and license must be reviewed before registry
import.

## Remaining work

1. **P0 — numeric process data for completed mechanisms.** Import product-resolved
   electron cross sections and validate the temperature/E/N applicability of published
   rates. A total-ionization curve must not be substituted for product branching.
2. **P1 — missing semiconductor gas families.** Acquire and review C4F8, NF3,
   Cl2/BCl3/HBr, SiH4/NH3/N2/H2 reaction sets, starting with QDB C11/C16/C31,
   C19/C20/C27, and C13/C14/C17.
3. **P1 — surface/material chemistry.** Add separate surface-state semantics for Si,
   SiO2, Si3N4, masks, chamber walls, adsorption, desorption, sputtering, etching, and
   polymer deposition. Surface reactions must not be disguised as gas-phase binary
   reactions.
4. **P2 — model validation.** Compare dominant pathways and observables over declared
   pressure, power, gas temperature, E/N, residence time, and wall-condition ranges.
   Add uncertainty and sensitivity analysis only after the relevant numerical data exist.

Benchmark cross sections are synthetic workflow fixtures and must never be promoted as
scientific registry data.
