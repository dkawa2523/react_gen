# Ar/CF4 registry data note

This note documents the first public-data realization of the Ar/CF4 registry.

## What was curated

- Ar, Ar+, F, F-, F+, CF4, CF4+, CF3, CF3+, CF3-, CF2, CF2+ species records.
- Electron-collision channels for e+Ar, e+CF4, e+CF3, e+CF2, and e+F.
- Ion-neutral channels for Ar+ + Ar, Ar+ + CF4, Ar+ + CF3, Ar+ + CF2, Ar+ + F, CF3+ + CF4, CF3+ + CF2, CF3+ + Ar, F- + CF4, and F+ + CF4.

## Important limitations

- Numeric cross-section curves are not embedded. Cross-section import from LXCat/NIST/literature remains a separate task.
- CF4 primary polarizability is curated from NIST CCCBDB; CF4 collision-radius and CF3/CF2 polarizability/collision-radius values marked `estimated` are transport hypotheses, not final recommended pair-potential constants.
- CF2 dipole moment is not curated and remains missing.
- Parent CF4+ channels are retained only as estimated/surrogate bookkeeping because CF4 ionization/charge transfer is strongly fragmenting.

## Suggested next import targets

1. LXCat/Bordage CF4 electron cross-section set.
2. Phelps/Biagi/Pancheshnyi Ar electron and Ar+ transport data.
3. Peko et al. absolute cross sections for CF3+ + CF4, F+ + CF4, and F- + CF4.
4. Reviewed ion-neutral measurements for channels that currently have estimates only.
