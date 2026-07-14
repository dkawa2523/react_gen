# 技術レポート掲載図

このディレクトリには、`plasma_reactgen_technical_report.md`で参照するベンチマーク図を保存する。
GitHub上でレポートを開いた場合も結果を確認できるよう、評価時点のSVGを固定したものである。

元データは次のコマンドで再生成できる。

```powershell
python -m external_data_tools.run_semiconductor_benchmarks
```

各caseの可視化は次のコマンドで再生成する。

```powershell
python -m plasma_reactgen.interface.cli visualize benchmarks/results/<case>/outputs
```

再評価時は、生成された`benchmarks/results/`のSVG、`benchmark_metrics.yaml`、
`summary.yaml`を確認してから、このディレクトリの図を更新する。

| ファイル | 内容 |
|---|---|
| `benchmark_comparison.svg` | 3ケースのspecies数、反応数、不足データ数 |
| `benchmark_summary.yaml` | 3ケースの機械可読な集計 |
| `*_metrics.yaml` | 各caseの機械可読な評価指標 |
| `ar_o2_reaction_depth.svg` | Ar/O2の反応family別depth |
| `*_reaction_network.svg` | speciesをnodeとする反応ネットワーク |
| `*_species_lineage.svg` | 新規speciesの生成経路 |
| `*_reaction_equations.svg` | 反応式をnodeとする前段–後段反応経路 |
