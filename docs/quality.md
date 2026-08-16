# Quality gates

Install the pinned development toolchain once:

```powershell
python -m pip install -e ".[quality]"
```

The repository exposes four Nox sessions and matching Make targets:

| command | purpose |
|---|---|
| `python -m nox -s quality-fast` | Strict format, lint, and mypy checks for changed Python files, then unit/property tests. |
| `python -m nox -s quality-pr` | Baseline-aware full static, typing, architecture, test, branch/diff coverage, security, dependency, secret, and dead-code gates. |
| `python -m nox -s quality-nightly` | PR gates plus three Hypothesis seeds, the semiconductor end-to-end benchmark, and scoped mutmut mutation testing. |
| `python -m nox -s quality-baseline` | Explicitly replace `quality/baseline.json` after reviewing every change. |

`make quality-fast`, `make quality-pr`, `make quality-nightly`, and
`make quality-baseline` are equivalent on systems with Make. Normal gates never
write the baseline.

## Baseline policy

The baseline records existing findings by tool-specific stable unit:

- Ruff and mypy: file and rule/error code;
- Radon: file and function;
- Bandit: file and test ID;
- Vulture: file and candidate description;
- detect-secrets and pip-audit: finding fingerprint or vulnerability ID;
- coverage: repository-wide branch-aware percentage.

Existing counts may decrease. A new key, a higher count, a newly unformatted
file, a function newly exceeding complexity 10, an existing complexity increase,
or lower branch coverage fails `quality-pr`. Changed Python files are checked
strictly with no baseline allowance. When `QUALITY_BASE_REF` is available,
changed production lines must have at least 90% coverage.

The baseline may be updated only by the dedicated command after reviewing its
diff. CI never invokes that command.

## Test scope

Hypothesis is used for formula/equation and conservation invariants. There is no
database service or browser UI in this repository, so Testcontainers and
Playwright are intentionally not installed. The three-case semiconductor runner
is the end-to-end workflow. Mutation testing is limited to the scientific
equation, formula, and validation modules and runs on scheduled Ubuntu CI;
mutmut does not support native Windows.

The sole production Ruff security exception is `S310` in `http_client.py`.
That module rejects non-HTTP(S), hostless, and credential-bearing URLs before
constructing the stdlib request; regression tests cover each rejected form.
Bandit reports no finding for the validated implementation.
