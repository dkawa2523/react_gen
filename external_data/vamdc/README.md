# VAMDC Raw Query Cache

This directory is for raw VAMDC TAP/XSAMS query outputs created by external
data tools. The core `plasma_reactgen` package and `reactgen generate` do not
access VAMDC.

VAMDC is a federation of nodes, and available species, processes, query
behavior, and metadata coverage vary by node. Users must choose endpoints and
queries explicitly and review node-specific citation, licensing, and data
quality requirements.

Use:

```bash
python -m external_data_tools.vamdc_query MANIFEST.yaml --output-root external_data/raw/vamdc --dry-run
python -m external_data_tools.vamdc_query MANIFEST.yaml --output-root external_data/raw/vamdc
```

This first implementation stores raw responses and provenance metadata only. It
does not perform full XSAMS parsing, reaction conversion, rate fitting, or
automatic promotion into the curated `registry/`. Raw VAMDC output should be
reviewed and converted later by source-specific tools.
