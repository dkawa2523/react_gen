# Semiconductor Low-Pressure Plasma Reaction-Network Benchmark

## Title And Scope

This report evaluates mechanism readiness, data coverage, missing-data transparency, and benchmark workflow for:
- Ar/O2 simple oxygen plasma (`ar_o2_simple`)
- Ar/CF4 fluorocarbon plasma (`ar_cf4_fluorocarbon`)
- Ar/SF6/O2 electronegative plasma (`sf6_o2_electronegative`)

This benchmark does not validate final quantitative plasma process accuracy. Fixture values and cross sections may be synthetic and must be replaced with reviewed data before scientific conclusions.

## Execution Summary

- Report generated at: 2026-06-15T06:46:20.965323+00:00
- Benchmark summary timestamp: 2026-06-15T06:46:17.172714+00:00
- Benchmark ids: ar_o2_simple, ar_cf4_fluorocarbon, sf6_o2_electronegative
- Passed workflow cases: 3
- Warning cases: 3
- Failed checks: 0
- Skipped solver cases: 3
- Needs domain review: 3

Solver status summary:
- ready: 0
- disabled: 15
- skipped_missing_executable: 0
- skipped_missing_adapter: 0
- skipped_missing_input_adapter: 0
- completed: 0
- failed: 0
- Live external solvers were skipped or disabled; this is a warning, not a benchmark failure.
- Setup report: `C:\Users\user\Desktop\react_gen-main\benchmarks\results\setup_report.yaml`

## Case-By-Case Summary

| Case | Status | Species | Reactions | Electron | Ion-neutral | Score | Xsec coverage | DNT ready | Missing actions | Provenance | Solver |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| Ar/O2 simple oxygen plasma | PASS_WORKFLOW, WARNING_DATA_GAPS, SKIPPED_SOLVER | 8 | 14 | 8 | 6 | 1.00 | 0.12 | 4 | 2 | 0.64 | skipped: disabled |
| Ar/CF4 fluorocarbon plasma | PASS_WORKFLOW, WARNING_DATA_GAPS, SKIPPED_SOLVER | 14 | 46 | 20 | 26 | 1.00 | 0.05 | 10 | 2 | 0.09 | skipped: disabled |
| Ar/SF6/O2 electronegative plasma | PASS_WORKFLOW, WARNING_DATA_GAPS, SKIPPED_SOLVER | 14 | 23 | 15 | 8 | 1.00 | 0.13 | 4 | 2 | 0.61 | skipped: disabled |

## Case Status Details

### Ar/O2 simple oxygen plasma
- Status tags: PASS_WORKFLOW, WARNING_DATA_GAPS, SKIPPED_SOLVER
- warning: Cross-section asset coverage is low.
- warning: Optional live solvers were disabled or skipped; this is not a registry benchmark failure.
- needs domain review: benchmark fixture and imported data should be reviewed before scientific use.

### Ar/CF4 fluorocarbon plasma
- Status tags: PASS_WORKFLOW, WARNING_DATA_GAPS, SKIPPED_SOLVER
- warning: Cross-section asset coverage is low.
- warning: Provenance coverage is low for generated reactions.
- warning: Optional live solvers were disabled or skipped; this is not a registry benchmark failure.
- needs domain review: benchmark fixture and imported data should be reviewed before scientific use.

### Ar/SF6/O2 electronegative plasma
- Status tags: PASS_WORKFLOW, WARNING_DATA_GAPS, SKIPPED_SOLVER
- warning: Cross-section asset coverage is low.
- warning: Optional live solvers were disabled or skipped; this is not a registry benchmark failure.
- needs domain review: benchmark fixture and imported data should be reviewed before scientific use.

## Ar/O2 Specific Evaluation

- passed: O2 electron elastic reaction type
- passed: O2 electron ionization reaction type
- passed: O2 electron dissociation reaction type
- passed: O2 electron attachment reaction type
- passed: ion-neutral family exists
- passed: Ar+ + O2 channel exists when fixture is present
- passed: O species present or generated
- passed: O- species present or generated
- passed: validation_error_count == 0
- warning: synthetic fixture data is present and must not be used for production plasma modeling.

## Practical Modeling Usefulness

### Ar/O2 simple oxygen plasma
- passed: at least one electron reaction
- passed: at least one ion-neutral reaction
- passed: required species present
- passed: charge/element balance errors are zero
- passed: missing data items are actionable
- passed: DNT pairs identified
- passed: at least one electron reaction has a cross-section asset
- passed: inferred fraction is not too high
- needs domain review: Import reviewed LXCat/internal cross sections for electron reactions.; Review missing-data actions and fill manual templates where source enrichment cannot help.; Configure live solver paths only if quantitative transport/coupling validation is needed.; Review ion-neutral reaction energetics for channels listed in the missing plan.

### Ar/CF4 fluorocarbon plasma
- passed: at least one electron reaction
- passed: at least one ion-neutral reaction
- passed: required species present
- passed: charge/element balance errors are zero
- passed: missing data items are actionable
- passed: DNT pairs identified
- passed: at least one electron reaction has a cross-section asset
- passed: inferred fraction is not too high
- needs domain review: Import reviewed LXCat/internal cross sections for electron reactions.; Promote reviewed imported/literature channels with provenance after domain review.; Review missing-data actions and fill manual templates where source enrichment cannot help.; Configure live solver paths only if quantitative transport/coupling validation is needed.

### Ar/SF6/O2 electronegative plasma
- passed: at least one electron reaction
- passed: at least one ion-neutral reaction
- passed: required species present
- passed: charge/element balance errors are zero
- passed: missing data items are actionable
- passed: DNT pairs identified
- passed: at least one electron reaction has a cross-section asset
- passed: inferred fraction is not too high
- needs domain review: Import reviewed LXCat/internal cross sections for electron reactions.; Review missing-data actions and fill manual templates where source enrichment cannot help.; Configure live solver paths only if quantitative transport/coupling validation is needed.; Review ion-neutral reaction energetics for channels listed in the missing plan.

## Plausibility Checks

### Ar/O2 simple oxygen plasma
- passed: required species present
- passed: required reaction families present
- passed: validation_error_count == 0
- passed: no unreviewed imported data was promoted to the curated registry by the benchmark runner
- passed: missing data is reported
- skipped: optional solver skipped status is not a failure for registry-level benchmarks

### Ar/CF4 fluorocarbon plasma
- passed: required species present
- passed: required reaction families present
- passed: validation_error_count == 0
- passed: no unreviewed imported data was promoted to the curated registry by the benchmark runner
- passed: missing data is reported
- skipped: optional solver skipped status is not a failure for registry-level benchmarks

### Ar/SF6/O2 electronegative plasma
- passed: required species present
- passed: required reaction families present
- passed: validation_error_count == 0
- passed: no unreviewed imported data was promoted to the curated registry by the benchmark runner
- passed: missing data is reported
- skipped: optional solver skipped status is not a failure for registry-level benchmarks

## Warnings And Limitations

- warning: fixture cross-section data may be synthetic.
- skipped: external solvers are not executed unless configured.
- skipped: no Boltzmann, DNT, ngspice, or other quantitative solver validation runs by default.
- warning: missing cross sections remain a modeling blocker for quantitative rates.
- warning: missing `collision_radius_A` remains a DNT blocker for affected neutral targets.
- needs domain review: synthetic fixture values must be replaced before scientific conclusions.

## Recommended Next Actions

- Import reviewed LXCat/internal cross sections for electron reactions.
- Review missing-data actions and fill manual templates where source enrichment cannot help.
- Configure live solver paths only if quantitative transport/coupling validation is needed.
- Review ion-neutral reaction energetics for channels listed in the missing plan.
- Promote reviewed imported/literature channels with provenance after domain review.
- Import reviewed LXCat/internal cross sections.
- Fill DNT neutral properties.
- Review ion-neutral reaction energetics.
- Reduce inferred reaction fraction by promoting reviewed data.
- Configure live solver paths if quantitative transport validation is needed.

## Appendix

- Summary: `benchmarks\results\summary.yaml`
- Setup report: `C:\Users\user\Desktop\react_gen-main\benchmarks\results\setup_report.yaml`
- Ar/O2 simple oxygen plasma report: `C:\Users\user\Desktop\react_gen-main\benchmarks\results\ar_o2_simple\benchmark_report.yaml`
- Ar/O2 simple oxygen plasma metrics: `C:\Users\user\Desktop\react_gen-main\benchmarks\results\ar_o2_simple\benchmark_metrics.yaml`
- Ar/O2 simple oxygen plasma missing plan: `C:\Users\user\Desktop\react_gen-main\benchmarks\results\ar_o2_simple\work\missing_plan.yaml`
- Ar/O2 simple oxygen plasma source profile: `C:\Users\user\Desktop\react_gen-main\benchmarks\fixtures\ar_o2_simple\source_profile.yaml`
- Ar/O2 simple oxygen plasma external solver config: `C:\Users\user\Desktop\react_gen-main\benchmarks\external_solvers.example.yaml`
- Ar/O2 simple oxygen plasma plot: `C:\Users\user\Desktop\react_gen-main\benchmarks\results\ar_o2_simple\outputs\visualizations\network\reaction_network.png`
- Ar/O2 simple oxygen plasma plot: `C:\Users\user\Desktop\react_gen-main\benchmarks\results\ar_o2_simple\outputs\visualizations\network\reaction_network.svg`
- Ar/O2 simple oxygen plasma plot: `C:\Users\user\Desktop\react_gen-main\benchmarks\results\ar_o2_simple\outputs\visualizations\network\species_lineage.png`
- Ar/O2 simple oxygen plasma plot: `C:\Users\user\Desktop\react_gen-main\benchmarks\results\ar_o2_simple\outputs\visualizations\network\species_lineage.svg`
- Ar/O2 simple oxygen plasma plot: `C:\Users\user\Desktop\react_gen-main\benchmarks\results\ar_o2_simple\outputs\visualizations\statistics\coverage_status_counts.svg`
- Ar/O2 simple oxygen plasma plot: `C:\Users\user\Desktop\react_gen-main\benchmarks\results\ar_o2_simple\outputs\visualizations\statistics\dnt_readiness_counts.svg`
- Ar/O2 simple oxygen plasma plot: `C:\Users\user\Desktop\react_gen-main\benchmarks\results\ar_o2_simple\outputs\visualizations\statistics\missing_data_counts.svg`
- Ar/O2 simple oxygen plasma plot: `C:\Users\user\Desktop\react_gen-main\benchmarks\results\ar_o2_simple\outputs\visualizations\statistics\reaction_depth_by_family.svg`
- Ar/O2 simple oxygen plasma plot: `C:\Users\user\Desktop\react_gen-main\benchmarks\results\ar_o2_simple\outputs\visualizations\statistics\reaction_family_counts.svg`
- Ar/O2 simple oxygen plasma plot: `C:\Users\user\Desktop\react_gen-main\benchmarks\results\ar_o2_simple\outputs\visualizations\statistics\reaction_type_counts.svg`
- Ar/O2 simple oxygen plasma plot: `C:\Users\user\Desktop\react_gen-main\benchmarks\results\ar_o2_simple\outputs\visualizations\statistics\species_charge_counts.svg`
- Ar/O2 simple oxygen plasma plot: `C:\Users\user\Desktop\react_gen-main\benchmarks\results\ar_o2_simple\outputs\visualizations\statistics\species_class_counts.svg`
- Ar/O2 simple oxygen plasma plot: `C:\Users\user\Desktop\react_gen-main\benchmarks\results\ar_o2_simple\outputs\visualizations\statistics\species_depth_counts.svg`
- Ar/CF4 fluorocarbon plasma report: `C:\Users\user\Desktop\react_gen-main\benchmarks\results\ar_cf4_fluorocarbon\benchmark_report.yaml`
- Ar/CF4 fluorocarbon plasma metrics: `C:\Users\user\Desktop\react_gen-main\benchmarks\results\ar_cf4_fluorocarbon\benchmark_metrics.yaml`
- Ar/CF4 fluorocarbon plasma missing plan: `C:\Users\user\Desktop\react_gen-main\benchmarks\results\ar_cf4_fluorocarbon\work\missing_plan.yaml`
- Ar/CF4 fluorocarbon plasma source profile: `C:\Users\user\Desktop\react_gen-main\benchmarks\fixtures\ar_cf4_fluorocarbon\source_profile.yaml`
- Ar/CF4 fluorocarbon plasma external solver config: `C:\Users\user\Desktop\react_gen-main\benchmarks\external_solvers.example.yaml`
- Ar/CF4 fluorocarbon plasma plot: `C:\Users\user\Desktop\react_gen-main\benchmarks\results\ar_cf4_fluorocarbon\outputs\visualizations\network\reaction_network.png`
- Ar/CF4 fluorocarbon plasma plot: `C:\Users\user\Desktop\react_gen-main\benchmarks\results\ar_cf4_fluorocarbon\outputs\visualizations\network\reaction_network.svg`
- Ar/CF4 fluorocarbon plasma plot: `C:\Users\user\Desktop\react_gen-main\benchmarks\results\ar_cf4_fluorocarbon\outputs\visualizations\network\species_lineage.png`
- Ar/CF4 fluorocarbon plasma plot: `C:\Users\user\Desktop\react_gen-main\benchmarks\results\ar_cf4_fluorocarbon\outputs\visualizations\network\species_lineage.svg`
- Ar/CF4 fluorocarbon plasma plot: `C:\Users\user\Desktop\react_gen-main\benchmarks\results\ar_cf4_fluorocarbon\outputs\visualizations\statistics\coverage_status_counts.svg`
- Ar/CF4 fluorocarbon plasma plot: `C:\Users\user\Desktop\react_gen-main\benchmarks\results\ar_cf4_fluorocarbon\outputs\visualizations\statistics\dnt_readiness_counts.svg`
- Ar/CF4 fluorocarbon plasma plot: `C:\Users\user\Desktop\react_gen-main\benchmarks\results\ar_cf4_fluorocarbon\outputs\visualizations\statistics\missing_data_counts.svg`
- Ar/CF4 fluorocarbon plasma plot: `C:\Users\user\Desktop\react_gen-main\benchmarks\results\ar_cf4_fluorocarbon\outputs\visualizations\statistics\reaction_depth_by_family.svg`
- Ar/CF4 fluorocarbon plasma plot: `C:\Users\user\Desktop\react_gen-main\benchmarks\results\ar_cf4_fluorocarbon\outputs\visualizations\statistics\reaction_family_counts.svg`
- Ar/CF4 fluorocarbon plasma plot: `C:\Users\user\Desktop\react_gen-main\benchmarks\results\ar_cf4_fluorocarbon\outputs\visualizations\statistics\reaction_type_counts.svg`
- Ar/CF4 fluorocarbon plasma plot: `C:\Users\user\Desktop\react_gen-main\benchmarks\results\ar_cf4_fluorocarbon\outputs\visualizations\statistics\species_charge_counts.svg`
- Ar/CF4 fluorocarbon plasma plot: `C:\Users\user\Desktop\react_gen-main\benchmarks\results\ar_cf4_fluorocarbon\outputs\visualizations\statistics\species_class_counts.svg`
- Ar/CF4 fluorocarbon plasma plot: `C:\Users\user\Desktop\react_gen-main\benchmarks\results\ar_cf4_fluorocarbon\outputs\visualizations\statistics\species_depth_counts.svg`
- Ar/SF6/O2 electronegative plasma report: `C:\Users\user\Desktop\react_gen-main\benchmarks\results\sf6_o2_electronegative\benchmark_report.yaml`
- Ar/SF6/O2 electronegative plasma metrics: `C:\Users\user\Desktop\react_gen-main\benchmarks\results\sf6_o2_electronegative\benchmark_metrics.yaml`
- Ar/SF6/O2 electronegative plasma missing plan: `C:\Users\user\Desktop\react_gen-main\benchmarks\results\sf6_o2_electronegative\work\missing_plan.yaml`
- Ar/SF6/O2 electronegative plasma source profile: `C:\Users\user\Desktop\react_gen-main\benchmarks\fixtures\sf6_o2_electronegative\source_profile.yaml`
- Ar/SF6/O2 electronegative plasma external solver config: `C:\Users\user\Desktop\react_gen-main\benchmarks\external_solvers.example.yaml`
- Ar/SF6/O2 electronegative plasma plot: `C:\Users\user\Desktop\react_gen-main\benchmarks\results\sf6_o2_electronegative\outputs\visualizations\network\reaction_network.png`
- Ar/SF6/O2 electronegative plasma plot: `C:\Users\user\Desktop\react_gen-main\benchmarks\results\sf6_o2_electronegative\outputs\visualizations\network\reaction_network.svg`
- Ar/SF6/O2 electronegative plasma plot: `C:\Users\user\Desktop\react_gen-main\benchmarks\results\sf6_o2_electronegative\outputs\visualizations\network\species_lineage.png`
- Ar/SF6/O2 electronegative plasma plot: `C:\Users\user\Desktop\react_gen-main\benchmarks\results\sf6_o2_electronegative\outputs\visualizations\network\species_lineage.svg`
- Ar/SF6/O2 electronegative plasma plot: `C:\Users\user\Desktop\react_gen-main\benchmarks\results\sf6_o2_electronegative\outputs\visualizations\statistics\coverage_status_counts.svg`
- Ar/SF6/O2 electronegative plasma plot: `C:\Users\user\Desktop\react_gen-main\benchmarks\results\sf6_o2_electronegative\outputs\visualizations\statistics\dnt_readiness_counts.svg`
- Ar/SF6/O2 electronegative plasma plot: `C:\Users\user\Desktop\react_gen-main\benchmarks\results\sf6_o2_electronegative\outputs\visualizations\statistics\missing_data_counts.svg`
- Ar/SF6/O2 electronegative plasma plot: `C:\Users\user\Desktop\react_gen-main\benchmarks\results\sf6_o2_electronegative\outputs\visualizations\statistics\reaction_depth_by_family.svg`
- Ar/SF6/O2 electronegative plasma plot: `C:\Users\user\Desktop\react_gen-main\benchmarks\results\sf6_o2_electronegative\outputs\visualizations\statistics\reaction_family_counts.svg`
- Ar/SF6/O2 electronegative plasma plot: `C:\Users\user\Desktop\react_gen-main\benchmarks\results\sf6_o2_electronegative\outputs\visualizations\statistics\reaction_type_counts.svg`
- Ar/SF6/O2 electronegative plasma plot: `C:\Users\user\Desktop\react_gen-main\benchmarks\results\sf6_o2_electronegative\outputs\visualizations\statistics\species_charge_counts.svg`
- Ar/SF6/O2 electronegative plasma plot: `C:\Users\user\Desktop\react_gen-main\benchmarks\results\sf6_o2_electronegative\outputs\visualizations\statistics\species_class_counts.svg`
- Ar/SF6/O2 electronegative plasma plot: `C:\Users\user\Desktop\react_gen-main\benchmarks\results\sf6_o2_electronegative\outputs\visualizations\statistics\species_depth_counts.svg`

