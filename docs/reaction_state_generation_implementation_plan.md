# 反応・状態候補生成基盤 0.5 固定方針

固定日: 2026-08-23

## 最低限達成する目的

1. 中性化学式の入力ガスから、Registryなしで状態・反応種・反応式候補を生成する。
2. 生成は証拠欠損で候補を削除しない。
3. Registry、overlay、snapshotを生成後の読み取り専用証拠にする。
4. 判定をConsistency、State、Thermochemistry、Reaction evidence、Kinetics/Dataに限定する。
5. 判定は4値で独立実行し、用途別policyはCandidateSetを変更せずIDだけを選ぶ。
6. 正規出力を`states.yaml / reactions.yaml / selected.yaml`に集約し、必要時だけ目視用の
   `states.csv / reactions.csv`と、5判定ごとの状態・反応別CSV、`summary.csv / SVG graph`を
   `assessments/<layer>/`へ付加する。指定順の累積pass-only screeningはCandidateSetを変更しない
   派生viewとして`assessments/screening/`へ付加する。
7. Registryの変更を明示的な`adopt`だけに限定する。

## 実装した一本化

```text
generate CandidateSet
  -> EvidenceCatalog.load: 全sourceを正規化し索引化
  -> with_attested: 到達可能な既知channelを和集合
  -> evaluate: 5判定と数値利用能力
  -> select: policyによるID選択
  -> export: 3 YAMLと任意の一覧・判定別CSV/graph viewを一括更新
```

EvidenceCatalogは`StateKey -> records`、`EquationKey -> records`、
`candidate ID -> overlay datasets`を一度だけ構築します。判定層にRegistry型と生の辞書を
混在させず、候補ごとのRegistry全走査を行いません。

反応候補は`EquationKey + family + process`で識別し、数値datasetはさらに`observable`と
`channel_scope`を持ちます。同じ反応式のelastic、charge exchange、momentum transferを
同じ証拠として扱いません。family/processはkey作成前に一度だけcanonical化し、source別名による
同一物理channelの二重化を許しません。

保存則は`balance.py`、熱力学式は`thermo.py`の一実装をRegistry checkと候補判定で
共用します。Registry読込み時の暗黙派生は行わず、派生値は`derive`で明示的に作ります。

## 数値利用の区別

- 断面積tableが使える: `cross_section_ready`
- ODEへ直接入るrateが使える: `direct_rate_ready`
- EEDF等の積分が必要: `required_transforms`
- 反応熱がある: `reaction_enthalpy_ready`
- 電子エネルギー損失が扱える: `electron_energy_loss_ready`
- 平衡・逆反応が扱える: `equilibrium_constant_ready` / `reverse_rate_ready`

`energy_balance`はThermochemistryの一般的なpassではなく、反応熱の利用可能性を要求します。
電子反応は電子分配関数/EEDFをこのcoreが持たないため、NASA係数だけから
`equilibrium_constant_ready`または`reverse_rate_ready`にしません。励起状態にはscalarな
level energyを使えますが、ground-state NASA polynomialを複製しません。
`reverse_rate_ready`はさらに、review済みforward rateがある同分子数の熱的可逆channelに限定し、
電子衝突、相互中和、解離性過程には適用しません。

## 科学的な候補境界

- formulaだけでradicalと断定せず、`fragment`を生成役割、
  `open_shell / closed_shell / unknown`を電子的性質として分離する。
- odd-electron、非希ガス原子、明確な`AXn`式での価電子不足を`reactive_candidate`とし、
  CF2、SiH2などをspin断定なしで中性反応frontierへ残す。
- `formula_only`組成には推定bond splitを行わない。
- 中心原子–配位子操作はhomoleptic `AXn`型だけに限定する。
- neutral noble-gas結合を禁止し、charged complexは解離チャネルとして扱う。
- 解離の逆候補は有限な`three_body_association`に限定する。
- 明示的unbound/transient state、負のEA、Penning energy不足を後段でfailにする。
- EA、生成熱、NASA係数はrecord全体でなく各物性のevidence tierで利用可否を決める。
- simulation policyはThermochemistryのunknownを許容し得るが、物理的failは許容しない。
- 数値table本体の単調性、非負性、範囲、threshold整合をKinetics/Dataで検査する。

## 意図的に作らないもの

- assessorの抽象基底、plugin、契約framework
- 二つ目のpipeline、legacy flag、互換alias
- DNT/DNT+断面積、Boltzmann/EEDF solver
- rank、coverage、graph、旧layer/gap/lock bundle
- private helper単位の大量テスト

## 完了条件

- Registry有無でmechanical集合が不変
- Registryなしでも対象ガスが非0生成
- 非有限・非物理的なCase条件を生成前に拒否
- source別名を含む同一physical channelが一候補へ統合される
- 生成段階にthermo/evidence/kinetics filterがない
- Evidence判定が正規化済みrecordだけを扱う
- 保存則と状態ID解析が各一実装
- total processとproduct-resolved channelを混同しない
- 同一式の異なるphysical processとobservableを混同しない
- 断面積と直接rate、thresholdと反応熱を混同しない
- fragmentとradical、missingとunboundを混同しない
- forward rate、熱平衡、反応次数整合なしに逆速度をreadyにしない
- table assetの所在だけでKinetics passにしない
- state/reaction双方の非選択理由とreadinessを出力
- 3ファイルが部分更新されず、path移動でevidence hashが変わらない
- pytest、Ruff、mypy、import-linterが成功
- README、core design、CLI help、schemaが実装と一致
