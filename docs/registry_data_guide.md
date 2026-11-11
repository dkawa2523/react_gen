# 科学記録の形式とRegistryの更新

Registry・snapshot・overlayは、出典付きの状態、反応、数値を共通の科学記録として読み込みます。
Registryはローカル証拠源で、候補生成の文法とは別に管理します。
取得・照合の操作は[データ取得・照合・採用](data_sources.md)、
収録・配布に必要な出典とnoticeは[出典・配布方針](source_license_policy.md)を参照してください。

```text
registry/species/*.yaml
registry/reactions/<family>/*.yaml
registry/materials/*.yaml
registry/assets/**
```

## 対象と反応

| 欄 | 意味 |
|---|---|
| `species`、`composition`、`charge` | 化学式または状態IDが物理対象を指します。組成・電荷を明示する場合はIDと一致させます。 |
| `phase`、`structure` | 一般snapshotの相の省略は `unknown` です。構造は異性体や核種を区別する情報です。任意の構造識別子をSMILESとして解釈しません。 |
| `state.kind`、`label`、`resolution` | 状態の種類、準位名、`resolved/lumped` を分けます。回転準位の例は `H2@J1;kind=rotational` です。`composition/lumped` は組成仮説です。 |
| `reaction`、`family`、`type` | 反応式、衝突・反応の区分、個別の過程です。式は `A + B -> C + D` と書き、係数は `2 e` のように指定します。 |
| `third_body`、`surface`、`stabilization` | 第三体、材料、安定化の宣言です。同じ正味反応式でも、これらの条件や過程が異なれば別チャネルとして扱います。 |
| `channel_scope` | `product_resolved` は指定生成物のチャネル、`total/total_process` は合計、`unknown` は未確認、`energy_relation` はエネルギーの関係量です。 |
| `transformation` | 組成・電荷、準位、明示Lewisグラフ等の変換の宣言です。形式と整合は[公開出力仕様](output_reference.md)を参照してください。 |

`N2` は `N2@ground`、`H+` は `H+@ground`、`Ar*` は `Ar@electronic` へ正規化します。
`ground/resolved` は化学式から異性体が確定したという意味ではありません。
相や構造の指定には `N2@ground;phase=solid`、`C2H6O@ground;structure=...` のような状態IDを使います。
検索名や原資料の行番号は出典として保持します。

旧外部語彙の `ion_neutral/ion_ion`、`neutral_neutral/three_body/unimolecular`、`electron_ion`
はそれぞれ `ion`、`neutral`、`electron` へ正規化します。
`charge_transfer`、`electron_detachment`、`neutralization` はそれぞれ
`charge_exchange`、`collisional_detachment`、`mutual_neutralization` です。
未知の原語は原宣言に保ち、似た名称の過程へ割り当てません。

## 状態と物性

```yaml
id: Ar
composition: {Ar: 1}
charge: 0
phase: gas
state:
  kind: ground
records:
- record_id: identity_record
  source: {provider: local_example, collection: state_identity, citation: "状態同定の出典"}
  existence: confirmed
  existence_source: "当該状態を同定した記録"
  status: imported
  review_scope: [state_existence]
- record_id: mass_record
  source: {provider: local_example, collection: atomic_properties, release: "1", citation: "質量の出典"}
  status: imported
  properties:
    mass_amu:
      value: 39.948
      unit: amu
      method: evaluated
      evidence_tier: imported
      review_scope: [mass_amu]
```

この例は形式の説明で、実在する出典の登録例ではありません。`imported` の宣言は保存できても、
科学的に審査済みとは扱いません。別出典・別モデルは `records` の別要素へ追加します。

Registry IDとcanonical候補IDは区別します。組成・電荷・状態に加え相と構造を照合し、
groundの`resolved`は異性体まで同定済みという意味ではありません。構造固有の記録には
`structure`を付けます。lumped状態には実際の`members`を記し、名前がelectronicというだけで
別準位を排他的としません。

化学式IDで管理しているRegistry種に、原資料で確認したグラフを対応づける場合は、種の
`molecular_identity` に `smiles` と `source` を記します。`source` には書誌情報とURLが必要です。
明示構造を入力した解析でだけ照合に使い、組成、電荷、相、準位、核種を含むグラフが一致する
場合に、その出典が対象とした記録を対応づけます。通常の化学式入力のIDと、原記録の対象IDは保持します。
独立した `records` 要素の出典が同じグラフを明示している場合は、その要素の `molecular_identity`
に照合根拠を記します。種全体に置いた構造宣言を、独立記録へ自動で引き継ぐ規則はありません。
準位差を明示構造に適用するには、その準位記録の構造根拠と参照状態との対応が必要です。
別構造や明示核種の異なる供給へ、化学式IDが共通することだけを理由に準位を適用しません。

存在の主張は`existence`と`existence_source`で記録します。物性がreviewedであること、
Registryにあること、反応式に出ることからconfirmedを自動生成しません。
独立記録の`status`はその科学宣言の受理・拒否状態で、存在・準位根拠の資格にも使います。
旧単一記録形式のstate statusは、
未指定の場合だけmetadataのstatusを使います。
物性とNASAはそれぞれ自身の`evidence_tier`を持ち、未宣言はimportedです。状態metadataの品質を全物性へ
広げません。分子量が既知でも束縛陰イオンの存在は決まりません。

物性・NASA・存在根拠は、対象ごとの独立科学記録として同時に保存できます。overlayは次の
`state_records` 形式で、各要素はRegistryの `records` と同じ記録形式です。

```yaml
state_records:
  Ar@ground:
  - record_id: mass_record
    phase: gas
    source: {provider: local_example, collection: atomic_properties, release: "1"}
    properties:
      mass_amu: {value: 39.948, unit: amu, method: evaluated, evidence_tier: imported}
```

対象IDと科学記録の `record_id` は別です。新しい状態snapshotの `record_id` / `source.record_id` は
原IDで、provider・collection・release・source_idの名前空間から `source-state` 正規IDを生成します。
原IDがなければ科学宣言と出典から `local-state` IDを生成します。保存済みoverlay・Registryでは
`record_id` が正規IDを表し、上の手書き例を含めて既存IDを保持します。原IDは `provenance.record_id`
と原宣言で追跡でき、同じ原ID・出典の旧記録を認識しても保存IDを付け直しません。

同じ科学記録の異内容は黙って上書きしません。値が異なっても物理対象まで別とは扱わず、
使用する量の競合として評価します。存在の矛盾はその存在審査範囲に限って未確定にします。

`ingest` は新形式へ保存し、`adopt` は対象種の `records` へ追加します。旧overlayの
`states/properties/thermo` とRegistry種の単一 `properties/thermo/state` 宣言は読込みadapterで
受け付けます。新しい記録は独立形式を使い、複数出典を一つのmappingへ混ぜないでください。

Propertyのmappingは全読込み経路で同じ形式検証を行います。各量の値には記録mappingを置き、
`mass_amu: 40`や`mass_amu: null`を値不足へ変換して消しません。未取得の値は
`mass_amu: {value: null, unit: amu}`のように記録内で示せます。記録の不正型は入力エラー、
値や参照条件の不足はその量の利用条件の不足として扱います。

snapshotとoverlayの物理対象は、化学式・状態IDと明示した組成、電荷、相、構造、状態欄を
共通規則で照合します。IDが`;phase=gas`を述べるのに別欄が`phase: solid`を述べるなどの
矛盾は、読込み時の入力エラーです。検索名や出典の行IDを物理対象IDへ読み替えません。
RegistryのローカルIDは別で、種の明示した組成・電荷・状態等からcanonical対象を作ります。

### 出典と資格

`provenance` はprovider、collection、release、record_id、citation、URL等の正規出典情報です。
`source` の明示識別子も入口でここへ正規化します。`source_declaration` は原宣言・補足を保全し、
`method` は measured / evaluated / calculated / estimated / unknown、`review_scope` は
宣言された審査範囲を保存します。方法と出典とtierは別です。存在根拠の承認を物性やNASAの
承認へ一括適用しません。各物性・モデルにも必要な方法・資格を明示します。

| 宣言 | `review_scope`で指定する審査対象 |
|---|---|
| 状態の存在 | `state_existence` |
| 個別物性 | `ionization_energy_eV`、`electron_affinity_eV`、`enthalpy_formation_eV`等の物性名 |
| NASAモデル | `thermochemical_model` |
| 反応根拠・エネルギー | `channel_assertion`、`threshold_eV`、`delta_e_eV` |
| 数値dataset | その`kind` |

明示scope外の宣言と `status: rejected/conflicting` は、資格あるtierでも採用しません。
scopeは承認を与える命題、statusは宣言の受理・拒否状態です。親科学記録の拒否・競合はその
宣言全体の利用停止で、個別Property・NASAの審査から復活させません。部分的に否定・未確定の
存在主張と、適格な物性を別資格で保持したい場合は独立記録へ分けてください。
Property・NASAにも独立したstatusを保存します。Propertyの `qualifier` は非束縛等の科学的内容を
表し、管理上のstatusと区別します。拒否statusを物理現象の否定へ転用しません。
空または省略scopeの旧記録は各型の既存資格を維持しますが、
資格・同定・適用条件の確認を省略しません。新規のレビューでは確認した命題を明示してください。

NASA7にはlow/high各7係数、明示した`t_min < t_mid < t_max`、source、phase、
`standard_pressure_Pa`を保存します。low/highが同じ係数の単一区間では境界の`t_mid`も受理します。
係数と温度は有限値、温度は正、範囲は非ゼロです。
気相と固相を組成だけで同一視しません。励起の物性やlumped熱化学は別の根拠が必要です。
NASAモデルが同じ係数、温度域、相、標準圧力を持つ場合は、出典名だけの違いを物理的競合と
しません。元記録は両方保持します。計算が利用する物性・NASAモデルは`data_selection`で
量別・対象別に優先・限定・record固定できます。資格・定義・参照条件はその指定でも検査します。
登録・選択の必要情報は[量ごとに必要な情報](#量ごとに必要な情報)、結果の規則は[公開出力仕様](output_reference.md)を参照してください。

### 形成エンタルピーの参照

形成量の比較基準はPropertyの`formation_reference`へ保存します。次は形式の説明用の合成値で、
科学データの登録・審査例ではありません。

```yaml
enthalpy_formation_eV:
  value: 1.0
  unit: eV
  evidence_tier: imported
  formation_reference:
    temperature_K: 298.15
    basis: standard_elements
    standard_pressure_Pa: 100000.0
    electron_convention: electron
```

温度は0 K以上、標準圧は正、数値は有限値です。`basis: standard_elements`は明示温度・圧での
各元素の標準参照状態からの形成量を表します。対象の相・構造・電子状態は状態記録で同定します。
電子規約は`ion`または`electron`で、必要なイオンの参照へ記録します。参照欄が不足した値も
原宣言とともに保存できますが、正味寄与する参加種の共通温度・元素基準・標準圧と必要な規約を確認できなければ
ΔHを計算しません。不正型・負の温度・不正語彙を情報不足へ読み替えません。
上限・下限等を含む未解釈の`qualifier`を、reviewedという理由で通常の点値として加減算しません。
注記と原値は保持し、点値としての意味が確定するまで依存するΔHを未確定にします。
中性形成量の比較には電子規約・電子形成量を使いません。有限温度のイオンでは、規約を明示した
同値の適格記録があれば規約未定の記録でその値を隠しません。未定記録の規約を補完したことにはせず、
元宣言はそのまま保持します。異なる明示規約は共通値として無言で選択しません。

0 Kでは両電子規約は一致します。有限温度の`electron`規約では電子の形成量は0です。
有限温度の`ion`規約で自由電子の係数が左右で変わる反応には、同じ参照での
`electron_enthalpy_eV`を非負の明示値として必要とします。左右で電子項が相殺される反応には不要です。
この補助量の欠落・差は、電子項が必要な反応だけへ作用します。同値・同じ基準の適格記録に
電子項未宣言と明示値がある場合は、必要な電子項を持つ記録をProperty全体として使用し、元の未定記録を
書き換えません。異なる明示電子項は依存するΔHを未確定にします。Electron Conventionの未宣言と0は
定義上同義です。
電子項の完備度で記録を絞る前に、同定済みの形成量と参照基準の整合を確認します。
電子項が未宣言でも、同じ基準の審査済み形成量が異なる値を述べていれば反対値を消しません。
未宣言の電子熱モデル、異なる規約・温度の変換を補いません。
[NISTの電子熱化学規約](https://webbook.nist.gov/chemistry/ion/)がこの区別の根拠です。

出力ΔHの参照温度・標準圧は`delta_h_reference_temperature_K`・`delta_h_standard_pressure_Pa`です。
気体温度を入力しても未参照の形成量は補完されません。参照不足はΔHだけに作用し、独立したNASA計算や
IE/EA等の判定を止めません。旧結果と旧Registryの値は読み込めますが、再分析ではこの使用前提を適用します。
移行では元資料を確認して各Propertyへ参照を付け、出典と審査を個別に記録してください。

`derive`による解像準位の形成量offsetは、個別に適格な親形成量と準位energyから、明示0 K共通参照で
生成します。準位は非負の有限energyと解像対象を必要とし、親記録の拒否・競合、Propertyの
審査対象外・未解釈注記をtierだけで昇格させません。独立した適格な記録は別に利用できます。
親形成量と準位Property全体、共通参照を`source_declaration`へ保存します。有限温度の振動・回転等の
熱寄与差や不確かさ伝播を電子準位のエネルギーだけから補いません。質量は励起エネルギーの不足と独立に、
適格な親状態の質量または原子質量から近似し、使用したPropertyと不足した質量の対象を保存します。

## 量ごとに必要な情報

次は各量を科学的に利用するための情報です。未取得の値と未確認の条件は不足として保存できます。

| 量・表現 | 利用する情報 |
|---|---|
| `ionization_energy_eV`、`electron_affinity_eV` | 対象、エネルギー単位、資格、`definition: atomic/adiabatic/vertical`。関係先が明示される場合は対応する正イオン／負イオンの基底状態。 |
| `excitation_energy_eV` | 準位または集団の同定、値、単位、資格。同電荷・同構造の参照基底状態を `related_state` で示します。集団の代表値は単一終状態を定めません。 |
| `enthalpy_formation_eV` | 共通の参照温度、元素基準と、量に応じた標準圧・電子規約。有限温度の値を単一衝突の0 K状態差へ転用しません。 |
| `proton_affinity_eV`、`gas_basicity_eV` | `related_state` に対応する共役酸の状態、`formation_reference.temperature_K` に参照温度を置きます。GBでは共通の明示標準圧も必要です。 |
| `mass_amu` | 対象と正の質量、`u/amu/Da`、資格。lab→COM換算には実際の参加粒子の質量を使います。 |
| `thermochemical_model` | NASA7のlow/high各7係数、境界温度、相、標準圧、資格。 |
| `rate_coefficient` | `constant` の値、または `arrhenius` の `A/b/Ea`、`parameter_units.Ea`、`reference_temperature_K`。単位、速度式の次数、測定量、チャネル範囲、適用条件、資格を記録します。 |
| `cross_section` | 軸の量と単位、2列の数値表asset、測定量、チャネル範囲、適用条件、資格。運動量移行断面積と反応断面積を区別します。 |
| `sticking_coefficient` | 材料・入射粒子、`sticking_probability`、無次元値または曲線、必要な表面条件、資格。入射流束は別の入力です。 |
| `threshold_eV`、`delta_e_eV` | 反応記録の独立 `energy_properties` に対象、値・単位、定義、資格を置きます。前者の `channel_threshold/appearance_energy` と後者の `products_minus_reactants` を区別します。 |
| `reference_only` | 対象と出典を保持します。数値用途では数値表または式を別途取得します。 |

`kind` は量、`form` は表現です。Arrheniusは `k=A(T/Tref)^b exp(−Ea/(kB T))` です。
速度係数は一次 `s-1`、二次 `m3/s`、三次 `m6/s`、断面積は `m2`、確率は `1` を推奨します。
`validity` の軸は `gas_temperature/electron_temperature/ion_temperature/surface_temperature`、
`electron_energy/collision_energy/ion_energy`、`reduced_field` を区別し、正規単位は `K/eV/Td` です。
温度のエネルギー表現と粒子の衝突エネルギーは別量です。Propertyのエネルギー単位の例は `eV`、`J`、`J/mol`、`kJ/mol` です。

## 反応とdataset

```yaml
pair: {family: ion_neutral, projectile: Ar+, target: O2}
channels:
- id: Arp_O2_charge_transfer
  type: charge_exchange
  products: [{species: Ar}, {species: O2+}]
  records:
  - id: local_example_channel
    reaction: "Ar+ + O2 -> Ar + O2+"
    type: charge_exchange
    status: reviewed
    source: {provider: local_example, collection: channels, record_id: channel_row}
    review_scope: [channel_assertion]
  data:
    datasets:
    - id: measured_rate
      kind: rate_coefficient
      representation: constant
      unit: m3/s
      independent_variable: gas_temperature
      observable: reaction_rate
      channel_scope: product_resolved
      reaction_order: 2
      parameters: {value: 1.0e-15}
      validity: {quantity: gas_temperature, minimum: 298, maximum: 298, unit: K}
      status: reviewed
      method: measured
      review_scope: [rate_coefficient]
      source: {provider: local_example, collection: rates, record_id: rate_row}
```

例の数値は形式の説明です。反応の左右、第三体、表面、family、processを照合します。
保存だけでは分類を承認しません。直接付着と解離性付着、elasticと電荷交換を区別します。
放射・第三体・壁などの安定化を宣言する場合は`stabilization`に意味を記録します。

同じpairの別ファイルにあるchannelも全件読込みます。channel IDはRegistry全体で一意にし、
重複は同内容でもファイルと位置付きで拒否します。一つのchannelの `records` に同じ物理反応の
独立出典を追加できるため、出典ごとにchannel自体を複製する必要はありません。
数値datasetの同一ID・異なる科学宣言は消さずに数値のID競合として評価します。

`validity`の区間は`quantity`、`minimum`、`maximum`、`unit`で表し、評価未対応の物理条件は
`unresolved_conditions`に原値とともに保持します。旧`conditions` mappingも受理し、
`method`・`derivation`は原宣言の注記、それ以外は未評価条件へ正規化します。既知の値・区間は
維持し、未評価条件を`external_models`の必要作業として返します。温度だけで利用可能としません。
未知の正規欄は形式エラーです。原条件の保存と、その条件を消費する物理モデルの実装・審査は
別の操作で、原欄を移しただけで適用性が確定するわけではありません。

反応の科学宣言は直接snapshot、overlayの `reaction_records`、channelの `records` で同じ
`ReactionRecord`へ正規化します。overlayでは対象反応IDをキーにした記録配列を持ち、各要素は
上の `records` と同じportable形式です。通常は `ingest` が対象IDと保存payloadを作ります。
各要素は `id`、`reaction`、`type`、必要なfamily・third_body・surface・stabilization、scope、
status/tier、threshold・deltaEの宣言、出典・方法・原宣言を保持します。保存配列の `id` は科学記録の
正規IDで、対象反応IDやRegistry channel IDと区別します。

新規snapshotでは原 `record_id` から `source-reaction`、原IDのない科学宣言から `local-reaction`、
明示 `id` から `reaction-record` IDを生成します。数値datasetとは別のIDを持ち、保存後は保持します。
純粋なチャネル・エネルギー主張には空datasetを生成しません。数値を併記したsnapshotは数値を
別途overlayの `datasets` / channelの `data.datasets` に保存します。反応の独立 `records` に
`datasets` を埋め込む形式は拒否します。旧channel直下のscalar・source宣言は読込み互換を維持します。

datasetの明示 `id` は全体で一意な正規IDです。原資料の行IDは `source.record_id` または
数値snapshotの `record_id` に置きます。正規IDがなければ、明示したprovider・collection・release・
source_idと原記録IDから生成します。異なるDBの同じ行番号を同一記録としません。同じ原記録の
異内容は競合です。原記録IDもない場合は、原宣言と正規出典情報のcontent IDを使います。

同じ科学記録を再取得した日時・保存先だけの差は、値の競合にしません。取得宣言の異なる記録は
同じ正規IDで配列へ併記し、未知の物理条件・注記や数値資格の違いは科学宣言の差として保持します。
この比較は状態・反応・数値に共通です。完全な再入力は重複追加せず、原宣言の取得履歴を消しません。
科学内容が変わる同ID入力はingestでreview queueへ、adoptでは入力エラーとして扱います。
constant/Arrheniusの既知単位コピーは共通の換算比較を使い、同単位の異値を厳密に区別します。
絶対不確かさの別単位は同次元の場合だけ値の単位へ正規化し、原宣言を保存します。

反応記録の `review_scope` は `channel_assertion`、`threshold_eV`、`delta_e_eV` を区別します。
`delta_e_eV` は入力の `deltaE_products_minus_reactants_eV` 宣言の審査対象名です。
明示scopeがある場合、reviewed tierをscope外の主張へ流用しません。数値snapshotのscopeを
省略した場合はその数値量へ限定し、係数の審査からチャネルやエネルギーを承認しません。
scopeのない従来の独立チャネル宣言は互換として既存資格を維持します。新規の科学的審査は
対象の主張を明示してください。数値のみのoverlayはチャネル存在根拠になりません。

datasetは測定量、軸、単位、適用条件、出典を明示します。温度のKだけからTg/Teを推定しません。
datasetに `review_scope` を明示する場合は、`rate_coefficient`、`cross_section`、
`sticking_coefficient` のうち当該 `kind` を含めます。チャネルだけの審査を数値に流用しません。
`reference_only`は数値データではなく、totalデータは個別生成物チャネルへ割り当てません。
tableは参照assetと宣言／保存実測hashを保持し、実際に解析するbytesを照合します。保存hashを
現在値へ置換せず、同じ検証済みbytesの保存場所だけで科学競合にしません。原参照と取得来歴は
保持します。直接Python型も保存実測hashのない表を計算へ使いません。
範囲外や不正データは修復対象であり、現象の否定ではありません。

利用者は数値3量について入力の `data_selection` で方法・provider・collectionの優先または
制限、dataset IDの固定を指定できます。記録の適格性確認を飛ばす指定ではありません。
優先`prefer`は同じobservable・速度式次数に属する記録の出典順位に適用します。
異なる断面積の測定量や速度式次数を、出典順位だけで一つの量へ決めません。用途に必要な
量・モデルを選ぶ場合は`record`で固定するか、`only`で該当する出典へ限定します。
限定後も異なる量・モデルが残れば、選択を未確定として返します。
選択要求、採用記録、他の適格記録との不一致は結果に残します。入力例は[README](../README.md)、
規則は[出力仕様](output_reference.md)を参照してください。旧dataset `preferred` は量別要求が
ない場合だけ使う互換指定で、2.0で撤去します。

個別datasetの判定は、その記録が述べる量の数値利用可否です。保存された断面積曲線が有効でも、
分布に対する積分や速度係数の成立は決まりません。付着確率が使えても、入射流束と表面速度への
変換は別の必要処理です。これらの変換作業は係数用途の`DataUse`へ分けて保存し、個別の
曲線・確率の判定へ重ねません。運動量移行断面積は反応衝突数を数える断面積と異なる量で、
エネルギー分布との積分だけでは反応速度係数へ変換できません。

## 科学量の定義と反応エネルギー

Propertyは`definition`で量の意味を保存します。IE/EAのatomic・adiabatic・verticalを区別し、同じ単位だけでgroundの比較へ流用しません。定義・相・構造・対象が対応しない量は、その利用を未確定にして原宣言へ残します。

`related_state` は関連する正規状態IDです。EAは電子束縛で放出されるエネルギーを正とし、
負イオンの基底状態差には適格な正のEAを使います。
分子の基底状態差には断熱IE／EAが必要です。原子の定義未指定値に対する互換処理は分子へ適用しません。
プロトン移動 `AH+ + B → A + BH+` では、同温度の `PA(A)−PA(B)` をΔH、
同温度・同標準圧の `GB(A)−GB(B)` をΔG°として別々に扱います。
これらの有限温度量と単一衝突の0 K状態差は独立です。[NISTの量定義](https://webbook.nist.gov/chemistry/ion/)

channelおよび独立`records`の`energy_properties`は`threshold_eV`と`delta_e_eV`のProperty mappingです。各量にvalue/unit、definition、tier/status/review_scope、method/provenance、uncertaintyを持たせます。新しい明示Propertyは親channelのtierやreviewで昇格しません。親科学宣言自体のrejected/conflictingは含む量も停止します。

断面積表の閾値比較は、曲線の `validity.unresolved_conditions.energy_frame` と閾値の `source_declaration.energy_frame` または `source_declaration.frame` が比較できる場合に行います。`com` は重心系、`target` と `lab` は静止標的への入射エネルギーを示します。異種の重粒子対の実験室系同士は、`projectile_state` で指定した入射粒子も一致した場合に比較します。同一状態の粒子対は等質量として座標系を換算します。異種粒子対で座標系が異なる場合は、曲線を保持して閾値との照合を保留します。 [IAEA CollisionDBの座標系](https://doi.org/10.1088/1741-4326/acf5da)

外部の旧scalar形式と現行の`energy_properties`を併記する場合は、換算値の一致が必要です。[量の定義と互換形式](output_reference.md#量の定義と独立した反応エネルギー)

D₀は指定の親状態から指定フラグメント状態への0 K差です。
関係量だけを記録するときは `channel_scope: energy_relation` とします。
逆向きの記録を用いる場合は原値と符号を反転する係数を保存します。
次は値と出典を調べる前の入力形式です。

```yaml
snapshot_version: 1
records:
- reaction: F2@ground;phase=gas -> 2 F@ground;phase=gas
  family: neutral
  type: dissociation
  channel_scope: energy_relation
  status: imported
  energy_properties:
    delta_e_eV:
      value: null
      unit: eV
      definition: products_minus_reactants
      formation_reference: {temperature_K: 0}
      status: imported
```

現行計算は、解像された気相端点への直接差、共通参照の0 K形成量差、D₀・IE・EA・準位差を使う限定的なサイクルを扱います。
適格な複数案が食い違う場合は各入力と不一致を保持します。定義を省略した旧エネルギー差を0 K関係量として推定しません。

## snapshotの入力例

次はWebBookの評価IEを未審査の取得記録として保持する例です。[原資料](https://webbook.nist.gov/cgi/cbook.cgi?ID=C7727379&Mask=21&Units=SI)

```yaml
snapshot_version: 1
kind: state_property
source:
  provider: nist_webbook
  collection: SRD69
  citation: NIST Chemistry WebBook, SRD 69
  url: https://webbook.nist.gov/cgi/cbook.cgi?ID=C7727379&Mask=21&Units=SI
records:
- species: N2
  phase: gas
  property: ionization_energy_eV
  value: 15.581
  unit: eV
  uncertainty: {absolute: 0.008, unit: eV}
  method: evaluated
  status: imported
```

別出典を追加する場合は `records` に要素を追加するか、別ファイルを `--evidence` に指定します。
反応記録は `reaction/type` で対象を記し、数値を持つ場合だけ `kind/form/unit/parameters/validity` 等を添えます。
未取得の値は `value: null` とします。

共通の `source` はマッピングで指定します。省略または `null` の場合は共通出典の指定なしとして扱います。数値記録では個別の `kind` を優先し、共通の `kind` も省略または `null` の場合は `rate_coefficient` を使います。`--evidence` と `ingest` は同じ規則で読み込みます。

## 更新操作

```powershell
rgen analyze Ar --supply e --evidence registry --out result
acquire lxcat export.txt --out work/lxcat
rgen ingest work/lxcat/snapshot.yaml --result result --overlay work/overlay.yaml
rgen analyze Ar --supply e --evidence registry --evidence work/overlay.yaml --out result
rgen adopt work/overlay.yaml --registry registry --dry-run
rgen adopt work/overlay.yaml --registry registry
rgen check --registry registry
```

analyzeとingestはRegistryを変更しません。ingestの成功は照合済みを意味し、科学的承認では
ありません。曖昧な同定、分類不一致、total過程の転記はreview queueで確認します。式だけで
processが不明な入力を既存の型付きチャネルへ推測で転記しません。式のない明示bundle `reaction_id`
入力は、保存対象の物理情報を参照して同定し、原入力も保持します。scope外の宣言は保存できても
その命題の審査資格を持ちません。adoptは明示した永続保存です。入力のsource、tier、status、
review_scopeを保持し、Registryへの保存を理由にimportedをreviewed/curatedへ昇格しません。
既存の値を黙って置換せず、sourceとasset完全性を採用後も追跡できます。正当に同定された対象でも
更新先がない場合は`unplaced`として返し、対象記録の形式不正やID矛盾とは区別します。

取得snapshotは `snapshot_version: 1` を宣言します。版なしの従来snapshotも受理しますが、未知の
版は拒否します。変換前ファイルを指定した取得では、rawファイルとSHA-256をsnapshotとともに
保存します。取得・形式受理・照合・永続採用・科学的審査はそれぞれ別の操作です。

直接`--evidence snapshot.yaml`で分析する記録は、そのsnapshotだけで物理対象を同定できる
必要があります。未同定の種・式を黙って捨てません。既存候補との照合や保留が必要な外部名は
`ingest`へ渡し、候補と理由・原記録を`review_queue.yaml`に残します。
未同定名や壊れたPropertyを旧overlayへ置いていた場合も、この明示した入口へ移行してください。
取得用の`id`と`query`、adapterの対象範囲と失敗分類は[data sources](data_sources.md#取得要求の対象と検索名)
を参照してください。

DNT由来の測定を記録できますが、主分析はポテンシャル・断面積・時間発展を計算しません。
