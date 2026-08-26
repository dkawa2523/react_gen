# Quality gates

```powershell
python -m pip install -e ".[quality]"
python -m pytest -q
ruff check .
mypy
lint-imports --config .importlinter --no-cache
```

テストはprivate helperの実装固定ではなく、次の公開動作に集約します。

- generation: Registry非依存、frontier深さ、保存則、上限、決定性
- evidence/assessment: exact/ambiguous/no match、4値、単位・範囲・scope、数値能力
- policy/pipeline: 全候補保持、用途別選択、resolution、truncation、3出力
- CLI/acquire: 入力拒否、終了コード、canonical ingest、asset参照

件数や巨大baselineを品質指標にしません。`.importlinter`は一方向のcore依存と、
`reactgen`がnetwork/acquireへ依存しない境界を検証します。
