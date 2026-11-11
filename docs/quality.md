# 品質確認

依存関係と対応Pythonは `pyproject.toml`、実行内容は `tools/quality.py` を正とします。既存の仮想環境を使用し、無ければREADMEに従って作成します。

```powershell
.\.venv\Scripts\python.exe tools/quality.py quality-pr
```

この入口はRuff format/check、mypy、pytest、import-linterを実行します。CIもPython 3.11で同じ入口を使います。

開発中に通常の入出力だけを短時間で確認する入口もあります。

```powershell
.\.venv\Scripts\python.exe tools/quality.py quality-smoke
```

`quality-smoke` は一時ディレクトリで解析、`needs`、CSV・ネットワークの再生成、保存結果の再読込みを通します。
`quality-nightly` はquality-prに加え、付属caseを現行の`analyze --input ... --evidence registry`で実行し、
その実行で生成した正規結果とCSVを検証して `build/nightly` へ保存します。終了コード1は、エラー出力がなく、正規結果に探索未完了が記録され、CSVまで検証できた場合に受理します。

CIの通常ジョブは基本依存で動かし、定期ジョブでは `[structure,thermo]` を導入して実構造と任意の物性取得経路を検査します。任意依存を使うテストは実行前に依存の有無を確認し、処理の例外や取得結果の不一致はテストの失敗として扱います。

RDKitの実装を検証するときは、`from rdkit import Chem` が成功する環境で同じ品質チェックを実行します。Windowsの実行制御がネイティブDLLを拒否する場合、既存のWSL2上でもLinux版RDKitによる構造照合と保存・再読込みを確認できます。WSL2での検証結果はLinux版の動作範囲です。Windowsでの実行には、その環境のポリシーが許可する配布物が必要です。[RDKit公式の導入手順](https://www.rdkit.org/docs/Install.html)・[Windowsの実行制御イベント](https://learn.microsoft.com/en-us/windows/security/application-security/application-control/app-control-for-business/operations/event-id-explanations)

変更に応じた検証と差分レビューの進め方は[開発指針](../AGENTS.md#変更ごとの進め方)に置きます。

## 検証が守る範囲

| 確認 | 守るもの |
|---|---|
| 科学判定・計算のテスト | 保存則、単位、既知の極限、出典・条件の不一致で結果がどう変わるかを確認する。数値や反証を決める根拠は物理モデルと元資料に置く |
| 入出力のテスト | 通常の入口から、対象・結論・出典を保存、再読込み、表示で辿れることを確認する。失敗時の保全、参照切れ、既存形式は境界ごとに代表例を残す |
| 依存関係の契約 | 解析から表示・書込みへの依存、表示から解析・証拠読込みへの依存、通常処理から外部取得への依存を検出する。内部モジュールの順番は実際の責務に合わせて変えられる |
| 利用時の診断 | 科学判定が返した理由と必要作業を保存し、`needs` と集計はその情報を投影する。ファイル形式・参照の検証は保存境界で扱う |

異なる故障を検出する検査は分け、同じ検証節に同じ理由で失敗する入力や、内部メソッドの存在・説明文・候補件数だけを固定する検査は整理します。[判定と診断の責務](core_design.md#正規結果経路表示)・[公開結果の整合](output_reference.md#保存の整合と移行)

保存結果の読込み時間は `tools/benchmark_result_io.py <result.yamlのパス> --compare-python-parser` で、化学計算を再実行せず同じ正規検証を含めて測れます。時間は環境に依存するため、品質チェックの合否条件には使いません。

現行の同梱ケースとイオンを明示供給した補足ケースの実測条件・結果は[ベンチマークとDNT向け出力](reaction_judgment_matrix.md#ベンチマークとdnt向け出力)にまとめています。

## 配布物の確認

確定したソースから、品質検査と時間を分けて新しい出力先へwheelとsdistを作ります。`python -m build --outdir PATH` ではsdistを作り、その展開内容からwheelをビルドします。`MANIFEST.in` がsdist、`pyproject.toml` がwheelの収録を定義します。

- sdistでRegistry本体・数表・帰属とnotice、文書、入力例、取得先台帳、fixture、検証工具を確認します。作業結果や外部の取得原本は同梱対象外です。[出典・配布条件](source_license_policy.md)
- wheelを新しい仮想環境へインストールし、`python -m pip check` を実行します。リポジトリ外から、sdistを展開した `registry` を絶対パスで指定して `rgen check --registry PATH` と `rgen analyze Ar --supply e --evidence PATH --out RESULT` を実行します。続けて `rgen needs RESULT`、CSVの再生成、HTMLの表示を確認します。
- 確認したwheelとsdistのファイル名、SHA-256、ビルド元のコミットを記録します。
