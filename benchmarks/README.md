# Benchmarks

This directory is for benchmark case inputs and local benchmark outputs.

Use:

- `cases/` for small benchmark case definitions that are safe to commit.
- `results/` for generated benchmark outputs, which are ignored by default
  unless a small result snapshot is intentionally reviewed and committed.

Do not commit large benchmark results unless they are intentionally reviewed and
kept small.

For any benchmark run, the generated per-case `benchmark_metrics.yaml` and
`benchmark_report.yaml`, plus `results/summary.yaml`, are the source of truth.
Checked-in Markdown result documents are review snapshots and are not live
status pages.
