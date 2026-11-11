# データ取得・照合・採用

`analyze`は有限文法による候補とローカル証拠が明示したチャネルを共通の探索へ渡します。
取得、候補との照合、科学的審査、永続採用は個別の操作です。
科学記録の形式・資格・量の定義は[記録ガイド](registry_data_guide.md)、
取得元の利用条件とnoticeは[出典・配布方針](source_license_policy.md)を参照してください。

```text
外部データ -> acquire -> snapshot.yaml と原本・参照asset
  -> rgen ingest SNAPSHOT --result RESULT --overlay OVERLAY
       一意に照合できる記録 -> overlay
       一意に照合できない記録・同定不足・分類不一致 -> review_queue.yaml
  -> rgen analyze Ar CF4 --supply e --evidence registry --evidence OVERLAY --out result
  -> 明示的な rgen adopt OVERLAY --registry registry
```

照合成功は科学的承認ではありません。`status: imported`の数値はレビュー前の値として保持し、
自動でreviewedへ昇格しません。Registryへの所属も個別物性の品質を保証しません。
収録した科学記録の審査範囲と適用条件は[出典・配布方針](source_license_policy.md)に記録します。
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

取得元が宣言した値・単位、注記、状態名、出典を`source_declaration`とともに保ちます。
測定方法や審査範囲が不明なら、その不明を残します。科学量を利用するための資格は
[記録の出典と資格](registry_data_guide.md#出典と資格)を確認してください。

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

新しい成果物の原本と数表は、内容のSHA-256を含む相対パスへ保存します。配置は宣言されたパスで辿り、旧パスの成果物も読めます。変換と原本の記録には同じバイト列を使います。原本・数表の用意が終わってからスナップショットを公開します。中断時に未参照のファイルが残っても、既存のスナップショットが参照するファイルは引き続き利用できます。

WebBook CLIは変換時の`request`（queryと元target）と原本のパス・hashを併せて保持します。

既存の独自fetch台帳は`--catalog`で指定でき、旧`id`欄も取得用adapterで読みます。

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

## 数値データと参照ファイル

取得した数値は共通の科学記録として読み込みます。項目は[記録形式](registry_data_guide.md#反応とdataset)、出典の選び方は[数値の採用要求](output_reference.md#数値の採用要求)を参照してください。

表は保存したハッシュに一致するバイト列を解析します。採用時は検証した同じバイト列をRegistry内へ置き、相対パスで参照します。

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

特定構造の値は取得元の構造付き対象として保存し、式だけの候補には関連証拠として残します。
通常Caseでは明示SMILESを入力でき、同じ構造表現を検証できる記録へ照合します。取得元が
別の識別体系を使う場合は、出典を示して対応関係を確認する必要があります。
同梱RegistryのO₂・F₂には、確認済みの名目種とグラフの対応を持たせています。照合範囲は
その宣言を持つ資料に限ります。[Registryの構造宣言](registry_data_guide.md#状態と物性)
F₂・NF₃・SiH₄のATcT形成量では、原資料自身が示すSMILESを個別記録へ付けています。
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

## 用途別の取得元と参照

必要な候補・端点と量を先に定めます。同じ対象について定義付きの直接値があれば、代替計算用の量まで一律に集める必要はありません。
別出典を組み合わせる場合は、参照基底、相、構造、電荷、核種、温度や標準状態を量の用途に応じて照合します。

| 量 | 原資料と現行の取扱い |
|---|---|
| 形成量・IE・EA | [ATcT版固定表](https://atct.anl.gov/Thermochemical%20Data/version%201.228/index.php)の0 K／298.15 K形成量、[WebBookの気相イオン熱化学](https://webbook.nist.gov/chemistry/ion/)の量定義と個別原典を確認します。WebBookは対応表を変換できます。ATcT専用の取得adapterはありません。 |
| 解離エネルギーD₀ | 原著が指定する親からフラグメントへの0 K差を用います。例えば[D₂](https://doi.org/10.1063/1.3374426)と[HD](https://doi.org/10.1063/1.3483462)ではそれぞれ対応する核種と準位を確認します。一般の解離表から自動変換する入口はなく、[関係量の記入例](registry_data_guide.md#科学量の定義と反応エネルギー)で入力できます。 |
| PA・GB | [WebBookのNH₃](https://webbook.nist.gov/cgi/cbook.cgi?ID=C7664417&Mask=20)等から共役対、参照温度、GBの標準圧を確認します。現行WebBook変換の対象外で、対応するPropertyを独立に記録します。 |
| 原子・原子イオンの準位 | [NIST ASD準位表](https://physics.nist.gov/PhysRefData/ASD/Html/levelshelp.html)の電荷段階、準位、帰属、基準を使います。各電荷段階の基底ゼロは独立なので、電荷段階をまたぐ差には対応するIEを使います。 |
| 分子の実準位 | 原著の直接差、または[ExoMolの形式原著](https://exomol.com/static/papers/548.pdf)と同一の同位体分子・データセット版の定義と準位表を用います。準位IDはデータセット内の番号です。遷移表全体や光学強度はエネルギー差に必須ではありません。 |
| 熱関数 | [JANAFのNH₃表](https://janaf.nist.gov/tables/H-083.html)の温度・標準圧と`H−H(Tr)`、[CCCBDBの熱関数](https://cccbdb.nist.gov/thermox.asp)・[元素参照](https://cccbdb.nist.gov/refstatex.asp)を個別に確認します。現行CCCBDB adapterは分極率を扱います。NASA7を有効温度域外へ外挿しません。[Canteraの熱化学仕様](https://cantera.org/stable/reference/thermo/species-thermo.html) |
| 構造・質量 | 原資料の構造、返却された[PubChem CID](https://pubchem.ncbi.nlm.nih.gov/pcfe/docs/pug-rest.html)と対象を照合します。ConnectivitySMILESでは核種・立体情報を失う場合があります。質量は[標準原子量](https://ciaaw.org/atomic-weights.htm)、[個別核種の質量](https://ciaaw.org/atomic-masses.htm)、中性原子の組成和、イオン質量を区別します。 |

`h_s(T)=H_s(T)−H_s(0)`が整合する表から得られれば、有限温度の反応エンタルピーの0 K差は
`ΔrH(0)=ΔrH(T)−Σν_s h_s(T)`です。中性種の個別形成量には
`ΔfH_s(0)=ΔfH_s(T)−h_s(T)+Σ_a n_sa h_element,a(T)` と元素参照の熱増分が必要です。
イオンを含む有限温度資料は電子の参照規約と熱項を確認します。
温度または基準の不足は、有限温度の原値とは分けて扱います。
この補正は資料を照合して導出した値を登録する場合の手順です。解析時に熱関数を自動取得して変換する処理はありません。

共通の参照基準が確認できる準位差を使います。例えば[WebBookのCO分光定数表](https://webbook.nist.gov/cgi/cbook.cgi?ID=C630080&Mask=1000)
にある `D_e` は遠心歪定数です。井戸底からの解離エネルギーとは別量で、現在のWebBook adapterはこの表を変換しません。
ExoMolの縮退度 `gtot` には核スピンの重みが入り、電子多重度へは変換しません。
同じ元データに由来する複数の出典を独立した測定とは数えず、標準不確かさと包含区間を区別します。

HTTPエラー、取得した内容の形式不一致、対象の不一致、変換機能の適用外、調べた資料の範囲内での未収録は個別に扱います。
部分取得では検証した範囲を記録し、そのhashを原本全体のhashとして使いません。

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
`--channel-scope`で明示できます。対応語彙は[記録ガイド](registry_data_guide.md#対象と反応)を参照してください。
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
全成分をparametersと原行付きの`reference_only`として保持します。利用には加算モデルの同定と評価が必要です。
原本の不正を修正するときは原本と変更内容を別に保存してください。

2026-10-12に取得した [RATE22原本](https://umistdatabase.uk/files/rate22_final.rates)（SHA-256 `2f83cdd0905e5dd50494f23bc5faf559a617d866b365cf9d1c5fef3621a1a219`）は、5488行目の引用符が閉じておらず変換が止まります。このハッシュの原本では、現行コマンドで同じエラーを再現できます。

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

- ASDは原子・原子イオンの掲載準位、元TSV全体、query URL、hash、個別行の注記・不確かさ・参考文献欄を
  保存します。`[]`・`()`の半経験・計算由来と、`?`・dagger・`+x`等の疑義や未知の基準を
  区別し、絶対閾値を確定できない宣言から最小値を出しません。Jが不明ならE1分類を保留します。
  `lowest_excitation_energy_eV`は返された準位のground termからの最小励起概要で、特定状態の
  同定・存在確認やデータの完全性を証明しません。`no_lower_e1_candidate_energy_eV`は、掲載集合内で
  厳密に低いエネルギーのparity/J候補がない準位の最小値、`ground_e1_candidate_energy_eV`は
  ground準位とのparity/J条件を満たす正の励起の最小値です。同エネルギー準位は下位遷移に使わず、
  行順に依存しません。ground termのfine structureはterm概要から除き、原準位を保持します。
  これらは必要なparity/J条件だけの候補で、行列要素・強度・寿命・衝突消光・人口は決まりません。
  [ASD準位・注記の公式説明](https://physics.nist.gov/PhysRefData/ASD/Html/levelshelp.html)
  [ASDのE1候補と強度の公式説明](https://physics.nist.gov/PhysRefData/ASD/Html/lineshelp.html)
  `acquire asd Ar C+ --resolved-below 12 --out WORK` は通常の概要に加え、各電荷段階で
  指定上限以下の実準位を `excitation_energy_eV` として取り込みます。正の絶対準位、確定したJ、
  一意の準位名と基底ゼロ、次の電荷段階を示す電離限界がそろった場合に、電離限界より低い準位を
  対象にします。各記録はその電荷の基底 `related_state` と原行を持ちます。自己電離注記、
  未確定の絶対基準、重複した準位名は原資料で確認できます。ASDの既定Hは¹Hを指すため、
  同位体未指定のHへの実準位の取り込みは保留します。出力は `imported` として保持し、計算に
  使う量だけを確認して審査してください。[ASDのスペクトル・準位仕様](https://physics.nist.gov/PhysRefData/ASD/Html/levelshelp.html)
- ExoMolの分子準位は、保存済みの同一同位体・同一データセットの公式 `.def.json` と
  `.states` または `.states.bz2` を対にして変換します。現行の対象は `dcs` の中性二原子分子で、
  `ID/E/gtot/J/v` と任意の `e/f` を持つ基底電子状態の回転振動表です。既存のoptional RDKitで
  入力SMILESを照合し、定義の核種と一致する気相基底、参照行のID、取得する励起行のIDを指定します。
  [ExoMolデータ仕様](https://exomol.com/data/)・[¹H₂ RACPPK](https://exomol.com/data/data-types/linelist/H2/1H2/RACPPK/)

  ```powershell
  acquire exomol 1H2__RACPPK.def.json 1H2__RACPPK.states.bz2 --ground 'H2@ground;structure=smiles:[1H][1H]' --ground-row 1 --rows 2 --out work/exomol
  ```

  参照行は読み込んだ表の一意な `E=0, v=0, J=0` で、対応する物理基底はデータセットの説明と
  照合してください。選択した行、参照行、版、元ファイル名、SHA-256、宣言行数と読込行数を保持します。
  行数の差は表示し、読めた行の範囲だけを対象にします。出力は量ごとの審査前の `imported` です。
  ¹H₂では解析入力の `structures: {H2: '[1H][1H]'}` と `supplies: [e]` に対応し、審査した
  量は既存の `excitation_energy_eV` として利用できます。元ファイルは取得先とともに保管してください。
- 原子IE/EAの取得はatomic量の名目値です。CLIのEA表示は有限な名目EAの符号を示します。
  不確かさを含む電子束縛、付着反応の安定化・速度は別の量と判定です。
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
  有限・非負の適格energyと共通0 K参照の形成量から名目offsetを求め、
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

NASA9・Shomate、EEDF積分、表面流束変換は現行計算へ追加していません。
値や原係数の取得と、それを消費するモデルの実装・審査を分けます。
