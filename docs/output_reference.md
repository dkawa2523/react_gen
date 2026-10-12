# 公開出力仕様：schema 5

0.7.4の正規科学結果は `result.yaml` 一つです。schemaの実装元は[result.schema.yaml](../src/reactgen/result.schema.yaml)で、[schemas/bundle.schema.yaml](../schemas/bundle.schema.yaml)はそこを参照します。保存と読込みは同じ検査を使います。0.7以降の追加項目は任意項目で、0.6・0.7のschema 5結果も読み込めます。保存した旧IDや判定は読込みで再生成・再評価しません。0.5の3分割YAMLや選択policyを現行形式として読みません。

## 正規結果

| キー | 意味 |
|---|---|
| input | 正規化したgases、表示name、物理conditions、surfaces、計算limits、明示したdata_selection |
| metadata | schema/generator version、証拠のfingerprint、生成範囲、命題の意味 |
| summary | 全候補の件数と判定・数値利用結果の集計。機構全体のready指標ではない |
| states | 全状態候補、同定情報、正規化した証拠、3判定 |
| reactions | 全反応候補、式・過程、正規化した証拠、5判定、熱化学値、data_use |
| helper_views | states.csvとreactions.csvの期待SHA-256 |

`metadata.generation` は `scope`、`limits`、`stop_reason`、`completion.mechanical`、`completion.attested` と両者の完了結果を持ちます。completeは全実在反応を網羅したことを表しません。入力・出典・乱数なしの同じ計算は同じ結果になります。

状態は `id, composition, charge, state(kind/resolution/label), phase, structure` で対象を表し、`classes, origin, depth, introduced_by` は生成・表現の情報です。`state_axes` はそこから導いた表示軸です。反応は正の化学量論数を持つ `reactants/products`、`family/process`、`third_body/surface`、`stabilization`、生成情報を持ちます。IDは正規化したチャネルから計算し、式と参照先が一致することを検査します。

通常のIDは `CF4@ground` や `Ar+@ground` です。多価は `Ar^2+@ground` と書き、`Ar2+@ground` と区別します。通常表現で区別できない相・構造・kind・resolutionには明示suffixを付けます。IDの内部構成を利用者が理解する必要はありませんが、API照合と図のseed/target指定には完全なIDを使います。

## 判定と数値利用

判定は `{verdict, basis, message, proposition, scope, requirements, dependencies}` です。新規結果は命題と個別の適用範囲を必ず持ちます。旧schema 5結果の追加項目は省略可能で、欠ける意味を再判定・補完しません。verdictは `pass / fail / unknown / not_applicable` の4値です。各命題の適用範囲は個別 `scope` と[現行責務](core_design.md)で定義します。metadataは判定区分全体の説明です。basisは重複しない出典・処理根拠、messageはその命題についての理由です。同一のpassを、別の命題へ流用しません。

現行の状態 `thermochemistry` は競合していない審査された形成量または有効なNASA表現の有無、反応 `thermochemistry` は比較できるエネルギー関係を表します。状態側のpassは指定温度での利用可能性・利用者の採用要求・存在を保証しません。共通の表示名だけで同じ判定と解釈せず、`proposition` とmessageで確認対象を読み取ります。

| proposition | 確認対象 |
|---|---|
| state_representation_consistency | 候補の組成・整数電荷の表現整合 |
| equation_consistency | 保存則と宣言過程の式patternの整合 |
| participant_state_support | 参加状態の各命題の集約（存在保証とは異なる） |
| channel_evidence_support | 当該対象・過程・scopeのチャネル主張への資料支持 |
| rate_coefficient_availability | 保存DataUseによる指定条件での係数利用可否 |
| state_existence_support | 当該状態の存在を支持する根拠 |
| ground_anion_electron_binding | 対応する基底アニオンの電子束縛 |
| thermochemical_representation_availability | 競合していない審査された熱化学表現の有無 |
| elastic_internal_energy_identity | elasticの左右が同じ物理対象であることと内部エネルギー差ゼロ |
| ionization_threshold_lower_bound | 対応するIEと宣言thresholdの下限関係 |
| penning_energy_requirement | 対応する準位・生成物のPenningエネルギー条件 |
| charge_transfer_energy_defect_consistency | 対応する親・生成物の電荷交換エネルギー欠損の整合 |
| reaction_energy_relation | その他の反応の比較できるエネルギー関係 |

`requirements`は`{responsibility, target, quantity, reason}`の配列です。必要な対象と量・条件、作業の区分と理由を保存します。`user_inputs`だけが実際に受理する条件名を指し、出典の定義・適用条件やモデル未対応を入力項目にしません。`dependencies`は`[state_id, assessment_key]`の配列で、参加状態の集約が参照する保存判定を指します。参照先が存在しない結果は拒否します。kineticsの要件は正規DataUseを参照し、同じ情報を二重管理しません。

宣言値の整合、モデル内の判定、現象の成立は別です。不確かさ未宣言は測定誤差ゼロではありません。名目点を比較した場合はその範囲をscope/messageへ記録し、区間比較も宣言された範囲の関係として返します。信頼水準・相関・確率分布を推定しません。

電子解離・非電子単分子解離・2粒子会合は、宣言familyに対応する式patternを確認します。対応外の誘起機構は`unknown`です。会合・解離の`consistency=pass`にも、安定化や励起起源を式から決められない旨をmessageへ残します。反応の発生や係数の利用可否は別の判定です。

`data_use` は以下を保持します。

- `status`: coefficient、needs_input、needs_transform、unavailable、conflict。
- `dataset_id/kind`: 採用した表現。採用不可ならnull。
- `value/unit`: 評価した値と単位。係数以外の確率値はstatusと併せて読む。
- `required_inputs/required_transforms/reason`: 足りない具体情報と操作、結果の理由。
- `estimated`: 推定によるデータかどうか。
- `datasets`: valid、invalid、out_of_range、needs_input、reference_only、unreviewed、conflictと各datasetの理由。
- `selection`: 入力の明示した量別採用要求。未指定なら空mapping。
- `disagreements`: 他の適格な記録との数値不一致、または同一IDの内容競合があるdataset ID。採用ID自身は含めない。

同じIDで異なる内容を見つけた場合も、元レコードはevidenceに保持します。単なる利用可否から状態・反応の実在や機構の予測可能性を結論しません。

datasetの`invalid`には、数値形式の不正だけでなく、総過程データと特定生成物チャネルの不適合も含みます。原数値が誤りであることや現象の不存在を一律に意味しません。`reason`で対象と不適合の理由を確認し、元の測定値と条件はevidenceで読めます。

読込み時はstatusと具体値・単位・選択dataset・不足の関係も検証します。`coefficient`は具体的な速度係数と採用datasetを必要とし、未解決の入力・変換を持ちません。選択した値とdataset評価の値・単位・不足が矛盾する結果を拒否します。ゼロ係数やゼロ確率は有効な数値で、nullと区別します。

明示要求がある結果では、`selection` が正規入力と一致し、採用IDとkindがevidenceの記録を指し、`prefer`・`only`・固定recordの要求に従うことも検査します。不一致IDは保存されたdataset評価に存在する必要があります。選択情報の追加前のschema 5結果は、従来の必須項目で読めます。

## 数値の採用要求

`input.data_selection.quantities` の対象は `rate_coefficient`、`cross_section`、`sticking_coefficient` です。各対象は次の項目を持ちます。物性、NASAモデル、存在根拠の範囲指定は未対応で、入力境界で拒否します。

| 項目 | 規則 |
|---|---|
| mode | prefer（既定）またはonly |
| methods | measured / evaluated / calculated / estimated / unknown のリスト |
| providers | 記録のprovenance.provider識別子のリスト |
| collections | 記録のprovenance.collection識別子のリスト |
| record | 固定する数値dataset ID。異なる量やonly制限と矛盾するID指定はエラー |

`prefer` は、指定した軸をmethods→providers→collectionsの順で比較し、各リスト内の順を優先します。リスト外はその軸の共通の後順位です。`only` は指定したすべての軸を満たす記録に制限し、リスト順を順位として使いません。`only` には少なくとも一つの軸またはrecordが必要です。record指定は分析全体の量別要求として各反応へ適用され、指定IDを持たない反応の同量はunavailableになります。適格性検査は免除しません。識別子は明示値を使い、出典台帳への登録を要求しません。

全記録を評価してから要求を適用します。優先記録が不正・範囲外なら他の適格な記録へ進めます。優先記録の適用条件が不足している場合は、その不足を残します。同順位の記録の異なる値は `conflict` で、明示優先から一つを採用できた場合も `disagreements` を保持します。出典の優先は、数値資格、科学的な同定、適用条件とは別です。対応する量に要求がない場合だけ、旧dataset `preferred` の互換処理を使い、理由へ移行案内を記録します。0.8で撤去する予定です。

異なる次数・物理量のデータは同じ数値でも同等としません。複数の速度則が適用できるときは採用根拠が必要です。`required_inputs` の `rate_law_selection` は出典・採用宣言の不足、`dataset_applicability_conditions` は出典の適用条件不足です。通常入力のキーではありません。非重複の適用域は競合とせず、条件入力による絞り込みを要求します。競合の場合も不足情報を保持します。

## 熱化学値と出典

`thermochemistry` は取得できた計算値と、現行の資格規則で受理した宣言値を保持します。`delta_h_eV, delta_g_eV, threshold_eV` は一反応イベントあたりのeVです。数密度形の平衡定数は `equilibrium_constant_number_density`、その密度次数は `equilibrium_constant_density_power=Δν`、単位は `m^(-3Δν)` です。`standard_pressure_Pa` は使用したNASA標準状態です。物理的な比較が未確定でも、単に得られた値を隠しません。

`delta_h_eV`は共通の明示参照条件での形成量の差です。`delta_h_reference_temperature_K`・`delta_h_standard_pressure_Pa`を併記します。参照不足・不一致ではΔHを返さず、判定messageに理由を残します。`temperature_K`はNASA由来の標準G/K計算に使った温度で、ΔH参照温度とは別です。`delta_g_eV`は標準状態モデルの量で、混合組成や非平衡の反応方向を返した値ではありません。

`Property.formation_reference`は`temperature_K`（0以上）、`basis: standard_elements`、`standard_pressure_Pa`（正値）、任意の`electron_convention: ion|electron`、`electron_enthalpy_eV`（非負）を保持します。欠落欄は不明として保存できます。比較には参加種の温度・基準・圧の一致が必要で、有限温度のイオンの規約も一致する必要があります。0 Kでは両電子規約が一致します。有限温度のion規約で自由電子の化学量論が変わる場合は、電子形成量の明示も必要です。未知の規約・無言の温度補正・電子熱モデルで不足を埋めません。

evidenceには宣言値、tier、status、出典、存在根拠、membership、thermoの相・標準圧力、datasetの次数・単位・不確かさ・asset情報を残します。`provenance` は明示されたprovider、collection、release、record_id、citation、URL等です。`source_declaration` は原宣言、`method` は科学的方法、`review_scope` は宣言された審査範囲を保全します。provider名から方法や品質を推定しません。これらの保存だけで各宣言を承認しません。実測SHA-256と宣言SHA-256は別々に保存します。読込みで保持可能なdataset等の非有限宣言はevidence内で文字列として保持し、計算に採用した数値は有限値だけにします。

明示scopeは存在宣言の `state_existence`、個別Propertyの物性名、NASAの `thermochemical_model`、反応記録の `channel_assertion`、`threshold_eV`、`delta_e_eV` をそれぞれ制限します。scope外と `status: rejected/conflicting` の宣言は、資格あるtierでも計算に採用しません。Property・NASAのstatusもevidenceへ保存します。Propertyの `qualifier` は非束縛等の科学的内容として区別します。空または省略scopeの旧記録は各型の既存資格を維持し、数値snapshotでは対応する数値量へ限定します。scope省略だけで科学的な承認を与えません。

scopeは承認する命題、statusは科学宣言自体の受理・拒否状態です。親状態記録の拒否・競合はその宣言全体の利用停止で、個別Property・NASAの審査から復活させません。部分的に否定・未確定の存在主張と適格な物性を別資格で扱う場合は独立記録へ分けます。宣言の拒否を現象の不存在とは解釈しません。

同じ反応IDに複数の科学記録を保持し、channelと各energy Propertyの資格・競合を主張ごとに評価します。競合・不正な量は除外し、当該量を使うエネルギー命題だけを未確定にします。別量だけの不一致をチャネル根拠や独立計算へ広げません。除外した量は判定messageへ残します。入力overlayの `reaction_records` とRegistry channelの `records` は、正規結果では共通の `reactions[].evidence.records` に保存します。純粋な主張のrecordは `datasets: []` で、数値を併記したsnapshotの数値は独立した数値保存経路からevidenceへ届きます。反応の量の定義・独立出典・不確かさは共通Propertyで保持します。新モデルの参照条件とProperty/NASAの利用者選択は用途に応じた拡張です。

同一対象の存在根拠が相反した場合は、照合のexactを保ち、存在判定をunknownとして根拠の相反を示します。独立物性・NASAは自身の資格で評価します。assetの実測SHA-256は保存時の観測を保持し、再分析では実際に使うbytesを照合します。旧保存結果の読込みは再分析せず、保存された判定をそのまま扱います。

励起値の数値資格はevidence内の `properties.excitation_energy_eV` の値・単位・tier・sourceで表します。`energy_eV` が存在する同一レコード内で、換算後のProperty値と矛盾する二重宣言は拒否します。別レコード間の値の競合は保持して評価します。存在のstatus更新でこのPropertyを昇格させません。正規化された絶対不確かさは親の値と同じ単位で表します。

科学記録の正規IDと出典の原 `record_id` は別です。新しい状態snapshotの原IDはprovider・collection・release・source_idの名前空間から `source-state`、原IDがない宣言は `local-state` IDにします。正規状態記録の `id` は対象、`record_id` は科学宣言を識別します。保存済みoverlay・Registry・旧schema 5結果のIDは再生成しません。

反応の科学記録は原IDから `source-reaction`、原IDなしで `local-reaction`、明示snapshot `id` から `reaction-record` IDを作り、正規結果の候補反応IDと区別します。数値記録は明示した正規 `id` を保持し、省略時は同じ原ID名前空間と科学内容に基づくIDを生成します。明示scopeの数値資格はその `kind` に限り、他の主張の審査を数値承認へ流用しません。

標準acquisitionの日時・原本保存先、同じ検証済みasset bytesの保存場所だけが異なる再取得は科学的競合とせず、各原宣言を残します。検証できないbytesは同一と推測せず、未知の物理条件・注記、値、方法、資格の差は比較へ残します。evidenceの科学IDは、この併記や競合保存によって複数回現れる場合があります。候補状態・反応のID重複とは区別します。

### 量の定義と独立した反応エネルギー

`Property.definition`は明示された量の定義です。IE/EAは`atomic`、`adiabatic`、`vertical`を区別し、groundのエネルギー評価は適合する定義と物理対象だけを使います。定義不明の分子値、垂直値、未対応の相・対象はその比較へ適用しません。単位がeVでも別測定量を同一視しません。

反応科学記録およびRegistry channelの`energy_properties`は`threshold_eV`と`delta_e_eV`をキーにしたProperty mappingです。Propertyは`value/unit`、`definition`、独立の`tier/status/review_scope`、`method/provenance/source_declaration`、任意の`uncertainty`を持ちます。閾値の定義は`channel_threshold`と`appearance_energy`、差は`products_minus_reactants`を区別します。appearance energyを衝突閾値へ流用せず、未対応qualifierから数値限界を推測しません。これらの定義だけでは測定の時間窓・エネルギーframe等を保証しません。

旧外部`threshold_eV`と`deltaE_products_minus_reactants_eV`は入口adapterで一度だけPropertyへ変換し、元の値・資格・宣言を保存します。定義や測定誤差は補いません。新Propertyと旧scalarの重複は換算値の一致が必要です。明示したPropertyは親channelのtierで承認しません。内部の`ReactionRecord`/`RegistryReaction`のconstructorと`dataclasses.replace`では`energy_properties`を使い、旧scalar keywordを残す内部互換経路はありません。scalarの読取getterは同じPropertyから導きます。

## 補助表・図


CSVは同じresultから作る補助表示です。状態表は可読名の `state`、相・構造、判定、理由、末尾 `id`。反応表は可読反応式、過程、5判定、エネルギー、数値利用結果、必要入力・変換、理由、末尾IDです。各判定は`*_verdict`、`*_proposition`、`*_scope`、`*_reason`で保存済み結論・命題・個別の適用範囲・理由を表示します。未宣言のpropositionを表示のために創作しません。数値の不足は`user_inputs`、`source_information`、`source_selection`、`external_models`、`transforms`、`unsupported_inputs`へ分け、入力可能な条件は実際の条件キーで表示します。詳細な出典や内部生成情報はYAMLで確認できます。空の一覧も同じCSVヘッダーを持ちます。

新規保存は`metadata.helper_view_format: 3`を持ちます。CSVは各判定の`*_requirements`、`*_dependencies`（JSONセル）、採用`dataset_id/quantity`、`conditions/data_selection/disagreements`、全`thermochemical_values`を追加します。個別scopeと既存値を含め、その表示内容はhashの対象です。形式2は当時のmetadata scopeと列、形式省略の旧結果は形式1の列・hashをそのまま再現します。旧判定を再計算せず、未記録項目を創作しません。新情報が必要なら原入力と証拠から明示的に再分析します。

`rgen needs RESULT`は概要、対象・量・責務による既知の必要情報`work`、保存判定・データ除外の指摘群`needs`を返します。`summary.known_prerequisites`は異なる対象・量・作業の組合せ数、`derived_findings`は既存結果から派生した指摘数、`findings_without_prerequisites`は具体的要件を記録していない指摘数です。`work.target_tasks`は各分類内の対象別必要情報数で、同じ原因・一括解消を保証しません。`--detail`の`details`は全対象・理由、`work_details`は必要情報ごとの理由・影響判定を持ちます。状態参照やDataUseの同じ不足を作業として重複計数しません。失敗した命題、範囲外データ、資料不足、同定、未対応モデルを区別し、`fail`を無条件の修復・削除要求にしません。

`rgen view`はCSV、offline HTML、matrix PNG、pathway PNGを保存結果から生成します。ネットワークの判定未選択表示は `unknown` と区別し、verdictフィルターを無効にします。行列は8000列以下で `matrix.png`、超過時は `matrix.html` と範囲ごとの `matrix-NNN-内容hash.png` を生成します。反応列を間引かず、全ページの範囲・総数を索引に示します。索引は全画像の保存後に公開し、失敗時は旧索引の参照を保持します。判定の累積gateや機構ready判定は追加しません。経路の電子seed、第三体・表面の前提、図から言えないことはREADMEで説明します。

## 保存の整合と移行

正規YAMLの公開は単一replaceです。複数のCSVを同時にatomic公開する保証はありません。CSV失敗時は `PartialOutputError` とCLI終了コード1で「正規結果は保存済み、CSV未完了」を示します。正規結果単独の読込みは可能です。API `export.read(..., verify_views=True)` はCSVの欠損・hash不一致を検出し、`rgen view RESULT --kind csv --out DIR` で再生成できます。

`helper_views`の宣言hash自体も、保存形式に従って正規内容から導いたCSVと一致する必要があります。CSVへ表示される判定・値・理由等を手編集して古いhashを残した結果は、CSV確認を省略した読込みでも拒否します。旧形式1に含まれなかった反応判定のmessage等はこのCSV hash検査の対象外で、YAML全体の署名ではありません。正規結果の変更は再分析で行い、補助CSVだけが古い場合に再生成します。全YAML入口は同一mapping内の明示した重複キーを拒否します。

schemaは型・必要フィールド・語彙を確認し、共通validatorは有限値、重複ID、IDと物理同定、反応の参照、入力と生成供給状態、集計・完了の矛盾も拒否します。形式受理は科学的承認ではありません。

schema4への対応は `tools/migrate_v4.py` に限定します。原本と出典を保存して新分析を行い、旧判定・選択・ready flagを採用しません。通常処理に旧形式のfallbackを持ちません。移行手順・対象と撤去時期は[README](../README.md)を参照してください。
