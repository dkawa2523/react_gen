# plasma-reactgen 1.0.0

中性ガスと明示供給から、電子・イオン・中性粒子の気相衝突候補を生成し、指定条件で辿れる経路を調べるツールです。弾性散乱を含むP0・P1を対象とします。反応式、判定した必要条件、使用した根拠と未確定理由を一つの結果に保存します。

## はじめる

Python 3.11以上を使用します。ソース配布物（sdist）には `registry/`、出典とnotice、入力例、取得先台帳、文書を収録します。wheelをインストールする場合は `python -m pip install plasma_reactgen-1.0.0-py3-none-any.whl` を実行し、展開したsdistのRegistryを `--evidence PATH` で指定します。[収録データと配布条件](docs/source_license_policy.md)

展開したsdistまたはリポジトリから起動する例です。

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\python.exe -m reactgen.cli analyze --input cases/ar/case.yaml --evidence registry --out result
.\.venv\Scripts\python.exe -m reactgen.cli view result --kind pathway --target Ar+@ground
```

`result/reactions.csv` に反応候補が、`result/judgments/energy.csv` に衝突エネルギー判定が入ります。経路図はコマンドが表示したPNGを開きます。ガスと供給だけを指定して候補を調べる場合は `rgen analyze Ar --supply e --out result` も使えます。以降の `rgen` は、仮想環境を有効にするか `.\.venv\Scripts\rgen.exe` に置き換えて実行します。

Windowsの実行制御で `rgen.exe` または `acquire.exe` を起動できない場合は、同じ仮想環境の `python -m reactgen.cli` または `python -m acquire.cli` を使います。

同梱例は供給から1段目までの候補を保存します。深さ上限で終了コード1が返っても、保存された結果は続けて表示できます。混合ガスの例では、電子衝突によるCF₃の生成候補と判定を確認できます。

```powershell
rgen analyze --input cases/ar_cf4/case.yaml --evidence registry --out cf4_result
rgen view cf4_result --kind energy --process dissociation
rgen view cf4_result --kind pathway --target CF3@ground
```

## 入力

最小入力は中性基底ガスのリスト `gases` です。電子を外部から供給する場合は `supplies: [e]` または `--supply e` を指定します。系内で生成する電子を使う経路は、その生成反応の支持も必要とします。

| 指定したい内容 | 入力 | 作用する範囲 |
|---|---|---|
| 系に供給する粒子 | `gases` と `supplies` | 候補生成の開始粒子と経路の供給。電子、イオン、励起状態は `supplies` |
| 個別に調べる反応式 | `reactions` | 自動生成の有無にかかわらず、指定した式を同じ判定と経路照会へ追加 |
| 読み込む資料 | `--evidence PATH` | Registryディレクトリ、スナップショット、overlay。複数指定可。省略時は組込みの候補生成と物理判定で調査 |
| 判定・計算に使う物理条件 | `conditions` | 指定した衝突エネルギー、温度等を、その量・条件を必要とする命題や数値評価に適用 |
| 優先・限定する出典 | `data_selection` | 量ごと、または対象と量ごとに適格な記録を選択。記録の資格や適用条件は引き続き評価 |
| 候補を探索する範囲 | `limits` | 探索の打切り・機械生成の範囲。部分結果にも打切り理由を保存 |

同梱の `cases/ar/case.yaml` は、供給した電子と基底Arの衝突を重心系17 eVで調べる例です。自分のYAMLは `rgen analyze --input input.yaml --evidence registry --out result` で読み込めます。

```yaml
gases: [Ar]
supplies: [e]
conditions:
  collision_energy_eV: 17
  collision_energy_frame: com
  projectile_state: e
  target_state: Ar
limits:
  max_atoms: 1
  max_depth: 1
```

- `collision_energy_eV` は単一の衝突エネルギーです。`com` は重心系を表します。衝突相手を指定すると、その指定に合う枝だけに適用します。`lab` からの換算には入射粒子、標的、`target_at_rest: true` と対応する質量を使います。`electron_energy_eV` と `ion_energy_eV` を換算に使う場合、入射粒子はそれぞれ電子とイオンです。温度や平均エネルギーを衝突エネルギー上限として流用しません。
- `structures: {C2H4: 'C=C'}` で明示SMILESを結び付けられます。構造演算は `python -m pip install -e ".[structure]"` で利用できます。供給・明示反応のSMILESは元素と電荷を照合し、判明した矛盾は入力エラーになります。RDKitを利用できない場合は明示構造を検証未確定として保存し、可能な組成探索を続けます。衝突相手が一意に決まらない場合は完全な状態IDを指定します。
- `limits` は有限探索の上限です。既定値は深さ12、状態300、反応10000、試行100000、離脱原子数2、機械生成の絶対電荷1です。`max_atoms` は既定で最大入力粒子の原子数の2倍です。状態数の上限に達しても、登録済みの状態で閉じる候補の探索は他の上限まで続けます。採用した候補の端点差には、資料で同定した基底参照も使えます。`surfaces` は既存資料の照合範囲を指定します。
- 混合ガスで未解像の粒子から仮説が増え続ける場合は、`limits: {expand_unresolved_states: false}` を指定できます。機械探索の入口を解像済み状態と明示供給に絞ります。生成済みの組成仮説や集約準位は保存し、それらを反応物とする資料由来・明示指定の式も探索できます。既定の `true` では、未解像の粒子も機械探索の入口に含めます。
- 数値モデルが参照する条件には `gas_temperature_K`、`electron_temperature_eV`、`ion_temperature_K`、`surface_temperature_K`、`electron_energy_eV`、`ion_energy_eV`、`reduced_field_Td` があります。必要な条件は個別の結果や `rgen needs result --detail` から確認できます。出典の優先・限定に使える識別子は `rgen records` で確認できます。[数値の採用要求](docs/output_reference.md#数値の採用要求)

### 調べる反応式を追加する

分析したい式が決まっている場合は、入力YAMLに `reactions` を追加します。下の例は同梱Ar入力へ追記できます。`process` には `elastic`、`ionization`、`charge_exchange`、`penning_ionization` などの過程名を指定します。判定の範囲は[反応別対応表](docs/reaction_judgment_matrix.md)を参照してください。

```yaml
reactions:
  - equation: 'e + Ar -> Ar+ + 2 e'
    process: ionization
  - equation: 'e + Ar+ -> Ar^2+ + 2 e'
    process: ionization
```

書式は ` -> `、粒子の区切りは ` + `、量論係数は `2 e` のように書きます。第三体 `M` は両辺に書きます。式中の粒子が明示供給の一つに対応すればその状態を使います。異性体などで候補が複数あれば `states.csv` 等で確認した完全な状態IDを指定します。

自動生成・資料と同じ状態、量論、過程の反応は一つにまとまります。明示式の反応物が探索で揃い、保存則に矛盾がなければ、その生成物から後続候補も探索します。探索が打ち切られた式や未到達の式も個別に判定します。経路は `gases` と `supplies` から始まり、他の候補と同様に全反応物の到達を求めます。文献による支持は読み込んだ資料から判定します。

上の明示式を追加し、同梱例の `conditions` と `limits` を下記に置き換えると、基底ArとAr⁺への電子衝突を一度の解析で比較できます。各組は実際の二粒子の状態に対応します。記載外の組はエネルギー判定の適用外として保存します。同じ組で別のエネルギーを比較する場合は別の入力として解析します。

```yaml
conditions:
  collision_pairs:
    - {projectile_state: e, target_state: Ar, collision_energy_eV: 17, collision_energy_frame: com}
    - {projectile_state: e, target_state: Ar+, collision_energy_eV: 28, collision_energy_frame: com}
limits: {max_atoms: 1, max_depth: 2}
```

上の明示式と条件で解析し、`rgen view result --kind network --checked --target 'Ar^2+@ground'` を実行すると、二段分の判定理由を経路から辿れます。
指定した衝突対の状態が保存候補に見つからない場合は、端末の概要とネットワークHTMLに表示します。

原子・結合の対応を必要とする過程は、式だけでは変換の整合が未確定になる場合があります。安定化を指定する場合は `stabilization` に宣言を記載します。宣言したエネルギー交換を扱うモデルが必要な場合、その不足は衝突エネルギー判定に残ります。

## 結果と経路

`analyze` は `result.yaml` に正規結果を保存し、同じディレクトリに一覧と判定別の表を出力します。探索が部分的に終わる場合は、得られた結果を保存して終了コード1を返します。形式・入力エラーは2です。

| 開く場所 | 確認できること |
|---|---|
| `reactions.csv` | 反応式、衝突区分、過程、安定化、主要判定、反応ID |
| `states.csv` | 状態の相、準位の区分・解像度、構造、経路照会に使う状態ID |
| `judgments/conservation.csv`、`consistency.csv` | 元素・電荷・核種の収支、宣言した過程の式形や対応を各表で確認 |
| `judgments/energy.csv` | 反応に照合した衝突対・入射値と座標系、重心系エネルギー、端点差、余裕、未確定理由 |
| `judgments/reaction_evidence.csv` | チャネルを支持する資料と、保存された出典の閾値。入射条件での端点収支は `energy.csv` |
| `judgments/thermochemistry.csv`、`kinetics.csv` | 熱化学値と参照条件、係数の利用結果を各表で確認 |
| `judgments/state-*.csv` | 個々の状態について保存された判定 |
| `graphs/`、`selection/` | `view` で指定した図、または絞り込んだ表を作成したときに使用 |

表は反応ID・状態IDで対応します。`--family` と `--process` は完全一致です。`--require` を繰り返すと、指定した保存判定をすべて満たす反応だけを抽出できます。未知や適用外を含む全結果は元の表から確認できます。物理条件を変える場合は入力を編集して再解析します。

```powershell
rgen view result --kind csv --family electron --process ionization --require conservation=pass --require consistency=pass --require energy=pass
rgen view result --kind csv --judgment energy --verdict unknown
rgen records result --target rxn_60cb094f8f47 --quantity delta_e_eV
```

Arの同梱例では、1つ目のコマンドが `selection/reactions.filtered.csv` に電離候補を抽出します。2つ目は `selection/energy.filtered.csv` にエネルギー判定が未確定の候補と理由を出します。`rxn_60cb094f8f47` は基底Arの電離の行にある `id` です。`records` は、対象に保存された記録と計算に使用した出典を表示します。

### 図で調べる

| 目的 | コマンド | 図の読み方 |
|---|---|---|
| 各枝のエネルギー余裕を比較 | `rgen view result --kind energy` | 衝突対ごとのSVGで、重心系の余裕をゼロからの距離で比較。余裕を算出できた枝が図に入り、未確定理由はエネルギー表に残る |
| 一つの判定の内訳を比較 | `rgen view result --kind judgment --judgment energy` | 一つの判定を一枚のSVGにし、衝突区分ごとの件数と割合を表示 |
| 一反応の参加状態を確認 | `rgen view result --kind reaction --reaction rxn_60cb094f8f47` | 反応物から生成物への方向と量論係数をSVGで表示。弾性散乱も指定できる |
| 対象種へ至る経路を確認 | `rgen view result --kind pathway --target Ar+@ground` | 全反応物・生成物と量論を矢印で表示。後続反応を支える生成物だけを次の反応へ接続 |
| 反応を検索して詳細を辿る | `rgen view result --kind network` | 任意のHTML。過程・適用した衝突入力・判定で反応一覧を絞れる |

図は既定で `graphs/` に保存されます。`--out DIR` で保存先を指定できます。エネルギー余裕が正でも、過程固有の出口条件や発生を支持する証拠は別に確認します。経路図では同じ反応段の供給電子を一つにまとめ、その段で終わる出射電子も一つにまとめます。後段を支える電子は保存された支持関係でつなぎます。矢印の数字は各反応の量論係数です。行列PNGは、各反応列への各状態の参加と役割を概観できます。

経路は明示供給からのAND到達性です。明示された全反応物に支持が必要です。`candidate` は保存則に反する枝を外し、`conditioned` はさらに宣言した過程の反証と、指定条件でのエネルギー収支の反証を外します。未確定や適用外の枝は理由付きで残ります。たとえばAr例のエネルギーを0 eVに変えると直接電離の枝は外れますが、指定した衝突対の条件が及ばない別経路は候補に残ることがあります。弾性散乱は反応一覧・近傍図から確認できます。正味生成がある反応だけが生成元になります。

```powershell
rgen needs result --data-missing --detail
rgen view result --kind pathway --checked --target Ar+@ground
rgen view result --kind matrix
```

`--checked` は保存則、過程、衝突エネルギーの必要条件が成立した枝を対象とし、未同定の参加状態を含む枝と供給を除きます。明示SMILESには保存したグラフ検証、資料内の構造IDには対象状態と厳密に一致した審査済みの証拠を使います。状態の存在や束縛に反証がある枝と供給も除き、枝に残る参加状態の未確定な証拠は判定への参照を付けます。`--seed` は照会時の供給を置き換えます。`--target STATE --via REACTION_ID` は、対象種を生成する指定枝と、その枝を支える供給・前段の経路を表示します。反応の発生、分岐、速度、支配経路の判断には個別の根拠と条件が要ります。[経路の公開仕様](docs/output_reference.md#形式7以降の計算と経路)

[Arの段階電離](docs/reaction_judgment_matrix.md#arの段階電離を通常入力で辿る)、[H＋D₂からHDへの交換](docs/reaction_judgment_matrix.md#明示同位体からhdへの候補経路を調べる)、[CF₄/O₂の酸化経路](docs/reaction_judgment_matrix.md#cf₄o₂の酸化経路を調べる)には、根拠の入力から経路出力までの実行例があります。

### DNT向けのイオン・中性衝突入力

`rgen view result --kind dnt` は `dnt/` に粒子対一覧 `dnt_pairs.csv`、反応チャネル一覧 `dnt_channels.csv`、詳しい物性宣言と計算入力を持つ `dnt_inputs.yaml` を出力します。CSVは表計算ソフトで開き、粒子対、過程、判定で絞り込めます。イオンが探索範囲に入るよう供給または探索深さを指定します。[DNT向け出力の仕様](docs/output_reference.md#dnt向けの出力)・[ベンチマークと出力例](docs/reaction_judgment_matrix.md#ベンチマークとdnt向け出力)

## 証拠を追加する

`--evidence registry --evidence overlay.yaml` は、同梱Registryと手元の追加資料を同時に読み込みます。参照したパスが存在しない場合は入力エラーになります。元の量と係数としての利用可否を調べるには、`rgen records result --target ID --quantity cross_section --detail` を使います。

例として、Hを含む入力の断面積でIAEA CollisionDBの記録を優先するには、以下をYAMLに追加します。`prefer` は適格な代替候補を許し、`only` は該当する出典だけに限定します。記録を一件に固定する場合は `data_selection.targets` で対象IDと量を指定します。[採用要求の入力欄](docs/output_reference.md#数値の採用要求)

```yaml
data_selection:
  quantities:
    cross_section:
      mode: prefer
      providers: [iaea_collisiondb]
```

`acquire` で取得・変換した記録を `rgen ingest` で既存候補へ照合します。overlayを `--evidence` で読み直して結果を調べ、Registryへ反映する場合は `rgen adopt` を明示的に実行します。照合、審査、採用は別の操作です。複数の出典は独立した記録として保持します。[取得・照合・採用](docs/data_sources.md)・[記録形式と語彙](docs/registry_data_guide.md)

## 既存データと開発

- 保存済みschema 5の結果は、各版の判定と補助表の形式を保持して読みます。旧版の表の扱い、schema 4からの移行手順、旧overlayと `preferred` は[互換と移行](docs/output_reference.md#保存の整合と移行)を参照してください。
- 実装の変更は[開発指針](AGENTS.md)に従い、[品質確認](docs/quality.md)の既存入口を使います。開発用依存は `python -m pip install -e ".[quality]"` で導入できます。

| 資料 | 参照する内容 |
|---|---|
| [現行設計](docs/core_design.md) | モジュール間の依存と処理・判定の責務 |
| [公開出力仕様](docs/output_reference.md) | 保存形式・量の採用・経路・互換 |
| [反応別レポート](docs/reaction_judgment_matrix.md) | P0・P1の過程・判定式、Registryの収録範囲、ベンチマーク、実行例、文献 |
| [取得・照合・採用](docs/data_sources.md) | 取得コマンドと物性の取得・算出 |
| [記録形式と語彙](docs/registry_data_guide.md) | Registry、スナップショット、overlayの入力形式 |
| [収録データと配布条件](docs/source_license_policy.md) | 出典、適用条件、notice、第三者資料 |
