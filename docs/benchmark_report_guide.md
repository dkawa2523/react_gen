# Benchmark Report Guide

`external_data_tools.benchmark_report` converts benchmark runner outputs into a
human-readable Markdown evaluation. It is intended for the local semiconductor
benchmark suite:

- Ar/O2 simple oxygen plasma
- Ar/CF4 fluorocarbon plasma
- Ar/SF6/O2 electronegative plasma

The report evaluates mechanism readiness, data coverage, missing-data
transparency, and workflow execution. It does not claim final quantitative
plasma process accuracy.

## Command

```powershell
python -m external_data_tools.benchmark_runner benchmarks/benchmark_config_semiconductor.yaml
python -m external_data_tools.benchmark_report benchmarks/results/summary.yaml --output benchmarks/results/semiconductor_benchmark_report.md
```

On Windows environments where `python` is not the active launcher, use `py`:

```powershell
py -m external_data_tools.benchmark_report benchmarks/results/summary.yaml --output benchmarks/results/semiconductor_benchmark_report.md
```

## Status Labels

- `passed`: the workflow produced required species, reaction families, outputs,
  and zero validation errors.
- `warning`: the workflow ran, but data coverage, provenance, DNT readiness, or
  solver availability needs attention.
- `failed`: setup, generation, or validation failed.
- `skipped`: optional live solvers were disabled or missing; this is not a
  registry-level benchmark failure.
- `needs domain review`: fixture or imported data must be reviewed before
  scientific use.

## Evaluation Rules

`PASS_WORKFLOW` requires:

- expectation score at least `0.75`
- `validation_error_count == 0`
- at least one electron reaction
- at least one ion-neutral reaction

`WARNING_DATA_GAPS` is emitted for low cross-section coverage, low provenance
coverage, high inferred reaction fraction, or no DNT-ready pairs.

`WARNING_SOLVER_SKIPPED` or `SKIPPED_SOLVER` means optional solver paths or
adapters were not configured. The benchmark still passes if the registry-level
workflow succeeded.

`FAIL_SETUP`, `FAIL_VALIDATION`, and `FAIL_GENERATION` indicate missing required
fixtures, charge/element balance errors, or no generated reactions.

## Interpreting The Report

Use the report to decide whether the current prepared registry is useful for
review and next-step data work. Low-pressure plasma modeling still requires
reviewed cross sections, transport/DNT parameters, reaction energetics, and
domain expert review before quantitative conclusions.
