# Registryの記録と更新

0.7.4のRegistryは生成文法ではなく、出典付きの状態・反応・数値データのローカル証拠源です。

```text
registry/species/*.yaml
registry/reactions/<family>/*.yaml
registry/materials/*.yaml
registry/assets/**
```

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

NASA7にはlow/high各7係数、明示した`t_min <= t_mid <= t_max`、source、phase、
`standard_pressure_Pa`を保存します。係数と温度は有限値、温度は正、範囲は非ゼロです。
気相と固相を組成だけで同一視しません。励起の物性やlumped熱化学は別の根拠が必要です。
NASAモデルが同じ係数、温度域、相、標準圧力を持つ場合は、出典名だけの違いを物理的競合と
しません。元記録は両方保持します。物性・NASAモデルの利用者による優先指定と、反応
エネルギー宣言を独立した量の記録へ分ける拡張は[基盤計画](data_foundation_plan.md)の残件です。

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
原宣言とともに保存できますが、全参加種の共通温度・元素基準・標準圧と必要な規約を確認できなければ
ΔHを計算しません。不正型・負の温度・不正語彙を情報不足へ読み替えません。
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

`derive`による解像準位の形成量offsetは、審査済み親形成量が明示0 K参照を持つ場合だけ生成します。
親の原宣言、level値と出典、共通参照は既存の`source_declaration`へ保存します。有限温度の振動・回転等の
熱寄与差を電子準位energyだけから補いません。新旧の原データの条件確認は引き続き科学データ整備です。

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
保持します。直接Python型も保存実測hashのない表を計算へ使いません。Arrheniusの宣言は[data sources](data_sources.md)
を参照してください。範囲外や不正データは修復対象であり、現象の否定ではありません。

利用者は数値3量について入力の `data_selection` で方法・provider・collectionの優先または
制限、dataset IDの固定を指定できます。記録の適格性確認を飛ばす指定ではありません。
選択要求、採用記録、他の適格記録との不一致は結果に残します。入力例は[README](../README.md)、
規則は[出力仕様](output_reference.md)を参照してください。旧dataset `preferred` は量別要求が
ない場合だけ使う互換指定で、0.8で撤去します。

## 科学量の定義と反応エネルギー

Propertyは`definition`で量の意味を保存します。IE/EAのatomic・adiabatic・verticalを区別し、同じ単位だけでgroundの比較へ流用しません。定義・相・構造・対象が対応しない量は、その利用を未確定にして原宣言へ残します。

channelおよび独立`records`の`energy_properties`は`threshold_eV`と`delta_e_eV`のProperty mappingです。各量にvalue/unit、definition、tier/status/review_scope、method/provenance、uncertaintyを持たせます。新しい明示Propertyは親channelのtierやreviewで昇格しません。親科学宣言自体のrejected/conflictingは含む量も停止します。

旧外部threshold・deltaEのscalarは入口で一度だけ共通Propertyへ正規化し、元宣言を保全します。新Propertyとの二重宣言に矛盾があれば入力エラーです。内部の同義scalar fieldを独立更新する経路はありません。quantityの詳細と移行は[公開形式](output_reference.md)を参照してください。

## 更新操作

```powershell
rgen analyze Ar --evidence registry --out result
acquire lxcat export.txt --out work/lxcat
rgen ingest work/lxcat/snapshot.yaml --result result --overlay work/overlay.yaml
rgen analyze Ar --evidence registry --evidence work/overlay.yaml --out result
rgen adopt work/overlay.yaml --registry registry --dry-run
rgen adopt work/overlay.yaml --registry registry
rgen check --registry registry
```

analyzeとingestはRegistryを変更しません。ingestの成功は照合済みを意味し、科学的承認では
ありません。曖昧な同定、分類不一致、total過程の転記はreview queueで確認します。式だけで
processが不明な入力を既存の型付きチャネルへ推測で転記しません。式のない明示bundle `reaction_id`
入力は、保存対象の物理情報を参照して同定し、原入力も保持します。scope外の宣言は保存できても
その命題の審査資格を持ちません。adoptは明示した
永続採用で、既存の値を黙って置換しません。sourceとasset完全性を採用後も追跡できます。

取得snapshotは `snapshot_version: 1` を宣言します。版なしの従来snapshotも受理しますが、未知の
版は拒否します。変換前ファイルを指定した取得では、rawファイルとSHA-256をsnapshotとともに
保存します。取得・形式受理・照合・永続採用・科学的審査はそれぞれ別の操作です。

DNT由来の測定を記録できますが、主分析はポテンシャル・断面積・時間発展を計算しません。
