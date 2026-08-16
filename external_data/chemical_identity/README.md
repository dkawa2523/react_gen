# Chemical Identity Snapshots

This directory is for local identity snapshots derived from reviewed sources
such as ChEBI, ChemSpider, OPSIN, NCI/Cactus, PubChem, or internal identity
tables. These sources help with names, aliases, formulas, SMILES/InChI/InChIKey,
and ontology tags. They are not plasma reaction databases.

External online helper code lives under `external_data_tools/`. Core
prepare/enrich code reads local snapshots only, and `reactgen generate` does not
access online identity services.

ChemSpider may require API credentials. ChEBI, OPSIN, and NCI/Cactus support
different public access paths, but generated data should be cached locally,
reviewed, and converted into the merged snapshot format before use.

Example snapshot:

```yaml
schema_version: 1
source:
  source_type: local_snapshot
  database: chemical_identity_merged
records:
  - species: CF4
    query: tetrafluoromethane
    identifiers:
      chebi_id: CHEBI:38834
      inchikey: TXEYQDLBPFQVAA-UHFFFAOYSA-N
      canonical_smiles: C(F)(F)(F)F
    formula: CF4
    aliases:
      - tetrafluoromethane
      - carbon tetrafluoride
    ontology_tags:
      - halocarbon
    source_records:
      - database: ChEBI
        raw_file: external_data/raw/chemical_identity/chebi/cf4.yaml
```

Identity enrichment merges aliases and missing identifiers only. Existing
composition or formula conflicts are reported for review rather than overwritten.
