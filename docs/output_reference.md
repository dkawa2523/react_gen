# 出力形式仕様

本書は、`rgen generate ... --csv`が出力する正規YAML、状態・反応CSV、判定CSV、集計CSVの正式仕様である。
数値計算へ採用する前の確認、データ取得対象の整理、第三者への結果引き渡しに使用する。

仕様対象はファイル名、ディレクトリ、CSV列名と列順、YAML schema、IDによる集合関係である。
`*.svg`、`*.png`、`network.html`は同じ正規データから作る補助表示であり、本書の互換仕様には含めない。
補助表示の追加・レイアウト変更は、YAML・CSVの形式変更とは扱わない。

| 対象 | 値 |
|---|---|
| generator version | `0.5.0` |
| bundle schema version | `4` |
| 物理量の基本表記 | SI単位。状態・反応energyは主にeV |

## 1. 最初に確認するファイル

| 確認したい内容 | ファイル | 位置付け |
|---|---|---|
| 状態候補の全体 | `states.csv` | 状態名、状態解像度、物性、判定の一覧 |
| 反応候補の全体 | `reactions.csv` | 反応式、反応分類、5判定、数値利用可否の一覧 |
| 電子衝突だけ | `reactions_electron.csv` | `family=electron`の抽出表 |
| イオン衝突だけ | `reactions_ion.csv` | `family=ion`の抽出表 |
| 中性気相反応だけ | `reactions_neutral.csv` | `family=neutral`の抽出表 |
| 表面反応だけ | `reactions_surface.csv` | `family=surface`の抽出表 |
| 判定理由 | `assessments/<判定名>/` | 判定ごとの状態表、反応表、件数集計 |
| 段階的な絞り込み | `assessments/screening/` | 複数判定を順に通したpass-only view |
| 全体集計 | `assessments/statistics.csv` | 判定別件数、累積残存数、候補構成 |
| 再現・証拠の詳細 | `states.yaml`、`reactions.yaml` | 正規データ。CSVより情報量が多い |
| 選択結果 | `selected.yaml` | policyによる採用ID、除外理由、readiness |

`states.yaml`、`reactions.yaml`、`selected.yaml`が正規bundleである。CSVは同じ内容を確認しやすくした表形式viewであり、
独立した候補集合ではない。CSVを出力しない通常実行ではYAML 3ファイルだけを出力する。

## 2. 出力ディレクトリ

```text
<case>/
  states.yaml
  reactions.yaml
  selected.yaml
  states.csv
  reactions.csv
  reactions_electron.csv
  reactions_ion.csv
  reactions_neutral.csv
  reactions_surface.csv
  assessments/
    statistics.csv
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

各個別判定ディレクトリには次の表形式ファイルがある。

| ファイル | 内容 |
|---|---|
| `states.csv` | 状態へ適用するConsistency、State、Thermochemistryだけに出力 |
| `reactions.csv` | その判定に対する全反応候補と判定理由 |
| `reactions_electron.csv` | 電子衝突反応だけを抽出 |
| `reactions_ion.csv` | イオン衝突反応だけを抽出 |
| `reactions_neutral.csv` | 中性気相反応だけを抽出 |
| `reactions_surface.csv` | 表面反応だけを抽出 |
| `summary.csv` | 状態、反応、両者合計の4値判定件数 |
| `family_summary.csv` | 反応family別の4値判定件数 |

family別CSVは`reactions.csv`の分割表である。4ファイルの反応IDを合わせると、元の`reactions.csv`の反応IDと一致する。
該当反応がないfamilyも、列見出しだけのCSVとして出力される。

CSVの共通形式は次のとおりである。

| 項目 | 仕様 |
|---|---|
| 文字コード | UTF-8、BOMなし |
| 区切り | comma。値のquoteとescapeは標準CSV規則 |
| 改行 | LF |
| 先頭行 | 本書で定義する列名。列順も仕様に含む |
| 空の値 | 空文字。未取得、非適用、競合は判定列・理由列と併読する |
| boolean | `true`または`false` |
| 行順 | depth、目視名、canonical IDによる決定的順序 |
| 集合の参照キー | 状態・反応とも末尾の`id`列 |

## 3. 共通の判定値

すべての判定は次の4値を使用する。

| 値 | 意味 | 取り扱い |
|---|---|---|
| `pass` | 判定に必要な条件と証拠を満たす | その判定について利用可能 |
| `fail` | 物理的不整合、明確な非実在、条件範囲外などを確認 | 原則として当該用途から除外 |
| `unknown` | 証拠または数値が不足し、合否を決められない | 候補として保持し、追加調査対象とする |
| `not_applicable` | その対象へ判定を適用しない | 合格・不合格のどちらにも数えない |

`unknown`は`fail`ではない。Registryに記録がないことだけを理由に、生成候補を物理的に存在しないとは判断しない。

## 4. 反応式の表記

### 4.1 記号

| 表記 | 意味 | 例 |
|---|---|---|
| `e` | 自由電子 | `e + Ar -> Ar+ + 2 e` |
| `+` | 同じ側にある反応参加粒子の区切り | `Ar+ + O2` |
| `->` | 候補反応の向き | `O + O + M -> O2 + M` |
| 数字 | 化学量論係数 | `2 O`、`2 e` |
| 上付きでない`+`、`-` | 目視用の電荷 | `Ar+`、`O2-` |
| `(v)` | 未分解の振動励起状態群 | `O2(v)` |
| `*` | 準位未指定の電子励起状態群 | `CF4*` |
| `(m)` | 未分解の準安定電子状態群 | `Ar(m)` |
| `(r)` | 未分解の共鳴・放射性電子状態群 | `Ar(r)` |
| 項記号 | 分解済みの分光状態 | `O(¹D₂)`、`O2(a¹Δg)` |
| `M` | 反応前後で明示的に消費されない第三体 | `2 O + M -> O2 + M` |
| `[material]` | 表面材料または表面reservoir | `... + [SiO2]` |

### 4.2 参加粒子の表示順

表示順は読みやすさのための規則であり、化学量論、反応ID、証拠照合を変更しない。

| 側 | 表示順 |
|---|---|
| 反応物 | 電子 → 正イオン → 負イオン → 励起中性種 → 活性中性種・原子 → 安定中性種 → `M`・surface |
| 生成物 | 正イオン → 負イオン → 励起中性種 → 活性中性種・原子 → 安定中性種 → 電子 → `M` |

| 分類 | 表示例 |
|---|---|
| 電子励起 | `e + Ar -> Ar(4s) + e` |
| 電子衝突電離 | `e + Ar -> Ar+ + 2 e` |
| 電子脱離 | `e + Ar- -> Ar + 2 e` |
| 電荷交換 | `Ar+ + O2 -> O2+ + Ar` |
| Penning電離 | `Ar(m) + O2 -> O2+ + Ar + e` |
| 三体会合 | `2 O + M -> O2 + M` |

### 4.3 IDと表示名

| 種類 | 例 | 用途 |
|---|---|---|
| 表示名 | `Ar+`、`Ar(m)`、`O2(a¹Δg)` | CSVでの目視確認 |
| canonical state ID | `Ar+@ground`、`Ar@metastable`、`O2@a1dg` | 照合、参照、一意性確保 |
| reaction ID | `rxn_683f67de893f` | 反応channelの一意な参照 |

reaction IDはfamily、process、第三体、surface、両辺の集約済み化学量論から決定される。
CSV上の表示順を変更してもreaction IDは変わらない。

## 5. 状態記号と状態軸

### 5.1 代表的な表示

| 表示 | 状態の意味 | 解像度 |
|---|---|---|
| `Ar`、`O2` | 電子基底状態 | `resolved` |
| `Ar+`、`O2-` | 基底状態として扱う正・負イオン | `resolved` |
| `e` | 自由電子 | `resolved` |
| `O2(v)`、`CF4(v)` | 振動励起状態をまとめたmanifold | `lumped` |
| `CF4*`、`SF6*` | 準位と寿命を特定しない電子励起manifold | `lumped` |
| `Ar(m)` | 準安定電子状態をまとめたmanifold | `lumped` |
| `Ar(r)` | 共鳴・放射性電子状態をまとめたmanifold | `lumped` |
| `Ar(4s)` | 4s配置の混合manifold。準安定2準位と共鳴2準位を含む | `lumped` |
| `O(¹D₂)` | 分光学的に特定した原子状態 | `resolved` |
| `O2(a¹Δg)` | 分光学的に特定した分子状態 | `resolved` |

`Ar(4s)`は`Ar(m)`または`Ar(r)`と同一ではない。`Ar(4s)`の証拠は両者に関連するが、
完全一致しない状態の固有物性値としては転記されない。

### 5.2 `excitation`

| 値 | 意味 |
|---|---|
| `ground` | 電子基底状態として扱う |
| `electronic` | 電子励起状態 |
| `vibrational` | 振動励起状態 |
| `electron` | 自由電子。重粒子の内部状態ではない |

### 5.3 `resolution`

| 値 | 意味 | 注意点 |
|---|---|---|
| `resolved` | 項記号、準位名、または基底状態として個別に表現 | 状態固有の数値が必要 |
| `lumped` | 複数準位または未分解状態群を一つにまとめた表現 | 対応するresolved状態と同時計上しない |

### 5.4 `lifetime_class`

| 値 | 意味 |
|---|---|
| `not_applicable` | 基底状態、振動状態、電子など、当該分類を使用しない |
| `metastable` | 放射遷移が抑制された比較的長寿命の状態またはmanifold |
| `resonant_radiative` | 許容放射遷移を持つ共鳴状態またはmanifold |
| `mixed_metastable_resonant` | 準安定状態と共鳴状態を両方含むumbrella manifold |
| `unspecified` | 電子励起は表すが、寿命・放射特性を特定していない |

### 5.5 `structure_scope`

| 値 | 意味 |
|---|---|
| `not_applicable` | 電子または単原子種。構造異性体の区別を必要としない |
| `formula_determined` | 二原子分子など、化学式だけで結合骨格の曖昧性が小さい |
| `formula_only` | 組成だけを表し、構造異性体、結合配置、配座を同定していない |

`formula_only`は「構造が存在しない」という意味ではない。化学式から一意な構造を断定していないことを示す。

### 5.6 `alternative_resolution_states`

| 表示例 | 意味 |
|---|---|
| `O2(a¹Δg); O2(b¹Σg+)` | 現在行のlumped状態と同じ励起種別を、resolved状態で表した候補 |
| `O2*` | 現在行のresolved状態に対応するlumped候補 |
| 空欄 | 出力集合内に反対解像度の候補がない |

この列は同一状態を断定するものではなく、計算モデルで重複採用を避けるための関係表示である。

## 6. `states.csv`の列

| 列 | 内容 | 空欄の意味 |
|---|---|---|
| `species` | 目視用の状態名 | 通常は空欄にならない |
| `formula` | 元素組成から組み立てた化学式 | 電子では空欄になり得る |
| `charge` | 素電荷単位の整数電荷 | `0`は中性 |
| `excitation` | 基底、電子励起、振動励起、電子の区分 | 通常は空欄にならない |
| `resolution` | `resolved`または`lumped` | 通常は空欄にならない |
| `lifetime_class` | 寿命・放射特性の分類 | 非適用は`not_applicable` |
| `state_label` | canonicalな機械用状態ラベル | 表示記号とは異なる |
| `state_symbol` | `m`、`r`、`v`、`*`、項記号など | 基底状態では空欄 |
| `state_meaning` | 状態表現の説明 | 通常は空欄にならない |
| `alternative_resolution_states` | 反対解像度の関連候補 | 該当候補がなければ空欄 |
| `structure_scope` | 化学式から構造を確定できる範囲 | 通常は空欄にならない |
| `origin` | 候補が機械生成か証拠由来か | 通常は空欄にならない |
| `depth` | frontier生成深さ | `0`は入力または証拠から直接導入 |
| `state_verdict` | State判定 | 実在性、bound性、状態証拠を確認 |
| `thermochemistry_verdict` | 状態の熱化学表現に対する判定 | 数値不足は`unknown` |
| `selected` | 現在のpolicyで選択されたか | `true`または`false` |
| `state_energy_eV` | 参照基準からの状態エネルギー | exact証拠がなければ空欄 |
| `lifetime_s` | 状態寿命 | 未取得または非適用なら空欄 |
| `mass_amu` | 原子質量単位での質量 | 未取得なら空欄 |
| `enthalpy_formation_eV` | 生成エンタルピー | 未取得なら空欄 |
| `ionization_energy_eV` | 当該状態からの電離エネルギー | 未取得なら空欄 |
| `electron_affinity_eV` | 電子親和力 | 未取得または非束縛なら値・qualifierをYAMLで確認 |
| `id` | canonical state ID | 一意参照用 |

数値の`0`と空欄は異なる。`0`は既知のゼロ、空欄は未取得、非適用、または複数証拠が一致しない場合を表す。

## 7. 状態証拠の照合区分

State判定ディレクトリの`states.csv`では、`evidence`列に照合結果と証拠IDを表示する。

| 区分 | 意味 | 例 |
|---|---|---|
| `exact` | 組成、電荷、状態表現が候補と一致 | `exact: Ar_4s` |
| `compatible` | 関連状態だが、候補と同一の状態表現ではない | `compatible: Ar_4s` for `Ar(m)` |
| `ambiguous` | 複数候補または競合があり一意に決められない | 自動採用しない |
| `none` | 照合できる状態証拠がない | State判定は通常`unknown` |

compatible証拠の数値は、候補固有の`state_energy_eV`や`lifetime_s`へ転記されない。

## 8. 状態判定ディレクトリの列

### 8.1 状態に適用する判定

| ディレクトリ | 主な列 | 判定内容 |
|---|---|---|
| `consistency/` | `candidate`、状態軸、`verdict`、`reason` | 化学式、組成、電荷、表現形式 |
| `state/` | 上記 + `evidence` | 状態の実在証拠、bound性、寿命、解像度 |
| `thermochemistry/` | 状態軸、`verdict`、`reason` | 生成熱またはNASA表現の有無と品質 |

共通列は次のとおりである。

| 列 | 内容 |
|---|---|
| `candidate` | 目視用状態名 |
| `excitation` | 励起種別 |
| `resolution` | 状態解像度 |
| `lifetime_class` | 寿命・放射特性 |
| `state_meaning` | 状態表現の説明 |
| `alternative_resolution_states` | 代替解像度候補 |
| `verdict` | 4値判定 |
| `reason` | 判定理由 |
| `id` | canonical state ID |

### 8.2 状態に適用しない判定

| ディレクトリ | `states.csv`の扱い |
|---|---|
| `reaction_evidence/` | 反応式に対する判定のため、状態行は出力しない |
| `kinetics/` | 反応datasetに対する判定のため、状態行は出力しない |

両ディレクトリには`states.csv`を作らない。状態へ適用しない判定の空表を正式出力に含めないためである。

## 9. `reactions.csv`の列

| 列 | 内容 | 読み方 |
|---|---|---|
| `equation` | 目視用反応式 | 状態記号と化学量論係数を含む |
| `reaction_type` | 人が読みやすい英語の反応名 | 表示用。詳細分類は`process` |
| `family` | 電子、イオン、中性、surfaceの大分類 | family別CSVの分割基準 |
| `process` | 安定した機械用process名 | 証拠照合とreaction IDに使用 |
| `origin` | `mechanical`または`attested_only` | 候補の導入経路 |
| `depth` | 候補生成frontierの深さ | 時間順序や重要度ではない |
| `consistency_verdict` | 保存則・表現整合性 | 元素、電荷、係数など |
| `state_verdict` | 参加する非電子状態のState判定を集約 | 反応速度や既知反応性は表さない |
| `thermochemistry_verdict` | 反応エネルギー・thresholdの判定 | 発熱反応だけをpassにする判定ではない |
| `reaction_evidence_verdict` | 同一channelの既知記録 | 速度係数の利用可否とは別 |
| `kinetics_verdict` | 断面積・速度係数datasetの利用可否 | 単位、範囲、channel対応を含む |
| `delta_h_eV` | 反応エンタルピー | 正は吸熱、負は発熱 |
| `delta_g_eV` | 指定温度でのGibbs energy差 | 条件とNASA等がそろう場合だけ出力 |
| `threshold_eV` | channel threshold | 速度係数そのものではない |
| `kinetic_data` | 利用可能な数値形式の要約 | `cross_section`、`rate_coefficient`、`estimated`等 |
| `selected` | policyで選択されたか | `review`では原則すべて`true` |
| `exclusion_reason` | 非選択の最初の理由 | 選択済みなら空欄 |
| `id` | deterministic reaction ID | 全出力を横断する参照キー |

### 9.1 `origin`

| 値 | 意味 |
|---|---|
| `mechanical` | 入力ガスと有限生成文法から生成した候補 |
| `attested_only` | 機械生成集合にはなかったが、Registryまたはsnapshotの既知記録から和集合した候補 |

`attested_only`は自動的に数値計算可能という意味ではない。State、Reaction evidence、Kineticsの各判定を確認する。

### 9.2 `depth`

| 値 | 意味 |
|---|---|
| `0` | 入力状態、電子、または証拠から直接導入した候補 |
| `1`以上 | 生成frontierで新しい状態・反応を導入した深さ |

depthは反応時間、反応回数、支配経路、反応速度、重要度を表さない。

## 10. 反応family

| family | 対象 | 反応物側の代表形 | family別CSV |
|---|---|---|---|
| `electron` | 電子衝突、電子–イオン反応 | `e + A`、`e + A+` | `reactions_electron.csv` |
| `ion` | イオン–中性、イオン–イオン衝突 | `A+ + B`、`A+ + B-` | `reactions_ion.csv` |
| `neutral` | 中性粒子間の気相反応 | `A* + B`、`R + AB` | `reactions_neutral.csv` |
| `surface` | 材料表面を必要とする反応 | `A + [material]` | `reactions_surface.csv` |

surface反応は中性気相反応へ含めない。材料、活性site、被覆率、ion assistanceなどが別途必要になるためである。

## 11. 電子衝突process

| `process` | `reaction_type` | 意味 |
|---|---|---|
| `elastic` | Electron elastic scattering | 内部状態と化学種を変えない弾性散乱 |
| `excitation` | Electron-impact excitation | 電子衝突による振動・電子励起 |
| `deexcitation` | Electron-impact deexcitation (superelastic) | 励起状態から低い状態への超弾性衝突 |
| `ionization` | Electron-impact ionization | 電子衝突による電離 |
| `attachment` | Electron attachment | 親分子・原子への電子付着 |
| `dissociation` | Electron-impact dissociation | 電荷を変えない電子衝突解離 |
| `dissociative_ionization` | Dissociative ionization | 解離と電離が同時に起こるchannel |
| `dissociative_attachment` | Dissociative electron attachment | 電子付着に伴い解離するchannel |
| `detachment` | Electron-impact detachment | 負イオンから電子を脱離するchannel |
| `dissociative_detachment` | Dissociative electron detachment | 解離を伴う電子脱離channel |
| `recombination` | Electron-ion recombination | 電子と正イオンの非解離再結合 |
| `dissociative_recombination` | Dissociative recombination | 電子–分子イオン再結合後に解離するchannel |

電子衝突断面積`σ(ε)`は速度係数ではない。速度係数にはEEDFとの積分が必要になる。

```text
k = integral sigma(epsilon) v(epsilon) f(epsilon) d epsilon
```

## 12. イオン衝突process

| `process` | `reaction_type` | 意味 |
|---|---|---|
| `elastic` | Ion-neutral elastic scattering | イオン–中性粒子の弾性・運動量移行channel |
| `charge_exchange` | Charge exchange | 非共鳴を含む電荷交換 |
| `resonant_charge_exchange` | Resonant charge exchange | 同一組成など、エネルギー差が小さい共鳴電荷交換 |
| `dissociative_charge_transfer` | Dissociative charge transfer | 電荷移行と標的または生成物の解離 |
| `collision_induced_dissociation` | Collision-induced target dissociation | 衝突による標的中性種の解離 |
| `projectile_dissociation` | Projectile-ion dissociation | projectile ion側の解離 |
| `ligand_transfer` | Ligand transfer | 原子またはligandの移行 |
| `reactive_scattering` | Ion-neutral reactive scattering | 組成交換を伴うbounded reactive channel |
| `ion_induced_excitation` | Ion-induced excitation | イオン衝突による状態励起 |
| `ion_induced_deexcitation` | Ion-induced deexcitation | イオン衝突による状態緩和 |
| `collisional_detachment` | Collisional electron detachment | 負イオンからの衝突電子脱離 |
| `mutual_neutralization` | Ion-ion mutual neutralization | 正負イオンの相互中和 |

イオン衝突候補が存在することは、DNT+等の断面積モデルを実装したことを意味しない。
本出力は反応種と反応channelの候補を表し、数値利用可否はKinetics判定で別に示す。

## 13. 中性気相process

| `process` | `reaction_type` | 意味 |
|---|---|---|
| `association` | Bimolecular association | 二体会合候補。既定生成では制限される |
| `three_body_association` | Three-body association | 第三体`M`が余剰エネルギーを受け取る会合 |
| `associative_ionization` | Associative ionization | 励起種などの会合に伴う電離 |
| `dissociation` | Neutral-impact dissociation | 中性衝突による解離 |
| `penning_ionization` | Penning ionization | 励起種の内部エネルギーによる相手中性種の電離 |
| `quenching` | Excited-state quenching | 励起状態の衝突失活 |
| `v_t_relaxation` | Vibrational-translational (V-T) relaxation | 振動エネルギーから並進エネルギーへの緩和 |
| `radical_abstraction` | Radical abstraction | radicalによる原子・ligand引き抜き |
| `reactive_scattering` | Neutral reactive scattering | 中性粒子間の組成交換・反応散乱 |

候補生成では、radical、励起種、振動励起種、入力ground speciesなどを含む有限pairだけを評価する。
全中性種の無制限な直積ではない。

## 14. surface process

| `process` | `reaction_type` | 意味 |
|---|---|---|
| `surface_recombination` | Surface recombination | 表面を介した再結合またはgas-phase speciesの表面消費 |

surface反応の元素収支は、gas phaseだけでは閉じない場合がある。surface reservoir、材料、site種を含む証拠を確認する。

## 15. 5つの判定レイヤー

判定は表示上の順序を持つが、個別判定は独立に実行される。前段が`unknown`でも後段判定を省略しない。

| 判定 | 主な確認事項 | `pass`が意味する範囲 |
|---|---|---|
| `consistency` | 化学量論係数、状態参照、元素保存、電荷保存、第三体、surface | 表現と保存則が整合する |
| `state` | 状態実在性、bound性、寿命、状態energy、lumped/resolved | 参加状態がState判定を通る |
| `thermochemistry` | 生成熱、NASA、IE、EA、threshold、反応energy | 利用可能なenergy情報がある、またはhard feasibilityを判断できる |
| `reaction_evidence` | 同一式、状態、family、process、第三体、surface、channel scope | 同一channelの既知記録がある |
| `kinetics` | 断面積・速度係数、単位、独立変数、範囲、channel、不確かさ | 条件に適用可能な数値datasetがある |

反応の`state_verdict`は、反応物と生成物に現れる非電子状態のState判定を集約した値である。

| 参加状態の内訳 | 反応の`state_verdict` |
|---|---|
| 全状態が`pass` | `pass` |
| 一つ以上が`fail` | `fail` |
| `fail`はないが一つ以上が`unknown` | `unknown` |

反応のState判定は、反応自体が既知か、速いか、重要かを表さない。

## 16. 判定別反応CSVの列

### 16.1 Consistency

| 列 | 内容 |
|---|---|
| `candidate` | 反応式 |
| `reaction_type` | 表示用反応名 |
| `verdict` | 保存則・構造整合の4値判定 |
| `reason` | 判定理由 |
| `id` | reaction ID |

### 16.2 State

列構成はConsistency反応表と同じである。`reason`には参加状態のうち、failまたはunknownとなった状態判定の集約理由が入る。

### 16.3 Thermochemistry

| 列 | 内容 |
|---|---|
| `candidate` | 反応式 |
| `reaction_type` | 表示用反応名 |
| `delta_h_eV` | 反応エンタルピー |
| `delta_g_eV` | 指定条件でのGibbs energy差 |
| `threshold_eV` | 反応threshold |
| `verdict` | 熱化学判定 |
| `reason` | 利用したenergy情報または不足理由 |
| `id` | reaction ID |

反応熱は次の符号規約を用いる。

```text
Delta H = sum(nu Hf(products)) - sum(nu Hf(reactants))
```

| `delta_h_eV` | 意味 |
|---|---|
| 負 | 発熱側 |
| 正 | 吸熱側 |
| 空欄 | 必要な状態熱化学が不足 |

### 16.4 Reaction evidence

| 列 | 内容 |
|---|---|
| `candidate` | 反応式 |
| `reaction_type` | 表示用反応名 |
| `matched_source` | 照合したRegistry、snapshot等のsource ID |
| `channel_scope` | total processかproduct-resolved channelか |
| `verdict` | 既知反応照合の4値判定 |
| `reason` | exact、related、競合、未照合などの理由 |
| `id` | reaction ID |

| `channel_scope` | 意味 |
|---|---|
| `product_resolved` | 生成物channelまで指定したdatasetまたは反応記録 |
| `total` | 複数生成物channelを合計したtotal process |
| 空欄 | channel scopeを持つ証拠がない |

total processのdatasetを、根拠なく一つのproduct-resolved channelへ割り当てない。

### 16.5 Kinetics

| 列 | 内容 |
|---|---|
| `candidate` | 反応式 |
| `reaction_type` | 表示用反応名 |
| `data_kind` | datasetの数値形式 |
| `unit` | dataset値の単位 |
| `applicable_range` | 温度、collision energy等の適用範囲 |
| `dataset_id` | 数値datasetのID |
| `verdict` | 数値利用可否の4値判定 |
| `reason` | 欠損、競合、範囲外、利用可能などの理由 |
| `id` | reaction ID |

| `data_kind` | 意味 |
|---|---|
| `cross_section` | collision energy等に対する断面積table |
| `rate_coefficient` | 直接利用できる速度係数またはその式 |
| `sticking_coefficient` | surfaceへの付着・反応確率 |
| 複数値 | 複数種類のdataset候補がある |
| 空欄 | 照合した数値datasetがない |

Kinetics判定では、単位、独立変数、適用範囲、channel対応、tableの単調性・非負性なども確認する。

## 17. 累積スクリーニング

screeningはCandidateSetを削除する処理ではない。個別判定から作るpass-onlyの派生viewである。

| ディレクトリ | 反応に要求する条件 |
|---|---|
| `state_consistency/` | State pass AND Consistency pass |
| `state_consistency_thermochemistry/` | 上記 AND Thermochemistry pass |
| `state_consistency_thermochemistry_kinetics_or_reaction_evidence/` | 上記 AND (Kinetics pass OR Reaction evidence pass) |

最後の段階はKineticsとReaction evidenceのANDではない。少なくとも一方がpassなら保持する。

### 17.1 screening `states.csv`

| 列 | 内容 |
|---|---|
| `species` | 状態表示名 |
| `formula` | 化学式 |
| `charge` | 電荷 |
| `excitation` | 励起種別 |
| `resolution` | 状態解像度 |
| `lifetime_class` | 寿命・放射特性 |
| `state_meaning` | 状態の説明 |
| `alternative_resolution_states` | 代替解像度候補 |
| `origin` | 候補由来 |
| `depth` | 生成深さ |
| `id` | state ID |

KineticsとReaction evidenceは状態へ適用しないため、最終二判定を加えても状態数を直接減らさない。

### 17.2 screening `reactions.csv`

| 列 | 内容 |
|---|---|
| `equation` | 反応式 |
| `reaction_type` | 表示用反応名 |
| `family` | 反応大分類 |
| `process` | 機械用process名 |
| `origin` | 候補由来 |
| `depth` | 生成深さ |
| `state_verdict` | 参加状態の集約判定 |
| `consistency_verdict` | 保存則・表現整合判定 |
| `thermochemistry_verdict` | 熱化学判定 |
| `kinetics_verdict` | 数値dataset判定 |
| `reaction_evidence_verdict` | 既知反応照合判定 |
| `kinetics_or_reaction_evidence_verdict` | KineticsとReaction evidenceのOR結果 |
| `accepted_by` | 最後のOR条件を通した判定名 |
| `id` | reaction ID |

`accepted_by`は`kinetics`、`reaction_evidence`、または両方をセミコロン区切りで表示する。

## 18. 集計CSV

### 18.1 `summary.csv`

| 列 | 内容 |
|---|---|
| `entity` | `state`、`reaction`、`all` |
| `pass` | pass件数 |
| `fail` | fail件数 |
| `unknown` | unknown件数 |
| `not_applicable` | 非適用件数 |
| `total` | 対象総数 |

### 18.2 `family_summary.csv`

| 列 | 内容 |
|---|---|
| `family` | `electron`、`ion`、`neutral`、`surface` |
| `pass` | family内のpass件数 |
| `fail` | family内のfail件数 |
| `unknown` | family内のunknown件数 |
| `not_applicable` | family内の非適用件数 |
| `total` | family内の総反応数 |

### 18.3 screening `summary.csv`

| 列 | 内容 |
|---|---|
| `entity` | `state`または`reaction` |
| `step` | `all`または、この行までに追加した判定gate名 |
| `applicability` | 状態・反応への適用方法。通常は`required`、非適用なら`not_applicable` |
| `input` | このstepへ入った候補数 |
| `retained` | このstepを通過した候補数 |
| `rejected_at_step` | このstepで除外された候補数 |
| `total` | screening前の候補総数 |
| `retained_percent` | `100 × retained / total`。小数点以下3桁へ丸める |

### 18.4 `assessments/statistics.csv`

| 列 | 内容 |
|---|---|
| `metric` | 集計指標名 |
| `layer` | 判定名、`cumulative`、または`all` |
| `entity` | `state`または`reaction` |
| `category` | verdict、family、電荷、励起種別など |
| `count` | category件数 |
| `total` | 分母 |

| `metric` | 集計内容 |
|---|---|
| `assessment_verdict` | 個別判定の4値件数 |
| `reaction_readiness` | 判定を順にpassした累積反応数 |
| `state_charge` | 状態の電荷構成 |
| `state_excitation` | 状態の励起種別構成 |
| `state_resolution` | lumped/resolved構成 |
| `state_lifetime_class` | 寿命・放射特性構成 |
| `reaction_family` | 反応family構成 |
| `reaction_depth` | 反応生成depth構成 |

## 19. YAMLで確認できる追加情報

### 19.1 `states.yaml`

| 項目 | 内容 |
|---|---|
| `composition` | 元素と原子数 |
| `state` | 内部state kind、resolution、label |
| `state_axes` | excitation、lifetime class、canonical label、structure scope |
| `classes` | ion、fragment、feed、mixed lifetime等の生成・分類タグ |
| `chemical_character.formula_scope` | `particle`、`atom`、`diatomic`、`central_ligand`、`formula_only` |
| `chemical_character.electronic` | `open_shell`、`closed_shell`、`unknown` |
| `introduced_by` | 状態を導入した生成rule |
| `evidence.records` | 証拠record、source、tier、状態energy、寿命、物性 |
| `assessments` | 各判定のverdict、basis、message |

### 19.2 `reactions.yaml`

| 項目 | 内容 |
|---|---|
| `reactants`、`products` | canonical state IDと係数 |
| `family`、`process` | 反応channel分類 |
| `generation_rule` | 候補を生成または導入したrule |
| `third_body`、`surface` | 第三体・表面条件 |
| `kinetic_effects` | `fast_product`等の運動論的注記 |
| `thermochemistry` | 利用可能なenergy値 |
| `numerical_capabilities.thermochemistry` | threshold、反応熱、平衡、逆速度への利用能力 |
| `numerical_capabilities.kinetics` | 断面積、直接rate、必要変換、利用dataset ID |
| `evidence` | exact channel、related total process、dataset参照 |
| `assessments` | 5判定のverdict、basis、message |

### 19.3 metadata

| 項目 | 内容 |
|---|---|
| `schema_version` | bundle schema version |
| `generator_version` | 生成器version |
| `case_digest` | case入力内容のdigest |
| `evidence_snapshot_hash` | 読み込んだ証拠内容のhash |
| `complete` | 設定した生成文法がclosureまで到達したか |
| `stop_reason` | closureまたは上限打切り理由 |
| `limits` | depth、状態数、反応数、電荷、fragment上限 |
| `counts` | 全候補数とmechanical候補数 |

`complete: true`は、設定した有限生成文法がclosureした意味である。自然界の全反応を網羅した意味ではない。

## 20. 選択結果とreadiness

### 20.1 主なpolicy

| policy | 選択条件の要点 |
|---|---|
| `review` | 全候補を表示・選択 |
| `chemistry_candidate` | Consistency pass |
| `acquisition` | hard failがなく、必要判定にunknownがある |
| `exploratory_simulation` | Consistency、State、Thermochemistryにfailがなく、利用可能kineticsまたはestimateがある |
| `strict_simulation` | Consistency、State、Reaction evidence、Kinetics pass、非estimate |
| `energy_balance` | strictに加えて反応エンタルピー利用可能 |
| `resolved_state_model` | strictに加えてresolved状態だけを使用 |

### 20.2 readiness

| 項目 | 意味 |
|---|---|
| `candidate_complete` | 生成が上限打切りでない |
| `evidence_ready` | 選択反応の必要判定がpass |
| `kinetic_data_ready` | 選択反応に断面積または直接rateがある |
| `direct_rate_ready` | 直接利用できるrate coefficientがある |
| `energy_source_ready` | 反応エンタルピーをenergy equationへ利用できる |
| `reverse_rate_ready` | 適用可能なforward rateと熱力学から逆速度を構成できる |
| `required_transforms` | EEDF積分など、利用前に必要な変換 |

## 21. 確認時の注意

| 誤読しやすい項目 | 正しい解釈 |
|---|---|
| 候補にある | 起こり得るchannelとして列挙された。実在・速度・重要性は別判定 |
| `unknown` | 不合格ではなく、判断に必要な証拠不足 |
| `reaction_evidence=pass` | 既知記録がある。数値datasetが利用可能とは限らない |
| `kinetics=pass` | 宣言条件で使える数値がある。現在のplasmaで重要とは限らない |
| `threshold_eV`あり | 反応開始energyがある。rate coefficientがあるとは限らない |
| `cross_section`あり | EEDF積分前の断面積。直接ODEへ入れるrateではない |
| `depth`が小さい | 生成文法上早く導入された。反応が速い・重要という意味ではない |
| `complete=true` | 有限生成規則がclosureした。自然界を完全網羅した意味ではない |
| lumpedとresolvedが共存 | 代替モデル候補。通常は同時計上しない |
| `formula_only` | 構造未同定。物理的非実在を意味しない |
| `Ar(4s)`と`Ar(m)` | 関連するが同一状態ではない |

## 22. 推奨する確認順序

| 手順 | 確認内容 | 使用ファイル |
|---:|---|---|
| 1 | 生成が打切りでないか | `selected.yaml`、YAML metadata |
| 2 | 状態名、電荷、励起、解像度を確認 | `states.csv` |
| 3 | lumped/resolvedの重複候補を確認 | `alternative_resolution_states` |
| 4 | 元素・電荷保存を確認 | `assessments/consistency/reactions.csv` |
| 5 | 参加状態の実在性を確認 | `assessments/state/` |
| 6 | 反応energyとthresholdを確認 | `assessments/thermochemistry/` |
| 7 | 既知反応記録を確認 | `assessments/reaction_evidence/` |
| 8 | 断面積・速度係数・適用範囲を確認 | `assessments/kinetics/` |
| 9 | 用途に応じた残存集合を確認 | `assessments/screening/`または`selected.yaml` |

CSVで空欄または要約となっている値は、同じ`id`を使ってYAMLのevidence、basis、message、dataset参照まで確認する。
