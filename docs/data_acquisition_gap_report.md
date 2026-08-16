# Data-acquisition gap report

Measured on 2026-08-14 with exhaustive registered-graph expansion. These are reusable
species/reaction gaps for the given input, not requests for predefined mixture packs.

| Input scope | Species | Reactions | Missing e-process data | Missing heavy-particle data | Property targets | Active P1-P2 reaction candidates |
|---|---:|---:|---:|---:|---:|---:|
| Ar/O2 | 10 | 22 | 13 | 3 | 0 | 22 |
| CF4/O2 | 30 | 98 | 38 | 11 | 34 | 86 |
| SF6/O2 | 41 | 230 | 51 | 1 | 66 | 140 |
| Ar/O2/CF4/SF6 integration | 59 | 318 | 76 | 28 | 89 | 337 |
| Ar/NF3 acquisition start | 3 | 5 | 3 | 2 | 0 | 4 |

The Ar/NF3 row contains the Ar mechanism plus an explicit missing `e + NF3` pair. It is
not reported as a complete NF3 chemistry. QDB C31 (104 reactions in the cited 2016
inventory) is routed as the first licensed acquisition candidate.

## Priority interpretation

- **P0: reaction equations.** Review and register balanced, source-backed channels for
  missing feedstocks and missing reachable pairs. A reaction equation may be retained
  without a numerical dataset.
- **P1: numerical data.** Collect exact process-resolved electron cross sections,
  heavy-particle rates/cross sections, and required species properties. Total ionization
  does not resolve product branches.
- **P2: applicability.** Verify states, units, temperature/energy ranges, pressure model,
  uncertainties, and source licensing before promotion.
- **P3: deferred combinations.** Product-product combinations remain discovery
  candidates until literature supplies a real channel; combinations are not invented.

DNT and calculated-result ingestion are outside this acquisition-plan scope. Their
absence does not suppress the chemical reaction list.

## Source routing

| Information | Primary route | Acceptance rule |
|---|---|---|
| Bounded plasma mechanisms | Primary mechanism papers | Every declared row mapped to a balanced reaction ID |
| Licensed semiconductor chemistry sets | QDB API | Explicit chemistry ID, site-local raw file, key redacted, license review |
| Electron cross sections | Evaluated O2 workbook, NIST SRD 107, reviewed LXCat export | Exact process mapping; eV and m2; local asset |
| Molecular rates | Primary kinetics literature, then reviewed KIDA/UMIST candidates | Exact equation; source range preserved; plasma applicability reviewed |
| Identity/formula/aliases | PubChem PUG REST | Identity only; never treated as reaction evidence |
| IE/EA/dipole/polarizability/thermochemistry | NIST/ATcT reviewed snapshots | Value, unit, source record, state/reference convention |
| Atomic state/process inventory | Reviewed VAMDC/OpenADAS sources | Explicit node/state/process mapping and redistribution review |

## Reproduce

```powershell
python -m external_data_tools.data_admin plan_data_acquisition `
  --seed-gases Ar O2 CF4 SF6 `
  --registry registry `
  --output-dir external_data/acquisition_work
```

Omitting `--max-depth` now expands to closure. An explicit depth is a diagnostic limit
and is recorded as truncation when reachable registered chemistry remains.

The plan writes a QDB request manifest in addition to property, cross-section, rate,
VAMDC, OpenADAS, identity, and reaction-candidate manifests. QDB fetch requires a
reviewed chemistry ID and `QDB_API_KEY`; the repository does not contain a credential.
