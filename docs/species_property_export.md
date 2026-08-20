# 状態リストの物性CSV出力 — 現状・不足機能・不足データ

反応式・状態リストの出力を入力として、各化学種の質量・組成・分極率・双極子モーメント・
熱化学係数などを CSV で出す、という要求に対する整理です。

数値はすべて実測です(レジストリ102種、`cases/` の実出力、インストール済みパッケージへの問い合わせ)。

---

## 1. 現状 — すでにあるもの

### 1.1 物性はすでに集まっている(`species.yaml`)

各バンドルの `species.yaml` は、種ごとに以下を持っています。**出力形式が無いだけで、
データは既に揃っています。**

```yaml
id: CF4
charge: 0
composition: {C: 1, F: 4}
classes: [molecule, neutral]
state: {kind: ground, label: X, energy_eV: 0.0, resolution: state_resolved}
depth: 0
introduced_by: [...]            # この種を生んだ反応
properties:
  mass_amu:              {value: 88.0043,  unit: amu, source: NIST WebBook SRD 69}
  polarizability_A3:     {value: 2.824,    unit: A3,  source: NIST CCCBDB; Olney 1997}
  dipole_moment_D:       {value: 0.0,      unit: D,   source: Td symmetry of CF4}
  enthalpy_formation_eV: {value: -9.673802,unit: eV,  source: chemicals, CAS 75-73-0}
  entropy_J_mol_K:       {value: 261.6,    unit: J/mol/K, source: chemicals}
  ionization_energy_eV:  {value: 14.7,     unit: eV,  source: NIST WebBook}
  electron_affinity_eV:  {value: null,     unit: eV,  source: Bjarnason 2013}
  collision_radius_A:    {value: 2.35,     unit: A,   source: 工学的推定}
  vibrational_quantum_eV:{value: 0.1017,   unit: eV,  source: chemicals TRC 熱容量}
thermo: null                    # ← NASA多項式。全102種で null
status: estimated
```

**1値ごとに出典が付いている**のが重要で、CSV でもこれを落とさない設計にすべきです。

### 1.2 いま出ている CSV

| ファイル | 列 |
|---|---|
| `layers/{layer}/species.csv` | `id, charge, depth, status, reactions, ready, missing` |
| `layers/{layer}/species_passed.csv` | 同上(判定を通過した種のみ) |
| `reactions.csv` | 反応リスト |

`species.csv` の `missing` 列は「このレイヤーの判定に足りない物性名」であって、
**物性値そのものは1つも出ていません**。バンドル直下に種の CSV はありません。

---

## 2. 不足機能

| # | 機能 | 現状 | 規模 |
|---|---|---|---|
| **F1** | 物性CSVの書き出し | 無い。`export.write` は `species.yaml` のみ | 小 |
| **F2** | NASA多項式の取得 | スキーマに `thermo` はあるが **0/102** | 小 |
| **F3** | 双極子モーメントの取得 | `acquire` に該当モジュール無し | 小 |
| **F4** | 衝突径 / Lennard-Jones の取得 | 同上。現在 3/102 | 小 |
| **F5** | イオン・励起状態への物性の伝播 | 一部のみ。下記 §4.3 | 小 |
| **F6** | 分極率の取得 | **自動取得源が存在しない**(§4.2) | — |

`export.py` には `_reactions_csv` があるので、F1 は同じ形で `_species_csv` を足すだけです。

---

## 3. レジストリの現在の充足率(102種)

| 物性 | 値あり | 主な出どころ |
|---|---:|---|
| `mass_amu` | **102 (100%)** | 組成から導出 44 / 導出 13 / mendeleev 11 / WebBook手動 10 |
| `enthalpy_formation_eV` | 79 (77%) | chemicals 46 / pyromat 3 / 導出(イオン・励起) / WebBook手動 |
| `dipole_moment_D` | 46 (45%) | **分子対称性から 42**(=ゼロ) / CCCBDB手動 2 / 実測 2 |
| `ionization_energy_eV` | 35 (34%) | mendeleev 18 / WebBook手動 6 / 導出 |
| `entropy_J_mol_K` | 35 (34%) | chemicals 35 |
| `electron_affinity_eV` | 28 (27%) | mendeleev 16 / WebBook手動 8 |
| `vibrational_quantum_eV` | 20 (20%) | chemicals TRC 熱容量からの当てはめ |
| `polarizability_A3` | **5 (5%)** | NIST CCCBDB 手動のみ |
| `collision_radius_A` | **3 (3%)** | 工学的推定 |
| NASA多項式 (`thermo`) | **0 (0%)** | — |

`dipole_moment_D` の 46件のうち 42件は「対称性からゼロ」なので、**実測値は4件**です。
分極率・衝突径・NASA係数の3つが実質的な空白です。

---

## 4. 不足データベース連携 — 何が自動で取れるか実測

### 4.1 cantera が NASA多項式を持っている(最大の収穫)

**cantera 3.2.0 がインストール済み**で、同梱データに 862組成分の熱力学多項式があります。
組成と電荷で照合したところ:

| 取得できるもの | 件数 |
|---|---:|
| **NASA多項式(NASA7/NASA9)** | **91 / 102** |
| 衝突径(`transport.diameter`) | 24 / 102 |
| 分極率(`transport.polarizability`) | 9 / 102 |

```python
# nasa_gas.yaml に 748種、他 22ファイル。すべてオフライン、pip 同梱
CF4  -> thermo: NASA7   (nasa_gas.yaml)
Ar   -> transport: {well-depth: 136.5, diameter: 3.33}   (air.yaml)
```

**0/102 が 91/102 になります。**外部ネットワークも手動エクスポートも不要です。
これが今回最も費用対効果の高い連携です。

なお cantera の `transport` ブロックは燃焼系60組成しか無く、分極率はそのうち9件だけなので、
輸送物性の解決にはなりません。

### 4.2 分極率には自動取得源が無い(実測して確認)

試した経路と結果:

| 経路 | 結果 |
|---|---|
| cantera `transport.polarizability` | 9 / 102 |
| `chemicals` 屈折率 → Lorentz–Lorenz | **3 / 57**(中性基底種) — 使えない |
| mendeleev | 原子のみ。分子は無い |
| NIST CCCBDB | **手動エクスポートのみ**(フォーム形式、API 無し) |

分極率は Langevin 率係数 $k_L = 2.342\times10^{-15}\sqrt{\alpha/\mu}$ の唯一の入力なので、
**kinetics レイヤーが 3.6% しか判定できない直接の原因**がここにあります。
CCCBDB の手動エクスポートを増やすか、分子分極率の加成則(結合分極率の和)で
推定値を入れるかの二択です。後者は誤差20%程度ですが、Langevin は $\sqrt{\alpha}$ 依存なので
率係数の誤差は10%程度に収まります。

### 4.3 `chemicals` から取れるもの(中性基底種57種に対して)

| 物性 | 取得数 | 出どころ |
|---|---:|---|
| 双極子モーメント | **40 / 57** | CCCBDB / POLING / PSI4_2022A のバンドル表 |
| Lennard-Jones $\sigma$ | 22 / 57 | Stiel–Thodos ほか |
| Lennard-Jones $\varepsilon/k$ | 22 / 57 | 同上 |

双極子は現在の「対称性からゼロ42件」を**実測値40件**で置き換えられます。
極性分子(SOF2, SO2, SOF4 など)の値が入るので、イオン-双極子衝突を
Su–Chesnavich で扱う道も開きます(現在は Langevin のみで、極性標的では過小評価)。

### 4.4 イオン・励起状態への伝播

102種のうち、イオンと非基底状態が半数近くを占めます(ar_sf6_o2 では 80種中 イオン21・非基底39)。
これらは外部DBに載らないので、恒等式で埋めます。

| 物性 | $X_v$, $X^*$ | $X^+$ / $X^-$ |
|---|---|---|
| 組成・元素数 | 親と同一 | 親と同一 |
| 質量 | 親と同一 | 親 $\mp m_e$(0.00055 amu、無視可) |
| 生成エンタルピー | 親 $+ E^{*}$ | 親 $+IE$ / 親 $-EA$ ← **実装済み** |
| 双極子モーメント | 親と同一で可 | **不可** — 電荷分布が変わる |
| 分極率 | 親と同一で可 | **不可** — 陽イオンは小さく、陰イオンは大きい |
| NASA多項式 | 親 + 定数シフト | 親 + 定数シフト |

$X_v$ と $X^*$ については伝播してよく、これだけで分極率・双極子の充足率が
実質的に倍近くになります。イオンについては伝播してはいけません。

---

## 5. 提案する出力形

### 5.1 `species.csv` — 1種1行

```
id, formula, charge, class, state_kind, state_label, energy_eV, depth, status,
n_Ar, n_C, n_F,                                  ← バンドルに出る元素だけ列を立てる
mass_amu, polarizability_A3, dipole_moment_D,
enthalpy_formation_eV, entropy_J_mol_K, ionization_energy_eV,
electron_affinity_eV, vibrational_quantum_eV, collision_radius_A,
reactions, introduced_by_count, missing
```

元素の列はバンドルごとに可変です(ar_cf4 なら Ar・C・F の3列、ar_sf6_o2 なら Ar・F・O・S の4列)。
レジストリ全体では18元素あるので、固定列にすると大半が空になります。

### 5.2 `species_sources.csv` — 出典を落とさないための対

```
id, property, value, unit, source
```

縦持ちにすることで、`species.csv` を数値だけの表として使いつつ、
どの値がどのDB由来かを別に追えます。**この分離が無いと、
「chemicals の実測値」と「対称性からのゼロ」と「工学的推定」が同じ列で見分けられなくなります。**

### 5.3 `species_thermo.csv` — NASA多項式

```
id, model, T_low, T_mid, T_high, a1_low..a7_low, a1_high..a7_high, source
```

係数15列は `species.csv` に混ぜると読めなくなるので別ファイルにします。
NASA9 は9係数なので `model` 列で区別します。

---

## 6. 実装結果

§5 の設計と §6 の順序どおりに実装しました。すべてインストール済みパッケージ内で完結します。

### 6.1 追加したコマンド

```powershell
python tools/refresh_properties.py   # 下の4段を通しで実行し、レジストリに書き戻す
```

| 段 | コマンド | 出どころ | 答えるもの |
|---|---|---|---|
| 1 | `acquire atoms` | mendeleev | 電離エネルギー、電子親和力、**原子の分極率** |
| 2 | `acquire molecular` | chemicals | 双極子モーメント、Lennard-Jones 径と井戸深さ |
| 3 | `acquire nasa` | cantera | NASA多項式(**基底状態のみ**) |
| 4 | `rgen derive` | — | 状態が基底から受け継ぐもの、組成からの質量 |
| 5 | `rgen adopt` | — | レジストリへの書き戻し。**curated 値は絶対に上書きしない** |

### 6.2 レジストリの充足率(102種)

| 物性 | 前 | 後 |
|---|---:|---:|
| `mass_amu` | 102 | **102** |
| NASA7 多項式 | **0** | **83** |
| `dipole_moment_D` | 46(うち実測4) | **72** |
| `polarizability_A3` | 5 | **38** |
| `collision_radius_A` | 3 | **27** |
| `well_depth_K` | 0 | **27**(新規) |

`rgen adopt` は 193値を書き、53値は既にレジストリが答えていたので残しました。
再実行すると 0値書き込み・204値保持で、冪等です。

### 6.3 出力への影響

| | ar_cf4 | ar_sf6_o2 |
|---|---:|---:|
| 種の質量 | **31/31** | **80/80** |
| kinetics 判定 | 21 → **92** | 75 → **307** |
| DNT+ 実行可能ペア | → **92/176** | 59 → **382/1180** |

DNT+ の実行可能ペアが 6.5倍になったのが最大の効果です。分極率が Langevin の
唯一の入力なので、原子の分極率(mendeleev)と状態への伝播が効いています。

### 6.4 実装中に見つかった不具合

**NASA多項式が励起状態に誤って付いていた。** 組成と電荷だけで照合すると `O_1D` は
`O` と一致し、基底の多項式をそのまま受け取ります。O(¹D) は 1.967 eV 上にあるので
エンタルピー定数がずれます。`acquire nasa` を基底状態のみに限定し、励起状態は
`rgen derive` が $a_6$ を準位分だけずらす形にしました。

**提案された種が物性を一つも持っていなかった。** `SF4_v` のような walk 中に発明される
状態は、質量すら空でした。提案器が親から受け継ぐようにし、`rgen derive` と同じ規則を
共有させました。

**種のIDがファイル名として不正だった。** `F2*` の `*` は Windows で使えず、
分極率が入って DNT+ ペアが実行可能になった途端に書き出しが落ちました。
`export.py` と `dnt.py` に重複していたスラグ処理を `naming.slug` に統合しました。

---

## 7. 残る空白(取得手段が無いもの)

| 対象 | 物性 | 理由 |
|---|---|---|
| **分子全般** | **分極率** | どのパッケージにも表が無い。CCCBDB 手動のみ |
| イオン | 分極率、双極子 | 親から伝播できず(電荷分布が変わる)、測定値も乏しい |
| SF, SF3, SOF, SOF3, SOF4, SO2F2 | 生成エンタルピー、熱容量 | どの編纂にも無い |
| C2F3, C4F8, SO2F, SOF, SOF3, SOF4 | NASA多項式 | cantera 同梱にも無い |
| 全ペア | 短距離ポテンシャル | DNT+ 自身が計算するもの。範囲外 |

分子の分極率が唯一の本質的な不足です。原子は mendeleev で正確に埋まりますが
(Ar 1.642 に対し実測 1.641)、分子については加成則を試した結果 SF6 で +36%、
F 原子で +39% の誤差となり、採用しませんでした。CCCBDB からの手動エクスポートを
増やすのが唯一の道です。
