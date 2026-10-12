# データ源と証拠の流れ

0.7.2の候補生成は証拠と独立した有限文法による列挙です。`analyze`は指定したローカル証拠だけを
読み、取得やRegistry変更を行いません。取得、照合、科学的レビュー、永続採用は別操作です。

```text
外部データ -> acquire -> snapshot.yaml と原本・参照asset
  -> rgen ingest SNAPSHOT --result RESULT --overlay OVERLAY
       一意に照合できる記録 -> overlay
       同定不足・分類不一致・totalデータ -> review_queue.yaml
  -> rgen analyze Ar CF4 --evidence registry --evidence OVERLAY --out result
  -> 明示的な rgen adopt OVERLAY --registry registry
```

照合成功は科学的承認ではありません。`status: imported`の数値はレビュー前の値として保持し、
自動でreviewedへ昇格しません。Registryへの所属も個別物性の品質を保証しません。

## 出典と原宣言の管理

`external_data/source_catalog.yaml`は提供量・取得方法・converter・確認すべき利用条件を示す
一つの台帳です。`acquire sources`はこのローカル台帳を表示します。台帳の登録は科学的承認、
利用許諾、分析時の優先順位を意味しません。ユーザーデータのproviderは台帳への登録なしでも
明示できます。取得先ごとの条件は[source/license policy](source_license_policy.md)を参照してください。

各記録の`provenance`はprovider、collection、release、record_id、citation、URL等の出典情報です。
`method`は`measured`・`evaluated`・`calculated`・`estimated`・`unknown`、
`tier`は証拠の資格、`review_scope`は宣言されたレビュー対象を表します。存在には
`state_existence`、Propertyにはその物性名、NASAには`thermochemical_model`、反応には
`channel_assertion`・`threshold_eV`・`delta_e_eV`の資格をそれぞれ確認します。
明示scope外と`status: rejected/conflicting`の値は、reviewed tierでも採用しません。
scopeは承認する命題、statusは科学宣言自体の受理・拒否状態です。親状態記録の拒否・競合は
その宣言全体の利用停止で、個別Property・NASAの審査から復活させません。部分的な存在否定と
適格な物性を別資格で保持したい場合は独立記録へ分けます。
Propertyの`qualifier`は非束縛等の科学的内容として別に保持し、管理上の拒否statusから
現象の不存在を導きません。空または省略scopeの旧記録には各型の既存資格を維持しますが、
scope省略だけでtierを昇格しません。数値snapshotはscope省略時もその数値kindに限定します。
係数のレビューを反応・閾値の承認へ広げません。これらを分け、
provider名やsource_typeの文字列から測定方法・品質を推測しません。元の欄、注記、原資料は
`source_declaration`に保持します。方法やレビュー範囲が不明なら、その不明を残します。

新しいsnapshotは`snapshot_version: 1`を持ちます。版なしの既存snapshotも読み込めますが、
未対応の版は入力エラーです。LXCat・UMISTのファイル変換は原本をsnapshot内の`raw/`へ保存し、
`acquisition`にファイル名・相対path・完全なSHA-256を記録します。`acquire fetch`は台帳の
明示したHTTPS file URLだけを取得し、原本と`acquisition.yaml`へ要求URL・最終URL・取得時刻・
完全なSHA-256・形式と形式版を保存します。形式版の判別はDBのreleaseや科学的品質の確認ではありません。

入力ファイルの隣にある`acquisition.yaml`は同じfile名と完全なhashが一致した場合に限り、
`acquisition.source_manifest`としてsnapshotと科学記録の原宣言へ引き継ぎます。取得URL・時刻・
明示されたprovider/collection/releaseを保持し、変換先の`raw_path`と元manifest内のpathを
区別します。別fileのmanifestは引き継ぎません。同名hashの不一致、不正形式、重複した欄は
書込み前にエラーになります。source_idからproviderやreleaseを推測しません。

旧`source_access_profiles.yaml`と`sources.yaml`は台帳へ統合して撤去しました。
今回の移行前の原本とhashは`build/source_catalog_migration/`へ保存しています。
既存の独自fetch台帳は`--catalog`で指定でき、旧`id`欄も取得用adapterで読みます。
旧priority/profileを分析の選択設定として利用する経路はありません。

## 同定と存在根拠

数値の明示`id`は正規ID、`source.record_id`は原資料のIDです。UMIST変換は原fit IDを保持し、
正規IDを共通読込みで生成します。明示releaseの異なる同じ行番号を混同しません。既存の
正規IDを持つsnapshotや保存結果は、読込みでIDを再生成しません。

新しい状態snapshotの`record_id`または`source.record_id`は原IDとして、provider・collection・
release・source_idとともに`source-state` IDを生成します。原IDがなければ科学宣言と出典から
`local-state` IDを生成します。保存済み`state_records`とRegistryの`records`では`record_id`を
正規IDとして保持します。同じ原ID・出典の旧記録へ追加する場合も、既存IDを維持します。

組成、電荷、相、構造、状態の指定を照合します。異相をexact照合せず、構造固有値を
化学式だけの候補へexact転記しません。相を記さないsnapshotの物性は相不明の関連証拠です。

物性やNASA係数から状態の存在を確定しません。状態の主張には`existence`、
`existence_source`、その主張の`status`を明示します。reviewed反応記録も全参加状態の
存在確認には読み替えません。reviewed数値datasetだけでも、反応自体の証拠判定を成立へ昇格させません。

`--evidence`はRegistry directoryとsnapshot/overlay fileに対応し、繰り返し指定できます。
存在しない明示パスや認識できない形式は入力エラーです。順序で競合を解消しません。
同じ対象の別出典は独立したStateRecordとして残し、新しいoverlayでは`state_records`、
Registry種では`records`配列に保存します。物性値の不一致は量の競合として扱い、同定済みの
対象や別の有効な量を失わせません。無修飾のnull物性は一致する値で補完できても、非束縛等の
否定根拠は消しません。形式は[Registry guide](registry_data_guide.md)を参照してください。

同じ科学記録の再取得では、標準`acquisition`情報の日時・保存先だけの差を内容競合に
しません。匿名IDにも同じ科学内容比較を使います。未知の物理条件、注記、方法、資格、値は
比較へ残します。原宣言は削らず、取得の異なる記録を併記し、完全な再入力は重複追加しません。
同IDの科学内容変更はingestでreview queueへ送り、adoptでは上書きせず入力エラーにします。

## 反応主張の独立保存

反応式、process、第三体・表面・安定化を共通の`ReactionRecord`へ正規化します。直接snapshotで
評価するチャネル根拠、threshold、deltaEを、ingestではoverlayの`reaction_records`へ、adoptでは
Registry channelの`records`へ保存し、同じ命題の評価へ戻します。対象反応IDと科学記録IDは別です。
原IDから`source-reaction`、原IDがない宣言から`local-reaction`、明示snapshot `id`から
`reaction-record` IDを生成し、保存後のIDは再生成しません。出典・方法・審査範囲と原宣言も保ちます。

純粋な反応主張には空の数値Datasetを作りません。数値を併記したsnapshotでは数値を別途
overlayの`datasets`へ、採用後はchannelの`data.datasets`へ保存します。数値だけを審査した記録は
チャネル根拠へ昇格しません。独立反応`records`の要素に`datasets`を埋め込む形式は拒否します。

式だけでprocessが不明な入力は、既存の型付きチャネルへ推測で転記せずreview queueへ置きます。
式を持たず明示したbundleの`reaction_id`を参照する入力では、その保存対象から物理対象を同定し、
元の入力宣言も保持します。同じIDの別エネルギー量だけの差から、チャネル根拠の競合を導きません。

## 数値データと利用者の選択

取得元によらず同じ`NumericDataset`へ正規化し、同じ数値評価へ渡します。

| 項目 | 意味 |
|---|---|
| kind / form | 断面積、速度係数、付着確率と、table・constant・arrhenius・reference_only |
| unit / observable | 数値の次元と測定量。momentum transferと反応断面積を区別する |
| independent_variable / validity | 物理量、適用範囲、単位。TgとTeを区別する |
| reaction_order | sourceが宣言する速度式の次数。未宣言時は許可された素反応の次数を使う |
| reference_temperature_K / parameter_units | Arrhenius基準温度と活性化項の単位 |
| channel_scope | product_resolved、total等の対象範囲。不明を個別生成物の値へ補完しない |
| provenance / source_declaration | 出典と元の宣言。sourceの表示文字列も保持する |
| method / status / tier / uncertainty | 生成方法、証拠の資格、不確かさ |
| asset | 参照path、実測sha256、元のdeclared_sha256 |

入力の`data_selection.quantities`で、`rate_coefficient`・`cross_section`・
`sticking_coefficient`ごとにmethod、provider、collectionの`prefer`順または`only`限定、
特定recordを指定できます。同じ適用性評価の後に選択するため、優先指定で未レビュー・
誤単位・範囲外・対象不一致のデータを利用可能にはしません。適用条件が不足する優先記録は
必要入力を返します。採用値と競合・不一致記録は正規結果へ残します。

指定した量では旧datasetの`preferred`を使いません。未指定の量に残る`preferred`は移行用の
互換処理です。具体的な入力と選択規則は[README](../README.md)を参照してください。
物性・NASAモデル・存在根拠の優先指定は未対応で、指定すると入力エラーになります。
これらの選択と、反応threshold/deltaEの独立した出典・不確かさ・参照条件は[残件計画](remaining_work_plan.md)へ置いています。形成量の共通参照型と比較前提の検査は実装済みです。

同一dataset IDの異内容は競合です。不正・範囲外・未レビューの記録も結果へ残し、修復・
代替取得の対象にします。数値の不適用は反応不存在を意味しません。断面積から速度への
分布積分、付着確率から表面fluxへの変換は別の必要処理として返します。

assetは作者の宣言hashと保存時の実測hashを分けて保持します。表を使う際は保存hashを
照合した同じbytesを解析し、再読込みや読込み後の変更で新しい値を無言で採用しません。
adoptは検証したbytesをRegistry内へコピーし相対pathにします。同じ科学内容と検証済み
bytesの保存場所だけでは競合にせず、各取得の原宣言・参照場所は残します。検証できない
bytesや異なる科学条件を同一化せず、宣言hash不一致のデータには計算資格を与えません。

## 取得adapterの範囲

### UMIST

`acquire umist`はRATE12の8欄fitとRATE22の9欄fitを区別します。ファイル全体から形式が
一意に決まらない場合は`--format-version RATE12`または`RATE22`を要求します。
各行の全fit、数値、温度範囲を検証し、不正な行やfitを一部だけ利用せず、行番号と理由を返します。
元行、方法欄、accuracy、reference、note、形式版、反応IDを保持します。M/C/Eはそれぞれ
measured/calculated/estimated、L等はunknownとして原宣言を残します。

二体係数を`k=A(T/300)^b exp(-Ea/(kB T))`へ変換し、宣言された温度範囲を別datasetにします。
電子を反応物に含む記録はelectron_temperature、他はgas_temperatureを軸にします。
これだけで電子分布やプラズマ環境への適用を確認したことにはなりません。光・宇宙線過程
CP/CR/PHと二体以外は数値snapshotの対象外で、保存した原本で確認できます。
[RATE12一次資料](https://www.aanda.org/articles/aa/pdf/2013/02/aa20465-12.pdf)、
[RATE22一次資料](https://umistdatabase.uk/files/UDfA2024.pdf)

同じ過程・式の別行が温度範囲で重なる場合、和の成分か代替値かを確定できないため、
全成分をparametersと原行付きの`reference_only`として保持します。加算モデルの科学的同定と
評価は残件です。2026-10-12に確認した[公式RATE22原本](https://umistdatabase.uk/files/rate22_final.rates)
（SHA-256 `2f83cdd0905e5dd50494f23bc5faf559a617d866b365cf9d1c5fef3621a1a219`）は、
5488行の余分な引用符をstrict parserが拒否します。この原本の全件変換が成功したとは扱わず、
修正する場合は原本と修正内容を別に保存してください。

### LXCat

LXCat/BOLSIG+のenergy eV・cross section m2の二列表に対応します。明示された`COLUMNS`の
別単位・別量・列順はエラーにし、壊れた数値行や未完のprocess/tableを捨てません。
header省略時はこの対応形式の固定単位を使います。CSV化で数値の桁を切り詰めません。

全headerを保持し、`CHANNEL SCOPE`・`CHANNEL_SCOPE`・`SCOPE`の明示がなければscopeは
unknownです。`ELASTIC`だけではtotalかmomentum transferかを決めず、observableも未確定に
します。明示された`OBSERVABLE`を保持し、EFFECTIVEはeffective_momentum_transferとして
区別します。曲線の取得から特定生成物の断面積や速度係数を宣言しません。
[対応形式の公式説明](https://us.lxcat.net/notes/index.php?download=lxcat_team28)

### 原子準位・熱化学・物性

- ASDは中性原子の掲載準位、元TSV全体、query URL、hash、個別行の注記・不確かさ・参考文献欄を
  保存します。`[]`・`()`の半経験・計算由来と、`?`・dagger・`+x`等の疑義や未知の基準を
  区別し、絶対閾値を確定できない宣言から最小値を出しません。Jが不明ならE1分類を保留します。
  `lowest_excitation_energy_eV`は返された準位のground termからの最小励起概要で、特定状態の
  同定・存在確認やデータの完全性を証明しません。metastable/resonantという出力名も、掲載準位の
  parity/JによるE1経路の概要であり、寿命・遷移確率・衝突消光・人口は決まりません。
  [ASD準位・注記の公式説明](https://physics.nist.gov/PhysRefData/ASD/Html/levelshelp.html)
- PyroMatは`h(300 K)`を`enthalpy_eV`（model_enthalpy）として保存します。温度、Tref、pref、ho、
  Tlim、元モデル、package版を保持し、`enthalpy_formation_eV`へ読み替えません。現在の形成量による
  反応エネルギー評価はこのh(T)を利用しません。
  [PyroMatの公式モデル実装](https://github.com/chmarti1/PYroMat/blob/master/src/pyromat/registry/ig2.py)
- NASA adapterはCanteraの明示した`nasa_gas.yaml`のみを読み、凝縮相を気相候補へ渡しません。
  複数構造が同組成で競合する場合は`source_species`を要求します。相、基準圧、温度範囲を
  保存します。[Canteraの熱化学形式](https://cantera.org/stable/yaml/species.html)
- molecular adapterは取得先の化学式を照合し、CFをCH3Fの別名として採用しません。
  CCCBDB adapterは中性ground対象だけを受け付け、同組成で複数構造・状態が掲載される場合は
  明示した`source_species`で選びます。chemicals・mendeleev等の各値の上流資料・方法が不足する
  記録はunknownを残し、package名だけから品質を決めません。
- deriveは励起へmassを明示近似として運びますが、polarizability、dipole、collision radius、
  well depthを基底からコピーしません。lumped人口が未定義なら熱化学を自動導出しません。

chemicalsの形成量取得は、実際に選んだHfg/S0gのtable名を指定して値を取得し、package版、
CASと量の原ID、tableを出典情報へ残します。公式資料で確認できたATCT_G/CRCの温度は
298.15 Kとして保持しますが、未確認の標準圧や電子規約は補いません。各Propertyの
`formation_reference`は読込み・取込み・採用・正規保存で保持され、参照条件不足は
当該ΔHの計算だけを止めます。詳しい型と条件は[Registry guide](registry_data_guide.md)を参照してください。

0 Kの解像準位については、共通参照を持つ親の形成量へ審査された準位差を加える導出を
行います。有限温度の熱寄与差、lumped人口、不明な形成参照は無言で補正しません。

反応threshold・deltaEは原宣言に加えてReactionRecordのscalar値と審査範囲を保持し、資格を満たす
値を共通のエネルギー判定へ供給します。各量に独立した単位・不確かさ・参照基準・適用条件を
持たせる完全な型と利用者の選択は残件です。今回の保存経路の整合と、この拡張を区別してください。
