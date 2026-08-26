# Core design 0.5

## 一方向の処理

```text
Case(gases, conditions, limits)
  -> generate: 化学式と有限テンプレートによるCandidateSet
  -> evidence: 証拠の正規化・索引・attested-only和集合
  -> assessment: 独立した5判定
  -> policy: CandidateSetを変更しないID選択
  -> export: canonical YAML bundle + optional flat CSV views
```

生成はRegistry、熱化学、断面積、速度係数を参照しません。`acquire`だけが外部データを
取得し、`reactgen`はofflineで動作します。Registryへの書込みは`rgen adopt`だけです。
`complete: true`は設定した生成文法がclosureした意味で、自然界の全反応を含むという意味では
ありません。上限打切りだけを`complete: false`として明示します。

## ファイル責務

| ファイル | 責務 |
|---|---|
| `model.py` | Registry非依存のCandidate、canonical family/process、Channel key |
| `records.py` | Registry・snapshot・overlayを統一した読み取り専用証拠recordと数値値型 |
| `chemistry.py` | 化学式、状態ID、有限な組成操作 |
| `generate.py` | seed、電子・イオン・中性テンプレート、frontier、上限 |
| `registry.py` | Registry YAMLの読込み。暗黙の派生や書込みは行わない |
| `evidence.py` | 証拠の正規化、StateKey/EquationKey索引、照合、和集合 |
| `balance.py` | Registryと候補で共用する元素・電荷保存計算 |
| `thermo.py` | 生成熱、NASA多項式、Gibbs energy、平衡・逆速度の純粋計算 |
| `assessment.py` | 5判定と熱化学・速度論の利用能力 |
| `pipeline.py` | 唯一の実行経路と用途別ID選択 |
| `export.py` | 3 YAML、任意の一覧CSV、5判定別CSVの一括書出し |
| `ingest.py` | snapshotとbundle canonical indexの照合 |
| `derive.py` | 明示的な派生値overlayの作成 |
| `adopt.py` | review済みoverlayのRegistry採用 |
| `cli.py` | 公開CLIと終了コード |

抽象assessor、plugin、互換pipeline、診断frameworkは置きません。5判定は
`assessment.py`の明示的な関数として読める状態を維持します。

## 生成文法の科学的境界

`chemistry.py`が構造操作を行うのはatom、diatomic、homoleptic中心原子–配位子型だけです。それ以外は
`formula_only`として保持し、化学式から存在しない結合を推定して開裂・交換しません。
状態の`fragment`と`rearranged`は生成経路上の役割です。radical性はodd-electronなら
`open_shell`、既知の少数のeven-electron種だけtableで補い、残りは`unknown`にします。

中性反応の生成ではspin判定と反応候補性を分けます。odd-electron、非希ガス原子、または
明確な`AXn`式で価電子が未充足のCF2、SiH2、SFxなどを`reactive_candidate`とします。
中性二体反応はfeed、一次fragment、reactive candidate、励起状態を含むpairに限定し、
rearranged-only生成物の無制限な連鎖は行いません。解離には対応する有限な
`three_body_association`候補を置きます。
中性希ガス化合物は組成操作で作りません。荷電希ガスへの一配位子移動でできるcomplex ionは
直接neutral groundへ戻さず、解離再結合・解離電荷移行・衝突解離候補として扱います。

この境界は、CF2がフルオロカーボン膜形成で重要である実験報告
([Inayoshi et al., DOI 10.1116/1.580977](https://doi.org/10.1116/1.580977))、
SiH3とHがSiH4 PECVDの主要気相種・成長前駆体である測定
([Abe et al., DOI 10.1063/1.4974821](https://doi.org/10.1063/1.4974821))、
SF6プラズマのSiエッチング速度がF原子fluxと相関する実験
([Kokkoris et al., DOI 10.1016/j.mee.2004.02.059](https://doi.org/10.1016/j.mee.2004.02.059))
を考慮しています。ただし膜成長・エッチングのsurface channelは材料、活性site、被覆率、
ion assistanceを必要とするため、ガス化学式だけから生成せずRegistry証拠として和集合します。

## 証拠境界

EvidenceCatalogは読込み時に次の形式を`StateRecord`、`ReactionRecord`、
`NumericDataset`へ一度だけ変換します。

1. curated Registry
2. reviewed overlay
3. imported snapshot
4. derived data
5. estimated data

StateKeyとEquationKeyの索引も読込み時に一度だけ作ります。family/processは候補、Registry、
snapshotの入口で同じcanonical語彙へ変換してからChannel keyを作ります。照合はEquationKeyから
family・processを確認し、datasetではさらにobservable・channel scopeを確認します。候補ごとにRegistry全体を
再走査しません。overlayはRegistryの欠損だけを補い、curated値を上書きしません。

## 5判定

判定は表示上`Consistency -> State -> Thermochemistry -> Reaction evidence -> Kinetics/Data`
の順ですが、すべて独立に実行します。前段の`unknown`を理由に後段を省略しません。

| 判定 | 内容 |
|---|---|
| Consistency | 化学量論係数、state参照、元素保存、電荷保存、surface reservoir |
| State | exact/compatible/ambiguous、bound/unbound/transient、状態energy・寿命、lumped/resolved |
| Thermochemistry | 生成熱、ground-state NASA、IE/EA、threshold、Penning/charge-transfer energy |
| Reaction evidence | exact state-resolved equation、family、process、third body、surface、total/channel区別 |
| Kinetics/Data | kind、observable、反応次数と単位、独立変数、範囲、channel scope、品質、競合 |

反応の`state_verdict`は反応物・生成物に現れる非電子状態それぞれのState判定を集約します。全状態がpassなら
pass、一つでもfailならfail、failはないがunknownがあればunknownです。反応の存在や速度を判定する列では
ありません。

反応熱とGibbs energyは次で評価します。

```text
Delta H_r(T) = sum(nu h_products) - sum(nu h_reactants)
Delta G_r(T) = Delta H_r(T) - T Delta S_r(T)
K(T) = exp(-Delta G_r / RT)
```

電子衝突断面積は直接rateではありません。

```text
k = integral sigma(epsilon) v(epsilon) f(epsilon) d epsilon
```

このため`reactions.yaml`は次を区別します。

- `cross_section_ready`
- `direct_rate_ready`
- `required_transforms: [eedf_integration]`
- `reaction_enthalpy_ready`
- `electron_energy_loss_ready`
- `equilibrium_constant_ready` / `reverse_rate_ready`

thresholdだけでは重粒子のエネルギー源項や逆反応をreadyにしません。電子を0エンタルピーの
参照として反応熱には使えますが、gas-temperatureのNASA speciesとして平衡計算には入れません。
逆速度は平衡定数だけでなく、適用可能なforward rate、同じ状態解像度、third-bodyを含まない
同じ反応次数のthermal channelがそろう場合だけreadyにします。現時点では
charge exchange、ligand transfer、radical abstraction、reactive scatteringだけを対象とし、
電子衝突、相互中和、解離性過程から逆速度を自動導出しません。
励起状態もlevel energyを生成熱へ加えることはできますが、ground-state NASA多項式を複製して
entropy・partition functionまで既知とはみなしません。

Kinetics/Dataはasset参照の存在だけでpassにしません。tableは2点以上、有限値、独立変数の
狭義単調増加、非負値、宣言範囲、既知threshold以下の非零値を確認します。

## Policyとreadiness

| policy | 選択条件 |
|---|---|
| `review` | 全候補 |
| `chemistry_candidate` | Consistency pass |
| `acquisition` | Consistency pass、hard failなし、必要判定にunknown |
| `exploratory_simulation` | Consistency/State/Thermochemistry failなし、利用可能datasetまたはestimate |
| `strict_simulation` | Consistency/State/Reaction evidence/Kinetics pass、Thermochemistry failなし、非estimate |
| `energy_balance` | strictかつ`reaction_enthalpy_ready` |
| `resolved_state_model` | strictかつresolved State |

`selected.yaml`のreadinessはclosure、証拠、数値dataset、直接rate、エネルギー源項、
逆反応を別々に示します。断面積があるだけで「ODE計算準備完了」とは表示しません。

## 出力の整合性

出力先directory自体は置換しません。選択した出力ファイルを同じdirectory内の一時fileへ
先に書き、完成後にfile単位で置換します。Windows側のdirectory ACLとExplorerから見えるpathを
維持します。evidence hashは内容だけから計算し、
checkoutの絶対パスを含めません。大きなassetは複製せず、安定した参照pathとSHA-256だけを
出力します。

YAML 3ファイルがingest可能な正規bundleです。`--csv`はcase directory直下へ`states.csv`、
`reactions.csv`を出し、5判定を`assessments/<layer>/`へ分けます。case直下、各判定directory、
各累積screening directoryでは、全反応の`reactions.csv`に加えて
`reactions_electron.csv / reactions_ion.csv / reactions_neutral.csv / reactions_surface.csv`を
同一列構成で出します。surfaceをneutralへ混入させず、4ファイルのID和集合が全反応CSVと一致します。
各判定directoryは`summary.csv`、`family_summary.csv`と補助図を持ちます。
状態へ適用するConsistency、State、Thermochemistryだけは`states.csv`も持ち、
Reaction evidenceとKineticsには意味のない空の状態表を作りません。さらにcase全体で1つの
`assessments/network.html / network.png / pathways.png`と、
`assessments/statistics.csv / statistics.svg`が5判定の
累積pass-only readinessと各判定単独の構成を、`composition.svg`が状態の電荷・励起種別・解像度・寿命特性、
反応family・生成depthの全候補統計を保持します。同じ候補・判定・選択を
平坦化した目視用viewで、独立した証拠形式や第2のpipelineではありません。行ごとの再現metadata、
JSON列、重複する`selected.csv`は出しません。機械的な同一性には状態を含むcanonical IDを使いますが、
主要表示ではground markerを省略し、`Ar+`や`CF4`のような名前を使います。canonical IDは最後の
`id`列にだけ残し、完全な証拠と再現情報はYAMLに保持します。状態表現は、励起種別
`excitation`、解像度`resolution`、寿命・放射特性`lifetime_class`、canonicalな`state_label`、
目視用`state_symbol`を直交する列として出します。`alternative_resolution_states`は同じ組成・電荷・
励起種別に対するlumped/resolvedの代替表現を明示します。`structure_scope`は化学式から構造まで
確定できる範囲を示し、formula-only候補に異性体同定を暗黙付与しません。
励起状態は`Ar(m)`、`Ar(r)`、`CF4*`、`O2(v)`および既知の項記号で簡潔に表示します。
証拠側の`Ar(4s)`のように寿命特性が混在するumbrella manifoldは
`mixed_metastable_resonant`とし、`Ar(m)`・`Ar(r)`への関連証拠にはしても完全一致物性として転記しません。
反応行には英語の`reaction_type`を付けます。
表示用の参加粒子順はreaction keyから独立させ、反応物側では電子、重粒子イオン、励起・活性中性種、
安定中性種、生成物側では重粒子、電子の順に正規化します。third bodyとsurface markerは末尾です。
この順序はYAML、全CSV、network explorerで共用し、化学量論、候補ID、証拠照合を変更しません。
`summary.csv`とverdict構成図は全候補を集計します。Network explorerは全反応を一度だけ内包し、
5判定・3screening、検索、family・verdict・depth filterを同じfileで扱います。既定の全体表示は
状態行×反応列の化学量論incidence matrixで、1反応を必ず1列へ対応させます。これによりmulti-reactant、
multi-product反応をspecies間edgeへ展開して反応数を増やしません。反応物・生成物・正味係数ゼロ参加と、
5判定bandを同じ列上へ配置します。markから選択反応の方向付きhyperedgeへ、状態行から状態近傍networkへ
移動します。状態近傍は化学量論差`Δν`により正味生成・正味消費・正味係数ゼロ参加へ分類し、3区分を
独立pageで表示します。正味係数ゼロ参加はtransport、momentum、charge carrier等へ補足分類し、
物理的無変化とは扱いません。反応nodeから完全hyperedgeへ戻れるため、全接続を隠れたsamplingなしで
辿れます。

静的`network.png`も全候補を1反応1列で描く同じmatrixであり、1caseに1枚だけ生成します。状態数、反応数、
反応ID digest、scopeをPNG metadataへ保持し、代表抽出や反応統合を行いません。PNGは全体構造の確認、
HTMLはzoom・filter・完全反応式確認を担当します。全状態・全反応の正確な判定は各レイヤーの
`states.csv`と`reactions.csv`にも分けて残します。

Explorerの階層経路viewは、feed classのground stateと電子をseedとするAND-hypergraph到達判定です。
反応物が一つでも未到達ならその反応を進めず、生成物側の正味化学量論係数が正の場合だけ新しい状態を
導入します。このため弾性衝突や同一性保存channelから状態を生成しません。状態層は最小生成反応段数、
反応層は全反応物層の最大値+1であり、候補生成`depth`とは独立です。選択対象までの最短supportを主図、
同率producer、対象消費、対象の正味係数ゼロ参加を関連反応一覧として分離します。主図に出さない反応数を
明示し、反応nodeから完全hyperedgeへ移れるため、経路の判読性のためにcanonical reactionを失いません。
主図内は状態名と`INPUT / INTERMEDIATE / TARGET`、反応番号と短い反応種別だけに限定し、完全反応式、ID、
判定根拠はclick後の詳細へ分離します。edgeはfamily色と方向だけを担い、太さは意味に使いません。
これは到達可能性のviewであり、速度係数・密度・EEDFからreaction fluxを計算するまでは支配経路を
主張しません。静的`pathways.png`は最終screeningで到達できる代表対象を1枚だけ出し、HTMLはviewと
対象状態の切替および表示中経路のPNG取得を担当します。
Reaction evidenceとKineticsは状態を判定しないため、その2レイヤーには`states.csv`を出力しません。
Reaction hyperedge view内の全edgeは同じ太さとし、色をelectron・ion・neutral・surfaceのfamily、線種を4値verdictへ
割り当てます。反応式、reaction type、canonical ID、生成情報、5判定のverdictと理由を同時確認できます。

`assessments/screening/`は判定器やpolicyを増やさない派生viewです。State–Consistency、
State–Consistency–Thermochemistry、State–Consistency–Thermochemistry–
(Kinetics OR Reaction evidence)の3段階を別directoryへ出します。最後のgateだけはORであり、
KineticsまたはReaction evidenceの少なくとも一方がpassなら反応を保持します。反応CSVには
両方の元verdict、合成OR verdict、採用根拠を保持します。各段階は残存候補の`states.csv / reactions.csv`、
step別の正確な`summary.csv`、残存率を示す`retention.svg`を持ちます。残存反応networkは
case共通の`assessments/network.html`でviewを切り替えます。
状態に定義されないKineticsとReaction evidenceは`not_applicable`として素通しします。
したがってこれはCandidateSetを破壊するfilter pipelineではなく、個別の4値判定から決定的に作る
pass-only projectionです。
