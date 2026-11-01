# 公開出力仕様：schema 5

1.0の正規科学結果は`result.yaml`一つです。schemaの実装元は[result.schema.yaml](../src/reactgen/result.schema.yaml)で、[schemas/bundle.schema.yaml](../schemas/bundle.schema.yaml)はそこを参照します。保存と読込みは同じ検査を使います。schema 5の過去結果では後から追加された項目を省略でき、0.6以降の結果も読み込めます。新規の`helper_view_format: 6`では元の数値量、typed work、独立計算、判定ラベルと不足統計の意味・整合を確認します。形式1–5はその版の列・ラベル投影とhashを維持します。旧IDや判定は読込みで再生成・再評価しません。0.5の3分割YAMLや選択policyを現行形式として読みません。

## 正規結果

| キー | 意味 |
|---|---|
| input | 正規化したgases、表示name、物理conditions、surfaces、計算limits、明示したdata_selection |
| metadata | schema/generator version、証拠のfingerprint、生成範囲、命題の意味 |
| summary | 全候補の件数と判定・数値利用結果の集計。機構全体のready指標ではない |
| states | 全状態候補、同定情報、正規化した証拠、3判定 |
| reactions | 全反応候補、式・過程、正規化した証拠、5判定、熱化学計算結果・値、data_use |
| helper_views | states.csvとreactions.csvの期待SHA-256 |

`metadata.generation` は `scope`、`limits`、`stop_reason`、`completion.mechanical`、`completion.attested` と両者の完了結果を持ちます。completeは全実在反応を網羅したことを表しません。入力・出典・乱数なしの同じ計算は同じ結果になります。

新規の`input_scope`は入力式を`atom / diatomic / central_ligand / formula_only`へ分類した機械文法の範囲です。物理構造の同定結果ではありません。`formula_only`の結合分割未対応は完了時もCLIへ表示します。過去結果では省略でき、表示で再分類しません。

状態は `id, composition, charge, state(kind/resolution/label), phase, structure` で対象を表し、`classes, origin, depth, introduced_by` は生成・表現の情報です。`state_axes` はそこから導いた表示軸です。反応は正の化学量論数を持つ `reactants/products`、`family/process`、`third_body/surface`、`stabilization`、生成情報を持ちます。IDは正規化したチャネルから計算し、式と参照先が一致することを検査します。

状態の`evidence.records`は評価に渡す照合記録、任意の`related_records`は採用していない同組成・電荷の関連資料です。`rgen records`の各記録の`target_match`は、保存した照合groupから導く`exact / compatible / related`という対応範囲で、資料の資格ではありません。完全一致があっても関連資料を消さず、表示で新しく照合・採用しません。過去結果では追加欄を省略できます。

外部科学記録の原項は合算前に有限・正・非booleanを確認します。正の分数と同種の重複項は保持でき、負項の相殺は形式不正です。候補の整合判定は同じ規則の違反を`fail`にし、形式不正と科学命題の失敗の入口を区別します。

新規の係数集約・正味差・保存則は、保存された十進係数の加減算を共通に使います。微小な別種の寄与を絶対許容差で消さず、同一種の宣言値だけを相殺します。最終数値はfloat表現の範囲です。旧形式1～5の反応ID照合では当時の合算規則も保持し、過去のIDやCSVを変更しません。

通常のIDは `CF4@ground` や `Ar+@ground` です。多価は `Ar^2+@ground` と書き、`Ar2+@ground` と区別します。通常表現で区別できない相・構造・kind・resolutionには明示suffixを付けます。IDの内部構成を利用者が理解する必要はありませんが、API照合と図のseed/target指定には完全なIDを使います。

## 判定と数値利用

判定は `{verdict, basis, message, proposition, scope, requirements, dependencies, label, blocking_causes}` です。ラベルは保存されたverdict・typed work・依存先から導く投影で、新しい科学判定ではありません。新規結果は命題と個別の適用範囲を必ず持ちます。旧schema 5結果の追加項目は省略可能で、欠ける意味を再判定・補完しません。verdictは `pass / fail / unknown / not_applicable` の4値です。各命題の適用範囲は個別 `scope` と[現行責務](core_design.md)で定義します。metadataは判定区分全体の説明です。basisは重複しない出典・処理根拠、messageはその命題についての理由です。同一のpassを、別の命題へ流用しません。

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

`requirements`は`{responsibility, target, quantity, reason}`の配列です。必要な対象と量・条件、作業の区分と理由を保存します。`user_inputs`だけが実際に受理する条件名を指し、出典の定義・適用条件やモデル未対応を入力項目にしません。数値記録の`conditions.gas_temperature_K`等は同じ受理条件の参照です。`dependencies`は`[state_id, assessment_key]`の配列で、参加状態の集約が参照する保存判定を指します。参照先が存在しない結果は拒否します。参加状態の集約とDataUseからkineticsへの投影は共通規則から導き、保存読込みでも参照先・verdict・重複要件の矛盾を拒否します。kineticsの要件は正規DataUseを参照し、同じ情報を二重管理しません。

`participant_state_support`は電子以外の参加状態の名前付き判定を参照し、一つでもfailならfail、failがなくunknownがあればunknown、残りはpassです。個々の命題・scopeを保持し、束縛支持を観測存在へ昇格しません。kineticsはDataUseがcoefficientならpass、提供された元量の評価が全てinvalid/out_of_rangeならfail、それ以外はunknownです。命題は提供された証拠集合と入力条件での係数利用で、未取得の全データを含む可用性や反応の不存在を意味しません。形式6のDataUseラベルは全範囲外なら`out_of_range`、それ以外の全除外なら`excluded`となり、この同じ規則を使います。

宣言値の整合、モデル内の判定、現象の成立は別です。不確かさ未宣言は測定誤差ゼロではありません。名目点を比較した場合はその範囲をscope/messageへ記録し、区間比較も宣言された範囲の関係として返します。信頼水準・相関・確率分布を推定しません。

電子解離・非電子単分子解離・2粒子会合は、宣言familyに対応する式patternを確認します。対応外の誘起機構は`unknown`です。会合・解離の`consistency=pass`にも、安定化や励起起源を式から決められない旨をmessageへ残します。反応の発生や係数の利用可否は別の判定です。

`data_use`は指定条件で係数を利用する目的の結果です。元の断面積や確率の資格と、係数へ変換するための必要情報を区別し、以下を保持します。

- `status`: coefficient、needs_input、needs_transform、unavailable、conflict。
- `dataset_id/kind`: 採用した表現。採用不可ならnull。
- `value/unit`: 評価した値と単位。係数以外の確率値はstatusと併せて読む。
- `scope/requirements/reason`: 目的・保証範囲、必要な対象・量・作業、結果の理由。
- `required_inputs/required_transforms`: typed requirementsから共通規則で導く従来の不足配列。別に更新しない。
- `estimated`: 推定によるデータかどうか。
- `datasets`: 元の量ごとのDatasetAssessment。valid、invalid、out_of_range、needs_input、reference_only、unreviewed、unavailable、conflictと個別の意味・不足を保持。
- `selection`: 入力の明示した量別採用要求。未指定なら空mapping。
- `disagreements`: 他の適格な記録との数値不一致、または同一IDの内容競合があるdataset ID。採用ID自身は含めない。

同じIDで異なる内容を見つけた場合も、元レコードはevidenceに保持します。単なる利用可否から状態・反応の実在や機構の予測可能性を結論しません。

`datasets[]`は`dataset_id/status/reason/value/unit`に加え、`kind/observable/scope/requirements`を持ちます。kindは係数・断面積・sticking確率、observableは反応衝突・運動量移行等の量の意味です。scalar量は指定条件で評価し、断面積は曲線として確認するため、`valid`でも`value: null`です。単位・収録域、点列または数値表の参照・hashはevidenceへ保持します。外部表の点列を確認する場合は対応するassetも必要です。入力エネルギーから暗黙の一点評価を行いません。ID競合で量を一意に決められない場合はkind/observableもnullになり得ます。

元の曲線の評価へEEDF・分布積分の作業を、元の確率の評価へ入射・流束変換の作業を混ぜません。係数用途のDataUseには、元の記録自身の不足に加えて必要な分布・変換を保存します。直接利用できる係数があれば独立曲線の変換不足で消しません。運動量移行断面積は衝突回数を表す別量へそのまま変換できず、分布積分だけで反応係数が得られるとは扱いません。有効な元曲線と、必要な反応衝突断面積を別に示します。

新規結果ではtyped requirementsが不足の正です。従来配列には出典条件・採用・未対応モデルの歴史的語彙も含まれるため、全要素をConditionsの入力キーと解釈しません。通常利用者が入力できる項目は`responsibility: user_inputs`から読み取ります。変換名だけで実行済みとは解釈しません。

datasetの`invalid`には、数値形式の不正だけでなく、総過程データと特定生成物チャネルの不適合も含みます。原数値が誤りであることや現象の不存在を一律に意味しません。`reason`で対象と不適合の理由を確認し、元の測定値と条件はevidenceで読めます。

原記録の`status: rejected`は`invalid`、`conflicting`は`conflict`として保持し、`reference_only`でも欠測へ読み替えません。拒否・競合した親反応記録内の数値offerも利用を停止しますが、元の数値宣言を変更せず、別の独立した適格offerは利用できます。除外された記録の修復を、別記録から係数を得るための必須条件にはしません。

evidence内の数値記録は`reaction_target`に正規物理チャネルID、`declared_target`に入口で明示した`reaction/reaction_id/family/type/third_body/surface/stabilization`を必要な範囲で保持します。候補への参照IDと物理IDを区別し、候補を得た境界で対応付けます。同じ数値科学IDの異対象への割当て、明示対象との不一致は入力不整合です。同対象の再取得や値の競合とは別です。過去の記録では両欄を省略でき、原宣言自由文から後付けしません。

読込み時はstatusと具体値・単位・選択dataset・不足の関係も検証します。`coefficient`は具体的な速度係数と採用datasetを必要とし、未解決のtyped workを持ちません。新規結果では元の量のkind/observableとevidence、元の量に不適切な変換作業、typed workと従来配列、採用値・単位と用途結果を照合します。DataUseは元の記録の不足を落としてはならず、必要な用途変換を追加できます。ゼロ係数やゼロ確率は有効な数値で、nullと区別します。

`A=0`のArrhenius係数や明示ゼロ定数はゼロとして利用できます。一方、正の計算値が浮動小数点の表現範囲を超える場合は、元の量を`unavailable`、作業を`external_models / numerical_evaluation_range`とします。計算限界を科学データの不正、入力・資料の欠測、ゼロの係数へ読み替えません。
形式6のDataUse `unavailable`では、旧互換の`required_inputs`に未対応モデルの名前が残る場合があります。実際の担当作業は`requirements.responsibility`を使い、これを受理可能な物理入力の不足と解釈しません。

明示要求がある結果では、`selection` が正規入力と一致し、採用IDとkindがevidenceの記録を指し、`prefer`・`only`・固定recordの要求に従うことも検査します。不一致IDは保存されたdataset評価に存在する必要があります。選択情報の追加前のschema 5結果は、従来の必須項目で読めます。

## 数値の採用要求

`input.data_selection.quantities`は全体方針、`input.data_selection.targets.<正規対象ID>.<量>`は個別上書きです。対象量は`rate_coefficient`、`cross_section`、`sticking_coefficient`、`enthalpy_formation_eV`、`ionization_energy_eV`、`electron_affinity_eV`、`excitation_energy_eV`、`thermochemical_model`です。存在根拠の範囲指定は未対応です。各要求は次の項目を持ちます。

| 項目 | 規則 |
|---|---|
| mode | prefer（既定）またはonly |
| methods | measured / evaluated / calculated / estimated / unknown のリスト |
| providers | 記録のprovenance.provider識別子のリスト |
| collections | 記録のprovenance.collection識別子のリスト |
| record | 数値datasetのid、物性・NASAでは独立状態record_id。異なる量やonly制限と矛盾する指定はエラー |

`prefer` は、指定した軸をmethods→providers→collectionsの順で比較し、各リスト内の順を優先します。リスト外はその軸の共通の後順位です。`only` は指定したすべての軸を満たす記録に制限し、リスト順を順位として使いません。`only` には少なくとも一つの軸またはrecordが必要です。`quantities`のrecord指定は分析全体の同量へ作用し、指定IDを持たない対象では選択不足になります。`targets`のrecord指定は指定対象の同量だけへ作用し、その対象・量の全体方針を置き換えます。個別記録の固定には対象別指定を使います。適格性検査は免除しません。識別子は明示値を使い、出典台帳への登録を要求しません。

全記録の元の量を評価してから要求を適用します。preferの順位比較は同じkind・observable、係数では同じ速度次数の代替記録内で行います。別の量・速度則を高順位資料へ置き換えません。優先記録が不正・範囲外なら他の適格な記録へ進めます。優先記録の適用条件が不足している場合は、その不足を残します。同じ量の同順位記録が不一致なら`conflict`で、明示優先から一つを採用できた場合も`disagreements`を保持します。出典の優先は数値資格、同定、適用条件とは別です。対応する量に要求がない場合だけ旧dataset `preferred`の互換処理を使い、理由へ移行案内を記録します。2.0で撤去する予定です。

異なる次数・物理量のデータは同じ数値でも同等としません。複数の速度則や数値量が適用できるときは、必要条件または固定record・制限による明示選択で用途を定めます。preferの品質順だけで異なる定義を一つにしません。従来`required_inputs`の`rate_law_selection`は採用宣言、`dataset_applicability_conditions`は出典の適用条件不足で、通常の条件入力キーではありません。非重複の適用域は競合とせず、条件入力による絞り込みを要求します。競合の場合もtyped workを保持します。

## 熱化学値と出典

新規の`reactions[].thermochemical_calculations`はΔH・標準ΔG・数密度形Kの独立した計算結果です。各要素は`{status, value, unit, reason, requirements, conditions}`を持ち、形式5以降では`label/blocking_causes`も保存します。エネルギー命題のverdictと分けて読みます。形式4以降では現行3量の結果を未計算の場合も保存し、欠けた結果を拒否します。追加の計算量も受理でき、今後の拡張数を固定する制限ではありません。

| quantity | 値の意味・条件 |
|---|---|
| delta_h_eV | 共通参照での形成量の生成物−反応物差。条件はdelta_h_reference_temperature_K、delta_h_standard_pressure_Pa |
| delta_g_eV | thermal gas ground-state NASA7評価、または同一表現の恒等差による標準Gibbs反応エネルギー。NASA評価で使うtemperature_K、必要なstandard_pressure_Paを保存 |
| equilibrium_constant_number_density | 同じNASA7差、または同一表現の恒等差から導く数密度形平衡比。NASA評価で使うtemperature_K、必要なstandard_pressure_Pa、密度次数equilibrium_constant_density_powerを保存 |

| status | 意味 |
|---|---|
| computed | 有限値と使用条件を返す。未解決のrequirementsはない |
| needs_input | 現行計算に必要な利用者条件が未入力。値はnull |
| unavailable | 資格・対象・参照条件の不足や競合、未対応モデル、数値表現限界。値はnull |
| out_of_range | 指定温度が保存モデルの適用範囲外。条件・理由を保持し、外挿せず値はnull |

unitはΔH/Gが`eV`、Kが`m^(-3Δν)`の具体表記（Δν=1で`m-3`、−1で`m3`、0で`dimensionless`）です。Kを逆係数として使う機能や、反応方向・発生を保証しません。不足はその計算のrequirementsへ置き、エネルギー命題へ足しません。例えば温度未入力や範囲外でも参照ΔHを保持し、形成参照不足でも独立NASA値を保持します。電子チャネルと表面reservoirを含む反応のNASA計算、気相のみから表面反応全体の熱化学を得る計算は未対応です。

Kは`log K = −ΔG°/(kBT) + Δν log(p°/(kBT))`の項をまとめてから指数化します。最終値が有限でも中間項だけがoverflow/underflowすることを避けます。最終値そのものの表現限界は計算不能として保持します。

`thermochemistry`は成功した計算値・条件と、エネルギー命題の補助値を併せるflat表示です。`delta_h_eV, delta_g_eV, threshold_eV`は一反応イベントあたりのeVです。物理的な比較が未確定でも独立に得られた値を隠しません。Pythonの`Evaluation.thermochemistry`は読み取りMapping viewで、`get/items/lookup`を維持し、取得辞書の編集で正規値を変更しません。計算値は`thermochemical_calculations`、補助値は`energy_values`から投影し、同名量の上書きを拒否します。内部Evaluationを直接構築する場合の旧`thermochemistry`引数は`energy_values`へ置き換え、計算値をそこへ複写しません。`assess_thermochemistry`の従来の2戻り値は維持します。

`delta_h_eV`の参照不足・不一致や上限・近似注記では点値ΔHを返さず、その計算の理由・必要作業へ残します。`temperature_K`はNASAの標準G/K計算に使った温度で、ΔH参照温度とは別です。同一状態が両側で打ち消される場合、その状態の量・参照を要求しません。相・構造・状態が異なる項は打ち消さず、式の参加者や速度則から粒子を削除しません。電子・表面を含まず、全参加状態が明示された気相基底状態で完全に打ち消される場合は、温度・係数・標準圧に依存せずΔG=0・K=1をcomputedとして返します。未使用T/pをconditionsへ置かず、Kには密度次数0だけを保存します。未知相・非気相・非groundはこの恒等枝へ入れず、存在や別命題の不足も解消しません。`delta_g_eV`は標準状態モデルの量で、混合組成や非平衡の反応方向を返した値ではありません。

`Property.formation_reference`は`temperature_K`（0以上）、`basis: standard_elements`、`standard_pressure_Pa`（正値）、任意の`electron_convention: ion|electron`、`electron_enthalpy_eV`（非負）を保持します。欠落欄は不明として保存できます。比較には参加種の温度・基準・圧の一致が必要で、有限温度のイオンの規約も一致する必要があります。0 Kでは両電子規約が一致します。有限温度のion規約で自由電子の化学量論が変わる場合は、電子形成量の明示も必要です。未知の規約・無言の温度補正・電子熱モデルで不足を埋めません。

evidenceには宣言値、tier、status、出典、存在根拠、membership、thermoの相・標準圧力、datasetの次数・単位・不確かさ・asset情報を残します。`provenance` は明示されたprovider、collection、release、record_id、citation、URL等です。`source_declaration` は原宣言、`method` は科学的方法、`review_scope` は宣言された審査範囲を保全します。provider名から方法や品質を推定しません。これらの保存だけで各宣言を承認しません。実測SHA-256と宣言SHA-256は別々に保存します。読込みで保持可能なdataset等の非有限宣言はevidence内で文字列として保持し、計算に採用した数値は有限値だけにします。

取得側の要求query・対象別名は`source_declaration.acquisition.request`に保存します。同じ物理対象・原記録の取得検索文脈だけの差を科学的な内容差にしません。独立に返された`source_identity`や未知の科学条件・注記は保持して比較します。反応snapshotから作る参加状態表現は反応原IDを状態原IDへ流用せず、原反応への派生参照を保持します。

明示scopeは存在宣言の `state_existence`、個別Propertyの物性名、NASAの `thermochemical_model`、反応記録の `channel_assertion`、`threshold_eV`、`delta_e_eV` をそれぞれ制限します。scope外と `status: rejected/conflicting` の宣言は、資格あるtierでも計算に採用しません。Property・NASAのstatusもevidenceへ保存します。Propertyの `qualifier` は非束縛等の科学的内容として区別します。空または省略scopeの旧記録は各型の既存資格を維持し、数値snapshotでは対応する数値量へ限定します。scope省略だけで科学的な承認を与えません。

scopeは承認する命題、statusは科学宣言自体の受理・拒否状態です。親状態記録の拒否・競合はその宣言全体の利用停止で、個別Property・NASAの審査から復活させません。部分的に否定・未確定の存在主張と適格な物性を別資格で扱う場合は独立記録へ分けます。宣言の拒否を現象の不存在とは解釈しません。

同じ反応IDに複数の科学記録を保持し、channelと各energy Propertyの資格・競合を主張ごとに評価します。競合・不正な量は除外し、当該量を使うエネルギー命題だけを未確定にします。別量だけの不一致をチャネル根拠や独立計算へ広げません。エネルギー関係の除外量はそのmessageへ、Hf/NASAの計算不能理由は独立calculationへ残します。入力overlayの`reaction_records`とRegistry channelの`records`は、正規結果では共通の`reactions[].evidence.records`に保存します。純粋な主張のrecordは`datasets: []`で、数値を併記したsnapshotの数値は独立経路からevidenceへ届きます。反応の量の定義・独立出典・不確かさは共通Propertyで保持します。Property/NASAも量別・対象別要求を適用します。新モデルの参照条件は用途に応じて拡張します。

同一対象の存在根拠が相反した場合は、照合のexactを保ち、存在判定をunknownとして根拠の相反を示します。独立物性・NASAは自身の資格で評価します。assetの実測SHA-256は保存時の観測を保持し、再分析では実際に使うbytesを照合します。旧保存結果の読込みは再分析せず、保存された判定をそのまま扱います。

励起値の数値資格はevidence内の `properties.excitation_energy_eV` の値・単位・tier・sourceで表します。`energy_eV` が存在する同一レコード内で、換算後のProperty値と矛盾する二重宣言は拒否します。別レコード間の値の競合は保持して評価します。存在のstatus更新でこのPropertyを昇格させません。正規化された絶対不確かさは親の値と同じ単位で表します。

科学記録の正規IDと出典の原 `record_id` は別です。新しい状態snapshotの原IDはprovider・collection・release・source_idの名前空間から `source-state`、原IDがない宣言は `local-state` IDにします。正規状態記録の `id` は対象、`record_id` は科学宣言を識別します。保存済みoverlay・Registry・旧schema 5結果のIDは再生成しません。

反応の科学記録は原IDから `source-reaction`、原IDなしで `local-reaction`、明示snapshot `id` から `reaction-record` IDを作り、正規結果の候補反応IDと区別します。数値記録は明示した正規 `id` を保持し、省略時は同じ原ID名前空間と科学内容に基づくIDを生成します。明示scopeの数値資格はその `kind` に限り、他の主張の審査を数値承認へ流用しません。

標準acquisitionの日時・原本保存先、同じ検証済みasset bytesの保存場所だけが異なる再取得は科学的競合とせず、各原宣言を残します。検証できないbytesは同一と推測せず、未知の物理条件・注記、値、方法、資格の差は比較へ残します。evidenceの科学IDは、この併記や競合保存によって複数回現れる場合があります。候補状態・反応のID重複とは区別します。

同IDの定数・Arrhenius数値記録では、振幅・Ea・同じ物理量の適用範囲・絶対不確かさの明示単位が等価なら、単位表記の違いだけを競合にしません。同単位の異値は厳密に区別し、異単位換算にはroundoffだけを許します。observable・速度次数・scope・資格・出典と未知の科学欄の差は保持します。数値評価、ingest/adopt、保存選択の整合検証は同じ比較を使いますが、原宣言やfingerprintの内容表現は変更しません。数値表・未知modelをこの変換で等価と推定しません。

### 量の定義と独立した反応エネルギー

`Property.definition`は明示された量の定義です。IE/EAは`atomic`、`adiabatic`、`vertical`を区別し、groundのエネルギー評価は適合する定義と物理対象だけを使います。定義不明の分子値、垂直値、未対応の相・対象はその比較へ適用しません。単位がeVでも別測定量を同一視しません。

反応科学記録およびRegistry channelの`energy_properties`は`threshold_eV`と`delta_e_eV`をキーにしたProperty mappingです。Propertyは`value/unit`、`definition`、独立の`tier/status/review_scope`、`method/provenance/source_declaration`、任意の`uncertainty`を持ちます。閾値の定義は`channel_threshold`と`appearance_energy`、差は`products_minus_reactants`を区別します。appearance energyを衝突閾値へ流用せず、未対応qualifierから数値限界を推測しません。これらの定義だけでは測定の時間窓・エネルギーframe等を保証しません。

旧外部`threshold_eV`と`deltaE_products_minus_reactants_eV`は入口adapterで一度だけPropertyへ変換し、元の値・資格・宣言を保存します。定義や測定誤差は補いません。新Propertyと旧scalarの重複は換算値の一致が必要です。明示したPropertyは親channelのtierで承認しません。内部の`ReactionRecord`/`RegistryReaction`のconstructorと`dataclasses.replace`では`energy_properties`を使い、旧scalar keywordを残す内部互換経路はありません。scalarの読取getterは同じPropertyから導きます。

## 補助表・図


CSVは同じresultから作る補助表示です。状態表は可読名の `state`、相・構造、判定、理由、末尾 `id`。反応表は可読反応式、過程、5判定、エネルギー、数値利用結果、必要入力・変換、理由、末尾IDです。各判定は`*_verdict`、`*_proposition`、`*_scope`、`*_reason`で保存済み結論・命題・個別の適用範囲・理由を表示します。未宣言のpropositionを表示のために創作しません。数値の不足は`user_inputs`、`source_information`、`source_selection`、`external_models`、`transforms`、`unsupported_inputs`へ分け、入力可能な条件は実際の条件キーで表示します。詳細な出典や内部生成情報はYAMLで確認できます。空の一覧も同じCSVヘッダーを持ちます。

新規保存は`metadata.helper_view_format: 6`を持ちます。形式3の各判定の`*_requirements`、`*_dependencies`（JSONセル）、採用`dataset_id/quantity`、`conditions/data_selection/disagreements`、全`thermochemical_values`と、形式4で追加した次の4列を維持します。

| 追加列 | 内容 |
|---|---|
| data_use_scope | 係数用途の保証範囲 |
| data_use_requirements | 係数用途のtyped work（JSON） |
| numerical_record_assessments | 元の数値量ごとの保存評価（JSON） |
| thermochemical_calculations | 独立3量の計算結果（JSON） |

形式5では各判定の`*_label`と`*_blocking_causes`（JSONセル）、反応CSVの`data_use_label`と`data_use_blocking_causes`を末尾ID前に追加します。形式6は同じ列を使い、全除外・全範囲外の係数用途を共有可用性規則から投影します。形式5の保存ラベル・hashは旧投影のまま読みます。数値記録・熱化学計算のラベルも既存JSONセルに含まれます。この表示内容はCSV hashの対象です。形式4は当時の列、形式3は当時の個別scope・要件・値の列、形式2はmetadata scopeと当時の列、形式省略の旧結果は形式1の列・hashをそのまま再現します。旧判定を再計算せず、未記録の元量評価・作業・計算結果を創作しません。新情報が必要なら原入力と証拠から明示的に再分析します。

`rgen needs RESULT`は概要、対象・量・責務による既知の必要情報`work`、保存判定・データ除外の指摘群`needs`を返します。`summary.known_prerequisites`は異なる対象・量・作業の組合せ数、`derived_findings`は既存結果から派生した指摘数、`findings_without_prerequisites`は具体的要件を記録していない指摘数です。`work.target_tasks`は各分類内の対象別必要情報数で、同じ原因・一括解消を保証しません。`--detail`の`details`は全対象・理由、`work_details`は必要情報ごとの理由・影響判定を持ちます。状態参照やDataUseの同じ不足を作業として重複計数しません。失敗した命題、範囲外データ、資料不足、同定、未対応モデルを区別し、`fail`を無条件の修復・削除要求にしません。

`rgen view`はCSV、offline HTML、matrix PNG、pathway PNGを保存結果から生成します。ネットワークの判定未選択表示は `unknown` と区別し、verdictフィルターを無効にします。行列は8000列以下で `matrix.png`、超過時は `matrix.html` と範囲ごとの `matrix-NNN-内容hash.png` を生成します。反応列を間引かず、全ページの範囲・総数を索引に示します。索引は全画像の保存後に公開し、失敗時は旧索引の参照を保持します。判定の累積gateや機構ready判定は追加しません。経路の電子seed、第三体・表面の前提、図から言えないことはREADMEで説明します。

## 保存の整合と移行

正規YAMLの公開は単一replaceです。複数のCSVを同時にatomic公開する保証はありません。CSV失敗時は `PartialOutputError` とCLI終了コード1で「正規結果は保存済み、CSV未完了」を示します。正規結果単独の読込みは可能です。API `export.read(..., verify_views=True)` はCSVの欠損・hash不一致を検出し、`rgen view RESULT --kind csv --out DIR` で再生成できます。

`helper_views`の宣言hash自体も、保存形式に従って正規内容から導いたCSVと一致する必要があります。CSVへ表示される判定・値・理由等を手編集して古いhashを残した結果は、CSV確認を省略した読込みでも拒否します。旧形式1に含まれなかった反応判定のmessage等はこのCSV hash検査の対象外で、YAML全体の署名ではありません。正規結果の変更は再分析で行い、補助CSVだけが古い場合に再生成します。全YAML入口は同一mapping内の明示した重複キーを拒否します。

schemaは型・必要フィールド・語彙を確認し、共通validatorは有限値、重複ID、IDと物理同定、反応の参照、入力と生成供給状態、集計・完了の矛盾も拒否します。形式4以降では元の数値量のevidence参照、typed workと従来配列、係数用途・状態の共通投影、成功計算とflat値・条件の整合も検査します。形式5以降では保存verdict・必要作業・依存先とラベル、不足統計の一致も確認します。未計算の量へ数値を置いた結果や、成功値へ未解決作業を残した結果を拒否します。これらは保存結果の関係を照合する処理で、元ファイルの再取得、算術・科学判定の再実行ではありません。形式受理は科学的承認ではありません。

schema4への対応は `tools/migrate_v4.py` に限定します。原本と出典を保存して新分析を行い、旧判定・選択・ready flagを採用しません。通常処理に旧形式のfallbackを持ちません。移行手順・対象と撤去時期は[README](../README.md)を参照してください。

## 形式5以降のラベルと不足率

| label | 意味 |
|---|---|
| satisfied / not_satisfied | 保存された命題の成立 / 不成立。反応全体の採否ではない |
| data_missing | 必要な科学量・宣言・出典条件の不足 |
| input_missing | 利用者が供給できる物理条件の不足 |
| review_required / identity_unresolved / selection_required | 資料審査 / 物理対象の同定 / 記録選択が必要 |
| model_unsupported / interface_unsupported | 計算・変換モデル / 必要入力の入口が未対応 |
| unresolved | 原因が複合する、または保存情報から一原因へ限定できない |
| available / computed | 当該数値用途で利用可能 / 当該量の計算成功 |
| excluded / out_of_range / conflicting_data | 数値記録の除外 / 範囲外 / 科学宣言の競合 |
| not_applicable | 命題の対象外 |

`blocking_causes`は未確定に作用する原因です。複合原因では`label: unresolved`と複数原因を保存します。
成立・不成立・数値除外へ不足ラベルを重ねません。kineticsはDataUse、参加状態はdependenciesの保存結果へ
従います。Curve availableから係数成功、係数利用不可から反応不存在は導きません。

`summary.coverage.judgments.<states/reactions>.<domain>`は`total`、対象外を除く`applicable`、
`by_label`、`data_missing`、`data_missing_fraction`、`unresolved_by_cause`、命題別`by_proposition`を持ちます。
割合はdata_missing/applicable、分母ゼロならnullです。`coefficient_use`と`thermochemical_calculations.<量>`も
別に集計します。`native_quantities`はkind/observable別の元記録の評価件数で、係数用途と分けます。
同じ記録を複数チャネルで評価した場合は評価ごとの件数で、独立観測数にはしません。
`targets.<states/reactions>`は候補総数`total`と、少なくとも一判定にデータ不足がある候補の
重複しない件数`with_data_missing_judgment`です。
原因件数は重なり得ます。候補・所見・作業の件数を混ぜず、機構完成度や反応発生率とは解釈しません。

`rgen needs RESULT --data-missing --detail`は保存`blocking_causes`に`data_missing`を含む未確定結果を抽出します。
複合原因で`label: unresolved`の結果も対象です。
`data_completion`はsource情報・調査の補完作業、`coverage`は保存された全体の不足統計です。
旧形式にはラベルを後付けせず、この抽出には再分析が必要です。
`rgen records RESULT --target ID [--quantity 量] [--detail]`は選択可能記録の内容を表示します。
通常表示は値・条件・資格・出所、詳細表示は全原宣言です。`targets`の方針はその対象だけで全体方針を上書きします。
NASA計算の選択は指定温度の範囲内で行い、状態の表現有無は温度利用を判定しません。
