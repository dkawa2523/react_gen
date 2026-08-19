# Data sources

Where the numbers come from, and what has to be true before they are used.

## The path any external number takes

```
acquire fetch      explicit URL manifest, checksummed        (network)
acquire lxcat      foreign format -> snapshot.yaml + assets  (local)
rgen ingest        structural match onto registered reactions
                     -> overlay.yaml        exactly one match
                     -> review_queue.yaml   zero or several matches
rgen generate --overlay ...                 try it before committing
registry/                                   a person copies it in
```

Nothing skips a step. `rgen ingest` never writes `registry/`; it writes an
overlay that generation merges in memory, so a bad import is discarded by
deleting one file. Promotion into `registry/` is a human edit and a commit.

## Acceptance rules

| data | source | accepted when |
|---|---|---|
| electron cross sections | LXCat (Biagi, Phelps, IST-Lisbon, Morgan), Itikawa and Christophorou–Olthoff evaluations | product-resolved channels, eV and m², threshold consistent with the equation, complete set declared, one momentum-transfer channel per target |
| rate coefficients | NIST Chemical Kinetics, IUPAC and JPL evaluations, primary kinetics literature | temperature range preserved as `validity`, SI units, plasma applicability reviewed |
| three-body rates | evaluated kinetics compilations | m⁶/s with third-body efficiencies stated |
| wall loss | surface-loss measurements | γ with material, temperature and coverage stated |
| species properties | NIST Chemistry WebBook and CCCBDB | value, unit, state convention, citable source record |
| thermochemistry | ATcT, NIST-JANAF, Burcat | NASA 7-coefficient polynomial with its temperature ranges |
| identity and aliases | PubChem | identity only; never treated as reaction evidence |

A total ionization curve is never accepted as a product-resolved channel.

## Licensing

`external_data/source_catalog.yaml` records, per source, whether it may be
redistributed, whether it needs a key, and its review status. Site-local and
internal data stays out of the shared registry: keep it in an overlay and pass
`--overlay` at generation. See [source and license policy](source_license_policy.md).

## Network access

`acquire fetch` is the only code that opens a connection, it accepts http and
https only, it is dry-run by default, and it writes `fetch_record.yaml` with a
SHA-256 for every file. `reactgen` cannot reach the network at all — an import
contract forbids it.

## What to acquire next

Run it against a real case rather than reading a list:

```powershell
rgen plan cases/ar_sf6_o2/case.yaml
```

The plan groups the case's gaps by the source family that can close them, with
the acceptance rule for each, and marks priority by severity.
