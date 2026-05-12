# plasma-reactgen

`plasma-reactgen` は、登録済みの化学種データと衝突反応チャネルから、低圧プラズマ反応ネットワークを自動生成する Python ツールです。

主に以下を行います。

- 入力ガスから frontier 展開により反応ネットワークを生成
- 電子衝突反応とイオン中性衝突反応のリストを生成
- species 参照、電荷収支、元素収支の基本検証
- 状態種リスト、DNT+/DNT+DM 計算準備タスク、coverage report、missing-data report の出力
- 生成済み output から統計グラフと Graphviz ネットワーク図を作成

本コードの中核は、断面積・速度係数・DNT+ 断面積を数値計算するものではありません。反応チャネルと状態種の登録データをもとに、反応機構の構築、検証、欠損データ確認、可視化を再現可能にするための基盤です。

## 1. 必要環境

| 項目 | 必須/任意 | 内容 |
|---|---|---|
| Python | 必須 | Python 3.11 以上 |
| pip | 必須 | Python パッケージのインストールに使用 |
| PyYAML | 必須 | YAML 入出力に使用。`pip install -e .` で入ります |
| pytest | 任意 | テスト実行に使用 |
| Graphviz | 任意 | `reaction_network.png/svg` などの画像レンダリングに使用 |

Graphviz がない場合でも、統計グラフ SVG と Graphviz DOT ファイルは生成されます。ただし、`reaction_network.png` や `species_lineage.png` の自動レンダリングには Graphviz の `dot` コマンドが必要です。

## 2. 環境構築

### Windows PowerShell

リポジトリのルートで実行します。

```powershell
cd C:\Users\user\Desktop\DNT\plasma-reaction-generator

py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1

python -m pip install --upgrade pip
python -m pip install -e .
python -m pip install pytest
```

`reactgen` コマンドが使えるか確認します。

```powershell
reactgen --help
```

### macOS / Linux

```bash
cd /path/to/plasma-reaction-generator

python3.11 -m venv .venv
source .venv/bin/activate

python -m pip install --upgrade pip
python -m pip install -e .
python -m pip install pytest
```

確認:

```bash
reactgen --help
```

## 3. インストールせずに実行する方法

開発中に editable install せず実行する場合は、`PYTHONPATH=src` を指定します。

Windows PowerShell:

```powershell
$env:PYTHONPATH = "src"
python -m plasma_reactgen.interface.cli --help
```

macOS / Linux:

```bash
PYTHONPATH=src python -m plasma_reactgen.interface.cli --help
```

以降の説明では、環境構築済みとして `reactgen` コマンドを使います。インストールしない場合は、`reactgen` を `python -m plasma_reactgen.interface.cli` に置き換えてください。

## 4. Ar/CF4 サンプルケースの実行

入力ファイルは `cases/ar_cf4/input.yaml` です。登録データは `registry/` 以下にあります。

```powershell
reactgen generate cases/ar_cf4/input.yaml --registry registry --output cases/ar_cf4/outputs
```

正常に実行されると、標準出力に以下のような概要が表示されます。

```text
Generated outputs: cases\ar_cf4\outputs
  species: 12
  reactions: 42
  dnt_tasks: 12
  missing_data_items: 19
```

## 5. 出力ファイル

`cases/ar_cf4/outputs/` に以下が生成されます。

| ファイル | 内容 |
|---|---|
| `network.reactions.yaml` | 生成された反応ネットワーク |
| `network.reactions.csv` | 反応ネットワークの CSV 版 |
| `network.states.yaml` | 生成された状態種リスト |
| `network.states.csv` | 状態種リストの CSV 版 |
| `dnt_tasks.yaml` | DNT+/DNT+DM 計算準備タスク |
| `coverage_report.yaml` | 登録済み pair / 未登録 pair の coverage |
| `missing_data.yaml` | 不足している物性値・断面積 table などの一覧 |
| `missing_data.csv` | missing data の CSV 版 |
| `summary.json` | species 数、reaction 数などの概要 |

結果を手早く確認する場合は、まず `summary.json`、次に `network.reactions.csv`、`network.states.csv`、`coverage_report.yaml` を見るのがおすすめです。

## 6. 可視化の実行

生成済み output から統計グラフと反応ネットワーク図を作成します。

```powershell
reactgen visualize cases/ar_cf4/outputs --output cases/ar_cf4/visualizations
```

生成と可視化を一度に行うこともできます。

```powershell
reactgen generate cases/ar_cf4/input.yaml `
  --registry registry `
  --output cases/ar_cf4/outputs `
  --visualize `
  --visualization-output cases/ar_cf4/visualizations
```

macOS / Linux では行継続記号を `\` にしてください。

```bash
reactgen generate cases/ar_cf4/input.yaml \
  --registry registry \
  --output cases/ar_cf4/outputs \
  --visualize \
  --visualization-output cases/ar_cf4/visualizations
```

## 7. 可視化出力

`cases/ar_cf4/visualizations/` に以下が生成されます。

| パス | 内容 |
|---|---|
| `statistics/*.svg` | reaction family、reaction type、coverage、missing data などの統計グラフ |
| `network/reaction_network.dot` | 反応ネットワークの Graphviz DOT ソース |
| `network/reaction_network.svg` | 反応ネットワーク図。Graphviz がある場合に生成 |
| `network/reaction_network.png` | 反応ネットワーク図 PNG。Graphviz がある場合に生成 |
| `network/species_lineage.dot` | species 生成経路の Graphviz DOT ソース |
| `network/species_lineage.svg` | species lineage 図。Graphviz がある場合に生成 |
| `network/species_lineage.png` | species lineage 図 PNG。Graphviz がある場合に生成 |
| `manifest.json` | 生成された可視化ファイルの一覧 |

Graphviz の描画形式を指定する場合:

```powershell
reactgen visualize cases/ar_cf4/outputs `
  --output cases/ar_cf4/visualizations `
  --formats svg,png,pdf
```

大きいネットワークで描画対象を制御したい場合:

```powershell
reactgen visualize cases/ar_cf4/outputs `
  --output cases/ar_cf4/visualizations `
  --max-reactions 100
```

すべての反応を描画したい場合:

```powershell
reactgen visualize cases/ar_cf4/outputs --max-reactions -1
```

## 8. 登録データの確認

登録データの読み取りと基本参照を確認します。

```powershell
reactgen dev-check --registry registry
```

より厳密に確認する場合:

```powershell
reactgen dev-check --registry registry --strict
```

registry index を更新する場合:

```powershell
reactgen dev-index --registry registry
```

## 9. 登録テンプレートの作成

新しい species や reaction pair を登録するための YAML テンプレートを標準出力に表示できます。

species:

```powershell
reactgen template species CF3+
```

電子衝突 pair:

```powershell
reactgen template electron-pair e CF4
```

イオン中性衝突 pair:

```powershell
reactgen template ion-pair Ar+ CF4
```

表示されたテンプレートをもとに、`registry/species/` または `registry/reactions/` 以下へ YAML を追加します。

## 10. テスト

開発環境でテストを実行します。

```powershell
python -m pytest
```

主なテスト対象:

- Ar/CF4 サンプルケースの smoke test
- 反応式と元素・電荷収支の検証
- pair selection の挙動
- registry validation
- 可視化ファイル生成

## 11. ディレクトリ構成

```text
plasma-reaction-generator/
├─ cases/
│  └─ ar_cf4/
│     ├─ input.yaml
│     ├─ outputs/
│     └─ visualizations/
├─ registry/
│  ├─ species/
│  ├─ reactions/
│  ├─ rules/
│  ├─ sources/
│  └─ data_notes/
├─ src/plasma_reactgen/
│  ├─ application/
│  ├─ domain/
│  ├─ infrastructure/
│  ├─ interface/
│  ├─ validation/
│  └─ visualization/
├─ tests/
└─ docs/
```

| ディレクトリ | 役割 |
|---|---|
| `cases/` | 実行ケース。現在は Ar/CF4 ケースを同梱 |
| `registry/species/` | 化学種の登録 YAML |
| `registry/reactions/` | 電子衝突・イオン中性衝突 reaction pair の登録 YAML |
| `registry/rules/` | 反応タイプ、role、必要物性などのルール |
| `src/plasma_reactgen/application/` | ネットワーク生成、状態種生成、DNT task 生成 |
| `src/plasma_reactgen/domain/` | 化学種、反応、式、識別子などのドメインモデル |
| `src/plasma_reactgen/infrastructure/` | YAML/CSV 入出力、ファイル registry |
| `src/plasma_reactgen/interface/` | CLI |
| `src/plasma_reactgen/visualization/` | 統計グラフと Graphviz 図の生成 |
| `docs/` | 技術報告書、可視化設計メモ |

## 12. 注意点

- 現時点では、数値電子衝突断面積 table の import は未実装です。
- DNT+/DNT+DM 用の task は生成しますが、DNT+ 計算そのものはこのコード内では実行しません。
- missing-data report に出る警告の多くは、断面積 table や一部物性値が registry に未登録であることを示します。
- 反応ネットワーク図は読みやすさのため species graph として描画しており、厳密な hypergraph 表現ではありません。係数や完全な反応式は `network.reactions.yaml` または `network.reactions.csv` を確認してください。

## 13. 関連ドキュメント

- `docs/visualization_design.md`: 可視化設計の詳細
- `docs/plasma_reactgen_ar_cf4_technical_report.md`: Ar/CF4 技術報告書 Markdown
- `docs/plasma_reactgen_ar_cf4_technical_report.html`: 技術報告書 HTML
- `docs/plasma_reactgen_ar_cf4_technical_report.pdf`: 技術報告書 PDF
- `registry/README_ar_cf4_public_data.md`: Ar/CF4 登録データの出典整理
