# データ源と証拠の流れ

現行の候補生成は証拠と独立した有限文法による列挙です。`analyze`は指定したローカル証拠だけを
読み、取得やRegistry変更を行いません。取得、照合、科学的レビュー、永続採用は別操作です。

```text
外部データ -> acquire -> snapshot.yaml と原本・参照asset
  -> rgen ingest SNAPSHOT --result RESULT --overlay OVERLAY
       一意に照合できる記録 -> overlay
       一意に照合できない記録・同定不足・分類不一致 -> review_queue.yaml
  -> rgen analyze Ar CF4 --evidence registry --evidence OVERLAY --out result
  -> 明示的な rgen adopt OVERLAY --registry registry
```

照合成功は科学的承認ではありません。`status: imported`の数値はレビュー前の値として保持し、
自動でreviewedへ昇格しません。Registryへの所属も個別物性の品質を保証しません。
汎用取得経路と出典・参照条件を整備し、個別審査できた熱化学モデル・形成量・
電子電離断面積を補充しました。追加記録と資格・制約は[科学レビュー](scientific_data_review.md)、
登録する欄と必要情報は[表記辞書](data_dictionary.md)を参照してください。
手元のデータが共通snapshot形式なら、converterを追加せず`ingest`または`--evidence`へ
直接渡せます。必要な取得・変換と、すでに共通形式にある記録の読込みを分けてください。

| 操作 | 決める内容 | 他の操作へ渡す内容 |
|---|---|---|
| acquire | 取得・対応形式の変換、明示した対象との照合 | 値、原宣言、取得条件・出典、具体的な取得失敗 |
| 共通読込み | 型・単位語彙・明示した物理対象の整合 | 原宣言を保持した共通記録。科学的な承認は与えない |
| ingest | 保存結果の候補への一意な対応 | 対応済みoverlay、保留理由と原記録のreview queue |
| 個別数値評価 | その記録が述べる量を指定条件で利用できるか | 曲線・確率・係数の評価、依存する条件や不足 |
| 用途評価・選択 | 指定した量・モデルと係数用途の対応 | 採用値、別途必要な変換・モデル、選択・不一致 |
| adopt | 永続保存先への配置と保存整合 | 入力の出典・資格を保持したRegistry。承認へ昇格しない |

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
未対応の版は入力エラーです。LXCat・UMIST・CollisionDBのファイル変換は原本をsnapshot内の`raw/`へ保存し、
`acquisition`にファイル名・相対path・完全なSHA-256を記録します。`acquire fetch`は台帳の
明示したHTTPS file URLだけを取得し、原本と`acquisition.yaml`へ要求URL・最終URL・取得時刻・
完全なSHA-256・形式と形式版を保存します。形式版の判別はDBのreleaseや科学的品質の確認ではありません。

入力ファイルの隣にある`acquisition.yaml`は同じfile名と完全なhashが一致した場合に限り、
`acquisition.source_manifest`としてsnapshotと科学記録の原宣言へ引き継ぎます。取得URL・時刻・
明示されたprovider/collection/releaseを保持し、変換先の`raw_path`と元manifest内のpathを
区別します。別fileのmanifestは引き継ぎません。同名hashの不一致、不正形式、重複した欄は
書込み前にエラーになります。source_idからproviderやreleaseを推測しません。
WebBookの取得・保存HTML変換も原ページと完全なhashを保存します。複数のページは各記録の
原宣言に独立した取得情報を持たせ、最後のページの情報を他の種へ流用しません。

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
plain formulaの読込みは共通文法で文字列全体を照合し、`CH3OH`のHを4個として加算します。
電荷・状態を別に解釈する種IDとは区別し、未対応の構造式を部分的な組成として受理しません。
snapshotと取得要求の物理対象は、同じIDと組成・電荷・相・構造・状態の整合規則を使います。
明示欄の矛盾や不正型は入力エラーで、同定不足や値不足とは区別します。

物性やNASA係数から状態の存在を確定しません。状態の主張には`existence`、
`existence_source`、その主張の`status`を明示します。reviewed反応記録も全参加状態の
存在確認には読み替えません。reviewed数値datasetだけでも、反応自体の証拠判定を成立へ昇格させません。

`--evidence`はRegistry directoryとsnapshot/overlay fileに対応し、繰り返し指定できます。
存在しない明示パスや認識できない形式は入力エラーです。順序で競合を解消しません。
snapshotの種名・式を直接同定できない場合も、黙って読込み対象から捨てません。
既存結果との照合が必要な外部名は`ingest`へ渡し、保留された記録を`review_queue.yaml`で
確認します。Propertyの不正mapping・不正な記録型を、値が未取得であることへ読み替えません。
同じ対象の別出典は独立したStateRecordとして残し、新しいoverlayでは`state_records`、
Registry種では`records`配列に保存します。物性値の不一致は量の競合として扱い、同定済みの
対象や別の有効な量を失わせません。null物性も原記録の内容として保持し、別出所で補完しません。
独立記録の量別選択で利用値を得て、原記録固定時はその記録自身の不足を返します。
非束縛等の否定根拠も消しません。形式は[Registry guide](registry_data_guide.md)を参照してください。

同じ科学記録の再取得では、標準`acquisition`情報の日時・保存先だけの差を内容競合に
しません。匿名IDにも同じ科学内容比較を使います。未知の物理条件、注記、方法、資格、値は
比較へ残します。原宣言は削らず、取得の異なる記録を併記し、完全な再入力は重複追加しません。
同IDの科学内容変更はingestでreview queueへ送り、adoptでは上書きせず入力エラーにします。

複数snapshotを同じoverlayへ順次`ingest`できます。`review_queue.yaml`は
`queue_version: 1`と`review`配列で、各entryへ原record・source・kind・snapshotを保存します。
旧queueの共通source・snapshotも各entryへ移します。前の未解決入力を次のimportで消さず、
同じ原入力の再実行で重複を増やしません。同じ原入力が候補の整備後に対応・採用できた場合は、
そのentryだけを除きます。原値・同定等を変更した入力は別宣言で、旧保留の訂正・削除は明示作業です。
CLIは今回入力の保留数と保存queue累計を別に表示します。overlayとqueueを同時に保存し、
通常のIO失敗では両方の変更を復旧します。復旧失敗時は回復用backupを保持して場所を報告します。

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

入力の`data_selection.quantities`で、数値3量に加え`enthalpy_formation_eV`・
`ionization_energy_eV`・`electron_affinity_eV`・`excitation_energy_eV`・
`thermochemical_model`ごとにmethod、provider、collectionの`prefer`順または`only`限定、
特定recordを指定できます。`data_selection.targets`では保存されたcanonical対象IDごとに
量のpolicyを上書きできます。同じ適用性評価の後に選択するため、優先指定で未レビュー・
誤単位・範囲外・対象不一致のデータを利用可能にはしません。適用条件が不足する優先記録は
必要入力を返します。採用値と競合・不一致記録は正規結果へ残します。
`prefer`による順位は同じobservableと、速度係数なら同じreaction_orderの記録内で適用します。
例えば別の測定量の断面積や異なる次数の速度式を、provider順位だけで選びません。
必要な量・モデルを明示するには`record`で固定するか、`only`で該当する出典へ限定します。
限定後も異なる量・モデルが残れば、さらに明示選択を必要とします。

指定した量では旧datasetの`preferred`を使いません。未指定の量に残る`preferred`は移行用の
互換処理です。具体的な入力と選択規則は[README](../README.md)を参照してください。
物性・熱化学モデルの選択も、量の定義・形成参照・同定の確認を飛ばしません。
状態・反応の存在根拠や反応エネルギー根拠の優先指定は、上の量別policyの対象ではありません。
形成量の共通参照型と比較前提、反応threshold/deltaEの独立Property化は実装済みです。

`rgen records RESULT --target N2@ground --quantity ionization_energy_eV`は、保存した出所・
内容・資格と選択に使う正規IDを先に表示します。`--detail`で原宣言を含む全記録を参照できます。
状態の`record_id`、数値datasetの`id`を対象別policyの`record`へ指定します。
一覧は保存結果の表示であり、再計算や記録の承認は行いません。

同一dataset IDの異なる科学内容は競合です。constant/Arrheniusの同一記録は、既知の単位換算で
一致する表現も共通規則で比較し、同じ単位の異値は厳密に区別します。換算の丸めだけを許容し、
source・observable・反応次数・注記・審査条件等の違いを消しません。絶対不確かさの別単位は
同じ物理次元の場合に値の単位へ正規化し、元の単位と原宣言を保持します。
不正・範囲外・未レビューの記録も結果へ残し、修復・
代替取得の対象にします。数値の不適用は反応不存在を意味しません。個別datasetの判定は
native量の数値利用可否です。断面積では、宣言したエネルギー範囲での曲線表現を確認し、
指定エネルギーの点評価、分布の収録範囲の完備、速度係数を決めたことにはしません。
確率では、必要な条件での確率を返せても入射粒子数・表面速度は決まりません。

係数用途の`DataUse`は別に、断面積に必要な明示分布と積分、確率に必要な入射モデルと
流束変換を必要作業へ保存します。これらの変換は現在未実装です。電子温度の入力だけで
電子エネルギー分布の形を指定したことにはなりません。運動量移行・実効運動量移行断面積は
反応衝突数を数える量と異なり、同じエネルギー分布との積分だけでは反応衝突速度係数を
求められません。その用途では対応する反応断面積が必要です。利用可能な係数を選べた場合にも、
他のnative記録の不足や評価はその記録に保持します。

assetは作者の宣言hashと保存時の実測hashを分けて保持します。表を使う際は保存hashを
照合した同じbytesを解析し、再読込みや読込み後の変更で新しい値を無言で採用しません。
adoptは検証したbytesをRegistry内へコピーし相対pathにします。同じ科学内容と検証済み
bytesの保存場所だけでは競合にせず、各取得の原宣言・参照場所は残します。検証できない
bytesや異なる科学条件を同一化せず、宣言hash不一致のデータには計算資格を与えません。

## 取得要求の対象と検索名

`molecular`・`thermo`・`idealgas`・`vibration`・`cccbdb`の種入力は、名前の配列または
`states`配列を持つYAMLです。物性を付ける対象は`id`、取得先の検索名は`query`で指定します。
入力形式を示す例です。

```yaml
states:
- id: O2@ground
  phase: gas
  query: oxygen
- id: CO2@ground
  phase: gas
  linear: true
```

組成・電荷・状態欄を併記する場合はIDと一致させます。構造を区別する対象は`structure`を
IDまたは別欄へ明示します。検索名は`query`、`source_species`、対象の`structure`、
IDの化学式部の順で使います。元の検索名・要求対象・その原表記は
`source_declaration.acquisition.request`の`query/target/written_target`へ保存します。
取得値の`species`は、要求別名を照合した後、取得元の独立したInChI・InChIKey・CAS等の
構造IDで統一します。同じ物質の別名取得を別物理対象や科学的競合にしません。
`source_identity`に取得元の組成・構造識別子・名前を保持し、検索queryを同定根拠にしません。
CCCBDBは同じ組成の複数の依頼対象を保持し、構造・状態が競合する出典には明示した検索名を使います。

化学式だけの多原子分子要求へ、取得した特定構造の値を無言で付けません。構造固有値は
取得元の構造付き対象として保存し、式だけの候補には関連証拠として残ります。現在の通常Caseは
構造入力・構造別生成に対応していないため、この同定不足を温度入力等で解消した扱いにしません。
取得成功と既存候補への数値利用は別です。構造を指定した要求が取得元と異なれば入力エラーです。

従来の取得出力の`source_query`は上記acquisitionコンテナへ移しました。既存snapshotの原宣言は
そのまま保持し、過去の誤同定を自由文から自動修復しません。必要な対象は元資料から再変換し、
同定・採用を改めて確認します。InChI/SMILES等は取得元の識別子を保存するもので、独立した
構造同値判定や分子構造解析を実装したものではありません。

これらのadapterが対応するのは中性・気相・基底状態です。異相・イオン・励起状態の依頼は、
中性気相の検索名へ縮めて値を付けず、対応範囲外の理由を表示します。簡略形の化学式文字列は
このadapterの気相基底対象を表します。相不明と宣言した対象へ気相を補いません。
NASA adapterは別に気相の基底状態・イオンを扱い、組成・電荷・構造・状態と出典種を照合します。
これらの取得によって状態の存在や、その物性を使う反応の成立を決めません。

PubChemは未同定のnative別名も`identity.yaml`へ`identity_only`として返せます。
対象が未同定のまま物性記録を作らず、同定済みの対象に対する質量値は検索名と対象を分けて保存します。
HTTP 404は該当entryなし、500/429・通信失敗・壊れたJSON等は取得失敗として区別します。
補助的なsynonym取得の失敗はその理由を残し、すでに取得したCIDや質量を消しません。

値が未掲載であること、対象の不適用、通信・元応答解析の失敗、依存packageや実装の異常は
異なる理由です。molecularの値読込みで予期しない例外を`None`へ変換せず、Cantera元ファイルの
破損・未配置を「当該種のfitがない」と扱いません。不正なProperty mappingや物理同定の矛盾は
読込み時の入力エラーです。出典に値や条件が本当にない場合は、その依存情報の不足として扱います。

## 取得adapterの範囲

### NIST WebBook

```powershell
acquire webbook SPECIES.yaml --out work/webbook
acquire webbook SPECIES.yaml --page PAGE.html --out work/webbook
```

取得要求は`[{id: N2, query: C7727379}]`等、物理対象と明示CAS/WebBook IDを分けます。
保存ページの変換は一対象ずつ行います。対応量は中性気相groundのHf・IE・EAです。
各値・単位・不確かさ・方法・原注記・参考文献とraw HTML/hashを保持し、
Shomate・出現エネルギー・他の量をHfやIEへ読み替えません。
個別IE/EA測定行には異なる初期状態が含まれるため、`source_state_unconfirmed`で
原資料確認まで点値利用を止めます。明示vertical/adiabaticの定義も別に保持します。

明示した対象structureは原名・InChI・掲載別名と照合します。多原子分子の構造が依頼側で
未同定なら、記録側に原InChI/名を保持して式だけの対象へexact転記しません。
同位体の宣言も潰しません。標準Hfの未記載温度・圧力を入力温度から補わず、明示0 Kは保持します。
CAS/URIは対象IDであり、個別測定の原IDではありません。公式行IDがなければ科学内容IDを使い、
派生`derived_row_key`と作成規則は原宣言側へ保存します。
[WebBook公式説明](https://webbook.nist.gov/chemistry/guide/)

### IAEA CollisionDB

```powershell
acquire collisiondb DATASET.txt --out work/collisiondb
```

JSONヘッダ、区切り線、2列の積分断面積に対応し、軸`eV/keV`と面積`m2/cm2`をSI表へ変換します。
stateful反応、原`qid`・文献・方法・frame・合計チャネル・fit・全体と各点の不確かさ、
raw/hashを保存します。微分断面積、質量当たりエネルギー、多列表、欠測点の補間は未対応です。
必要な対応を`--reaction`、`--type`、`--independent-variable`、`--observable`、
`--channel-scope`で明示できます。対応語彙は[表記辞書](data_dictionary.md)を参照してください。
原状態名をgroundへ省略せず、未指定scopeを`product_resolved`へ昇格しません。
重粒子衝突の原frameは`com/target`を必要とし、欠落・不正は取得形式エラーです。
利用者の軸指定で原frameを補いません。対応の不明な原反応はingestで同定作業へ回します。
fit由来の数表は`calculated`として原測定方法と分け、明示eV fit範囲を利用範囲へ反映します。
fit精度を実測値全体の不確かさとせず、ダウンロードfitコードも実行しません。
[公式形式説明](https://db-amdis.org/collisiondb/submitting-data/)

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
  同定・存在確認やデータの完全性を証明しません。`no_lower_e1_candidate_energy_eV`は、掲載集合内で
  厳密に低いエネルギーのparity/J候補がない準位の最小値、`ground_e1_candidate_energy_eV`は
  ground準位とのparity/J条件を満たす正の励起の最小値です。同エネルギー準位は下位遷移に使わず、
  行順に依存しません。ground termのfine structureはterm概要から除き、原準位を保持します。
  これらは必要なparity/J条件だけの候補で、行列要素・強度・寿命・衝突消光・人口は決まりません。
  Pythonの`Levels`も`no_lower_e1_candidate_eV`・`ground_e1_candidate_eV`・
  `no_lower_e1_candidate_levels`、関数は`no_lower_e1_candidates`へ名称を統一しました。
  旧metastable/resonant/trapped名の内部aliasは残しません。旧外部snapshotの
  `metastable_energy_eV`・`resonant_energy_eV`は汎用Propertyとして読み、意味や資格を昇格させません。
  [ASD準位・注記の公式説明](https://physics.nist.gov/PhysRefData/ASD/Html/levelshelp.html)
  [ASDのE1候補と強度の公式説明](https://physics.nist.gov/PhysRefData/ASD/Html/lineshelp.html)
- 原子IE/EAの取得はatomic量の名目値です。CLIのEA表示とPythonの
  `Atom.nominal_ea_positive`は有限な名目EAの符号だけを示し、不確かさを含む電子結合を
  判定しません。旧`binds_electron`はこの名前へ変更しました。束縛陰イオンの命題と
  付着反応の安定化・速度は、それぞれの評価・計算の責務です。
- PyroMatは`h(300 K)`を`enthalpy_eV`（model_enthalpy）として保存します。温度、Tref、pref、ho、
  Tlim、元モデル、package版を保持し、`enthalpy_formation_eV`へ読み替えません。現在の形成量による
  反応エネルギー評価はこのh(T)を利用しません。
  [PyroMatの公式モデル実装](https://github.com/chmarti1/PYroMat/blob/master/src/pyromat/registry/ig2.py)
- NASA adapterはCanteraの明示した`nasa_gas.yaml`のみを読み、凝縮相を気相候補へ渡しません。
  複数構造が同組成で競合する場合は`source_species`を要求します。canonical ID内の構造も
  独立した対象宣言として照合し、`source_species`で異なる構造へ差し替えません。同組成のfitが
  一件だけでも、多原子分子は出典種名を構造として保持します。式だけの汎用対象に対しては
  compatible照合に留まり、当該構造への適用を無言で一般化しません。相、基準圧、温度範囲を
  保存します。canonical IDが述べる相・状態も検査し、明示欄がなくても固相・励起対象へ
  気相基底のfitを転記しません。原NASA TM-4513の気相標準圧1 barを、当該ファイルの
  省略参照圧へ適用します。明示YAMLの圧力を優先し、他ファイルへ一律に広げません。
  Canteraの省略時ソフトウェア既定1 atmと原資料の圧力を原宣言に別々に保持します。
  [Canteraの熱化学形式](https://cantera.org/stable/yaml/species.html)、
  [NASA原資料](https://ntrs.nasa.gov/api/citations/19940013151/downloads/19940013151.pdf)
- molecular adapterは取得先の化学式を照合し、CFをCH3Fの別名として採用しません。
  CCCBDB adapterは中性ground対象だけを受け付け、同組成で複数構造・状態が掲載される場合は
  明示した`source_species`で選びます。chemicals・mendeleev等の各値の上流資料・方法が不足する
  記録はunknownを残し、package名だけから品質を決めません。
- 振動adapterは気相基底種のTRC熱容量から有効Einstein modeを近似します。原子数は
  照合した組成・出典化学式から求め、`atoms`を併記する場合はその数と一致させます。
  二原子分子の線形性は原子数から決まります。多原子分子の`linear: true/false`は明示入力が必要で、
  不足時に非線形・二原子として計算しません。出力は`quantity: effective_vibrational_quantum`、
  `status/quality: estimated`とし、適用fit温度範囲、mode数、元係数と化学式を保存します。
  分光準位・最低振動mode・lumped人口のエネルギーを同定したことにはしません。
  支持する近似範囲外のfitは、この近似の不適用であって分子振動の不存在ではありません。
- deriveは既存の個別Property資格から原子mass入力・親mass・親0 K形成量・解像励起energyを選び、
  独立した近似計算へ渡します。拒否・競合中の親記録、その量のreview_scope外や未解釈注記付きの
  点値を、tierだけでderivedへ昇格させません。massは励起energyの不足と独立に導出でき、
  組成和では化学結合のmass欠損、励起へのmass転記ではE/c²を無視する近似を明示します。
  使った原子mass・親Propertyと準位Property全体を`source_declaration`へ保存します。
  `carried_from(parent, excitation)`のexcitationはPropertyまたはNoneとし、旧scalar/energy_source
  引数は廃止しました。finite・非負の適格energyと共通0 K参照の形成量から名目offsetだけを求め、
  不確かさ伝播・有限温度の熱寄与・人口を補いません。polarizability、dipole、collision radius、
  well depthも基底からコピーしません。

deriveのoverlay保存は内容を確定・読込み検証した隣接一時ファイルからreplaceします。同一入出力の
書込み・置換失敗では旧ファイルを保持します。別ディレクトリへ出力する場合は元overlayを基準に
asset参照を再配置し、元の解決先・観測hash・宣言hashを保ちます。参照先の欠落・改変を修復したり、
利用資格を昇格したりしません。

chemicalsの形成量取得は、実際に選んだHfg/S0gのtable名を指定して値を取得し、package版、
CASと量の原ID、tableを出典情報へ残します。公式資料で確認できたATCT_G/CRCの温度は
298.15 Kとして保持しますが、未確認の標準圧や電子規約は補いません。各Propertyの
`formation_reference`は読込み・取込み・採用・正規保存で保持され、参照条件不足は
当該ΔHの計算だけを止めます。詳しい型と条件は[Registry guide](registry_data_guide.md)を参照してください。

0 Kの解像準位については、共通参照を持つ親の形成量へ審査された準位差を加える導出を
行います。有限温度の熱寄与差、lumped人口、不明な形成参照は無言で補正しません。

反応threshold・deltaEは`energy_properties`内の独立Propertyとして、定義、値・単位、
資格・status・review_scope、出典・方法、不確かさ、原宣言を保持します。親channelの審査で
明示Propertyを昇格せず、量ごとの適格性を確認して共通エネルギー判定へ渡します。
旧外部scalarは入口で一度だけこの表現へ変換し、元宣言も残します。
形式と定義は[Registry guide](registry_data_guide.md#科学量の定義と反応エネルギー)を参照してください。

NASA9・Shomate、EEDF積分、表面流束変換は現行計算へ追加していません。
値や原係数の取得と、それを消費するモデルの実装・審査を分けます。
DBで得られない量の独立計算packageは未実装の[将来設計](data_generation_plan.md)へ分け、
必要な用途と実装順は[残件計画](remaining_work_plan.md)へ置きます。
