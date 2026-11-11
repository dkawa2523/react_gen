# 公開出力仕様：schema 5

正規科学結果は `result.yaml` です。schema 5の新規結果は `helper_view_format: 10` で保存します。schemaの実装元は [result.schema.yaml](../src/reactgen/result.schema.yaml) です。[公開schemaの参照](../schemas/bundle.schema.yaml)・[保存の整合と移行](#保存の整合と移行)

## 正規結果

| キー | 意味 |
|---|---|
| input | 正規化したgases、supplies、明示structures、任意のreactions、表示name、物理conditions、surfaces、探索limits、data_selection |
| metadata | schema/generator version、証拠のfingerprint、生成範囲、命題の意味 |
| summary | 全候補の件数と判定・数値利用結果の集計。機構全体のready指標ではない |
| states | 全状態候補、同定情報、正規化した証拠、3判定 |
| reactions | 全反応候補、式・過程・transformation、証拠、従来5判定とconservation／energy、計算結果・値、data_use |
| scientific_records | 計算で使った他反応の関係量と、計算・判定・出典選択で参照した候補集合外の状態記録。原対象・量・出典を保持。マップのキーは格納用で、原記録IDが同じでも記録を分ける。候補外の状態には `calculation_target` を保持 |
| pathways | 実供給・条件、candidate／conditionedの到達性、全producerと代表、除外／未確認の判定参照 |
| helper_views | 一覧と判定別CSVの相対パスおよび期待SHA-256 |

`metadata.generation` は `scope`、`limits`、`stop_reason`、`completion.mechanical`、`completion.attested` と両者の完了結果を持ちます。completeは全実在反応を網羅したことを表しません。入力・出典・乱数なしの同じ計算は同じ結果になります。

`max_depth` は機械生成、明示式、資料由来チャネルが探索に加わる深さに共通です。上限で展開できなかった枝は `unexpanded` に残します。明示式は後続探索の対象外になった場合も個別判定に残ります。

`limits.expand_unresolved_states: false` は、組成仮説や未解像・集約準位を機械生成の入射粒子として再展開する範囲から外します。明示供給と、登録済み粒子を使う資料由来・明示指定の式は引き続き探索できます。この範囲指定を `input.limits` と `metadata.generation.limits` に保存します。省略時の `true` は全候補を機械探索の入口に含める既定範囲です。意図して選んだ範囲の外は上限での打切りと区別し、完了状態は選んだ範囲内での結論です。

`input_scope`の`atom / diatomic / central_ligand / formula_only`は式の表現範囲で、物理構造の同定ではありません。formula-onlyでも整数partitionの組成仮説は生成し、実bond切断の同定と区別します。`metadata.generation.trials/unexpanded/gaps`は試行数、上限で未展開の演算・対象、依存／表現未対応を保持します。要求した演算に未対応が残る場合も機械生成を未完了とし、組成側の閉包だけを全体の完了へ昇格しません。`max_atoms`は機械生成の範囲で、既定の実数値をinputへ保存します。

状態は `id, composition, charge, state(kind/resolution/label), phase, structure` で対象を表し、`classes, origin, depth, introduced_by` は生成・表現の情報です。`state_axes` はそこから導いた表示軸です。反応は正の化学量論数を持つ `reactants/products`、`family/process`、`third_body/surface`、`stabilization`、生成情報を持ちます。IDは正規化したチャネルから計算し、式と参照先が一致することを検査します。

`input.reactions` は明示仮説がある場合に保存し、各要素は正規化した `equation`、`process`、任意の `stabilization` を持ちます。式の粒子から衝突カテゴリーを定め、宣言した過程の式形は科学判定で評価します。同じ候補IDの機械生成・資料由来の枝があれば、その候補を共有します。追加分は `origin: requested` です。反応物が揃い収支に反証がない明示式は探索の作業列に入り、探索上限内でその生成物を展開します。探索の外に残った明示式も評価対象として保存するため、全件数は探索上限を上回る場合があります。式にだけ現れる粒子は明示供給に含まれず、指定した枝への到達は経路照会で判定します。

非原子の未同定生成物は`state.kind: composition`と`resolution: lumped`で表し、既知ground／isomerへ無言統合しません。`transformation`は親／collider、移動group・qG、graphのmap／edit等の実対応を持ち、同じ式の別解釈はalternativesに保持します。生成履歴だけでなく、この対応を宣言変換の検査に使います。外部feed classは供給にせず、`metadata.supply_state_ids`は明示input由来の状態だけです。

## 形式7以降の計算と経路

各反応の`conservation`は`element_charge_conservation`、`energy`は`collision_energy_necessary_condition`です。後者は整数量論・入射二粒子のeventと、その条件に対応する端点energyの名目必要条件です。分数量論の熱化学差を単一衝突へ無言で換算しません。COM値に役割を併記した場合はそのpairへの条件として扱い、未指定COMへmass／役割を追加要求しません。

外部記録の明示された非気相状態を含む式は、気相COM判定の対象外です。状態の相が未同定の場合は、相の同定に必要な作業を示します。元素・電荷・核種の収支は独立して保存します。

`thermochemical_calculations`は従来のΔH/G/Kと、`state_energy_difference_eV`、`collision_energy_margin_eV`、適格な場合の`proton_transfer_delta_h_eV/proton_transfer_delta_g_eV`を持ちます。成功値の`operation`は演算、`inputs`は実使用record／quantity／係数または上流計算／条件を参照します。`alternatives`は完備した別案の値・演算・入力と採否です。参照・定義の互換性を確認してからsource順位を使い、未採用の値の相違を消しません。

端点差の代替値は `state_energy_difference_eV` に残します。差を選べない場合、残余エネルギーには採用に必要な作業を示します。単一生成物の捕獲では、安定化の宣言がなければ交換条件の確認を求めます。放射などを宣言した場合や第三体がある場合は、対応する交換モデルが必要です。いずれも計算できる端点差は独立して保持します。衝突条件の適用外など、作業を伴わない `unavailable` の理由は正規結果で確認できます。`rgen needs` はこれらを調査項目から除きます。

初終の対応が得られた準位移行は、`level_gap_1_eV` 等に粒子別の差を持ちます。番号は初状態ID、終状態IDの順です。`inputs` の `operation: level_state_pair` が `initial` と `final` を指し、数値の項が使用記録と係数を指します。相殺後の衝突全体が一つの準位移行と一致する場合、採用済みの `state_energy_difference_eV` を参照します。正の差は励起方向、負の差は失活方向です。数値が不足する場合は同じ計算に不足理由を残します。

複合衝突の `state_energy_difference_eV` を粒子別の準位差と残りの端点差から合成した場合、`operation` は `level_gaps_plus_remaining_endpoints` です。`inputs` に粒子別の計算への参照と、残りの端点差に使った記録が入ります。

機械生成では非基底準位間を `level_transfer`、解離と準位移行の同時変換を `dissociation_with_level_transfer` として保存します。重粒子の `dissociative_detachment` は分割・相手粒子・放出電子を `transformation` に持ちます。旧結果は当時の過程名・IDで読み込みます。旧生成IDで `data_selection.targets` を指定していた場合は、対象指定を外して再分析し、現候補のIDを確認してください。

明示核種を持つ中性ラジカル原子と中性閉殻分子の終端単結合同位体交換は `isotope_exchange` です。`transformation` に原子対応と結合編集を保存し、同じ候補の別の有効な原子対応も保持します。

衝突誘起解離の `graph_edit` では、`parent` と `fragments` に対する結合編集・原子対応を再生します。`collider` と `collider_product` は別に照合します。昇降を宣言した重粒子の準位移行では、符号付き `level_gap_1_eV` を参照して宣言との整合を判定します。基底と励起の順序が使える場合は、差の値がなくても方向を判定できます。両端が励起準位で差の符号が決まらない場合は、方向も未確定です。

PA差は同温度のΔH、GB差は同温度・標準状態のΔGです。0 K端点差、垂直IE／EA、appearance、統計不確かさを同じenergy閾値へまとめません。新しい比較は名目点値モデルで、真値の包含保証ではありません。未同定nuclideやunboundとの競合を0や成功ラベルで補いません。

PA差とGB差の参照温度は、それぞれ `proton_transfer_delta_h_reference_temperature_K` と `proton_transfer_delta_g_reference_temperature_K` に保存します。GBの標準圧は `proton_transfer_delta_g_standard_pressure_Pa` です。適格な出典の組が競合すると、計算を `unavailable` とし、採用作業と符号付きの代替入力を保持します。値を選択した場合も他の完備した案を辿れます。従来の保存結果は当時の条件名で読み込みます。

`pathways`は`seeds/conditions/scope/unconfirmed_states`と二つのmodeを持ちます。各modeの`state_layers/reaction_layers`はAND深さ、`producer_ids`は到達グラフ中の全生成枝、`primary_producer`は一代表、`default_target`は表示用の例です。`excluded/unresolved`は反応と保存判定への参照です。形式8以降では `candidate` が保存則の反証、`conditioned` がさらに過程と同条件のエネルギーの反証を適用します。条件外、量の不足、Mの交換、未同定中間体は理由を辿れます。系内で生成する電子も全反応物の支持に含め、閉路から供給を作りません。形式7の結果は保存時の経路規則で読みます。

CSV形式7は従来列にconservation／energyのverdict・命題・scope・理由・要件・依存・ラベルとtransformationを追加します。PNG／HTMLは保存indexを使います。追加seedは同じ計算への明示再問い合わせであり、その供給・条件・支持案を成果物にも保存します。

探索前に入力粒子へ結び付けた衝突相手は、完全な状態IDを `input.conditions` と `pathways.conditions` に保存します。経路照会では、実際に辿れる枝と、共反応物が未到達の周辺反応を区別します。

`collision_energy_eV` を指定すると、その値と座標系を衝突比較に使います。これを省略した場合、電子・イオン衝突では該当する入射エネルギー欄を実験室系として使えます。入射粒子の種類、標的の静止条件、質量を確認し、採用した入力欄と換算に使った粒子を保存します。指定した条件を束縛・換算できない場合は必要な入力や出典を示します。

`input.conditions.collision_pairs` は、入射粒子・標的の状態ID、`collision_energy_eV`、`collision_energy_frame`、任意の `target_at_rest` のリストです。粒子の並び順にかかわらず同じ入射二粒子の組には一件を指定し、実験室系では入射側と静止標的の役割を保持します。直下の単一衝突エネルギー・役割欄とは併用しません。記載した組だけを比較し、照合されない組には単一エネルギーへの代入を行いません。成功した計算の `inputs[].input` は、正規化した保存リスト上の `conditions.collision_pairs[N].collision_energy_eV` を参照します。各組のエネルギーは単一衝突の必要条件に作用し、分布平均や係数の入力とは区別します。

`view --checked` は `conditioned` を起点にした経路照会です。保存則・過程・衝突エネルギーの必要条件が `pass` の枝を対象に、未同定の参加状態や、存在支持・基底アニオンの束縛に反証を持つ枝と供給を除外します。`structure_unverified` は、明示SMILESの検証結果、または資料内の構造IDに厳密に一致する審査済みの状態支持が得られていないことを表します。同定済みの枝に残る存在支持・束縛の `unknown` は根拠への参照を保持します。PNGとHTMLは実際の支持案と、供給の除外理由 `excluded_seeds` を持ちます。HTMLでは枝の除外理由 `excluded` も確認できます。`excluded` と `unresolved` の状態参照は `{state, assessment, proposition}` で保存判定を指します。速度、分岐、経路全体の条件の同時実現には別の評価が必要です。

条件付き経路の代表は各状態の最小AND深さを維持します。同じ深さでは、供給まで辿る各枝のうち最も弱い判定で順位を決めます。`--checked` の条件を満たす支持、保存則・過程・エネルギーが通った支持、未確定の枝を含む支持、参加状態に明示的な反証を含む支持の順です。保存した代表枝と既定表示対象は、保存された到達性との整合を確認して読みます。`view --target STATE --via REACTION_ID` は、指定枝が対象種を正味生成し、全反応物が対象種を除いた供給から到達できるとき、その支持経路を表示します。条件付き照会では、前段に参加状態の反証がない支持を優先し、指定枝を含めて保存則・過程・エネルギーが通る支持があればその範囲を使います。同じ深さでの順位は通常の代表経路と共通です。`network` と `pathway` は同じ照会を使います。

計算入力は同じ反応内の計算や保存された出典を参照します。形式9の科学記録参照は原記録ID `record_id` と宣言を識別する `record_ref` を持ち、対象、量、保存された原値・単位と照合します。候補に入らなかった状態から計算に使った記録は、元の状態と `calculation_target` を持つ `scientific_records` に残ります。原記録IDが重複する場合も別々の記録を保持します。循環する計算参照は保存検証でエラーになります。

候補外の基底参照で出典を保存した対象と、個別の採用要求を指定した対象は、`metadata.calculation_reference_state_ids` に残ります。`rgen records RESULT --target STATE_ID --quantity QUANTITY` で参照対象の保存記録を確認できます。`target_scope: calculation_reference` は参照状態を表し、探索候補や経路の供給は `states` と `metadata.supply_state_ids` から確認できます。

表示では同じ最小深さの別の生成枝と、その状態が既に存在することに依存し得る後段の生成枝を区別します。経路図の付属情報は照会時の供給 `seeds` と実効供給 `effective_seeds` を保持します。`state_claims` は保存済みの存在・束縛の反証と未確定を、`unconfirmed_states` は同定不足を示します。副生成物を含む参加状態が対象です。探索上限で展開されず個別評価に残った明示式が経路に入る場合、`skipped_requested_expansions` に反応IDごとの探索深さと打切り理由を示します。

状態の`evidence.records`は評価に渡す照合記録、任意の`related_records`は採用していない同組成・電荷の関連資料です。`rgen records`の各記録の`target_match`は、保存した照合groupから導く`exact / compatible / related`という対応範囲で、資料の資格ではありません。完全一致があっても関連資料を消さず、表示で新しく照合・採用しません。過去結果では追加欄を省略できます。

化学式IDで書かれたRegistry記録を明示構造へ照合した場合は、原記録の対象と構造照合の根拠を保持します。状態記録は `molecular_identity`、反応記録は原参加状態IDをキーとする `molecular_identities` にSMILESと出典を持ちます。準位差を明示構造へ適用した場合も、原記録の対象と参照状態IDを保持します。形式9の `metadata.input_structure_bindings` は、`structures` で指定した元のSMILESと、それが束縛された供給状態IDを保存します。再読込み時にRDKitを使える場合はグラフを再照合します。RDKitが使えず表記が異なる場合は、保存時に検証した組合せだけを受理します。

`rgen records RESULT --target REACTION_ID --quantity delta_e_eV` は、保存済みの状態差と準位差から出典を辿ります。`energy_role: direct` は同じ初終端点の直接差の選択候補で、逆向きに記載された量も含みます。`derived` はD₀・IE・EA・準位差・形成量などの導出に使った記録、`declaration` は計算への使用が記録されていない対象式の宣言です。`energy_uses` は採用値と代替値を区別し、使った対象・量・演算・符号付き係数を示します。反応の `delta_e_eV` を直接選択する場合は `direct` の記録のIDか `record_ref` を使います。

外部科学記録の原項は合算前に有限・正・非booleanを確認します。正の分数と同種の重複項は保持でき、負項の相殺は形式不正です。候補の整合判定は同じ規則の違反を`fail`にし、形式不正と科学命題の失敗の入口を区別します。

新規の係数集約・正味差・保存則は、保存された十進係数の加減算を共通に使います。微小な別種の寄与を絶対許容差で消さず、同一種の宣言値だけを相殺します。最終数値はfloat表現の範囲です。旧形式1～5の反応ID照合では当時の合算規則も保持し、過去のIDやCSVを変更しません。

通常のIDは `CF4@ground` や `Ar+@ground` です。多価は `Ar^2+@ground` と書き、`Ar2+@ground` と区別します。通常表現で区別できない相・構造・kind・resolutionには明示suffixを付けます。IDの内部構成を利用者が理解する必要はありませんが、API照合と図のseed/target指定には完全なIDを使います。

## 判定と数値利用

判定は `{verdict, basis, message, proposition, scope, requirements, dependencies, label, blocking_causes}` です。ラベルは保存されたverdict・typed work・依存先から導く投影で、新しい科学判定ではありません。新規結果は命題と個別の適用範囲を必ず持ちます。旧schema 5結果の追加項目は省略可能で、欠ける意味を再判定・補完しません。verdictは `pass / fail / unknown / not_applicable` の4値です。各命題の適用範囲は個別 `scope` と[現行責務](core_design.md)で定義します。metadataは判定区分全体の説明です。basisは重複しない出典・処理根拠、messageはその命題についての理由です。同一のpassを、別の命題へ流用しません。

気相の一価ground anionで、存在支持と電子束縛を分ける必要がある場合は`electron_binding`を保存します。命題は`ground_anion_electron_binding`です。既存の`state`がこの命題を所有する場合は二重保存せず、そちらを参照します。存在のconfirmedから束縛を推定せず、束縛との不適合が固定終状態の前提に作用した場合はenergy判定から参照できます。独立に計算できるΔやmarginは保持します。形式7の状態CSVにこの任意判定の列を追加し、集計の分母は判定を持つ対象だけです。無関係な中性・cationへ欠測を作りません。

電子束縛の判断で比較に使ったEA宣言は、該当する判定の `record_inputs` に対象・量・原記録ID・`record_ref` を保持します。対象アニオンの `records --quantity electron_affinity_eV` は、対応する中性基底の宣言と、使った判定を `assessment_uses` に表示します。

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

状態差が未確定の場合は、対応する断熱IE・EA、実準位差、共通0 K参照の形成量など、適用できる導出が使う対象と量を示します。別の導出による取得方法は理由欄で説明します。値の競合は採用作業、未解像の端点や核種は同定作業です。保存則に明示的な矛盾がある式では、衝突エネルギー判定を対象外として保存します。

対応が確定した気相基底状態で、中性から正イオン、または正イオンから上の電荷段に進む端点差は正です。逆向きは同じ差の負符号を使います。同じ基底から励起準位への差も準位の順序を満たす必要があります。直接宣言と導出値に同じ規則を適用します。矛盾する記録は出典確認の対象に残り、他に適格な値があれば計算に使います。

`participant_state_support`は電子以外の参加状態の名前付き判定を参照し、一つでもfailならfail、failがなくunknownがあればunknown、残りはpassです。個々の命題・scopeを保持し、束縛支持を観測存在へ昇格しません。kineticsはDataUseがcoefficientならpass、提供された元量の評価が全てinvalid/out_of_rangeならfail、それ以外はunknownです。命題は提供された証拠集合と入力条件での係数利用で、未取得の全データを含む可用性や反応の不存在を意味しません。形式6のDataUseラベルは全範囲外なら`out_of_range`、それ以外の全除外なら`excluded`となり、この同じ規則を使います。

宣言値の整合、モデル内の判定、現象の成立は別です。不確かさ未宣言は測定誤差ゼロではありません。名目点を比較した場合はその範囲をscope/messageへ記録し、区間比較も宣言された範囲の関係として返します。信頼水準・相関・確率分布を推定しません。

電子解離・非電子単分子解離・2粒子会合は、宣言familyに対応する式patternを確認します。対応外の誘起機構は`unknown`です。会合・解離の`consistency=pass`にも、安定化や励起起源を式から決められない旨をmessageへ残します。反応の発生や係数の利用可否は別の判定です。

`data_use`は指定条件で係数を利用する目的の結果です。元の断面積や確率の資格と、係数へ変換するための必要情報を区別し、以下を保持します。

- `status` は `coefficient`、`needs_input`、`needs_transform`、`unavailable`、`conflict`、`not_applicable`。保存則で棄却した式の係数利用は `not_applicable` とし、元の数値記録とその評価は保持します。
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

明示SMILESの表記が異なる資料をグラフの同一性で照合した場合、`reactions[].evidence.structure_aliases` に、式を照合した元の状態IDから共通比較IDへの対応を必要なときだけ保存します。元の状態ID、原反応式、データの宣言は保持します。再読込みでは組成・電荷・相・準位の整合を確認し、RDKitを利用できる環境ではグラフも照合します。

読込み時はstatusと具体値・単位・選択dataset・不足の関係も検証します。`coefficient`は具体的な速度係数と採用datasetを必要とし、未解決のtyped workを持ちません。新規結果では元の量のkind/observableとevidence、元の量に不適切な変換作業、typed workと従来配列、採用値・単位と用途結果を照合します。DataUseは元の記録の不足を落としてはならず、必要な用途変換を追加できます。ゼロ係数やゼロ確率は有効な数値で、nullと区別します。

`A=0`のArrhenius係数や明示ゼロ定数はゼロとして利用できます。一方、正の計算値が浮動小数点の表現範囲を超える場合は、元の量を`unavailable`、作業を`external_models / numerical_evaluation_range`とします。計算限界を科学データの不正、入力・資料の欠測、ゼロの係数へ読み替えません。
形式6のDataUse `unavailable`では、旧互換の`required_inputs`に未対応モデルの名前が残る場合があります。実際の担当作業は`requirements.responsibility`を使い、これを受理可能な物理入力の不足と解釈しません。

明示要求がある結果では、`selection` が正規入力と一致し、採用IDとkindがevidenceの記録を指し、`prefer`・`only`・固定recordの要求に従うことも検査します。不一致IDは保存されたdataset評価に存在する必要があります。選択情報の追加前のschema 5結果は、従来の必須項目で読めます。

## 数値の採用要求

`input.data_selection.quantities`は全体方針、`input.data_selection.targets.<正規対象ID>.<量>`は個別上書きです。反応の対象量は `rate_coefficient`、`cross_section`、`sticking_coefficient`、`delta_e_eV` です。状態の対象量は `enthalpy_formation_eV`、`ionization_energy_eV`、`electron_affinity_eV`、`excitation_energy_eV`、`proton_affinity_eV`、`gas_basicity_eV`、`mass_amu`、`thermochemical_model` です。存在根拠の範囲指定は未対応です。各要求は次の項目を持ちます。

| 項目 | 規則 |
|---|---|
| mode | prefer（既定）またはonly |
| methods | measured / evaluated / calculated / estimated / unknown のリスト |
| providers | 記録のprovenance.provider識別子のリスト |
| collections | 記録のprovenance.collection識別子のリスト |
| record | 係数・断面積等ではdatasetのID。物性・NASAでは独立状態記録、`delta_e_eV` では対象式への直接量を持つ反応記録を指定する。原記録IDを共有する資料を区別するには `rgen records` の `record_ref` を使う |

`prefer` は、指定した軸をmethods→providers→collectionsの順で比較し、各リスト内の順を優先します。リスト外はその軸の共通の後順位です。`only` は指定したすべての軸を満たす記録に制限し、リスト順を順位として使いません。`only` には少なくとも一つの軸またはrecordが必要です。`quantities`のrecord指定は分析全体の同量へ作用し、指定IDを持たない対象では選択不足になります。`targets`のrecord指定は指定対象の同量だけへ作用し、その対象・量の全体方針を置き換えます。個別記録の固定には対象別指定を使います。適格性検査は免除しません。識別子は明示値を使い、出典台帳への登録を要求しません。

端点差の直接量への `prefer` は、優先軸のいずれかに適格な記録が一致した場合に直接量を優先します。空の優先指定や全軸で該当記録がない場合は、直接量と独立した導出値の比較を続けます。候補外の基底参照には、電荷・準位を介した計算で使う形成エンタルピー・電離エネルギー・電子親和力を `targets` で個別指定できます。実験室系から重心系への換算に必要な質量は、適格な記録の選び直し、提供済み記録の審査、未取得の質量を区別して報告します。

全記録の元の量を評価してから要求を適用します。preferの順位比較は同じkind・observable、係数では同じ速度次数の代替記録内で行います。別の量・速度則を高順位資料へ置き換えません。優先記録が不正・範囲外なら他の適格な記録へ進めます。優先記録の適用条件が不足している場合は、その不足を残します。同じ量の同順位記録が不一致なら`conflict`で、明示優先から一つを採用できた場合も`disagreements`を保持します。出典の優先は数値資格、同定、適用条件とは別です。[旧 `preferred` の扱い](#保存の整合と移行)

異なる次数・物理量のデータは同じ数値でも同等としません。複数の速度則や数値量が適用できるときは、必要条件または固定record・制限による明示選択で用途を定めます。preferの品質順だけで異なる定義を一つにしません。従来`required_inputs`の`rate_law_selection`は採用宣言、`dataset_applicability_conditions`は出典の適用条件不足で、通常の条件入力キーではありません。非重複の適用域は競合とせず、条件入力による絞り込みを要求します。競合の場合もtyped workを保持します。

## 熱化学値と出典

`reactions[].thermochemical_calculations` には、衝突エネルギーに関する計算に加えて、ΔH・標準ΔG・数密度形Kの独立した計算結果を保存します。未計算の量にも `status`・`reason`・`requirements` を持たせます。エネルギー命題の `verdict` と分けて読みます。

保存則で反証された式のΔH・標準ΔG・数密度形Kは `not_applicable` になります。原資料は証拠として残し、これらの値と係数利用を適用対象の集計から外します。

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

unitはΔH/Gが`eV`、Kが`m^(-3Δν)`の具体表記（Δν=1で`m-3`、−1で`m3`、0で`dimensionless`）です。Kを逆係数として使う機能や、反応方向・発生を保証しません。不足はその計算のrequirementsへ置き、エネルギー命題へ足しません。例えば温度未入力や範囲外でも参照ΔHを保持し、形成参照不足でも独立NASA値を保持します。電子衝突チャネルの標準ΔG・Kは現行の熱平衡モデルの範囲外として、`unavailable` と理由を保持します。その欄から候補経路の調査に不要なデータ補完作業を生成しません。気相のみから表面反応全体の熱化学を得る計算は未対応です。

Kは`log K = −ΔG°/(kBT) + Δν log(p°/(kBT))`の項をまとめてから指数化します。最終値が有限でも中間項だけがoverflow/underflowすることを避けます。最終値そのものの表現限界は計算不能として保持します。

`thermochemistry` は、成功した計算値・条件とエネルギー命題の補助値をまとめた表示です。`delta_h_eV`、`delta_g_eV`、`threshold_eV` は反応イベントあたりのeVです。Pythonの `Evaluation.thermochemistry` も同じ値を読むためのMappingです。

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

外部記録の旧 `threshold_eV` と `deltaE_products_minus_reactants_eV` は、読み込み時にPropertyへ変換し、元の値・資格・宣言を保存します。現行の `energy_properties` と併記する場合は換算値の一致が必要です。量の定義、測定誤差、Propertyの資格は個別の記録から判断します。

## 補助表・図

形式10では `states.csv` と `reactions.csv` は一覧です。`judgments/KEY.csv` は反応の一つの判定、`judgments/state-KEY.csv` は状態の一つの判定を表示します。状態の `state` 判定は `state-support.csv` です。表は `id` で正規結果や出典へ対応します。同じ表示名の状態はIDを添えて区別し、反応の安定化は独立列で示します。判定を持つ対象ごとに `verdict`、`label`、`proposition`、`reason`、`scope`、`basis`、`blocking_causes`、`next_steps`、`depends_on` を表示します。

| 判定表 | 固有の列と読み方 |
|---|---|
| `energy.csv` | `projectile_state` と `target_state` は適用した入射条件の状態ID。役割が未確定の場合は `collision_entrance` に入射側の状態IDを表示。入射値・座標系、重心系の値、端点状態差、余裕はそれぞれ独立列。元の入力欄は `collision_input` で辿れる |
| `reaction_evidence.csv` | `declared_threshold_eV` は保存された出典の閾値。定義・適用条件は出典レコードで確認 |
| `thermochemistry.csv` | 反応エンタルピー差・基準温度・標準圧力、ギブズエネルギー差 |
| `kinetics.csv` | 係数用途、元の量・値・単位・記録ID、係数利用に必要な作業 |

`collision_energy_margin_eV.inputs` の `input` を持つ項が照合済みの宣言を指し、状態ID・入射値・座標系・標的静止の既知項目を保持します。`conditions.relative_collision_energy_eV` は重心系の値が決まった場合に保存します。照合済みの入射条件があっても、余裕を算出できなければ余裕欄は空です。保存則・適用相などの前提で比較対象から除外した枝には適用条件を付けません。エネルギーの `pass` は、保存された命題の必要条件が成立したことを示します。文献閾値、装置条件での発生、確率やレートは個別の根拠を確認します。

`rgen view RESULT --kind csv` は保存形式に対応する一覧と判定表を再生成します。`--judgment KEY` は指定した判定表を再生成し、`--verdict` でその判定だけを絞れます。`--family`、`--process`、繰り返し指定できる `--require KEY=VERDICT` は、反応の保存済み区分・過程・判定の完全一致で絞ります。反応フィルター付きの照会は反応だけを対象とします。絞った表は既定の `selection/` に `*.filtered.csv` として保存します。該当行がなければヘッダーを残します。`--out DIR` で出力先を変更できます。

`rgen needs RESULT`は概要、対象・量・責務による既知の必要情報`work`、保存判定・データ除外の指摘群`needs`を返します。`summary.known_prerequisites`は異なる対象・量・作業の組合せ数、`derived_findings`は既存結果から派生した指摘数、`findings_without_prerequisites`は具体的要件を記録していない指摘数です。`work.target_tasks`は各分類内の対象別必要情報数で、同じ原因・一括解消を保証しません。`--detail`の`details`は全対象・理由、`work_details`は必要情報ごとの理由・影響判定を持ちます。状態参照やDataUseの同じ不足を作業として重複計数しません。失敗した命題、範囲外データ、資料不足、同定、未対応モデルを区別し、`fail`を無条件の修復・削除要求にしません。

係数用途に必要作業が記録されている場合は、その担当区分を表示します。作業がなく、係数用途が `out_of_range` または `excluded` と保存されている場合は `excluded_data` にまとめます。

`rgen view` は図を既定の `graphs/` に生成します。`energy` は照合済みの入射対ごとの符号付き重心系余裕を描きます。点を描いた件数と照合した件数を示し、余裕を持たない枝は表で確認できます。同じ対が複数ページになる場合は共通の数値軸を使います。`judgment --judgment KEY` は反応の一つの判定について、衝突区分ごとの件数と割合を描きます。未確定・適用外・判定未記録を区別します。エネルギー図・判定図には反応の絞り込みを適用できます。

`reaction --reaction ID` は一反応の量論と参加状態を示すSVGです。`pathway --target STATE` は対象種への代表経路のPNGです。反応ノードに過程と照合済みの入射エネルギーを添え、各反応の両側と量論を直接描きます。同じ反応段の局所的な電子ノードは、入口と出口それぞれで共有します。各反応の矢印と量論は個別に保持します。中間種への接続は、上流で生成された電子を含め、保存された支持関係を表します。第三体Mは両側、表面の宣言は反応ノードに添えます。既定出力先では照会ごとに別名を使います。`reactgen.pathway_query` の `blocked_direct_producers` は保存判定による除外と、未到達の共反応物を区別します。

`network` はオフラインHTMLの詳細閲覧です。過程・適用した入射条件・選択した判定を絞り、保存則と過程の `pass` を追加条件にできます。`--target` を指定すると経路を開きます。`matrix` は反応列と状態行の参加関係を表示し、8000列以下で `matrix.png`、超過時は索引とページごとのPNGを生成します。図は対象となる保存結果の探索範囲を示します。再解析後に使う図は新しい結果から生成します。

`rgen records RESULT --target ID [--quantity QUANTITY]` は出典と選択に使える記録IDを表示します。数値記録の `native_evaluation` は元の量の保存評価、反応単位の `coefficient_use` は係数用途の結論です。`coefficient_use.dataset_id` は保存された選択先で、係数が未確定のときも候補を指す場合があります。`--quantity` は記録一覧に作用します。反応単位の係数評価は異なる量の記録を指すことがあります。`--detail` は保存されている適用条件・選択・不一致・不足の詳細を含めます。旧結果に保存されていない評価は補いません。

### DNT向けの出力

`rgen view RESULT --kind dnt [--out DIR]` は既定の `dnt/dnt_inputs.yaml` に DNT+／DNT+DM の前処理用データを保存します。入口が量論係数1の気相イオン・中性粒子各一者で、保存と過程の判定が `pass` の二体反応が対象です。第三体・表面・外部安定化を指定する枝を除きます。出口の状態支持・エネルギー・文献支持は判定を保持し、個別に判断できます。該当する入口がなければ `pairs: []` を出力します。

| 欄 | 内容 |
|---|---|
| `analysis` | 元の形式、Registry等を含む証拠指紋、探索の完了、物理条件。`states` は入口・出口IDに対応する組成・電荷・状態・構造。 |
| `pairs` | イオンの質量、中性粒子の質量・分極率・永久双極子の大きさ・衝突半径の保存宣言。`declared` は、対応が厳密で出典付きの有効な点値が一意のとき。推定値を含み、採用・校正の判断は宣言の出典・tierから確認する。競合・利用できる宣言がない場合は値が `null`。 |
| `reduced_mass_amu`、`neutral_dipole_model_hint` | 両質量の宣言値から換算質量 $\mu=m_\mathrm{ion}m_\mathrm{neutral}/(m_\mathrm{ion}+m_\mathrm{neutral})$ を計算する。永久双極子の点値がゼロなら `dnt_plus`、正なら `dnt_plus_dm`、値が決まらなければ `null`。中性分子の双極子によるモデル候補を示す。 |
| `channels` | 各候補の過程・生成物・安定化宣言・保存判定・端点差と計算入力・文献閾値と出典・照合済み重心系入射エネルギー。閾値と端点差は別の欄に出力する。計算入力の記録IDは元の正規結果から辿れる。 |

出力形式は `reactgen_dnt_preprocessing`、`schema_version: 1` です。外部の実装に渡すには、そのソルバーが要求する入力形式への変換、チャネル選択、相互作用パラメータやエネルギー格子の決定が必要です。[ベンチマークでの利用例](reaction_judgment_matrix.md#ベンチマークとdnt向け出力)

## 保存の整合と移行

正規YAMLの公開は単一replaceです。複数のCSVを同時にatomic公開する保証はありません。CSV失敗時は `PartialOutputError` とCLI終了コード1で「正規結果は保存済み、CSV未完了」を示します。正規結果単独の読込みは可能です。API `export.read(..., verify_views=True)` はCSVの欠損・hash不一致を検出し、`rgen view RESULT --kind csv --out DIR` で再生成できます。

`helper_views`の宣言hash自体も、保存形式に従って正規内容から導いたCSVと一致する必要があります。CSVへ表示される判定・値・理由等を手編集して古いhashを残した結果は、CSV確認を省略した読込みでも拒否します。旧形式1に含まれなかった反応判定のmessage等はこのCSV hash検査の対象外で、YAML全体の署名ではありません。正規結果の変更は再分析で行い、補助CSVだけが古い場合に再生成します。全YAML入口は同一mapping内の明示した重複キーを拒否します。

schemaは型・必要フィールド・語彙を確認し、共通validatorは有限値、重複ID、IDと物理同定、反応の参照、入力と生成供給状態、集計・完了の矛盾も拒否します。形式4以降では元の数値量のevidence参照、typed workと従来配列、係数用途・状態の共通投影、成功計算とflat値・条件の整合も検査します。形式5以降では保存verdict・必要作業・依存先とラベル、不足統計の一致も確認します。未計算の量へ数値を置いた結果や、成功値へ未解決作業を残した結果を拒否します。これらは保存結果の関係を照合する処理で、元ファイルの再取得、算術・科学判定の再実行ではありません。形式受理は科学的承認ではありません。

schema 5の形式1〜9は当時の一覧とハッシュ規則で読み込み・再生成します。`helper_view_format` が省略された結果は形式1です。旧結果からも `--judgment` で判定別CSVや図を作れます。保存されている入射条件の参照を辿り、照合結果の記録がない枝の条件欄は空になります。通常出力を形式10に移すには、元の入力と証拠で再分析します。以前の `judgments.csv` を使う手順は、判定名を持つCSVの列 `verdict`、`reason`、`id` などを参照する形に変更してください。旧 `states/properties/thermo` overlayは読み込み時に変換します。datasetの旧 `preferred` は量別要求が無い場合だけ使い、2.0で撤去予定です。[記録形式](registry_data_guide.md)

新規の反応結果では、値を生成する処理がなかった `kinetic_effects` を省略します。旧結果にこの欄があれば保存内容として読み込めます。結果を直接読む利用側は、同梱schemaを更新し、この欄の有無に依存せず `family`・`process`・各判定を使ってください。

schema 4のbundleは移行工具で別ディレクトリへ再分析します。

```powershell
.\.venv\Scripts\python.exe tools/migrate_v4.py --input old_input.yaml --bundle old_outputs --out new_result --evidence registry
```

移行工具は原入力・旧bundle・出典を保全し、取り込める宣言を `imported` として復元します。旧判定や採用を持ち込まず、元の反応式が特定できない関連資料は原本に残します。未使用の旧条件は移行報告に分けます。この工具は2.0で撤去予定です。

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
