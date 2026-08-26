# Registry data guide

Registryは生成文法ではなく、curatedな状態・反応・数値データの証拠源です。配置は次の
3種類です。

```text
registry/
  species/*.yaml
  reactions/<family>/*.yaml
  materials/*.yaml
  assets/**
```

## Species record

```yaml
schema_version: 1
id: Ar_4s
composition: {Ar: 1}
charge: 0
classes: [neutral, excited, metastable]
state:
  kind: excited
  label: 3p5 4s manifold
  excitation_energy_eV: 11.6
  resolution: lumped
  members: [Ar_1s5, Ar_1s4, Ar_1s3, Ar_1s2]
  existence: confirmed
  configuration: 3p5 4s
  term: manifold
  parity: odd
  lifetime_s: 5.6e-8
properties:
  enthalpy_formation_eV: {value: 11.6, unit: eV, source: ...}
metadata: {status: literature_supported}
```

`id`はRegistry内の可読IDです。generate時にはcomposition、charge、stateをcanonical化し、
`Ar@metastable`等のCandidateへ照合します。同じ組成でもchargeとstateを別recordにします。
Lumped stateとresolved memberを同じsimulation選択に混在させません。

State判定に有用な情報:

- state kind、label、resolution、members
- existence (`confirmed / hypothetical / transient / unbound`)
- configuration、term、J、parity、degeneracy
- excitation energyと必要時のlifetime
- ionization energy、electron affinity
- formation enthalpyまたはNASA polynomial
- propertyごとのunitとsource

## Reaction record

```yaml
schema_version: 1
pair:
  family: ion_neutral
  projectile: Ar+
  target: SF6
channels:
- id: Arp_SF6_charge_transfer
  type: dissociative_charge_transfer
  products: [{species: Ar}, {species: SF5+}, {species: F}]
  deltaE_products_minus_reactants_eV: -0.44
  source_record:
    source_type: literature
    source_id: doi:...
    citation: ...
  data:
    datasets:
    - id: ds_rate_298K
      kind: rate_coefficient
      representation: constant
      unit: m3/s
      independent_variable: gas_temperature
      observable: reaction_rate
      channel_scope: product_resolved
      parameters: {value: 1.54e-15}
      validity: {minimum: 298.0, maximum: 298.0, unit: K}
      uncertainty: {factor: 2.0}
      status: literature_supported
      preferred: true
```

Reaction evidenceは左右の集約化学量論、third body、surfaceを照合した後、familyと`type`
（physical process）を一致させます。同じ式でもelasticとcharge exchangeは別channelです。
Registryの可読語彙は読込み時にcanonical化されます。例えば`ion_neutral/charge_transfer`は
`ion/charge_exchange`、`three_body/recombination`は`neutral/three_body_association`として
候補と照合します。別名を互換候補として二重に保持しません。

## Dataset rules

- `representation: reference_only`はcitationだけで、Kinetics passにはしない。
- tableは`asset.path`へ置き、元snapshot、source ID、checksumを追跡可能にする。
- table本体は2点以上、有限値、独立変数の単調増加、非負値、宣言範囲とthreshold整合を満たす。
- `channel_scope: total`をproduct-resolved channelへ付けない。
- cross sectionは`observable`でelastic、momentum transfer、reaction等を区別する。
- 同じ式でもstate-resolved productが異なれば別channelにする。
- validityの範囲外は値の存在に関係なくsimulation利用`fail`とする。
- estimated dataは明記し、strict simulationには使わない。
- curated値を自動上書きしない。

## 更新手順

```powershell
rgen generate CASE --registry registry --out outputs
acquire lxcat export.txt --out work/lxcat
rgen ingest work/lxcat/snapshot.yaml --bundle outputs --overlay work/overlay.yaml
rgen generate CASE --registry registry --overlay work/overlay.yaml --out outputs
rgen adopt work/overlay.yaml --registry registry --dry-run
rgen adopt work/overlay.yaml --registry registry
rgen check --registry registry
```

曖昧一致、source競合、未知単位、total/product scope不一致はreview queueで人が解決します。
generateやingestはRegistryを書き換えません。

## DNT+との境界

RegistryにDNT由来のion-neutral measurementやpotential情報を保存することはできますが、
coreはDNT+入力や断面積を生成しません。候補側はcharge exchange、dissociation、ligand
transfer、mutual neutralizationと`fast_product`効果を表現し、数値モデルは別工程に置きます。
