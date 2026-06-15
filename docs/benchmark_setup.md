# Benchmark Setup

`external_data_tools.benchmark_setup` checks whether local benchmark data,
optional Python tooling, and optional external solver executable paths are ready
before benchmarks run.

It does not vendor solver binaries, does not redistribute licensed database
files, and does not download files from sites that require manual license
acceptance or login.

## Commands

```powershell
python -m external_data_tools.benchmark_setup --config benchmarks/benchmark_setup.yaml --check
python -m external_data_tools.benchmark_setup --config benchmarks/benchmark_setup.yaml --install-python-deps
python -m external_data_tools.benchmark_setup --config benchmarks/benchmark_setup.yaml --download-explicit-data
python -m external_data_tools.benchmark_setup --config benchmarks/benchmark_setup.yaml --check --write-report benchmarks/results/setup_report.yaml
```

On Windows checkouts where `python` is not the active launcher, use `py -m`
instead.

## What Live Solver Means

A live solver benchmark means a benchmark that can call an external executable
such as BOLSIG+, ZDPlasKin, LoKI-B, ThunderBoltz, or ngspice. This setup command
does not run those solvers. It only checks whether the configured executable path
exists or whether a common executable name is available on `PATH`.

`reactgen generate` remains local-registry-only and never calls these solvers.

## Configuring Solver Paths

Copy `benchmarks/external_solvers.example.yaml` to
`benchmarks/external_solvers.yaml` if you want a local machine-specific solver
configuration. Set `enabled: true` and fill `executable` with an absolute or
workspace-relative path:

```yaml
solvers:
  ngspice:
    enabled: true
    executable: C:/Program Files/ngspice/bin/ngspice.exe
    adapter: ngspice_basic
```

If `executable` is null, the setup checks common names on `PATH`, such as
`ngspice`, `bolsigminus`, `loki-b`, or `zdplaskin`.

## Required Registry Benchmark Data

`benchmarks/data_requirements_semiconductor.yaml` lists the data needed for the
local registry-level benchmark. The current required data are the local Ar/CF4
smoke fixture and its synthetic cross-section CSV:

- `cases/ar_cf4_db_smoke/internal_data`
- `cases/ar_cf4_db_smoke/cross_sections/e_CF4_elastic.csv`

The checker verifies file or directory existence and records SHA-256 hashes for
files. It never creates fake data.

## Optional Solver-Coupled Data

Optional live-solver checks may reference reviewed LXCat asset sets, BOLSIG+
executables, ngspice, or other solver paths. Missing optional data is reported as
a warning and does not fail setup unless the policy is changed.

## Python Optional Dependencies

Python package installation is explicit only:

```powershell
python -m external_data_tools.benchmark_setup --config benchmarks/benchmark_setup.yaml --install-python-deps
```

The command runs `python -m pip install -r <requirements>` for the listed
requirements files. The initial requirements files are comment-only placeholders.

## Explicit Downloads

Downloads run only when both are true:

- the user passes `--download-explicit-data`
- `policies.allow_network_downloads: true`

The manifest must contain explicit user-provided URLs. The setup command does
not scrape sites, log in, discover hidden APIs, or auto-download licensed files.

## System Package Installation

System package installation does not run silently. The setup report may suggest
commands such as:

```powershell
winget install ngspice
```

```bash
brew install ngspice
sudo apt-get install ngspice
```

Users must run those commands themselves unless a future explicit
system-install flag is added.

## Why Solvers Are Not Bundled

BOLSIG+, ZDPlasKin, LoKI-B, ThunderBoltz, ngspice, and licensed data files have
their own distribution, citation, platform, and license constraints. This
repository records paths and setup status only. Users are responsible for
installation, licensing, and citation review.
