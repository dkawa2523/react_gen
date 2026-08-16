# LXCat Manual Raw Files

This directory is for local LXCat-related manifests and notes. The repository
does not implement LXCat scraping, login/session handling, automatic downloads,
or redistribution of LXCat data.

Users should manually download data from LXCat, review the applicable citation
and redistribution requirements, then import selected files with:

```bash
python -m external_data_tools.lxcat_raw_import RAW_FILE --workspace WORKSPACE --target CF4 --source lxcat_manual
```

The importer supports simple CSV/TSV files with `energy_eV` and
`cross_section_m2` columns and a conservative single-block BOLSIG+/LXCat-like
plain text format. Ambiguous files are reported as unresolved and are not
imported.

Optional mappings can be kept in `external_data/lxcat/mappings.yaml`:

```yaml
schema_version: 1
mappings:
  - target: CF4
    process_label_contains: dissociation
    reaction_id: e_CF4_dissociation_CF3_F
    mapping_status: manual_review_required
```

Mappings update only `workspace/prepared_registry` electron channels. They do
not modify the curated `registry/`.
