# Data sources and evidence flow

外部データは候補を生成する条件ではなく、生成済み候補の実在性と数値利用可否を判断する
証拠です。core generationはネットワークへ接続しません。

```text
external source
  -> acquire converter
  -> snapshot.yaml + referenced assets
  -> rgen ingest SNAPSHOT --bundle OUTPUTS --overlay OVERLAY
       exact match       -> overlay
       zero/ambiguous    -> review_queue.yaml
       total -> channel  -> review_queue.yaml
  -> rgen generate CASE --overlay OVERLAY
  -> rgen adopt OVERLAY --registry REGISTRY
```

## 共通dataset

取得元によらず、EvidenceCatalogへ入る時点で同じ`NumericDataset`になります。

| field | 意味 |
|---|---|
| `kind` | `cross_section`、`rate_coefficient`、`sticking_coefficient` |
| `form` | `table`、`constant`、`arrhenius`、`reference_only` |
| `unit` | 数値の単位。rateは反応次数と照合する |
| `independent_variable` | collision/electron/ion energy、各温度、reduced field |
| `observable` | reaction rate、elastic、momentum transfer、sticking probability等 |
| `channel_scope` | `product_resolved`または`total` |
| `validity` | quantity、minimum、maximum、unit |
| `uncertainty` | factor、relative、説明 |
| `source` | source type、ID、citation、URL、record ID |
| `status` | 元sourceの状態 |
| `tier` | curated、reviewed、imported、derived、estimated |

`reference_only`は反応存在の参考になりますが数値計算には使いません。processまたはobservableが
曖昧なdatasetも自動利用しません。total cross sectionは
関連processとして表示しますが、個別生成物channelのkineticsへ割り当てません。

table assetはbundleへコピーせず、overlayまたはsnapshotからの相対pathとchecksumを保持します。
`adopt`時には内容checksumで`registry/assets/adopted`へ一度だけ取り込み、Registry自身から
解決できる相対pathへ変換します。

Kinetics判定はchecksumとmetadataだけでなくtable本体を読み、点数、有限性、energy軸の
単調性、断面積・速度の非負性、validityと既知thresholdとの整合を確認します。読めない表や
矛盾する表はsimulation-readyにしません。

同じ条件で複数のpreferred値が有意に競合する場合は自動選択せず`unknown`にします。
推定値は`estimated`として保持し、strict policyへ入れません。

取得・再配布条件は[source/license policy](source_license_policy.md)に従います。
