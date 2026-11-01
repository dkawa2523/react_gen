# 科学データの表記辞書と登録

外部DB、文献、研究室のファイルを、同じ物理対象・科学量の記録へ読込みます。
出所の登録、形式変換、対象の照合、科学的審査、永続保存は別の操作です。
source catalogへの追加や`ingest`の成功は、値や現象の承認ではありません。
Registryの保存構成と詳細は[記録ガイド](registry_data_guide.md)、判定出力は
[出力仕様](output_reference.md)を参照してください。

## 対象と反応

| 表記 | 意味と必要な区別 |
|---|---|
| `species` | 物理対象の化学式または状態ID。検索名・原行IDはここへ置かない |
| `composition`, `charge` | 明示する場合はIDの組成・電荷と一致すること。式で同定できれば重複入力は不要 |
| `phase` | `gas`等の相。一般snapshotの省略は`unknown`であり、気相の利用根拠にならない |
| `structure` | 異性体等を区別する対象情報。同じ式を、別の構造へ自動割当てしない |
| `state.kind`, `label`, `resolution` | 励起の種類、準位名、`resolved`または`lumped`。解像された準位と集団の値を区別する |
| `reaction` | `A + B -> C + D`。係数は`2 e`等、結合符号は空白付き` + `。電荷の`+`と分ける |
| `family` | `electron`、`ion`、`neutral`、`surface`等、衝突・反応の区分 |
| `type` / 正規`process` | `elastic`、`excitation`、`ionization`、`dissociation`、`attachment`、`charge_exchange`等、調べる過程 |
| `third_body`, `surface`, `stabilization` | 第三体、材料、安定化の宣言。式が同じでもこれらの過程条件が違えば同一チャネルとはしない |
| `channel_scope` | `product_resolved`は指定生成物のチャネル、`total`・`total_process`は合計、`unknown`は未確認。合計から個別生成物へ配分しない |

証拠の対象表記`N2`は`N2@ground`、`H+`は`H+@ground`、`Ar*`は
`Ar@electronic`へ正規化されます。通常の分析入力`gases`は中性基底状態の化学式に限り、
イオン・励起状態を初期ガスとして指定する入口ではありません。気相以外や構造を指定するIDは
`N2@ground;phase=solid`、`C2H6O@ground;structure=...`のように区別します。
`ground/resolved`は、式だけから異性体まで確定したという意味ではありません。
特殊な原準位名・同位体表記は、確認できた対応を明示してください。

旧語彙`ion_neutral/ion_ion`は`ion`、`neutral_neutral/three_body/unimolecular`は
`neutral`、`electron_ion`は`electron`へ正規化します。
`charge_transfer`は`charge_exchange`、`electron_detachment`は
`collisional_detachment`、`neutralization`は`mutual_neutralization`です。
第三体・表面を伴う会合・再結合は、その過程を別に保持します。
未知の原語は`source_declaration`に保全し、似た名前の過程を推測しません。

## 量ごとに必要な情報

次は**その量を科学的に利用するため**の情報です。未確認の欄は不足として保存でき、
形式に存在する全項目を全記録へ要求するものではありません。

| 量・表現 | 利用する情報 | 決まらないこと |
|---|---|---|
| `ionization_energy_eV`、`electron_affinity_eV` | 対象、値・エネルギー単位、定義、資格。`definition`は`atomic/adiabatic/vertical`を区別 | 衝突速度、生成物分岐、有限温度のイオン形成量 |
| `excitation_energy_eV` | 親・準位または集団の同定、値・単位、資格 | 寿命・人口・熱化学モデル |
| `enthalpy_formation_eV` | 上記に加え`formation_reference.temperature_K/basis/standard_pressure_Pa`。必要なイオンでは電子規約 | 熱反応速度、任意温度のΔG |
| `thermochemical_model` | 現行NASA7のlow/high各7係数、`t_min/t_mid/t_max`、相、標準圧、資格 | 電子・励起集団・表面リザーバのモデル、反応障壁 |
| `rate_coefficient`、`constant` | `parameters.value`、単位、反応次数、observable、scope、必要な適用条件、資格 | 別温度への外挿、反応の実在保証 |
| `rate_coefficient`、`arrhenius` | `A/b/Ea`、`parameter_units.Ea`、`reference_temperature_K`、温度の種類、範囲、上記係数の前提 | 未宣言の圧力・浴ガス依存 |
| `cross_section`、`table` | 軸の量と単位、2列数値表asset、断面積のobservable、scope、適用条件、資格 | EEDFや速度係数。運動量移行断面積は反応衝突数の断面積とは別 |
| `sticking_coefficient` | 材料・入射対象、`sticking_probability`、無次元値または曲線、必要な表面条件、資格 | 表面反応速度・エッチング速度。入射流束等が別に必要 |
| `threshold_eV`、`delta_e_eV` | 独立`energy_properties`の値・定義・単位・資格。前者は`channel_threshold/appearance_energy`、後者は`products_minus_reactants` | 出現エネルギーから無条件の衝突閾値、障壁、速度 |
| `reference_only` | 対象と文献・参照情報 | 数値の利用。数値表・式を別途取得する |

新規数値記録では`kind`が量、`form`が表現です。現行計算表現は
`constant`、`arrhenius`、`table`で、文献だけの記録は`reference_only`です。
Arrheniusは`k=A(T/Tref)^b exp(-Ea/(kB T))`です。
NASA9・Shomateやダウンロードされた任意のfitコードを、NASA7等へ転記・実行しません。

速度係数の単位は一次`s-1`、二次`m3/s`、三次`m6/s`等、
断面積は`m2`、確率は`1`を推奨します。同次元の`cm`表記も換算します。
エネルギーPropertyは`eV`、`J`、`J/mol`、`kJ/mol`等を識別します。
単位が同じでも、温度`kB T`と粒子の衝突エネルギーは別量です。

軸は`gas_temperature/electron_temperature/ion_temperature/surface_temperature`、
`electron_energy/collision_energy/ion_energy`、`reduced_field`を区別します。
正規軸単位は温度`K`、エネルギー`eV`、換算電界`Td`です。
通常入力の対応欄は[README](../README.md)を参照してください。
`validity`は`quantity/minimum/maximum/unit`、未対応の原条件は
`unresolved_conditions`で保存します。原条件を保存しただけで適用性を承認しません。

## 出所・資格・ID

| 欄 | 責務 |
|---|---|
| `source.provider` | DB・機関・研究室の識別子。カタログ掲載は不要 |
| `collection`, `release` | 同じprovider内の表・収録群と版 |
| `source.record_id` | 原資料の記録識別子。同じ行番号でも異なる出所の記録を統合しない |
| `citation`, `url` | 原論文・公式資料へ辿る情報 |
| `source_declaration` | 原値・単位・注記・状態名・取得来歴等。判定側は説明文を解析して意味を補わない |
| `method` | `measured/evaluated/calculated/estimated/unknown`。DB名から品質を推測しない |
| `status`, `evidence_tier` | `imported`は未審査。個別審査の`reviewed/curated`等と、`rejected/conflicting`を区別 |
| `review_scope` | 審査した命題・量。`state_existence/channel_assertion/thermochemical_model`または個別量名 |
| `uncertainty`, `qualifier` | 不確かさと科学的な注記。未解釈の上限・近似等を点値へ流用しない |

対象のcanonical ID、科学記録の正規ID、出所の原IDは別です。

数値記録の`reaction_target`は正規物理チャネルIDです。`declared_target`は外部入力に明示された
反応式・反応ID・family・type・第三体・材料・安定化の宣言を入口で構造化したものです。
候補を参照するIDを物理IDへ対応付けた後に照合し、別チャネルの値を転記しません。
反応の原`record_id`は参加状態の原IDへ流用せず、参加状態の表現に派生元として保持します。

取得記録の`source_identity`は取得元が独立に返した組成・構造識別子・名前です。
要求した化学式や検索queryから構造を補いません。取得先が返した構造と通常の候補が異なる場合、
取得成功と、その候補へ数値を利用できることは別です。
新規snapshotの原IDは`source.record_id`へ置きます。正規IDは名前空間付きで生成され、
保存したoverlay/Registryでは保持されます。数値datasetの明示`id`は正規IDなので、
DBの行番号を単独でここへ置かないでください。
値が同じでも別出典は独立記録として保持し、合計・平均・上書きしません。
同じ正規IDの異内容は競合として扱います。取得日時・保存先だけの差は科学的な値の差にしません。

## 最小の登録例と複数出所

次はNIST WebBookの評価IEの実値を用いた**取得記録**の例です。
審査資格・原測定状態の確認は別で、入力しただけで判定根拠へ昇格しません。
このsnapshotは現行loaderで読込み確認しています。
[原資料](https://webbook.nist.gov/cgi/cbook.cgi?ID=C7727379&Mask=21&Units=SI)

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

同じ対象・量の別出所を追加するときは`records`へ別要素を置き、必要ならその要素に
別の`source`を明示します。種・反応名を別名にして出典を表さないでください。
反応のsnapshotでは`species/property/value`に代えて`reaction/type`と、必要な
数値量の`kind/form/unit/parameters/validity`等を記します。
`reaction/type/source`だけの記録は数値を持たない反応主張として読めます。
取得できない値は`value: null`として保存でき、0という仮値で埋めません。

出所ごとにファイルを分けても、同じ分析へ複数指定できます。

```powershell
rgen analyze N2 --evidence registry --evidence lab.yaml --evidence supplier.yaml --out result
rgen ingest external_snapshot.yaml --result result --overlay work/external/overlay.yaml
rgen ingest local_snapshot.yaml --result result --overlay work/local/overlay.yaml
rgen analyze N2 --evidence registry --evidence work/external/overlay.yaml --evidence work/local/overlay.yaml --out result
```

未同定の原宣言は`ingest`のreview queueへ残します。直接`--evidence`で読むsnapshotは
同定可能な対象が必要です。未知のDB書式を、読込み成功のために既存のガス名へ置換しません。
同じoverlayへ複数snapshotを順次`ingest`することもできます。
保存queueは`queue_version: 1`と`review`配列で、各entryへ原recordとsnapshot/source/kindを
保持します。旧queueの共通snapshot/sourceは各entryへ移します。
別出所の未解決入力を次のimportで消さず、同じ原入力の再実行で保留を増やしません。
候補・照合対象の整備後に同じ原入力が採用された場合は、そのentryだけを除きます。
原値・対象・資格等を書き換えた入力は別宣言なので、旧保留の訂正・削除は明示的に行います。
CLIの今回保留数と、保存queueの累計保留数は区別します。
overlayとqueueは同時に保存し、通常の保存失敗では変更を復旧します。
復旧にも失敗した場合は、報告されたbackupを保持します。

量別の選択は`data_selection.quantities`、対象別の上書きは
`data_selection.targets`へ指定します。対象キーは結果のcanonical対象IDです。
現行対象量は数値3量と`enthalpy_formation_eV/ionization_energy_eV/
electron_affinity_eV/excitation_energy_eV/thermochemical_model`です。
`prefer`は指定順の優先、`only`は限定、`record`は保存結果にある正規記録IDの固定です。
まず次の入口で、保存された対象・出所・量・条件と正規IDを確認できます。

```powershell
rgen records result --target N2@ground --quantity ionization_energy_eV
rgen records result --target N2@ground --quantity ionization_energy_eV --detail
```

状態記録の`record_id`、数値記録の`id`を、対象別policyの`record`へ指定してください。
この一覧表示は保存記録の参照であり、記録を承認したり不足を埋めたりしません。
通常表示はID・量の内容・出所・資格を先に返し、`--detail`で原宣言を含む全記録を返します。

```yaml
data_selection:
  quantities:
    rate_coefficient:
      mode: prefer
      methods: [measured, evaluated, calculated]
  targets:
    N2@ground:
      ionization_energy_eV:
        mode: prefer
        providers: [nist_webbook, local_lab]
```

出典の優先は、その量の資格・同定・条件を満たす記録に適用します。
異なるobservable、速度式次数、熱化学基準を出所順位だけで同じ量にしません。
選択した記録・未採用記録・不一致は結果から確認できます。

## 追加した取得経路

`acquire webbook SPECIES.yaml --out WORK`は明示CAS/`C`付きWebBook IDのページを取得します。
取得要求は`[{id: N2, query: C7727379}]`等です。保存HTMLには`--page PAGE.html`を付け、
一対象ずつ変換します。HfとIE/EAの個別行、出典・注記・単位・不確かさ、raw HTML/hashを保存します。
原ページの複数IE/EA測定には異なる初期状態が含まれるため、個別測定行は
`source_state_unconfirmed`で原資料確認まで点値利用を止めます。
評価IEを個別測定へ上書きせず、標準条件の未記載温度・圧力を補いません。
CAS/ページURIは対象の原識別子です。個別測定の公式行IDは未確認のままにし、
converterの`derived_row_key`と作成規則は原宣言側へ保存します。
`source.record_id`にこの派生キーを置かず、既存の科学内容による正規IDを使います。
現行取得対象は中性気相groundです。

`acquire collisiondb DATASET.txt --out WORK`はJSONヘッダと2列の積分断面積を変換します。
対応単位は軸`eV/keV`、面積`m2/cm2`です。
元のstateful反応、frame、合計チャネル、原fit、全体・各点の不確かさ、raw/hashを保存します。
重粒子衝突の元frameは`com/target`を必要とし、欠落・不正は取得形式エラーとして返します。
利用者が軸の種類を指定しても、未宣言の原frameを補ったことにはなりません。
必要な対応は`--reaction/--type/--independent-variable/--observable/--channel-scope`で明示できます。
省略した同定・用途を推測せず、元の状態名をgroundへ潰しません。
微分断面積、質量当たりエネルギー、多列表、欠測点の補間はこのconverterの範囲外です。
fit由来の数表は`calculated`として元の測定方法と分け、明示されたeV fit範囲を保持します。
fitの誤差を実測値全体の不確かさへ読み替えません。

Canteraの`nasa_gas.yaml`の省略標準圧は、当該NASA原資料の1 bar規約に従います。
明示YAMLの標準圧を優先し、他ファイルへこの規約を広げません。
Canteraの省略時ソフトウェア既定1 atmと原係数の参照圧は、原宣言に別々に保存します。
[NASA TM-4513](https://ntrs.nasa.gov/api/citations/19940013151/downloads/19940013151.pdf)

取得経路・利用権は[source catalog](../external_data/source_catalog.yaml)と
[出典方針](source_license_policy.md)を参照してください。
