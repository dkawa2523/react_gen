# plasma-reactgen 0.5

入力ガスの化学式から、低温プラズマで検討すべき状態・反応種・反応式候補を
Registryなしでも決定的に生成します。Registry、review済みoverlay、取得snapshotは
候補を作る条件ではなく、生成後に状態の実在性、熱化学、既知反応、断面積・速度係数を
照合する読み取り専用の証拠です。欠損は候補を消さず`unknown`として残します。

設計の詳細は[Core design](docs/core_design.md)、固定した改修方針と完了条件は
[Implementation plan](docs/reaction_state_generation_implementation_plan.md)を参照してください。
正式なYAML・CSV配置、状態記号、反応分類、列、判定値は
[出力形式仕様](docs/output_reference.md)にまとめています。

## 基本的な使い方

Caseには中性ground-state化学式だけを書きます。SMILES等の構造指定は要求しません。混合比`fraction`は
候補の存在を決めないため入力しません。

```yaml
name: ar_cf4
gases: [Ar, CF4]
conditions:
  gas_temperature_K: 350.0
  electron_temperature_eV: 4.0
limits:
  max_depth: 6
  max_species: 300
  max_reactions: 5000
```

```powershell
rgen generate cases/ar_cf4/case.yaml --out work/ar_cf4
rgen generate cases/ar_cf4/case.yaml --registry registry --policy review --out work/ar_cf4
rgen generate cases/ar_cf4/case.yaml --registry registry --policy review --csv --out work/ar_cf4
rgen plan cases/ar_cf4/case.yaml --registry registry
rgen check --registry registry
```

`generate`は次の3ファイルを正規bundleとして一括更新します。

- `states.yaml`: 全状態候補、formula scope、証拠、Consistency・State・Thermochemistry判定
- `reactions.yaml`: 全反応候補、5判定、数値dataset、数値利用能力
- `selected.yaml`: policyによるID選択、状態・反応の非選択理由、readiness

`--csv`を指定すると、目視・表計算用の一覧と判定別directoryも出力します。

- `states.csv`: 状態名、化学式、電荷、状態の意味、由来、判定、主要物性
- `reactions.csv`: 反応式、分かりやすい反応種別、family/process、5判定、反応熱、kinetics利用可否、選択結果
- `reactions_electron.csv / reactions_ion.csv / reactions_neutral.csv`: 上記反応表のfamily別view
- `reactions_surface.csv`: surface反応を中性気相反応へ混在させないための独立view

```text
assessments/
  composition.svg
  network.html
  network.png
  pathways.png
  statistics.csv
  statistics.svg
  consistency/
  state/
  thermochemistry/
  reaction_evidence/
  kinetics/
  screening/
    state_consistency/
    state_consistency_thermochemistry/
    state_consistency_thermochemistry_kinetics_or_reaction_evidence/
```

各判定directoryには次の表形式出力があります。

- `states.csv`: 状態へ適用するConsistency、State、Thermochemistryだけに出力
- `reactions.csv`: その判定を適用した反応とreaction type・verdict・理由
- `reactions_electron.csv / reactions_ion.csv / reactions_neutral.csv / reactions_surface.csv`:
  `reactions.csv`をfamilyで欠落なく分割した同一列構成のview
- `family_summary.csv`: 反応familyごとのverdict件数
- `summary.csv`: 状態数・反応数と`pass / fail / unknown / not_applicable`の件数
- `verdict_counts.svg`: 状態・反応の件数・比率と、その判定から直接言える要点
- `reaction_family.svg`: 共通count scaleによる反応family別の量とverdict構成

YAML・CSVの互換仕様は[出力形式仕様](docs/output_reference.md)を正とします。SVG、PNG、HTMLは
同じデータから作る補助表示であり、そのレイアウトは正式な出力形式に含めません。

3つの累積screening directoryにも、全反応の`reactions.csv`と同じfamily別4ファイルを出力します。
該当反応が0件の場合も、列見出しだけを保持します。

`assessments/statistics.svg`は5判定を順にpassした反応数を累積表示し、最大のreadiness
bottleneckと各判定単独のverdict構成を示します。`composition.svg`は状態の電荷・励起種別・解像度・寿命特性、
反応family・生成depthという候補構成だけを分離表示します。元の集計値は`statistics.csv`です。
`assessments/network.html`はcase全体で1ファイルだけのoffline network explorerです。全状態と全反応を
一度だけ内包し、5つの個別判定と3つの累積screeningをselectorで切り替えます。既定のComplete matrixは、
状態を行、反応を列とする化学量論incidence matrixです。各反応を必ず1列として表示し、反応物、生成物、
正味係数ゼロ参加を異なる色と形で示します。下段の5本のbandは各判定の4値を同じ反応列へ対応させます。
任意のmarkを選ぶと完全な反応hyperedgeへ移り、状態行または状態nodeを選ぶと状態近傍viewへ移ります。
状態近傍viewは`Δν = νproducts - νreactants`により正味生成・正味消費・正味係数ゼロ参加へ分け、各区分を
独立して7反応ずつpage表示します。正味係数ゼロは物理的に無変化とは限らず、transport、momentum、
charge carrierなどのsubroleを明示します。反応式・状態名・ID検索、family・verdict・depth絞込み、
100反応単位の一覧paginationも同じfileで扱います。

`assessments/network.png`は全候補を対象とする高解像度の静的化学量論matrixです。1反応1列でsamplingや
species間edgeへの投影を行わず、PNG metadataにも状態数、反応数、反応ID digest、`all_candidates_no_sampling`
scopeを記録します。PNGは全体構造、HTMLはzoom・filter・完全反応式の確認という責務分担です。

Network explorerの`Hierarchical pathways`は、選択した対象状態について、入力ground stateと電子からの
最短到達経路を左から右へ表示します。通常のspecies間経路ではなく、全反応物が到達済みの場合だけ反応を
進めるAND型hyperpathです。層は最小生成反応段数から求め、候補生成時の`depth`を物理的な時間順序として
流用しません。同じ最短段数では5判定の利用可能性を決定的なtie-breakに使いますが、支配反応とは解釈
しません。主図は状態名と役割、`R1`形式の反応番号と短い反応種別だけを示し、edgeはfamily色と方向だけに
限定します。完全反応式、canonical ID、5判定は反応nodeのclick先へ分離します。選ばれなかった代替生成、
対象消費、正味係数ゼロ参加反応も件数と完全な一覧を同じ画面に残します。表示中の対象経路は画面から
PNG downloadできます。
`assessments/pathways.png`は最終screeningで到達可能な代表対象を1枚だけ静的出力し、該当対象がなければ
より前のscreeningへ戻します。対象、使用view、経路反応数、関連反応数をPNG metadataへ記録します。

`assessments/screening/`は個別判定とは別の累積pass-only viewです。`State → Consistency`、
`State → Consistency → Thermochemistry`、`State → Consistency → Thermochemistry →
(Kinetics OR Reaction evidence)`の3段階を持ちます。各段階の`states.csv`と`reactions.csv`は、
その段階までのgateを通過した候補だけを保持します。最後のgateはKineticsとReaction evidenceの
両方を要求せず、どちらか一方がpassなら通過します。反応CSVには両判定、OR結果、`accepted_by`を
別列で保持します。`summary.csv`は各stepの入力数・残存数・そのstepでの除外数を、
`retention.svg`は同じ推移を状態と反応に分けて表示します。3つの残存反応集合は
case共通の`assessments/network.html`から切り替えて確認できます。
KineticsとReaction evidenceは状態へ適用せず、状態の累積件数を変えません。このscreeningは
CandidateSetや正規YAMLを変更せず、fail/unknownの詳細は個別判定CSVに残ります。

CSVには行ごとのrun metadataやJSONを入れず、確認に必要な値だけを通常の列として出します。
目視用の状態名は`Ar+`、`Ar(m)`（準安定）、`Ar(r)`（共鳴）、`CF4*`（電子励起）、
`O2(v)`（振動励起）のような記号で表示します。既知の項記号は`O2(a¹Δg)`や`O(¹D₂)`とします。
反応表には式の直後に`Electron-impact ionization`、`Resonant charge exchange`、
`Excited-state quenching`などの英語の
`reaction_type`を表示します。一意性が必要な
`Ar+@ground`等は各表の最後の`id`列だけに保持します。完全な証拠recordと再現metadataは
YAMLが正本です。選択結果は`states.csv`と`reactions.csv`の`selected`列および
`selected.yaml`へ記録するため、重複する`selected.csv`は出力しません。

反応式の表示順は化学量論やreaction IDと独立です。反応物側は電子、重粒子イオン、励起・活性中性種、
安定中性種の順とし、生成物側は重粒子を先に、電子を最後にします。したがって電子衝突は
`e + Ar -> Ar(4s) + e`、イオン衝突はprojectile ionを先頭とする形で全CSV・YAML・network表示を統一します。

状態略記は次の意味です。

| 表示 | 意味 |
|---|---|
| `O2` | 電子基底状態 |
| `O2(v)` | 未分解の振動励起状態群 |
| `CF4*` | 準位未指定の電子励起状態群 |
| `Ar(m)` | 未分解の準安定電子状態群 |
| `Ar(r)` | 未分解の共鳴・放射性電子状態群 |
| `Ar(4s)` | 4s配置の混合状態群（準安定2準位と共鳴2準位を含む証拠側のumbrella） |
| `O(¹D₂)`, `O2(a¹Δg)` | 証拠で名前が特定された分解済み状態 |
| `Ar+`, `O-`, `e` | 正イオン、負イオン、自由電子 |

`v / * / m / r`は一つの量子準位を断定せず、`resolution=lumped`の計算用候補を表します。
構造異性体を表す記号ではありません。化学式だけから構造異性体を分離せず、外部証拠で同定できる場合だけ
別のnamed stateとして扱います。`Ar(4s)`は`Ar(m)`または`Ar(r)`と同一ではなく、両方に関連する
混合manifoldです。関連証拠はState判定へ表示しますが、完全一致しない状態の物性値としては採用しません。
`states.csv`の`state_meaning`はこの意味を行ごとに明記します。

主要CSV列は次の区分です。

- 状態同定：`species / formula / charge / excitation / resolution / lifetime_class /
  state_label / state_symbol / state_meaning / alternative_resolution_states /
  structure_scope / id`
- 生成情報：`origin / depth`
- 状態判定：`state_verdict / thermochemistry_verdict / selected`
- 状態物性：`state_energy_eV / lifetime_s / mass_amu / enthalpy_formation_eV /
  ionization_energy_eV / electron_affinity_eV`
- 反応同定：`equation / reaction_type / family / process / id`
- 反応判定：5種類の`*_verdict`、`selected / exclusion_reason`
- 反応数値：`delta_h_eV / delta_g_eV / threshold_eV / kinetic_data`

`state_label`はcanonicalな機械用ラベル、`state_symbol`は`m / r / v / *`などの表示記号です。
`excitation`はground・electronic・vibrational、`lifetime_class`はmetastable・radiative等を表し、
状態解像度とは混ぜません。`alternative_resolution_states`は同じ組成・電荷・励起種別を
lumped/resolvedの別表現で表す候補を示し、同時計上を避けるための列です。
`structure_scope=formula_only`は化学式だけでは構造異性体まで同定していないことを示します。

反応の`state_verdict`は「反応物・生成物に現れる非電子状態それぞれのState判定」の集約です。
反応自体の存在、起こりやすさ、速度を意味しません。
`depth`は候補生成frontierの深さであり、時間順序、反応経路の段数、重要度ではありません。
`origin=mechanical`は生成文法由来、`attested_only`は証拠源にだけ存在して和集合された候補です。

判定値は`pass / fail / unknown / not_applicable`です。既定の`review`は全候補を
表示します。候補集合と数値計算用の選択集合は別物です。

生成時に化学式から確定できるのは元素組成、電荷、原子数、homolepticな中心原子–配位子型の
開裂と電子数parityまでです。`fragment`は生成経路、`reactive_candidate`はodd-electron、
非希ガス原子、または明確な`AXn`式での価電子不足を表し、spinの断定ではありません。
これによりCF2、SiH2などを中性反応候補へ残しつつ、構造異性体、spin、準位の実在性は
State証拠で判断します。非束縛anionやエネルギー不足のPenning反応も生成時に隠さず、
後段で`fail`にします。

圧力・温度・密度・換算電界・体積・表面積・滞留時間は有限性と符号をCase読込み時に検査します。
family/processは候補、Registry、snapshotのすべてでcanonical化してからIDを作るため、
`three_body/recombination`と`neutral/three_body_association`を別反応として重複させません。

## 外部データ

生成処理はネットワークへ接続しません。外部取得は`acquire`だけが担当します。

```powershell
acquire lxcat export.txt --out work/lxcat
rgen ingest work/lxcat/snapshot.yaml --bundle work/ar_cf4 --overlay work/overlay.yaml
rgen generate cases/ar_cf4/case.yaml --registry registry --overlay work/overlay.yaml
rgen adopt work/overlay.yaml --registry registry
```

`ingest`はbundleのcanonical IDへ照合するだけです。反応式が同じでもfamily・process・
observableが違うデータは別物です。曖昧一致やtotal processの
product-resolved channelへの割当てはreview queueへ送ります。Registryを書き換えるのは
明示的な`adopt`だけです。

公開形式は[単一のbundle schema](schemas/bundle.schema.yaml)で定義します。

## 開発

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[quality]"
python -m pytest -q
ruff check .
mypy
lint-imports --config .importlinter --no-cache
```

本ツールはBoltzmann方程式、DNT/DNT+、EEDF、プラズマ時間発展を解きません。
それらで扱う反応種・channelは候補化しますが、断面積モデル自体は実装範囲外です。
電子をground-state NASA speciesとみなした平衡定数や逆速度は導出しません。
