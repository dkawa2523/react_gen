# External data workspace

ここは外部sourceのアクセス条件、手動取得ファイル、local snapshotを管理する領域です。
`reactgen`はここへ接続せず、`acquire`が対応するlocal file/APIだけをsnapshotへ変換します。

```text
source_catalog.yaml          license・再配布・review区分
source_access_profiles.yaml  access方法と手動作業
sources.yaml                 plasma chemistry上の用途
raw/                         local raw data（通常git管理外）
snapshots/                   local snapshot（通常git管理外）
manifests/                   checksum・取得記録
worklist/                    未取得channel
```

現在の公開converter:

```powershell
acquire lxcat EXPORT.txt --out work/lxcat
acquire umist RATE.rates --out work/umist
acquire asd Ar O --out work/asd
acquire cccbdb states.yaml --out work/cccbdb
acquire nasa states.yaml --out work/nasa
acquire pubchem states.yaml --out work/pubchem
```

生成済みbundleへ照合します。

```powershell
rgen ingest work/lxcat/snapshot.yaml --bundle outputs --overlay work/overlay.yaml
rgen generate CASE --registry registry --overlay work/overlay.yaml --out outputs
```

Source固有の取得方法はcatalog/profileに集約し、実装されていないCLI例は置きません。
曖昧なstate/channel、total/product scope不一致、license未確認dataは自動採用しません。
Registryへ入れる場合だけ、review後に`rgen adopt ... --registry ...`を明示実行します。
