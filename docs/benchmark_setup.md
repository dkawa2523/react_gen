# Benchmark Setup

`external_data_tools.benchmark_setup` validates the local files needed by the
registry benchmark suite. It checks required fixtures, records file hashes, and
can write a machine-readable setup report. It neither downloads scientific data
by default nor executes simulation software.

```powershell
python -m external_data_tools.benchmark_setup --config benchmarks/benchmark_setup.yaml --check
python -m external_data_tools.benchmark_setup --config benchmarks/benchmark_setup.yaml --check --write-report benchmarks/results/setup_report.yaml
```

The checked-in configuration requires only local synthetic benchmark fixtures.
They validate the workflow, not scientific accuracy. Replace them with reviewed
data before using generated mechanisms for quantitative work.

Optional Python dependencies and explicit user-provided downloads are
maintenance features. They run only with `--install-python-deps` or
`--download-explicit-data`; network downloads additionally require
`policies.allow_network_downloads: true`. The tool does not scrape websites,
authenticate to data services, or mutate the curated registry.
