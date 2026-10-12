# External data workspace

ここは外部sourceの取得方法、利用条件、手動取得ファイル、local snapshotを管理する領域です。
`rgen analyze`は明示したローカル証拠だけを読み、外部へ接続しません。取得は`acquire`または
手動作業で行います。ライセンス方針は[source license policy](../docs/source_license_policy.md)、
各adapterの意味と制約は[データ源と証拠](../docs/data_sources.md)を参照してください。

```text
source_catalog.yaml  提供量・取得方法・converter・利用条件の確認項目
raw/                 local raw data（通常git管理外）
snapshots/           local snapshotと参照asset（通常git管理外）
manifests/           checksum・取得記録
worklist/            未取得channel
```

台帳はschema version 3で、旧`source_access_profiles.yaml`と`sources.yaml`を統合しました。
台帳は出典の科学的品質、優先順位、利用許諾を決めません。ユーザーデータには未登録providerも
指定できます。分析時の量別優先・限定は入力の`data_selection`で指定します。
現在の対象はrate coefficient、cross section、sticking coefficientで、物性・熱化学モデル・
存在根拠への選択は未対応です。具体的な入力は[README](../README.md)を参照してください。

リポジトリのルートで、同じPython環境にインストールした`rgen`と`acquire`を使います。
module入口は`python -m reactgen.cli ...`と`python -m acquire.cli ...`です。
利用できる取得先を確認し、台帳に直接file URLがあるsourceは明示的に取得できます。

```powershell
acquire sources
acquire fetch umist --out external_data/raw/umist
```

`fetch`は原本と`acquisition.yaml`へ要求URL、最終URL、UTC取得時刻、完全なSHA-256、形式と
形式版を保存します。取得成功は全行の変換成功や科学的承認を意味しません。
独自台帳は`--catalog PATH`で指定できます。

取得原本と隣の`acquisition.yaml`を一緒に保管すると、converterは同じfile名・完全なhashの
一致を確認し、取得URL・時刻・明示されたprovider/collection/release等を
`snapshot.acquisition.source_manifest`と科学記録の原宣言へ引き継ぎます。元manifestのpathと
変換先の`raw_path`は分けて保存します。同名hashの矛盾や不正なmanifestは書込み前にエラーにし、
別fileのmanifestは採用しません。

通常は、対象を分析して不足を確認し、取得した原本をsnapshotへ変換して照合します。

```powershell
rgen analyze Ar CF4 --evidence registry --out result
rgen needs result
acquire lxcat external_data/raw/EXPORT.txt --out external_data/snapshots/lxcat
rgen ingest external_data/snapshots/lxcat/snapshot.yaml --result result --overlay external_data/snapshots/overlay.yaml
rgen analyze Ar CF4 --evidence registry --evidence external_data/snapshots/overlay.yaml --out result
rgen needs result
```

`EXPORT.txt`は利用条件を確認して保存したLXCat原本です。別の対象や物理条件を使う場合は、
両方の`analyze`で同じ入力を指定します。取得・照合に成功しても、対象の同定、存在、数値の品質、
用途への適用が承認されたことにはなりません。曖昧なstate/channelやscopeの不一致は、
overlayと同じディレクトリの`review_queue.yaml`で確認します。断面積を取得しても、
速度係数には別途EEDFとの積分などが必要です。次に必要な情報は再分析後の`needs`で確認します。

LXCatの対応表はenergy eV・cross section m2の二列です。別単位・別量・列順の明示、壊れた
数値行、閉じていないtable、tableがないprocessは入力エラーです。header省略時はこの対応形式の
固定単位を使います。全headerと原本を保存し、channel scopeは明示がなければunknown、
ELASTICのobservableも明示がなければ未確定にします。CSV化で数値の桁を切り詰めません。

主なadapterの入口は次のとおりです。状態を対象とするadapterは保存結果の`result.yaml`にある
`states`を読めるため、別の状態一覧を手で作る必要はありません。

```powershell
acquire umist external_data/raw/RATE.rates --format-version RATE22 --out external_data/snapshots/umist
acquire asd Ar O --out external_data/snapshots/asd
acquire cccbdb result/result.yaml --page external_data/raw/cccbdb.html --out external_data/snapshots/cccbdb
acquire nasa result/result.yaml --out external_data/snapshots/nasa
acquire molecular result/result.yaml --out external_data/snapshots/molecular
acquire thermo result/result.yaml --out external_data/snapshots/thermo
acquire idealgas result/result.yaml --out external_data/snapshots/idealgas
acquire pubchem result/result.yaml --out external_data/snapshots/pubchem
```

UMISTはRATE12/22の異なるfit形式を区別し、一意なら版指定を省略できます。全fitの数値・温度
範囲を検証し、原行・方法・accuracy・noteを保持します。重なる別行が和の成分か未確定なら、
数値を捨てず`reference_only`にします。CP/CR/PHと二体以外は数値snapshotの対象外です。
LXCat・UMIST変換のsnapshotは`snapshot_version: 1`で、原本を`raw/`へコピーしhashを記録します。
2026-10-12に確認した公式RATE22ファイルには5488行に余分な引用符があり、その原本はstrict
parserが拒否します。原本のhashと詳細は[データ源と証拠](../docs/data_sources.md)に記録しています。

ASDは元素記号を受け取り、中性原子の返された準位から最小励起概要を
`lowest_excitation_energy_eV`として返します。元TSV・個別準位・注記・不確かさを保持し、
絶対基準や割当てが不明なら概要値を保留します。E1のparity/J概要は状態の寿命や人口を
決めません。外部取得失敗は値の不存在を意味しません。

CCCBDBは保存HTMLを読め、`--page`を省略すると明示的に公開ページへアクセスします。
NASAはCantera、molecular/thermoはchemicals、idealgasはPyroMatの別途導入が必要です。
PyroMatの出力は300 Kのモデルenthalpy `enthalpy_eV`であり、形成enthalpyへ転用しません。
PubChemは明示的なAPI取得で、identity情報だけでは状態や反応の成立は決まりません。
ATcT、OpenADAS、VAMDC、QDB等には専用converterがなく、対応snapshot形式へ手動で整理します。
datasetの必要情報と照合・採用手順は[Registry guide](../docs/registry_data_guide.md)を参照してください。

Registryへの永続採用は、出典・同定・適用範囲・利用条件を確認した後、
`rgen adopt OVERLAY --registry registry --dry-run`で変更を確認し、`--dry-run`を外して明示実行します。
adoptは記録と資格を保存する操作で、科学的レビューの代替ではありません。
