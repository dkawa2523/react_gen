# 反応候補調査基盤の改良実施記録

2026-10-12更新。0.6 / schema 5の履歴と、末尾の[0.7改良](#出典複数記録数値選択の改良07)、0.7.1–0.7.3の修復・検証を記録します。

本書は実施範囲と、その版で確認した検証結果を記録します。通常利用は[README](../README.md)、現行責務は[core_design](core_design.md)、公開形式は[output_reference](output_reference.md)、長期の開発原則は[AGENTS.md](../AGENTS.md)を正とします。計画を並行した現行仕様として残しません。以下の0.6節にある「最新」「最終」、品質件数・wheel・hash・性能・保全は当時の確認範囲です。0.7の検証や保全へ転用しません。

## 0.6の実施履歴

| 計画の段階 | 実施内容 |
|---|---|
| 同定・データの誤りを修正 | 存在の自動昇格を撤去。相・構造・解像度を同定へ追加。NASAの気相照合、分子同定、CCCBDB電荷、UMIST正式配置、hash往復を修正 |
| 判定と数値利用を整理 | 過程ごとの式パターン、存在命題、エネルギー比較を分離。全datasetを評価して具体係数と不足をDataUseへ集約。単位・適用域・重複・競合・sticking・Kcを修正 |
| 生成を履歴から独立させる | 組成と明示範囲で資格を決定。規則固定点、pair両側、自己衝突、complex解離、三体次数、seed上限、多価と状態表現IDを修正 |
| 通常入力・出力を切り替える | analyzeの直接指定とYAMLを同じ処理へ統一。未使用入力と7 policyを撤去。result.yamlに全候補・判定・出典・数値を保存し、補助表と図を導出 |
| 保存と移行を整える | 正規結果の単一commit、補助表hash・再生成、失敗の区別を実装。v4原本を保存して再評価する一回限りの工具を追加 |
| 継続開発の土台を整える | AGENTS.md、現行文書、schema、品質入口と一般的な境界テストを更新。旧policy・capability・累積screeningと重複出力経路を撤去 |

## 完了範囲と制約

今回の改良は候補調査・同定・科学データの利用判断です。文法の閉包は反応機構全体の完成ではありません。入力組成の構造、非熱平衡分布、光子・壁へのエネルギーの行先など、資料や入力から決められないものを推測で補いません。

EEDF solver、速度方程式、表面flux・エッチング速度、逆速度の自動採用は今回の対象外です。これらを拡張する際には、その計算が必要とする物理入力と具体出力を設計します。今回の判定数・モジュール名・CLI・物理モデルを永久に固定しません。

旧schema4の互換経路は通常処理に残していません。移行工具は原本の値と出典を保存し、旧判定・ready flagを破棄して再分析します。曖昧な旧IDを補完せず、来歴が不足した値はimported・未同定として保持します。工具の対象はv4、撤去予定は0.8です。

初回の統合確認では、`tools/quality.py quality-pr`が253テスト、Ruffの整形・検査、mypy、依存方向の2契約をすべて通過しました。Registryの構造検査は102状態・355反応で不正0件です。Ar/CF4およびAr/SF6/O2の通常入力で分析・正規結果の保存を確認しました。配布wheelには公開schemaが含まれ、撤去した旧実装は含まれていません。これらの検証は実装と明示した責務の整合を確認するもので、機構全体の完成や予測精度を保証するものではありません。

追加点検後の判定・照合・取得・表示・保存の修復と、提供資料・旧出力の整理は本書末尾の詳細記録にまとめています。残件と優先順位は[今後の改良計画](remaining_work_plan.md)へ分けました。[科学データの個別審査](scientific_data_review.md)では原資料と適用条件を分けています。主要改修・統合確認の完了を、全データの科学的承認とは扱いません。

## 初回後続修復の確認

この段階では、Windowsの既存Python 3.12.8環境は389テスト、新規Python 3.11.15のcore + quality環境は373テストと16件の任意依存スキップで確認しました。両環境ともRuff format/check、mypy 46対象、依存方向2契約が通過しています。新環境の生成ランチャーがWindowsポリシーで遮断されたため、品質入口のimport-linterも同じPythonから公式CLI関数を起動するように整理しました。

最新コードで通常入力4例を再実行し、全正規結果をschemaと補助CSVのhashまで再読込み確認しました。件数は利用例の観測結果であり、生成の正解条件にはしていません。

| 入力例 | 状態 / 反応 | 数値利用の結果 |
|---|---|---|
| Ar | 7 / 39 | unavailable 39 |
| Ar/CF4 | 37 / 1061 | needs_input 13、unavailable 1048 |
| Ar/O2 | 19 / 200 | coefficient 2、needs_input 3、unavailable 195 |
| Ar/SF6/O2 | 97 / 7397 | coefficient 2、needs_input 176、unavailable 7219 |

4例とも宣言文法内のmechanical/attested生成は完了しています。数値不足から機構の完成を結論しません。Registry構造検査は102状態・355反応、不正0件。NIST ASDの実取得→ingest→再分析で、最低励起閾値と基底状態自身のゼロエネルギーが別の量として往復することを確認しました。derive、needs、network/matrix表示も現行入口で実行しました。

この段階のwheelは公開schemaを含み、45個のpackage source/schemaがその時点のソースと一致し、撤去済み旧moduleを含みません。Python 3.11へcore依存だけでインストールし、リポジトリ外でanalyze、schema/CSVの整合、needs、matrixを確認しました。取得CLIの新規`acquire.exe`だけは端末のWindowsポリシーに遮断され、同じ入口の`python -m acquire.cli`で起動を確認しています。GitHub上のLinux CIは未実行です。

旧v4出力348ファイルの保全と4入力すべての移行・schema5再読込みも確認済みです。残る科学資料の確認と用途別の拡張は[継続項目](remaining_work_plan.md)を参照してください。

## 共通境界修復後の統合確認

本書末尾の共通境界修復と読込み改善を追加実装したコードで、Python 3.12.8は543テスト、Python 3.11.15のcore + quality環境は527テストが成功しました。3.11では任意依存の16件をスキップしています。両環境でRuff format/check、mypy 47対象、依存方向2契約が通過しました。追加した検証は、宣言の重複、状態同定・出典・資格の保持、照合時の部分成功、エネルギー区間、条件未定の速度則、取得単位・行・精度、正規DataUseと補助表hashの整合を対象にしています。最終検索で残っていたderiveの読込み経路も統一し、不正なoverlay構造を出力前に拒否する境界を確認しました。

通常入力4例は上表と同じ件数・数値利用結果で再分析しました。全例をschema・補助表hashまで再読込みし、CSVの対象・各判定・数値利用結果を正規結果と照合しました。needsのCLIと正規結果からの抽出、CSV/network/matrix/pathwayの出力、ASD snapshotのingest・再分析、derive overlayの再読込みと取得物性の資格保持も確認しました。ASDの最低励起閾値と基底状態自身のゼロエネルギーは別の量として保持されています。確認記録は `build/verified_boundaries/verification.json` にあります。Registryの構造検査は102状態・355反応、不正0件です。科学的なデータ不足をこの構造検査で承認しません。

この段階のソースでwheelを再作成し、46個のpackage source/schemaの一致と共通safe YAML実装の収録を確認しました。Python 3.11のcore依存だけの環境へインストールし、リポジトリ外でanalyze、正規結果とCSVの対象・判定の一致、needs、matrix、CLI helpを実行しました。配布版deriveも、重複宣言と不正mappingをexit 2・出力未作成で拒否しました。当時のwheelは `build/release_check/plasma_reactgen-0.6.0-py3-none-any.whl`、SHA-256は `e403fdcc8b74fec30eb5b53e784e5367166a33acc312b4555bd07cbaee192cd6` です。当時は新規`acquire.exe`がWindowsポリシーに遮断されたため、同じ入口の`python -I -m acquire.cli`で起動を確認しました。最新wheelでの両console起動の成功は後述の最終配布確認に記録しています。ローカル確認とLinux CIの実行は区別します。


## 後続修復の詳細記録（完了）

### 計画から実装した変更

| 対象 | 実施内容と結論の範囲 |
|---|---|
| 数値の比較・採用 | 同じ物理量・次元・次数だけ比較。異なる速度則は明示採用根拠を要求。片側適用域と非重複を扱い、競合でも不足入力を保持。有限点の一致で連続域全体の同等性を宣言しない |
| 未対応過程 | 定義不足はunknown、定義済みパターンの矛盾や保存則違反はfail。現象の不存在へ読み替えない |
| 証拠の照合 | 式検索と明示IDの双方でstabilizationを照合。無指定を放射・第三体の承認にしない |
| 取得・品質の保持 | ASDの原子/イオン、CCCBDBからのadditivity推定が宣言できるgas相を保持。ASDの最低励起閾値と状態自身のエネルギーを区別。推定品質を読込み・照合・採用で保持し、存在確認へ昇格しない。小さな学習入力の不足判定にNumPyを要求しない |
| 永続採用 | 全対象・assetの事前準備、変更fileのstage、置換失敗時の復旧を実装。復旧失敗はbackupとmanifestを残し場所を報告。複数fileの同時公開・電源断・同時writerのatomic性は保証しない |
| エネルギーの資格 | 存在根拠の追加で旧励起エネルギーを承認する経路を修復。値・単位・品質を個別propertyへ正規化し、Penningと形成エンタルピー導出はその資格を使う。絶対不確かさを親の単位へ換算し、元宣言を来歴に保持 |
| イオン化下限 | 宣言thresholdとIEの宣言された不確かさ範囲を比較。重なり・不正・数値不足はunknown。統計的誤差の範囲を絶対的な物理禁止とは説明しない |
| ネットワーク | 判定未選択とunknownを区別。badge・filter・線種・Resetの意味を統一 |
| 反応行列 | 8000列を超える場合は全列を分割。範囲・総数を索引に示し、全画像の保存後に索引を公開。失敗時は旧索引の参照を保持 |
| 利用手順・配布 | 旧取得手順・廃止provider説明・CI成果物を整理。現analyze/ingest入口、生成範囲、deriveの出力、CHANGELOG、任意依存と品質環境を一致させる |

新しい契約・診断frameworkや用途presetは導入していません。関連する境界・不変条件と通常利用を確認しました。統合確認は上記に記録しています。

### 続けて実装した共通境界の修復

| 対象 | 実施内容と結論の範囲 |
|---|---|
| 入力の受理 | 共通safe YAML読込みで同じmapping内の重複宣言を拒否。正当なmergeと明示overrideは保持。boolや不正な数値文字列を物理値や情報不足へ読み替えない |
| 状態の照合・保存 | 全物理キーに一意に対応するRegistry対象だけを採用。存在宣言、個別物性の資格、準位属性と出典を別々に保持。競合する独立存在宣言を後の入力で消さず、複数payloadの一部だけを照合成功にしない。deriveも正規物理キーを使う |
| エネルギーの判定 | IE・EA・Penningに共通のProperty区間を使用。未定量の誤差をzeroとせず、同じ中心値に異なる誤差があれば全範囲を保持。対応する相・構造・準位に限定し、励起生成物やlumped状態へ基底IE式を転用しない |
| 数値モデルの選択 | 条件未入力の別速度則を不適用として捨てない。明示preferredの対象にも不足条件を保持。単位換算後の非有限値は利用できない |
| 正規結果の整合 | DataUseのstatus・選択dataset・値・単位・不足条件の対応を保存と読込みで検査。ゼロ値はnullと区別。補助表の宣言hash自体も正規結果から導いたhashと照合する |
| LXCat取得 | 明示された列・量・単位と数値行を取得境界で確認。異なる単位をeV/m2へ黙って付け替えず、不正行を捨てない。表の保存で入力精度を固定桁に丸めない |

これらは特定のガスやケース名に依存しない修復です。既存の型・戻り値と共通境界を使い、判定用の新しいframeworkは追加していません。

### 保存結果の読込み性能

既存PyYAMLのsafe C parser/emitterが利用可能なら共通読込み・正規保存に使い、利用できない環境ではsafe Python実装へ戻ります。重複宣言、schema、対象参照、DataUse、補助表hashの検査は維持しています。Python実装へのfallbackもテストしています。

Windows / Python 3.12.8で、97状態・7397反応の保存結果13,425,658 bytesを読み込んだ一回の比較では、YAML解析が19.56秒から5.47秒、同じ正規結果検証が3.07秒と3.12秒でした。結果の保存場所・hash・環境・対象数と時間を `build/result_io_benchmark.json` に記録しています。化学計算は再実行していません。一般的な処理時間の保証や、ピークメモリの改善を示す測定ではありません。

再測定の入口は次のとおりです。通常の品質チェックへ時間依存の合否条件は追加しません。

```powershell
.\.venv\Scripts\python.exe tools/benchmark_result_io.py <result.yamlのパス> --compare-python-parser
```

### 旧出力の保全と移行

Git管理下の旧work 348ファイルと4つの原入力を `build/legacy_schema4_archive/work-v4.zip` に保全しました。ZIP内の全bytesを原本と照合し、対象ごとのSHA-256を `verified_work_files.json` に保存した後、保全対象の旧出力だけを開発ソースから除去しました。通常生成物はGit対象外にしています。旧原本はGitの既存履歴にも残ります。

原入力4例すべてをv4工具で再分析し、`build/legacy_schema4_archive/migrated_<入力名>/result.yaml` に保存しました。原入力・旧bundle・復元したimported証拠と移行報告も各migration内に保持します。旧判定・ready宣言は引き継ぎません。原本を再利用する場合は同定・数値資格・asset位置を個別に確認します。

v4工具の対象はv4だけ、撤去予定は0.8です。工具・専用テスト・移行案内の撤去はそのリリースの作業であり、通常処理へ互換分岐を戻しません。

## 残件棚卸しで追加した確認項目

同日、保存結果の各判定を照合して、非電子の単分子解離にも電子衝突patternを適用してfailへ落とす経路と、2→1の出典式をreactive_scatteringと宣言した現行patternとの不整合を確認しました。この棚卸しではコードと科学データは変更していません。対応の優先順位・完了条件は[残件計画](remaining_work_plan.md)へ置きます。上記の検証成功は当時の変更と検証範囲の結果であり、残件の不存在や全科学データの承認を示しません。

## 残件計画から実装した追加改良

### 判定対象と科学データの修復

familyから適用するprocess patternを選ぶよう修正しました。電子解離と、電子を含まない単分子解離を区別し、重粒子2→1会合には一般的な式検査を追加しました。保存則や定義済みpatternの矛盾はfail、未対応の誘起機構・family・高分子数会合はunknownです。式のpassから素反応、発生率、安定化、励起起源、生成物へのエネルギー配分を決めません。会合と非電子解離では、この限界をmessageに残します。

Pateauの原著者proofのTable III/VIIで既存167係数の式・数値・SI換算・二次次数を照合し、2→1式12件をassociationへ修復しました。原表から温度・圧力適用範囲は決まらず、その不足を保存します。SonのR21–R60は原著の700 Kモデル点へ揃え、既存6件以外の34件の適用条件を修復しました。会合の安定化を推測で追加していません。R138は単分子式と共通cm3/s見出しの次元不整合が残るため、数値datasetは未採用です。

O/O+、O(1D2)、O2の存在・状態同定、O/O+の独立IE、O(1D2)の励起値、O2の気相NASA7 fitを個別に照合しました。O(1D2)は1.9673642 eVへ訂正し、原資料で誤差が空欄であることを不明のまま保持します。旧形成enthalpy・NASA近似はimportedを維持し、確認していない物性・寿命・人口を昇格していません。廃止した励起propagation設定の説明1件も削除しました。

追加の一次abstract審査では、Wildt1988の自己消光が励起状態の消失測定、Gaucherel/Rowe1977の2係数が化学種レベルの生成式であることを確認しました。3datasetをtotal_processへ限定し、特定準位の候補チャネルはneeds_reviewとしました。原数値・単位・誤差・出典と未確認条件を保持し、reaction_evidenceはunknown、数値はその生成物チャネルへ不適用です。温度入力で状態別分岐を補完しません。確認できた原資料と取得範囲は[科学審査記録](scientific_data_review.md)にあります。

### 最終品質・通常利用・配布

| 環境 | quality-prの結果 |
|---|---|
| Windows / Python 3.12.8、既存環境 | 586成功 |
| Windows / Python 3.11.15、core + quality | 570成功、任意物性依存16スキップ |
| WSL Ubuntu 24.04.4 / Python 3.11.15、core + quality | 569成功、上記16とNode不在のJS検証1スキップ |

全環境でRuff format/check、mypy 47対象、依存方向2規則が通過しました。変更した命題、一般的な式と順序、物性の独立資格、数値の対象と条件、保存往復を検証しています。独立レビューも式の整合から発生・速度へ飛躍しないこと、無関係な状態で熱化学が変わらないこと、総測定から特定生成物の係数へ昇格しないことを確認しました。

通常利用4例を最新Registryから再分析し、正規YAML・schema・CSV hash、表の対象・各判定・値・単位、CLI needsと補助表示を照合しました。観測件数は次のとおりです。全例で宣言した生成範囲はclosureに達しています。

| 入力例 | 状態 / 反応 | 数値利用の結果 |
|---|---|---|
| Ar | 7 / 39 | unavailable39 |
| Ar/O2 | 19 / 200 | coefficient2、unavailable198 |
| Ar/CF4 | 37 / 1061 | needs_input8、unavailable1053 |
| Ar/SF6/O2 | 97 / 7397 | coefficient2、needs_input167、unavailable7228 |

consistencyはこの4例の全式でpassです。科学データや全化学を一括承認した結果ではありません。最大例の不足167件はPateauの出典適用条件です。kinetics failは、範囲外9件と特定生成物scopeに不適合の3件で、現象の不存在とは解釈しません。電子seedを省略・明示した経路図、全対象と判定のHTML、PNGの対象範囲も正規結果と照合しました。

最終Registryの単体content fingerprintは `8a8a21a5a315b1c87747afb25d03143f10b4d5eb01fd352859838cf30c41da08`、CLIの複数source集約入口で単一Registryを指定したfingerprintは `7220e53bca207a2e1c11249d3bb707b83ec2747e92e90a83eb96ce5ae7bbe7c4` です。通常利用記録は `build/current_verified_boundaries/verification_report.json`、最終品質ログは `build/quality_pr_current_py312.log`、`quality_pr_current_py311.log`、`linux311_quality_pr.log`です。

ローカルLinuxではNightly対象4入力の分析・保存・CSV再読込みと両console helpも確認しました。この入力実行は3datasetのtotal_process修復前のRegistryで、最終Linux品質確認は修復後です。両記録に対象hashと範囲を分けています。GitHubのQuality PR・Nightly jobは未実行です。

最新wheelは `build/current_release_check/plasma_reactgen-0.6.0-py3-none-any.whl`、157592 bytes、SHA256 `bdd59bf394c0e2d982e1a02adf9f1cb6d0d815f8edfdeaf6420d24418964ab5f`です。46個のpackage source/schemaが現行srcと一致し、core依存だけのPython 3.11へ導入して、リポジトリ外のisolated実行でanalyze・保存/CSV・needs・matrixを確認しました。今回のwheelではrgen.exeとacquire.exe双方が起動し、acquireのmodule入口も成功しました。以前のlauncher遮断を最新wheelの未確認事項とはしていません。Registryは別の証拠入力として扱います。

### 必要範囲だけの熱化学処理と性能記録

profilingで、各反応の熱化学評価が全候補状態を繰り返し選択することを確認しました。選択をその反応の参加状態だけへ限定し、cacheや新しいframeworkは追加していません。最新Registryの97状態・7397反応に対し、従来の全状態selectorと現行selectorのAnalysisResult・正規documentが全件一致しました。同じ一回の比較で分析は8.51秒から2.66秒、約3.2倍でした。これを全入力・全環境の速度保証にはしません。

同じ最大入力を別processで測った操作別結果は次のとおりです。

| 操作 | 秒 |
|---|---:|
| ローカル証拠読込み | 0.18 |
| 候補分析 | 2.09 |
| 正規結果とCSVの保存・公開前検査 | 17.29 |
| schema・CSVを含む再読込み | 8.76 |
| needs抽出 | 0.036 |
| HTML生成 / matrix / pathway | 0.21 / 3.25 / 0.048 |

process lifetimeのピークworking setは665165824 bytes（約634 MiB）、result.yamlは13532782 bytes、HTMLは8830388 bytesでした。ピークは操作ごとの独立した割当量ではありません。ブラウザーの応答時間は測っていません。保存が現在の時間・メモリの主要な負荷ですが、必要な運用規模・応答基準が未指定なので、その適否を断定しません。時間に依存する品質テストは追加していません。

入力・環境・上限・対象hash・全件同値・profileは `build/current_analysis_profile/`、操作別時間と容量・hashは `build/current_operation_benchmark/measurement.json`へ記録しました。再現用の `build/verify_thermo_scope_performance.py` と `build/measure_current_operations.py`も保管します。通常利用の入力や診断設定には追加していません。

### 作業フォルダー外への保全

`C:\Users\user\Desktop\react_gen-preserved\2026-10-11`へcopyだけで保全しました。元ファイルの移動・削除はしていません。

- `legacy-schema4/`：旧原本ZIP、元manifest、原入力4件、移行4例。コピー42ファイルのSHA256、ZIP352項目の全bytesとCRC、旧work348項目、原入力4件を照合しました。復元READMEと保存先から実行できる完全性検査を同封しています。ZIPのSHA256は `b21687df1c529d1267df7d5e88cfe0a6622d072cf0057818736ead399ad45a41`です。
- `current-verification/`：最新wheel、通常利用の入力・全結果・検証script・表示・report・配布ログ。元と保存先をSHA256で照合し、保存先の検査scriptでも確認しました。
- `current-verification/root-supplement/`：最終品質・Linux・性能記録と再現script、未commitを含む現行ソース・Registry・テスト・文書・設定のsnapshot。manifestで原ファイルとZIPのhashを記録し、復元は新しい空ディレクトリへ行います。既存Git cloneへの上書き復元は前提にしません。

これはworkspaceの削除から独立した同端末のローカル保管で、別媒体のbackupではありません。原資料PDFの取得・再配布資格は別で、未確認の全文は同梱していません。長期の開発原則はAGENTS.md、今後必要な科学資料と用途別拡張は[残件計画](remaining_work_plan.md)へ分けます。

## 出典・複数記録・数値選択の改良（0.7）

2026-10-12。[出典基盤計画](data_foundation_plan.md)のA修復と、B/C/Dの共通基盤・数値選択を実装しました。packageは0.7.0、公開結果はschema 5のまま、proposition・selection・disagreementsを任意項目として追加しています。旧schema 5結果を対象外へ変更しません。snapshot出力はversion 1を明示し、未version旧入力は境界で受理、未知versionは拒否します。

| 対象 | 実装した責務と結論の範囲 |
|---|---|
| 対応種・同一性 | 電荷交換の親と生成物を組成・電荷・相・構造・基底状態・唯一性で確認。無関係な固相/構造と入力順に依存しない。elasticは式上の同一性を確認してから内部エネルギー同一性を判定 |
| 複数出典 | 同PairKeyの全チャネルを安定順で保持。同一IDは同内容でも両file/位置を示して拒否し、後勝ちの上書きを止めた |
| 独立状態記録 | SourceRef、method、review_scope、source_declaration、科学record_idを保持。overlay state_records、Registry species recordsへ独立宣言を保存。取込み・採用は審査や恒久選択を行わない |
| 量ごとの評価 | 励起値の競合を物理対象の同定へ広げず、非競合の形成量/NASAを残す。同じNASA物理fitは出典文字列/tierの違いだけで競合にしない。状態表現有無と反応計算で同じ集約を使う |
| 命題の独立性 | unknownの同定記録でEA束縛推論を隠さず、明示存在根拠は別に評価。ReactionRecord.reviewed_forでchannel_assertion / threshold_eV / delta_e_eVを個別scopeへ限定し、直接snapshotの数値reviewも他主張へ広げない。状態存在・電子束縛・熱化学表現有無・反応エネルギー関係をpropositionで説明 |
| 数値選択 | rate_coefficient / cross_section / sticking_coefficientのprefer、only、recordをCaseから共通処理へ渡す。量・資格・条件を先に評価し、高順位の条件不足と同順位異値を保持。採用後も不一致を消さない |
| 保存整合 | DataUseに要求と不一致IDを保存。採用kind/IDと証拠、prefer/only/record要求、不一致参照を保存・再読込みで検査。公開表・不足は正規結果から導く |
| 取得・出典案内 | source_catalog schema 3へ提供量・取得方法・converterを統合。acquire sourcesで案内。fetchは要求/最終URL・UTC日時・full SHA256・形式をmanifestへ保存。local変換は原fileをraw/へ保存 |

旧state properties/thermo/states入口は読込みadapterで独立StateRecordへ正規化し、新ingest出力は二重に保存しません。Property/Thermoの表示sourceを残し、構造化provenanceと原宣言を追加しています。methodは明示宣言を読み、source_type名から推測しません。旧tier/statusは元の個別資格を境界で受理し、review_scopeや別命題の資格へ拡大しません。

数値snapshotの無scope記録はadapterでdataset.kindへ限定します。独立channelの無scope旧宣言は既存の資格を互換範囲として維持します。閾値・エネルギー差は宣言scopeに従って利用しますが、現行scalarに個別出典・tier・不確かさを持たせる独立量型と複数reaction claimの採用経路は残件です。

データ内preferredは未指定量の移行用として一か所に残り、利用時にdeprecated理由を返します。明示data_selectionは同量のpreferredに依存しません。必要な採用方針は分析入力へ移し、互換選択の撤去予定を0.8としました。

### 取得境界の確認

ASDは原TSV、SHA、全準位、注記・原欄を保持します。角括弧/丸括弧の由来を残し、疑義・未知の相対基準等では確定的な絶対最低閾値を返しません。未知JでE1概要を保留し、原資料の有効な掲載準位を失わせません。今回の実HTTP要求は403で、オンライン再取得成功とは報告しません。公式記法と回帰fixtureの確認を区別します。

PyroMatのh(300 K)はenthalpy_eVとして、温度・参照条件・元modelとともに出力します。形成量のenthalpy_formation_eVへ変換しません。packageの単位設定は成功/失敗時とも復元し、出力値を固定桁で丸めません。

UMISTはRATE12の8欄とRATE22の9欄の全fitを検証し、原行・accuracy・method・noteを保持します。形式版と出典releaseを区別し、電子反応をelectron_temperature軸へ置きます。重なる別行の加算関係が未解決ならreference_onlyとし、係数の一項だけを完全係数として選びません。放射等の未対応過程は数値化対象外で、原fileを保持します。

[公式RATE22配布file](https://umistdatabase.uk/files/rate22_final.rates)を`build/umist_format_verification/rate22_final.rates`へ取得しました。SHA256は`2f83cdd0905e5dd50494f23bc5faf559a617d866b365cf9d1c5fef3621a1a219`です。quote後の空白paddingは原行を保持して扱い、不正quoteは行付き入力エラーにします。この取得物は5488行目に不正quoteがあるため全件変換は成功しません。原資料を推測修復したとは扱いません。

LXCatは明示observable/headerを保持し、ELASTIC名だけで総/運動量移行を決めません。scope未宣言はunknown、明示totalはtotalで保持し、product_resolvedへ昇格しません。未完tableとtableなしのprocess blockを拒否して、正常部分だけの成功にしません。

統合前の旧source_access_profiles.yamlとsources.yamlは`build/source_catalog_migration/`へ原bytes・manifest/hashを保全して撤去しました。科学選択の別設定として残しません。台帳登録は科学承認・利用許諾・provider IDの登録必須条件ではありません。

### 変更した命題と残る範囲

対応する回帰確認は、[物理同一性](../tests/test_assessment_identity_boundaries.py)、[複数チャネル](../tests/test_registry_multisource_channels.py)、[科学記録の往復](../tests/test_scientific_record_roundtrip.py)、[取得準位の意味](../tests/test_acquire_atomic_semantics.py)、[releaseとscope](../tests/test_acquire_release_semantics.py)、[数値選択](../tests/test_data_selection.py)、[公開選択の保存整合](../tests/test_selection_result_roundtrip.py)、[審査範囲](../tests/test_review_scope_boundaries.py)、[数値記録の同定](../tests/test_numeric_record_identity.py)、[再取得と科学宣言](../tests/test_numeric_acquisition_identity.py)、[取得来歴の往復](../tests/test_acquisition_provenance.py)、[台帳入力境界](../tests/test_source_catalog_boundaries.py)で行います。対象・命題・原宣言・条件・採用の対応を確認し、特定ガスの件数を正解へ固定しません。

### 0.7最終統合確認

全ソース変更後に`tools/quality.py quality-pr`を実行しました。各環境でRuff整形・lint、mypy、pytest、依存方向2件が成功しています。

| 環境 | pytest | 記録 |
|---|---|---|
| Windows / Python 3.12.8 | 808成功 | build/quality_pr_0_7_py312.log |
| Windows / Python 3.11.15 | 792成功・16skip | build/quality_pr_0_7_py311.log |
| WSL Ubuntu / Python 3.11.15 | 791成功・17skip | build/quality_pr_0_7_linux311.log |

skipは既存の任意取得依存、Linuxでは追加でNodeによるJS確認がない環境の扱いです。GitHub CIを実行した記録ではありません。

通常利用4例を新しい`build/verified_0_7/`へ分析・保存し、正規結果、両CSVのhashと内容、needsを確認しました。4例とも終了コード0で、明示した機械生成・証拠追加の範囲は完了しています。件数と数値利用は次のとおりで、物理的網羅性や予測可能性の承認ではありません。

| 入力 | 状態 / 反応 | 数値利用 |
|---|---|---|
| Ar | 7 / 39 | unavailable 39 |
| Ar/CF4 | 37 / 1061 | needs_input 8、unavailable 1053 |
| Ar/O2 | 19 / 200 | coefficient 2、unavailable 198 |
| Ar/SF6/O2 | 97 / 7397 | coefficient 2、needs_input 167、unavailable 7228 |

旧schema 5結果9件をCSV照合も含めて読み込みました。保存結果の判定を再計算したりIDを再生成したりしていません。旧不具合を期待する監査scriptは実行していません。

wheelは`build/package_0_7/plasma_reactgen-0.7.0-py3-none-any.whl`、SHA256は`c208ef36191b6a6194415fac79bcdb3ebb7b580670dfb793c8c4ccb942966382`です。Python/schemaの47収録ファイルが現行ソースと一致し、インストール済み47ファイルも最新wheelのbytesと照合しました。core依存だけの独立したPython 3.11環境で、リポジトリ外から両console・moduleの起動、analyze・needs・view、schema/CSVを確認しました。実外部DBの全取得や追加の科学審査を行った配布確認ではありません。

検証結果・ソースhash・結果hash・Registry宣言件数は`build/package_0_7/verification.json`、配布起動は`build/package_0_7_smoke.log`、インストールbytes照合は`build/package_0_7_installed_bytes.log`です。Registry原データの直接fingerprintは前回と同じ`8a8a21a5a315b1c87747afb25d03143f10b4d5eb01fd352859838cf30c41da08`です。複数入力入口で集約した分析用hashは`7220e53bca207a2e1c11249d3bb707b83ec2747e92e90a83eb96ce5ae7bbe7c4`で、両者を区別して記録しています。

取得原宣言の異なる同じ数値科学記録は併記し、取得日時や保存先だけで競合にしません。未知の科学条件や方法は比較と匿名IDへ保持します。この保存・同定の改良は、未知条件を物理的に適用可能とする判断を追加したものではありません。

Registryの既存科学値・資格を一括変更せず、新数値assetも追加していません。原宣言の保持と命題の分離を改善した基盤です。独立した反応threshold/deltaEの型・資格・reaction_records採用/評価、形成量の参照基準、多条件AND、Property/Thermoと証拠範囲の優先指定、ASD概要の導出責務分離、chemicals/mendeleevの実際のmethod情報、UMIST加算モデルは残件です。

断面積/確率の数値選択は実装しても、curve参照・確率評価の専用用途、EEDF・分布積分・flux・時間発展を追加したわけではありません。必要入力と返す量を別に設計します。詳細と順序は[残件計画](remaining_work_plan.md)へ一本化しました。修復前のbuild/judgment_boundary_audit.*は履歴で、旧不具合を期待するscriptを現行検証へ使いません。

## 最優先の資格・ID・保存経路の修復（0.7.1）

2026-10-12。状態存在、各Property量、熱化学モデルへ明示review_scopeを適用し、宣言のrejected/conflictingを利用停止として扱いました。空scopeの旧互換と、不正なFalse・0・文字列・mappingを区別し、外部読込みと直接Python型の両入口で検証します。存在審査から自動生成した励起scalarの数値資格へ飛躍しません。

状態・数値・反応の原ID生成は同じ出典名前空間と匿名科学内容の規則を使います。状態の再取得は標準取得文脈を科学比較から除き、各原宣言を保持します。審査scopeの順序だけの差は集合として比較し、未知の科学配列は並べ替えません。既存保存ID、旧Property/NASAの既定status欠落、反復採用の整合を確認しました。同IDの実変更は対象ごとの保存配列だけでなく全体で照合し、異なる物理対象への割当てを形式不整合として拒否します。

反応主張はoverlay.reaction_recordsとRegistry channel.recordsへ独立保存し、直接snapshot・ingest・adopt後に同じ資格で反応根拠・閾値・エネルギー差を評価します。純粋な主張に空datasetを生成せず、数値は既存の量集合へ別に保存します。未同定過程の推測割当てと、独立主張へのembedded datasetsを禁止しました。保存の全科学内容比較と、評価の命題別比較を分け、閾値や係数だけの不一致でチャネル主張を未確定化しません。

| 確認範囲 | 実測結果・記録 |
|---|---|
| Windows / Python 3.12.8 quality-pr | 926成功。Ruff、mypy48ファイル、import-linter2件成功。build/quality_pr_0_7_1_py312.log |
| 通常入力4例 | Ar: 7状態/39反応、Ar/CF4: 37/1061、Ar/O2: 19/200、Ar/SF6/O2: 97/7397。build/verified_0_7_1/ |
| 係数利用・不足 | Ar/O2はcoefficient2、Ar/SF6/O2はcoefficient2 / needs_input167 / unavailable7228。科学資料の不足を仮入力で補わない |
| 保存・旧結果 | 正規結果とCSV照合、needs構築、旧schema5の9件を再計算なしで読込み。build/package_0_7_1/verification.json |
| wheel | source/schema47ファイルが現行と一致。SHA256: 70467cf0c35c1bf8a717861f62b664a941d57b53d67a8651ce72df6750d59e35 |
| Python 3.11 core環境 | wheelを再インストール、収録47ファイルのbytes一致、リポジトリ外のmodule分析、console needs、acquire sourcesを確認 |

0.7の検証・wheel・保存結果を上書きせず、0.7.1の記録を別に保存しました。現在のRegistry科学値・資格の一括変更と新assetの追加はありません。形成量の参照基準、複合条件、各反応エネルギー量の完全な型、Property/NASA選択は残件です。0.7.1のLinux全品質・GitHub CIは実行していません。

## 最優先の論理境界修復とリリース（0.7.2）

2026-10-12。保存したassetの実測SHA-256を保持し、作者の宣言SHA-256と別に扱います。表解析は照合した同じbytesを使うため、再読込み・読込み後・評価途中のfile変更で旧資格と新値を組み合わせません。adoptも検証したbytesをコピーし、作者hash不一致を保全しても利用資格を与えません。同じ検証済みbytesの保存場所だけを科学比較から分け、原宣言・各参照場所・取得来歴は保持します。未知bytesと未知科学条件を同一化しません。

混合snapshotの数値と反応主張は、それぞれの科学内容で比較します。新規の匿名数値IDは解決可能なbytesから保存場所を分離し、匿名反応主張IDは独立数値の欄を除いて実効scopeを含めます。保存済みの正規IDは保持します。同じ記録IDの実変更は上書きせず、ingest/adoptの反復・移動・保存往復を検証しました。

同じ物理対象の存在根拠が相反してもexact照合を保ち、存在命題だけをunknownへ返します。独立した物性・NASAと条件付き計算を保持し、存在不明の機構を承認しません。反応のエネルギー競合は各量へ局所化し、イオン化下限はthreshold、電荷移動の比較はdeltaE、elastic整合は両量を確認します。Penningの励起/IE、付着のEA、独立したΔH・ΔG・Kは無関係なscalar競合で抑止しません。除外量は既存messageへ残します。

既存の型・結果・比較処理を修正し、重複した数値宣言の除外規則を共通処理へまとめました。新しい通常入力、診断層、汎用framework、公開schema項目は追加していません。schema 5の旧結果は過去の判定として読み、再評価しません。

| 確認範囲 | 実測結果・記録 |
|---|---|
| Windows / Python 3.12.8 quality-pr | 996成功、Ruff・mypy48ファイル・依存方向2件成功。build/quality_pr_0_7_2_py312_final.log |
| Windows / Python 3.11.15 quality-pr | 980成功・16skip、同じ品質入口が成功。build/quality_pr_0_7_2_py311.log |
| WSL Ubuntu / Python 3.11.15 quality-pr | 979成功・17skip、同じ品質入口が成功。build/quality_pr_0_7_2_linux311.log。ローカルWSLで、GitHub jobの実行ではない |
| 通常入力4例 | Ar: 7状態/39反応、Ar/CF4: 37/1061、Ar/O2: 19/200、Ar/SF6/O2: 97/7397。正規結果・CSV・needsを確認。build/representative_0_7_2.json |
| 数値利用と旧結果 | Ar/O2はcoefficient2、Ar/SF6/O2はcoefficient2 / needs_input167 / unavailable7228。旧schema5結果13件を再計算なしで読込み |
| wheel / sdist | dist/0.7.2に作成。source/schema47ファイルが現行と一致。wheel SHA256: 18a1c1c9d8f0b75adaa889c99a95b6eac47ee1c2166808ceff368097d9fc9fd6 |
| coreだけのインストール環境 | Python 3.11へwheelをインストール、収録47ファイル一致、依存整合、リポジトリ外のanalyze・needs・CSV/network・Registry検査・acquire sourcesを確認。build/package_0_7_2_smoke.json |

配布物・ソース配布のhashと確認結果は `dist/0.7.2/verification.json`、`source-manifest.json`、`SHA256SUMS.txt` に保存しました。Registry・例・文書・testsを含む `plasma-reactgen-0.7.2-source.zip` は、Python標準sdistと別の開発用ソース配布です。旧版の配布物・検証記録は上書きしていません。

ソース・配布物・原取得物・確認記録は `C:\Users\user\Desktop\react_gen-preserved\2026-10-12-0.7.2` へhashと復元手順付きで保全しました。復元先の全fileを照合し、復元したRegistryと入力例を配布wheelで利用する確認を行いました。手順・確認結果は保全先の `preservation_manifest.json` と `README.md` を正とします。同端末のローカル保管で、別媒体backupではありません。

Registryの102状態・355チャネル・315datasetと科学内容fingerprintは変更していません。新たな科学値・資格の一括承認・数値assetの追加はありません。形成量の参照基準、必要な複合条件、反応量の独立した根拠・誤差、Property/NASA選択と必要資料の補充は後続計画に残します。GitHub CIと外部への公開はこのローカルリリース確認に含めません。

## 有用性レビューに基づく修復と確認：0.7.3

2026-10-12。EAの符号・不確かさ・電子非束縛宣言を一つの束縛判断で評価し、状態と付着で共有しました。正のEAとunboundの矛盾は未確定とし、その量だけを除外します。短寿命のtransientとunstableを電子非束縛に読み替えず、同義の既知qualifierは原語を保存して比較します。

形成量の共通参照をPropertyへ追加し、明示温度・標準元素基準・標準圧・必要な電子規約を比較します。参照不足・不一致はΔHだけを抑止します。一般Hfの値・参照の競合を先に確認し、有限温度のion規約で自由電子項が変わる反応だけ、電子形成量を持つwholePropertyを使います。補助量の不足で同じ参照の反対Hf値を消しません。中性の不要電子規約、0 Kの規約一致、Electron ConventionのNone/0、相殺時の電子項差を区別します。旧形成量へ未確認の基準を加えていません。

EvidenceCatalogは入力・取得記録の変更が元の索引へ波及しないsnapshotとなり、明示更新で索引と実際の記録内容を含むfingerprintを再構築します。不足一覧は責務・命題・保存結果でまとめ、全ID・個別理由は`--detail`へ残します。CSV形式2は判定の命題・範囲・理由とΔH参照温度・圧を表示し、形式1の旧hash・再生成は過去結果の読込みに維持します。

NASA/JPL Evaluation 20の全文表・注記を取得SHA付きで確認し、O(3P)項全体をO(3P2)準位へ転用する不整合を修復しました。O2の2分岐は正しい項全体と100–400 K推薦域へ限定し、N2の100–675 K、CO2の明示fit 200–354 Kの2係数を共通形式で追加しました。原資料が支持しない内部準位分岐・人口・形成量は補いません。quenching等の状態移動では相・構造・電荷を含む全参加者の対象を保持し、未対応の非ground終状態を不整合へ読み替えません。V-T分類は実際に変わる振動状態を要求します。

| 確認範囲 | 実測結果・記録 |
|---|---|
| Windows / Python 3.12.8 quality-pr | 1099成功、Ruff、mypy48ファイル、依存方向2契約成功。build/quality_pr_0_7_3_py312_frozen.log |
| Windows / Python 3.11.15 quality-pr | 1083成功・16skip、同品質入口成功。build/quality_pr_0_7_3_py311_frozen.log |
| WSL / Python 3.11.15 quality-pr | 1082成功・17skip、同品質入口成功。build/quality_pr_0_7_3_linux311_frozen.log。ローカルWSL |
| 通常入力7例 | 既存4例にN2/O2、CO2/O2の298 K、Ar/CF4の700 Kを追加。正規結果、CSV形式2、要約と全不足の対応を確認。build/representative_0_7_3.json |
| 最大例の表示 | Ar/SF6/O2は98状態・7399反応、係数2・出典条件不足167・利用不可7230。35823不足項目を17群へ集約 |
| 旧結果 | schema5の17結果を再計算せず読込み、旧CSVのhash整合を確認 |
| 配布・新規インストール | wheel、sdist、新規Python3.11 core環境の47source/schemaが現行と一致。リポジトリ外の分析、needs要約/詳細、CSV、network、Registry検査、取得元一覧、pip check、console help成功。build/package_0_7_3_smoke.json |

ローカル配布物、ソースZIP、検証・復元記録は`dist/0.7.3`、保全先は`C:\Users\user\Desktop\react_gen-preserved\2026-10-12-0.7.3`です。旧版の配布物・原記録を上書きしません。原PDF・確認画像は個人用の取得記録として保全し、公開ソースZIPへ含めません。復元手順とhashは保全先manifestを正とします。

再レビューは同じ配点で72から82/100です（責務19/20、物理判定22/25、データ10/20、出典管理14/15、利用方法8/10、保守9/10）。これは候補・証拠・数値利用条件の調査基盤としての評価で、実験との予測精度ではありません。Pateau167件の出典条件、電子断面積・表面数値、反応threshold/deltaEの独立量情報、Property/NASA選択、必要な人口・寿命・安定化の資料は残ります。今回の実装修復と、未取得の科学情報を分けます。GitHub CIと外部公開は行っていません。

## 科学判定と通常表示の改良・再レビュー：0.7.4

2026-10-12。直前の計画のS（科学命題・具体的不足）、C1（反応エネルギーの独立量情報）、U（通常利用・表示）を実装しました。現行仕様は[core_design](core_design.md)、[output_reference](output_reference.md)、[README](../README.md)を正とし、完了項目を残件計画の別仕様として残しません。AGENTS.mdの長期指針に沿い、DB別の判定、汎用登録framework、表示側の科学再判定は追加していません。

全判定に命題と個別scopeを付け、不足を実際に停止した枝から対象・量・責務・理由として返します。利用者入力、原資料の値/単位/定義、審査、対象同定、未対応モデルを区別しました。参加状態の集約は保存された状態判定を参照し、EA束縛を観測存在や付着安定化へ飛躍させません。未対応quenching等は未実装のエネルギー関係を明示し、独立に取得できた宣言値・計算値を保持します。

反応threshold/deltaEは既存Propertyを使うenergy_propertiesに一本化しました。親チャネル・各量の定義/資格/出典/不確かさを独立に保存し、旧外部scalar形式は入口で一度変換します。内部の重複scalar保存と旧constructorは整理し、APIの移行方法を公開仕様へ記しました。明示子量の資格を親から昇格せず、旧宣言へ未確認の定義や誤差を追加しません。

原子・断熱・垂直・出現エネルギーを区別し、基底関係が使う量と実際の相・構造・電荷の対応を検査します。閾値とIEの両側の宣言範囲、電荷交換の宣言差と導出差を比較し、名目点の整合を実験的な絶対限界や信頼区間へ広げません。上限/下限等の未対応注記を点値へ読み替えず、同じ記録のeV/J換算だけで競合を作りません。[科学的背景と確認範囲](scientific_data_review.md)に公式資料と境界例を記録しました。

CLIは対象・入力条件・使える係数/単位/適用範囲・次の必要情報を先に示します。CSV形式3とHTMLも同じ保存命題・scope・要件・熱化学値・選択・不一致から表示します。不足一覧は責務/必要量で整理し、派生所見と基礎の必要情報を別に数えます。個別理由と依存関係は詳細に保持し、集約から同じ原因や一括解消を推測しません。旧CSV形式1/2の列とhash、旧結果の省略された意味を再評価しない読込みを維持しました。

| 確認範囲 | 最終結果・記録 |
|---|---|
| Windows / Python 3.12.8 pytest | 1209成功。build/pytest_0_7_4_py312_frozen.log |
| Windows / Python 3.11.15 quality-pr | 1193成功・16skip、Ruff整形/lint、mypy48ファイル、依存方向2契約成功。build/quality_pr_0_7_4_py311_frozen.log |
| WSL / Python 3.11.15 quality-pr | 1192成功・17skip、同品質入口成功。build/quality_pr_0_7_4_linux311_frozen.log |
| 独立した科学境界確認 | 17項目すべて成功。拒否資格・値/単位/定義不足・相/構造違い・上限注記・同一記録の単位換算・独立量保持等。build/presentation_0_7_4_review/scientific_reaudit.json |
| 代表入力7件 | 全件終了コード0、正規結果・CSV形式3・命題/scope・needs要約/詳細の対応成功。build/representative_0_7_4.json |
| 旧保存結果 | schema5の24結果を再判定せず読込み、旧CSVのhashと内容を確認 |
| 配布・独立環境 | wheel/sdist/インストール済み47source/schemaが現行bytesと一致。Python3.11 core環境でリポジトリ外のanalyze、needs、CSV、network、Registry検査、取得元一覧、pip check、console help成功。build/package_0_7_4_smoke.json |

指定された既存.venvのPython3.12ではpytestを実行しました。mypyのcompiled DLLは端末のアプリ制御で実行できないため、既存のPython3.11環境で品質入口全体を確認しました。セキュリティ設定を変更していません。skipは任意取得依存、WSLでは追加のNode検証環境の差であり、GitHub CIの結果ではありません。

Registryは103状態・359チャネル・319dataset（constant213、Arrhenius6、reference_only100）のままです。通常最大例は98状態・7399反応、係数2・出典条件不足167・利用不可7230で、数値利用の充足は前版と同じです。36373所見を64群へ整理し、既知の責務/対象/量の前提13819件、他の保存判定へ依存する所見14765件を区別しました。前提件数は作業回数を意味しません。最終結果からCLI生成した大きなHTMLは28,590,196 bytes（約28.6 MB）で、詳細保持に伴う表示負荷は運用要件に合わせて検討します。

| 再レビューの対象 | 得点 | 評価の理由・制約 |
|---|---:|---|
| 処理と責務 | 19/20 | 共通入力・命題・値・表示の依存が明確。assessment/recordsの大きさには整理余地 |
| 科学判定の論理と適用範囲 | 24/25 | 対象/定義/宣言範囲/真の不足を分離。全モデルや統計的保証は未対応 |
| 実データの充足 | 10/20 | 新規曲線・上流条件を追加しておらず、係数利用件数を改善とは数えない |
| 出典・保存管理 | 14/15 | 各量の原宣言・資格・不確かさを保持。元資料の欠測は残る |
| 利用方法と結論の表示 | 9/10 | 通常要約、適用値、具体的作業が正規結果を共有。専門量と大規模表示の負担は残る |
| 保守・検証 | 9/10 | 入出力/保存互換/境界/配布を確認。GitHub CIや全運用条件の保証は別 |
| **総合** | **85/100（前版82）** | 有界な候補・証拠・数値利用条件の調査基盤としての評価 |

実験との予測精度を測定した採点ではありません。Pateau等の出典条件、数値断面積・表面データ、必要な人口/寿命/安定化、Property/NASAの採用指定、新しい条件を使うモデルは[残件計画](remaining_work_plan.md)へ残します。今回の論理・表示修復の完了条件へ、将来用途の網羅実装を混ぜません。

配布物と検証hashはdist/0.7.4/verification.json、SHA256SUMS.txtを参照します。source ZIPは現存するGit対象と非ignoredの新規ソース/文書/Registry/入力例を収録し、原PDF等は含めません。0.7.4の保全・復元確認はC:\Users\user\Desktop\react_gen-preserved\2026-10-12-0.7.4/preservation_manifest.jsonを正とします。過去版を上書きせず、同端末のローカル保管として確認しました。外部公開・GitHub CI・別媒体backupは今回の実施範囲ではありません。
