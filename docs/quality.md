# 品質確認

依存関係と対応Pythonは `pyproject.toml`、実行内容は `tools/quality.py` を正とします。既存の仮想環境を使用し、無ければREADMEに従って作成します。

```powershell
.\.venv\Scripts\python.exe tools/quality.py quality-pr
```

この入口はRuff format/check、mypy、pytest、import-linterを実行します。すべて同じPython環境から起動し、import-linterも生成された実行fileを探さず、そのパッケージのCLI入口を使います。CIも同じ入口をPython 3.11で実行します。`quality-fast` はimport-linterを除く同じ確認で、pytest全体を含みます。

開発中に通常の入出力だけを短時間で確認する入口もあります。

```powershell
.\.venv\Scripts\python.exe tools/quality.py quality-smoke
```

`quality-smoke` は一時ディレクトリの最小入力を通常CLIで分析し、needs、CSV・network表示、
hash確認付き再読込みを通します。表示の生成で正規結果が変わらないことも確認します。
固定の候補件数、ガス固有の期待値、外部データ取得は使いません。出力は一時領域へ置き、失敗したコマンドの出力を表示します。
既存pytestに同じ境界の検証があるため、quality-prでこの軽量確認を重複実行しません。
`quality-nightly` はquality-prに加え、付属caseを現行の`analyze --input ... --evidence registry`で実行し、
`build/nightly`へ保存します。例の名前は通常処理の分岐に使いません。

変更の進め方は[AGENTS.md](../AGENTS.md#変更ごとの進め方)を使います。PR・作業報告には、
変わる結論とその所有処理、検証の根拠、整理した旧内容と残る制約を短く記します。
PRを作らない作業も同じ観点で差分をレビューします。入力・出力の検証が通っただけで、
科学的妥当性や責務の明確さ、不要処理の不存在まで自動確認したとは扱いません。

テストは変更した命題・境界に合わせ、次の中から必要なものを選びます。全変更へ全項目を課しません。

| 変更 | 確認の根拠 |
|---|---|
| 入力・対象・証拠 | 正常例と誤同定・不正値・不足の違い。関連する結論だけが変わり、無関係な資料や入力順で意味が変わらないこと |
| 科学判断・計算 | 一次資料、単位・参照条件・保存則・既知の極限。値があることと対象・現象の成立を区別する例 |
| 保存・表示・外部形式 | 原宣言とhashの往復、同じ正規結果からの表示、変更に関係する失敗時の整合。新旧の必要な外部形式を保持すること |
| 置換・整理 | 旧名・呼出し元・文書・設定・専用テストを検索した差分。残す互換経路の利用先・撤去条件と、消した経路の代わりになる通常利用 |

新しいテスト・診断・契約を加える前に、独立した失敗を見つける役割が既存の確認で足りないか見ます。
同じ実装を写すassertや、特定gasの件数、診断の存在を検査するだけのテストは増やしません。
一つの境界の複数の入力は必要に応じてparameterize等でまとめ、置換した実装だけを守るテストは整理します。
テスト数・coverage・チェック欄の数を改善の指標にしません。新しい懸念がなければ同じ検証を繰り返しません。
依存方向とcoreのoffline性は`.importlinter`が検査しますが、意味的な責務と科学的な飛躍は差分レビューで確認します。

保存結果の読込み時間は `tools/benchmark_result_io.py <result.yamlのパス> --compare-python-parser` で、化学計算を再実行せず同じ正規検証を含めて測れます。時間は環境に依存するため、品質チェックの合否条件には使いません。

配布前は品質チェックに加え、現在のソースからwheelとsdistを新しい出力先へ作ります。
ビルド用環境へ`build`を入れ、`python -m build --outdir PATH`を実行します。
sdistの収録対象は`MANIFEST.in`、wheelの実行データは`pyproject.toml`で定義します。
`build/`・`dist/`・`work/`や外部原本・取得snapshotはソース配布へ含めません。

新しい仮想環境へwheelを通常インストールし、リポジトリ外から`rgen analyze Ar --out RESULT`、
`rgen needs RESULT`、`rgen view RESULT --kind network --out VIEW`と`python -m pip check`を確認します。
Registry・台帳を使う確認は、展開したsdistの`registry`と`external_data/source_catalog.yaml`を
絶対パスで指定します。sdistからwheelを再ビルドできることと、文書・fixture・検証工具の収録も確認します。
実行可能な成果物が作れたことと、公開版の確定・同梱データの再配布条件が整ったことは
別の確認です。古い`dist/`の成果物を現在のソースの検証結果として扱いません。
