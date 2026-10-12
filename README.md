# plasma-reactgen 0.7.4

入力ガスから、明示した文法範囲の状態・反応候補を生成し、ローカルの証拠と数値データを照合する調査ツールです。候補、確認できた命題、未確定の理由、数値の利用条件を一つの結果に残します。機構の網羅性や予測可能性は宣言しません。

## 実行

Python 3.11以上を使用します。依存関係の正は `pyproject.toml` です。

配布wheelは `python -m pip install plasma_reactgen-0.7.4-py3-none-any.whl` でインストールできます。Registry、入力例、開発文書を含むソース配布から使う場合は、次の手順で実行します。

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[quality]"
.\.venv\Scripts\rgen.exe analyze Ar CF4 --out result
.\.venv\Scripts\rgen.exe analyze Ar CF4 --evidence registry --out result
```

証拠を省略すると空の証拠で調査します。`--evidence` はRegistryディレクトリ、取得snapshot、overlayファイルを繰り返し指定できます。明示したパスが存在しない場合はエラーです。読込み・照合はネットワークやRegistryの変更を伴いません。

同じ入口を`.\.venv\Scripts\python.exe -m reactgen.cli ...`、取得を`.\.venv\Scripts\python.exe -m acquire.cli ...`としても起動できます。

入力・証拠・保存結果のYAMLで同じキーを二重に記述した場合は、後の値で上書きせず位置付きの形式エラーにします。数値欄の非数値や採用指定の非booleanも、不足情報として扱いません。

同じ処理を入力ファイルからも実行できます。直接指定との併用はできません。

```yaml
gases: [Ar, CF4]
conditions:
  gas_temperature_K: 350
  electron_temperature_eV: 4
surfaces: [SiO2, Si]
```

```powershell
.\.venv\Scripts\rgen.exe analyze --input input.yaml --evidence registry --out result
```

必須入力は中性基底状態の化学式のリスト `gases` だけです。`name` は表示用です。任意の条件は `gas_temperature_K`、`electron_temperature_eV`、`ion_temperature_K`、`surface_temperature_K`、`reduced_field_Td`、`ion_energy_eV`、`electron_energy_eV`、`collision_energy_eV` です。温度と単一の衝突エネルギーを区別し、対応する熱化学計算やデータの評価・適用範囲にだけ使います。温度や単一エネルギーから分布を無言で仮定しません。`surfaces` は照合対象の材料名で、表面flux計算の入力ではありません。

`limits` は `max_depth=12`、`max_species=300`、`max_reactions=10000`、`max_charge_abs=1`、`max_leaving_atoms=2` が既定です。すべて正の整数で、機械生成の電荷範囲は現在±1のみです。既知の多価イオンは証拠から追加できます。上限は完全性を左右する計算条件であり、物理条件ではありません。未知のキー、使わない圧力・密度・幾何量、用途preset、シナリオは受け付けません。

複数の出典がある数値は、任意の `data_selection` で量ごとに採用方針を指定できます。例えば、測定値、評価値の順に速度係数を優先する入力は次のとおりです。

```yaml
gases: [Ar]
conditions:
  gas_temperature_K: 300
data_selection:
  quantities:
    rate_coefficient:
      mode: prefer
      methods: [measured, evaluated]
```

対象量は `rate_coefficient`、`cross_section`、`sticking_coefficient` です。`prefer` は指定順に優先し、該当する適格データがなければ他の出典も調べます。`only` は指定した区分だけに制限します。区分は `methods`、`providers`、`collections` で、出典台帳にない独自providerも明示した識別子で指定できます。特定の数値記録を固定する場合は `record: datasetのID` を使います。これは全反応の指定量へ適用されるため、そのIDを持たない反応の同量は利用不可になります。軸の順序・複数軸の規則は[出力仕様](docs/output_reference.md)を参照してください。

優先指定は、同定、単位、適用域、数値資格の確認を省略しません。優先出典の適用条件が未確定なら、その不足を返します。物性、NASAモデル、存在根拠の採用区分をこの入力で指定する機能は未対応で、対応外の量・項目はエラーにします。

## 結果の読み方

通常CLIは対象と入力条件、使える係数の具体例、必要な対象・量と次の作業を先に表示します。通常の出力は3ファイルです。

- `result.yaml`: 入力、探索範囲と打切り、全候補、命題ごとの判定、出典・数値・利用条件を持つ唯一の正規結果。
- `states.csv`: 状態、相・構造、判定と理由。
- `reactions.csv`: 反応式、過程、判定、エネルギー値、数値の利用結果・不足。

CSVには各判定の命題、適用範囲、理由も表示します。利用者が入力できる条件、出典側で確認する情報、出典選択、分布等の外部モデル、未実装の変換を別列に示します。表示は保存された結論から作り、再判定しません。

`pass` はその判定の命題について支持があること、`fail` はその命題との矛盾、`unknown` は不足・競合・モデル未対応等により結論できないこと、`not_applicable` は対象外を表します。新規結果の全判定に `proposition` と個別の `scope` を記録し、必要情報は対象・量・作業を持つ `requirements`、参加状態の集約は個別判定への `dependencies` で確認できます。速度データの不正は反応の不存在を意味せず、熱化学値の存在は反応の実現を証明しません。候補は不足・不正があっても結果に残ります。

解離・会合の`consistency`は、宣言した反応族の保存則・式形を確認します。会合が安定化するか、解離が何によって励起されるか、どの条件で速度が使えるかは、その`pass`だけでは決まりません。

`data_use.status=coefficient` の場合は、指定条件で実際に評価した係数と単位を返します。`needs_input` と `needs_transform` は必要な情報・変換を返します。`unavailable` と `conflict` は採用できない理由を返します。断面積だけではEEDF積分後の係数、sticking確率だけでは表面流束は得られません。

`data_use.selection` は明示した採用方針、`disagreements` は数値の不一致やIDの競合がある記録IDです。優先指定で一つを採用しても、他の出典の記録と不一致を結果へ残します。優先指定なしで異なる値が競合する場合は、順番だけで一つに決めません。

不足には利用者の条件と、出典側の修復を区別して示します。`gas_temperature` は対応する温度入力、`dataset_applicability_conditions` はデータの適用条件の確認、`rate_law_selection` は異なる速度則の採用根拠が必要という意味です。後二者を通常入力の仮条件で埋めません。

形成エンタルピーの差は、参加種の共通参照温度・元素基準・標準圧力を確認できた場合に返します。イオンを含む有限温度の比較には電子規約も必要です。不明な既存値に298 K等を補わず、ΔHだけを計算不可にします。NASAからの標準ΔG/Kや、独立したIE・EAの結論はそれぞれの前提で評価します。

IE/EAは断熱・垂直等の量の定義を区別します。定義不明の旧分子値や別定義の値は原宣言として保全し、その定義を必要とする比較だけを未確定にします。反応の閾値・内部エネルギー差も、各量自身の資格・出典・不確かさで評価します。宣言値の整合は測定精度や反応発生の保証ではありません。

正の電子親和力と電子非束縛の宣言が矛盾する場合は未確定とし、そのEAを数値計算へ採用しません。`unstable`・`transient`や短寿命の存在宣言だけでは電子非束縛を結論しません。

励起状態の消失率や化学式全体の係数は、特定準位の生成物係数とは区別します。生成物の対応が未確認なら原数値を証拠へ残し、そのチャネルの計算には採用しません。温度を入力しても、この同定不足は解消しません。

`generation.complete` は明示した機械文法と証拠追加の範囲で処理が完了したことです。全化学の探索完了ではありません。打切りでも決まった範囲を保存し、CLIは終了コード1を返します。形式・入力エラーは2です。

## 保存結果からの補助表示

再計算せず、不足・修復一覧や図を作れます。

```powershell
.\.venv\Scripts\rgen.exe needs result
.\.venv\Scripts\rgen.exe needs result --detail
.\.venv\Scripts\rgen.exe view result --kind network --out result/views
.\.venv\Scripts\rgen.exe view result --kind matrix --out result/views
.\.venv\Scripts\rgen.exe view result --kind pathway --seed Ar@ground --seed e --target Ar+@ground --out result/views
.\.venv\Scripts\rgen.exe view result --kind csv --out result
```

`needs`は結論と不足の概要を先に返し、`work`に対象・量・責務で整理した具体的な必要情報、`needs`に保存判定やデータ除外の指摘を示します。既知の必要情報数、派生指摘数、具体的要件を持たない指摘数は別です。参加状態やDataUseから導いた同じ不足を作業として重複計数しません。`--detail`で全対象・理由・作業と影響先を確認できます。表示群数は作業数でも、一括解消の保証でもありません。判定の`fail`はその命題の失敗として示し、すべての用途で候補を修復・削除すべきという意味へ変換しません。

経路は全反応物を必要とするAND型の候補到達性です。既定の供給は入力ガスだけで、電子は明示した場合だけ供給します。`--seed` は既定供給を置換します。第三体・壁の利用可能性は図の暗黙の前提で、速度・時間・支配経路は分かりません。図は通常計算の依存先にしません。

ネットワークの詳細は、命題と範囲、利用できた値・条件・参照条件、理由・不足、採用記録・不一致・出典を保存結果から表示します。生成履歴は折り畳みます。旧結果の命題や要件の空欄は「未記録」とし、推測補完しません。

ネットワークの `All saved candidates` は判定未選択です。判定層を選んだときだけその命題のverdictを表示します。行列は8000反応以下で `matrix.png`、それを超えると全列を分割した `matrix.html` とPNGを返します。HTML索引から対象範囲を確認できます。

## 証拠の管理

```powershell
.\.venv\Scripts\rgen.exe check --registry registry
.\.venv\Scripts\rgen.exe ingest snapshot.yaml --result result --overlay overlay.yaml
.\.venv\Scripts\rgen.exe analyze Ar CF4 --evidence registry --evidence overlay.yaml --out result
.\.venv\Scripts\rgen.exe derive --registry registry --out derived.yaml
.\.venv\Scripts\rgen.exe adopt overlay.yaml --registry registry --dry-run
```

取得は別パッケージ `acquire`、照合は `ingest`、永続的な採用は `adopt` です。照合済み件数は科学的承認件数ではありません。状態の存在を支持するには、物性とは別に明示的な存在根拠が必要です。相や構造が不足したsnapshot値を気相へ無言で割り当てません。出典の資格やライセンスは[データガイド](docs/registry_data_guide.md)と[出典方針](docs/source_license_policy.md)を参照してください。

`adopt` は全件を事前検証し、通常の保存失敗では変更を復旧します。復旧にも失敗した場合は残ったbackupと失敗を報告します。[取得手順](external_data/README.md)と[個別データの科学レビュー](docs/scientific_data_review.md)を参照してください。

照合・採用は相、構造、状態と解像度まで一致する対象へ行います。`ingest` は独立した状態記録をoverlayの `state_records` へ保存し、`adopt` はRegistry種ファイルの `records` へ追加します。同一対象の異なる出典・値・NASAモデルを単一mappingへ上書きしません。出典識別子、原宣言、方法、宣言された審査範囲も保存します。値の不一致と対象の同定不足は別に扱い、競合する独立宣言を入力順で選びません。形式は[データガイド](docs/registry_data_guide.md)を参照してください。

反応主張はoverlayの `reaction_records`、Registryチャネルの `records` に独立保存します。純粋な反応根拠や閾値の宣言は数値datasetを作りません。係数等も宣言した入力は、反応主張と数値を別々に保持するため、`adopt`の書込み件数は一入力から複数になる場合があります。過程が不明な反応式を特定チャネルへ推測して割り当てず、必要な同定をreview queueへ返します。

同じ原記録の再取得は、取得日時だけで競合にせず、各取得の原宣言を併記します。状態の存在・各物性・熱化学モデルの審査範囲を対応する主張へ適用し、出典の優先指定で資格を補いません。

## 0.7からの変更

0.7.2はschema 5と通常入力を維持します。保存済みの結果は過去の判定として読み、再計算しません。新しい分析では、同一対象の存在根拠が相反しても、独立に審査された物性の利用は別に評価します。エネルギー量の競合は、その量を使う判定だけを未確定にします。量の利用成功から状態・反応の存在を承認しません。

数値表は保存した実測hashと作者の宣言hashを保持し、実際に利用する内容を照合します。表が変更された場合は旧資格のまま計算せず、同じ検証済み内容の保存場所だけが違う場合は科学的競合にしません。原宣言と取得場所は保持します。

0.7.1で導入した審査範囲と拒否宣言の資格確認、原IDの名前空間、独立反応主張の保存は継続します。既存overlay・Registry・結果の保存IDは保持し、原IDが確認できない旧記録を推測で統合しません。

## 0.6からの移行

0.7の公開結果はschema 5の追加形式です。0.6のschema 5保存結果も読み込めます。新しい `proposition`、出典情報、採用方針・不一致は、新しい分析で保存します。再読込みは過去の判定を再計算しません。

旧 `states/properties/thermo` overlayと単一のRegistry物性は読込みadapterで受け付けます。新規取得・照合・採用では独立記録を使ってください。datasetの `preferred` は、その量の `data_selection` がない場合だけ使う旧互換指定で、理由に移行案内を返します。0.8で撤去する予定です。

## 0.5からの移行

0.6は公開形式をschema 5へ変更しています。`generate`、7 policy、`selected.yaml`、累積screening、ready booleanは廃止しました。旧bundleを通常処理で読む互換経路はありません。

```powershell
.\.venv\Scripts\python.exe tools/migrate_v4.py --input old_input.yaml --bundle old_outputs --out new_result --evidence registry
```

移行先は新しいディレクトリを指定します。原入力・旧bundle・旧証拠を保存し、使わない旧条件は移行報告へ分けます。旧判定は引き継がず再評価します。旧証拠はimportedとして復元し、相・存在根拠・assetの位置が不明なら不明のまま残します。多価電荷などIDが矛盾する原本は修正が必要です。この一回限りの工具はv4のみを対象とし、0.8で撤去する予定です。

## 開発

```powershell
.\.venv\Scripts\python.exe tools/quality.py quality-pr
```

継続的な判断は[AGENTS.md](AGENTS.md)、現行責務は[Core design](docs/core_design.md)、公開形式は[出力仕様](docs/output_reference.md)、検証入口は[品質管理](docs/quality.md)を正とします。今回の変更は[実施記録](docs/reaction_state_generation_implementation_plan.md)、残件と優先順位・完了条件は[残件計画](docs/remaining_work_plan.md)に分けています。
