# NIST Local Snapshots

This directory is for manually prepared NIST-derived local snapshot YAML files.
The repository does not scrape NIST websites, call NIST online services, or
perform automatic bulk NIST downloads.

Use `external_data_tools.nist_snapshot_plan` to create a review checklist from
`missing_data.yaml` or `prepare_report.yaml`. Use
`external_data_tools.nist_snapshot_validate` to check a manually prepared
snapshot before using it with prepare/enrich workflows.

Users are responsible for source selection, licensing, citation, access dates,
and reviewing imported values. NIST snapshots must not be promoted into the
curated `registry/` automatically.

NIST is appropriate for selected identity, thermochemistry, atomic, and
molecular property references. It is not the default source for
`collision_radius_A`; use internal transport fits or manual DNT parameter review
for that value.
