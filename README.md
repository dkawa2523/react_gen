# plasma-reactgen

## 1. What this is

`react_gen` / `plasma-reactgen` は、低圧プラズマ反応機構を構築するための registry-driven reaction-network generator です。

入力ガスと local registry から、反応リスト、状態リスト、DNT task、coverage report、missing-data report、可視化用ファイルを生成します。通常の `reactgen generate` は外部 API やネットワークアクセスに依存しません。

## 2. What it does

- local registry の species / reaction pair / channel を読んで反応ネットワークを展開する。
- species 参照、電荷収支、元素収支などの基本チェックを行う。
- `network.reactions.*`、`network.states.*`、`dnt_tasks.yaml`、coverage、missing data を出力する。
- 生成済み output から統計図と Graphviz network 図を作る。
- 明示指定時に、solver-free の DNT+/DNT+DM pair-wise input YAML を出力する。
- 開発者向けに inferred candidate を `candidate_registry/` へ出力する。

## 3. What it does not do

- 電子衝突断面積、rate coefficient、DNT+/DNT+DM 断面積を数値計算しない。
- DNT solver や Boltzmann solver を内蔵しない。
- 通常の `generate` 中に外部 DB へアクセスしない。
- inferred candidate や imported data を curated registry へ自動保存しない。

## 4. Quick start

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e .
```

サンプルケース:

```powershell
reactgen generate cases/ar_cf4/input.yaml --registry registry --output cases/ar_cf4/outputs
reactgen visualize cases/ar_cf4/outputs --output cases/ar_cf4/visualizations
```

インストールせずに実行する場合:

```powershell
$env:PYTHONPATH = "src"
python -m plasma_reactgen.interface.cli --help
```

## 5. Main outputs

`reactgen generate` の主な出力:

- `network.reactions.yaml` / `network.reactions.csv`
- `network.states.yaml` / `network.states.csv`
- `dnt_tasks.yaml`
- `coverage_report.yaml`
- `missing_data.yaml` / `missing_data.csv`
- `summary.json`

DNT input export を有効にした場合の追加出力:

- `dnt_manifest.yaml`
- `dnt_inputs/<pair_id>.yaml`

`reactgen visualize` の主な出力:

- `statistics/*.svg`
- `network/reaction_network.dot`
- `network/reaction_network.svg` / `.png`
- `network/species_lineage.dot`
- `manifest.json`

## 6. User-facing commands

- `reactgen generate CASE --registry registry --output OUTPUT`: registry から標準 output を生成する。
- `reactgen visualize OUTPUT --output VIS_OUTPUT`: 生成済み output を可視化する。
- `reactgen export-dnt CASE --registry registry --output OUTPUT`: solver-free の `dnt_manifest.yaml` と `dnt_inputs/*.yaml` を生成する。

DNT input export の詳細は [docs/dnt_input_export.md](docs/dnt_input_export.md) を参照してください。

## 7. Developer-facing commands

- `reactgen dev-check --registry registry`: registry の読み取りと基本整合性を確認する。
- `reactgen dev-check --registry registry --strict`: より厳しく registry を確認する。
- `reactgen dev-index --registry registry`: registry index を更新する。
- `reactgen infer-candidates CASE --registry registry --output candidate_registry`: inferred candidate を確認用ディレクトリへ出力する。registry は自動変更しない。
- `reactgen template species SPECIES_ID`: species 登録テンプレートを表示する。
- `reactgen template electron-pair e TARGET`: electron reaction pair テンプレートを表示する。
- `reactgen template ion-pair ION NEUTRAL`: ion-neutral reaction pair テンプレートを表示する。

## 8. Registry concept

`registry/` は通常生成の local data source です。species、reaction pair、reaction channel、物性、DNT 関連情報、cross-section asset link、provenance を YAML と local assets として管理します。

外部 DB importer は、将来 LxCat などの public data を local registry/assets に変換する開発者向け補助です。placeholder は `tools/importers/` にあり、通常の `reactgen generate` からは呼び出されません。

Inference は default disabled です。明示的に `inference.enabled: true` と `include_inferred_reactions: true` を設定した場合だけ、最小限の inferred channel / in-memory species を generation に含められます。推論結果は `status: inferred` のままで、registry には自動保存しません。

## 9. Documentation links

- [Product architecture](docs/product_architecture.md)
- [DNT input export](docs/dnt_input_export.md)
- [Inference design](docs/inference_design.md)
- [Registry data guide](docs/registry_data_guide.md)
- [Visualization design](docs/visualization_design.md)

## 10. Tests

```powershell
python -m pytest
```

Windows 環境で `python` が違う interpreter を指す場合:

```powershell
.\.venv\Scripts\python.exe -m pytest
```
