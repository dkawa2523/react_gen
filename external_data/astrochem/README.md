# Astrochemical Network Conversions

This directory is for locally converted KIDA/UMIST-like astrochemical reaction
network snapshots. The repository does not download KIDA or UMIST data.

Use local CSV/TSV files with:

```bash
python -m external_data_tools.astrochem_network_convert NETWORK.csv --database KIDA --output external_data/snapshots/kida_converted_ion_neutral.yaml
python -m external_data_tools.astrochem_network_convert NETWORK.csv --database UMIST --output external_data/snapshots/umist_converted_ion_neutral.yaml
```

Converted reactions are candidate ion-neutral records marked
`status: imported` and `review_required: true`. Astrochemical rate parameters
are preserved under `data.rate_form`; they are not plasma cross sections and are
not semiconductor-validated kinetics.

Use these conversions for candidate discovery and manual review only. Do not
auto-promote converted records into the curated `registry/`.
