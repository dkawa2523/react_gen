# 判定基準の詳細

反応式リストに載る一本ごとに、4つの問いが別々に答えられます。本書はその判定式を、
物理量の定義・符号規約・妥当性の範囲・参考文献まで含めて記述します。

| レイヤー | 問い | 出力 |
|---|---|---|
| `structure` | この種は存在しうるか、式は保存するか | `conserved` / `conserved, species proposed` |
| `thermochemistry` | エネルギー的に開いているか | `exothermic by N eV` / `endothermic by N eV` / `unknown` |
| `kinetics` | この条件で効くほど速いか | `fast` / `comparable` / `slow` / `negligible` / `unknown` |
| `attestation` | 出典がこの反応を述べているか | 出典名 / `unattested` |

評価しなかったレイヤーは `not_run` と記録します。「見ていない」と「見たが分からない」は別の答えです。

---

## 1. structure — 存在と保存

### 1.1 電荷保存

$$\left| \sum_{i \in \text{react}} \nu_i q_i \;-\; \sum_{j \in \text{prod}} \nu_j q_j \right| \le 10^{-9}$$

$\nu$ は化学量論係数、$q$ は電荷数。表面反応のみ免除します — 壁が電荷を吸収し、気相の生成物だけを書くという表記上の約束に対応するためです。

### 1.2 元素保存

$$\forall E \in \text{elements}: \quad \sum_{i} \nu_i \, n_{E,i} \;=\; \sum_{j} \nu_j \, n_{E,j}$$

$n_{E,i}$ は種 $i$ に含まれる元素 $E$ の原子数。**質量は別途検査しません** — 元素組成が一致すれば質量は自動的に一致します。

### 1.3 価数(骨格が配位子を担えるか)

$$N_{\text{ligand}} \;\le\; \sum_{k \in \text{skeleton}} \nu_k V_k \;-\; 2\,(m - 1)$$

$V_k$ は元素の価数($\mathrm{C}=4,\ \mathrm{Si}=4,\ \mathrm{S}=6,\ \mathrm{N}=3,\ \mathrm{O}=2$、ハロゲン $=1$)、$m$ は骨格原子数。第2項は骨格内結合が消費する手の数で、**非環状飽和の上限**です。

これにより $\mathrm{CF_5}$($4 < 5$)、$\mathrm{C_2F_7}$($2\cdot4-2=6 < 7$)、$\mathrm{F_3}$ が棄却されます。環状構造には保守的で、環があれば実容量はこれより小さくなります。

### 1.4 陰イオンの存在

$$A^- \text{ を書く} \iff EA(A) > 0$$

$EA$ は電子親和力。負なら束縛状態が無く、$e + \mathrm{Ar} \to \mathrm{Ar}^-$ は**遅い反応ではなく起こらない反応**です。

### 1.5 準安定の選別

電気双極子(E1)遷移の選択則:

$$|i\rangle \to |f\rangle \text{ 許容} \iff \pi_i \neq \pi_f \;\wedge\; |\Delta J| \le 1 \;\wedge\; \neg(J_i = J_f = 0)$$

$$\text{準安定}(i) \iff \forall f \text{ with } E_f < E_i: \ \text{E1 禁制}$$

**基底状態だけでなく下位の全準位**を見るのが要点です。基底へのパリティ選択則だけで判定すると Ar の準安定が305個になりますが、正しくは2個($11.548\,\mathrm{eV}$ の $^3P_2$、$11.723\,\mathrm{eV}$ の $^3P_0$)。基底項の微細構造は同一化学種として除外します。

> 参考: NIST Atomic Spectra Database (Kramida et al., 2023), `energy1.pl`。
> 選択則は Condon & Shortley, *The Theory of Atomic Spectra* (1935).

---

## 2. thermochemistry — エネルギー的に開いているか

**このレイヤーが本コードの中核**です。断面積を使わずに反応の可否と閾値の下限を決めます。

### 2.1 符号規約と基準

$$\Delta H \;=\; \sum_{j} \nu_j \, \Delta_f H_j \;-\; \sum_{i} \nu_i \, \Delta_f H_i$$

- **$\Delta H > 0$ が吸熱**、$\Delta H < 0$ が発熱
- $\Delta_f H$ は $298.15\,\mathrm{K}$ の標準生成エンタルピー、単位 eV/molecule
- 標準状態の単体は $\Delta_f H = 0$($\mathrm{O_2},\ \mathrm{N_2},\ \mathrm{F_2},\ \mathrm{Ar}$ など)
- **電子は $\Delta_f H(e^-) = 0$**(電子規約 / *electron convention*)

> 電子規約と熱電子規約(*ion convention* / *thermal electron convention*)は $298\,\mathrm{K}$ で
> $\tfrac{5}{2}RT = 6.197\,\mathrm{kJ/mol} = 0.064\,\mathrm{eV}$ ずれます。本コードは前者を採用。
> 篩の閾値 $0.25\,\mathrm{eV}$ より小さいので判定は変わりませんが、他のデータと突き合わせる際は要注意です。
> 参考: Lias et al., *J. Phys. Chem. Ref. Data* **17**, Suppl. 1 (1988).

### 2.2 イオンと励起状態の生成エンタルピー

$$\Delta_f H(A^{+}) = \Delta_f H(A) + IE(A)$$
$$\Delta_f H(A^{-}) = \Delta_f H(A) - EA(A)$$
$$\Delta_f H(A^{*}) = \Delta_f H(A) + E^{*}$$

**測定ではなく恒等式**です。イオン化エネルギー $IE$ は断熱値(基底振動準位間)を用います。垂直 $IE$ ではありません。

### 2.3 相殺 — 実装上の要点

$\Delta H$ を骨格の項と荷電の項に分けます:

$$\Delta H \;=\; \underbrace{\sum_{s} c_s \, \Delta_f H_s}_{\text{骨格}} \;+\; \underbrace{\sum_{p} \sigma_p \, \Delta_p}_{\text{荷電コスト}}, \qquad c_s = \sum_{\text{prod}} \nu_s - \sum_{\text{react}} \nu_s$$

$c_s = 0$ の骨格は**値を参照しません**。絶対エンタルピーを先に評価すると、答えに影響しないデータを要求して解ける反応を落とします。

### 2.4 電子衝突の判定 — 詳細

電子は運動エネルギーを持ち込めるので、$\Delta H > 0$ でも**閉じません**。したがって:

- **篩は掛けない** — 全チャンネルを残す
- **$\Delta H$ は記録する** — 閾値の下限として、また整合検査のために

各過程の $\Delta H$:

**弾性散乱** $e + A \to e + A$
$$\Delta H = 0 \qquad E_{\text{th}} = 0$$

**励起** $e + A \to e + A^{*}$
$$\Delta H = E^{*} \qquad E_{\text{th}} = E^{*} \ \text{(厳密に一致)}$$

**脱励起(超弾性)** $e + A^{*} \to e + A$
$$\Delta H = -E^{*} \qquad E_{\text{th}} = 0$$
電子がエネルギーを**得る**過程で、閾値は定義上ゼロです。

**電離** $e + A \to 2e + A^{+}$
$$\Delta H = \Delta_f H(A^+) - \Delta_f H(A) = IE(A) \qquad E_{\text{th}} = IE(A)$$

**解離** $e + AB \to e + A + B$
$$\Delta H = \Delta_f H(A) + \Delta_f H(B) - \Delta_f H(AB) \;=\; D_0(A\!-\!B)$$

$D_0$ は基底振動準位からの解離エネルギー($D_e$ ではありません)。

**解離性電離** $e + AB \to 2e + A^{+} + B$
$$\Delta H = D_0(A\!-\!B) + IE(A)$$

これは**出現エネルギー(appearance energy, $AE$)の熱力学的下限**です:
$$AE(A^+/AB) \;\ge\; D_0(A\!-\!B) + IE(A)$$

**解離性付着** $e + AB \to A^{-} + B$
$$\Delta H = D_0(A\!-\!B) - EA(A)$$

**励起解離** $e + AB \to e + A + B^{*}$
$$\Delta H = D_0(A\!-\!B) + E^{*}(B)$$

### 2.5 垂直遷移と断熱極限

計算した $\Delta H$ は**断熱的**な値です。実測される閾値は**垂直遷移**の起点なので、一般に:

$$E_{\text{th}}^{\text{observed}} \;\ge\; \Delta H^{\text{adiabatic}}$$

実例:

| 反応 | 計算 $\Delta H$ | 実測閾値 | 差 |
|---|---:|---:|---:|
| $e + \mathrm{O_2} \to e + \mathrm{O} + \mathrm{O(^1D)}$ | 7.13 eV | 8.57 eV | 1.44 eV |

差は Franck–Condon 因子によるもので、垂直遷移が到達する上位ポテンシャル面の位置に対応します。

したがって、解離極限から導いた値は **`threshold_eV` ではなく `delta_e_eV` に記録**します。閾値として書くと推測を事実として提示することになります。

> 参考: Franck, *Trans. Faraday Soc.* **21**, 536 (1926); Condon, *Phys. Rev.* **32**, 858 (1928).

### 2.6 重粒子衝突の判定 — 詳細

イオンと中性は熱的($400\,\mathrm{K}$ で $k_BT = 0.0345\,\mathrm{eV}$)なので、**吸熱なら実際に閉じます**。ここでは篩が働きます。

$$\text{採用} \iff \Delta H \le E_{\max} = 2.0\ \mathrm{eV}$$

**$2.0\,\mathrm{eV}$ の根拠**: バルクのイオンは $\sim k_BT$ しか持ちません。$2\,\mathrm{eV}$ のチャンネルに届くのはプレシースで加速されたイオンで、Maxwell 分布の裾 $\exp(-2/0.0345) \approx 10^{-25}$ はバルクでは無視できます。シース研究では `--max-endothermic` で上げます。

統合式から導かれる特殊解(手書きしていません):

**電荷交換** $A^{+} + B \to A + B^{+}$
$$\Delta H = \bigl[\Delta_f H_A + \Delta_f H_B + IE_B\bigr] - \bigl[\Delta_f H_A + IE_A + \Delta_f H_B\bigr] = IE_B - IE_A$$

$\Delta_f H$ が**完全に相殺**するので、生成エンタルピーが未知でも $IE$ だけで解けます。

**解離性電荷交換** $A^{+} + BC \to A + B^{+} + C$
$$\Delta H = IE_B - IE_A + D_0(B\!-\!C)$$

**配位子移動** $A^{+} + BC \to AB^{+} + C$
$$\Delta H = \Delta_f H(AB^+) + \Delta_f H(C) - \Delta_f H(A^+) - \Delta_f H(BC)$$

**相互中和** $A^{+} + B^{-} \to A + B$
$$\Delta H = EA_B - IE_A$$

$IE \gg EA$ が通例なので常に大きく発熱し、実質的に必ず開きます。

**会合** $A^{+} + B \to AB^{+}$
$$\Delta H = \Delta_f H(AB^+) - \Delta_f H(A^+) - \Delta_f H(B)$$

二体会合は余剰エネルギーを捨てられないため、実際には放射性会合か三体でなければ成立しません。**本コードはこれを判定していません** — 現状の限界です。

### 2.7 中性反応の判定 — 詳細

**引き抜き・置換** $A + BC \to AB + C$

$$\text{open} \iff \Delta H < -0.25\ \mathrm{eV}, \qquad \text{closed} \iff \Delta H > +0.25\ \mathrm{eV}$$

$0.25\,\mathrm{eV}$ は約 $7k_BT$($400\,\mathrm{K}$)。**見えない活性化障壁の代わり**です。わずかに発熱なだけの引き抜き反応は通常障壁を持つため、意図的に厳しくしています。

> Arrhenius 的には $k = A\exp(-E_a/k_BT)$ で、$E_a$ は $\Delta H$ から決まりません。
> Evans–Polanyi 関係 $E_a = E_0 + \alpha \Delta H$($\alpha \approx 0.3$–$0.5$)が経験則としてありますが、
> 族ごとに $E_0$ が要るため本コードでは使っていません。
> 参考: Evans & Polanyi, *Trans. Faraday Soc.* **34**, 11 (1938).

**Penning 電離** $M^{*} + X \to M + X^{+} + e$

$$\Delta E = IE(X) - E^{*}(M) \qquad \text{open} \iff \Delta E < -0.25\ \mathrm{eV}$$

準安定の内部エネルギーが標的の電離エネルギーを上回るときに開きます。**原子の組み替えではなく電荷の生成**なので、統合式では表現できず専用の生成器を持ちます。

> 参考: Hotop & Niehaus, *Z. Physik* **228**, 68 (1969).

**振動緩和(V-T)** $AB(v) + M \to AB + M$

$$\Delta H = -E_{\text{vib}} \qquad E_{\text{th}} = 0$$

発熱が自明なので篩は不要です。必要なのは**量子の大きさ**だけで、それを熱容量から求めます(§2.8)。

速度は相手に強く依存します($\mathrm{N_2}(v)$ に対し $\mathrm{O}$ 原子は $\mathrm{Ar}$ より数桁速い)ため、相手を汎用の第三体 $M$ で隠さず**明示的に列挙**します。

> Landau–Teller 理論では $\log k_{V\text{-}T} \propto -T^{-1/3}$。
> 参考: Landau & Teller, *Phys. Z. Sowjetunion* **10**, 34 (1936).

### 2.8 振動量子の導出 — 熱容量から

分光データの代わりに理想気体熱容量を使います。振動こそが $C_p$ を温度とともに上げるものだからです。

$$C_p(T) = R + \underbrace{\tfrac{3}{2}R}_{\text{並進}} + \underbrace{\tfrac{f}{2}R}_{\text{回転}} + C_{\text{vib}}(T), \qquad f = \begin{cases} 2 & \text{直線} \\ 3 & \text{非直線} \end{cases}$$

Einstein モデルで1モードあたり:

$$\frac{C_{\text{vib}}^{(1)}(T)}{R} = x^2 \frac{e^{x}}{(e^{x}-1)^2}, \qquad x = \frac{\theta}{T}, \qquad \theta = \frac{h\nu}{k_B}$$

$n$ 原子分子のモード数は $N = 3n - 6$(直線なら $3n-5$)。**残差をモード数で割ってから**1モードを当てはめます:

$$\hat{\theta} = \arg\min_{\theta} \sum_{T} \left[ x^2\frac{e^x}{(e^x-1)^2} - \frac{C_p(T) - C_{\text{classical}}}{N R} \right]^2$$

$$E_{\text{vib}} = \frac{k_B \hat{\theta}}{e} = \frac{\hat{\theta}}{11604.518}\ \mathrm{[eV]}$$

**割らないと破綻します。** 1モードに $N$ モード分の熱容量を担わせると、フィットが $\theta$ を下げ続けて探索下限に張り付きます。

当てはめ範囲は $300$–$1500\,\mathrm{K}$。これより低温では $C_p$ がほぼ並進+回転で、残差が雑音になります。

**二原子分子による検証**(1モードしかないので実測と一致すべき):

| 種 | フィット | 実測基本振動 | 比 |
|---|---:|---:|---:|
| $\mathrm{N_2}$ | 0.283 eV | 0.289 eV | 0.98 |
| $\mathrm{O_2}$ | 0.185 | 0.196 | 0.95 |
| $\mathrm{CO}$ | 0.260 | 0.269 | 0.97 |
| $\mathrm{F_2}$ | 0.099 | 0.111 | 0.89 |
| $\mathrm{Cl_2}$ | 0.062 | 0.069 | 0.90 |

**多原子分子で得られるのはモード平均**であって最低モードではありません($\mathrm{CF_4}$ で最低モードの約1.3倍)。一括の $X_v$ にはこの解像度が適切です。

> 参考: McQuarrie, *Statistical Mechanics* (2000), Ch. 8。
> 熱容量相関は `chemicals` の TRC 気相データ(1961種)。

### 2.9 整合検査

$$E_{\text{th}} \;\ge\; \Delta H - \delta \qquad (\Delta H > 0 \text{ のとき})$$

$\delta$ は比較の性質で使い分けます:

| 比較 | $\delta$ | 根拠 |
|---|---:|---|
| 同一量の2測定(電離閾値 vs $IE$) | 0.05 eV | 実測残差 0.022 eV |
| 出現エネルギー vs 編纂エンタルピーの和 | 0.5 eV | 各 $\Delta_f H$ が 0.1 eV 程度、$AE$ も同程度 |

$\delta$ を超える不足は**物理的に不可能**なので blocking とします。実際に1件検出しています:

$$e + \mathrm{SF_6} \to 2e + \mathrm{F^+} + \mathrm{SF_4} + \mathrm{F}$$
閾値 $23.0\,\mathrm{eV}$、熱力学的下限 $23.81\,\mathrm{eV}$(doi:10.1116/1.4853675)。

さらに2つ:

$$E_{\text{th}}^{\text{excitation}} < IE(\text{target}), \qquad \bigl| E_{\text{th}}^{\text{ionization}} - IE \bigr| \le 0.05\ \mathrm{eV}$$

後者は**独立した出典どうしの検算**です。閾値は LXCat・文献、$IE$ は mendeleev から来ており、電離10反応で残差 $0.022\,\mathrm{eV}$ 以下。関係式が厳密に成立している証拠です。

### 2.10 判定していないこと

物理学者の観点から、**現状で見ていない制約**を明示します:

| 制約 | 内容 | 影響 |
|---|---|---|
| **スピン保存** | Wigner のスピン保存則。$\Delta S = 0$ でない反応は遅い | 一重項–三重項間の反応を通してしまう |
| **軌道対称性** | Woodward–Hoffmann 則 | 有機系で効くが本系では限定的 |
| **活性化障壁** | $E_a$ は $\Delta H$ から決まらない | 0.25 eV の余裕で代用 |
| **二体会合の余剰エネルギー** | 放射性会合か三体でなければ成立しない | §2.6 参照 |
| **微視的可逆性** | 順逆の速度係数が平衡定数で結ばれる | `thermo.reverse_rate` にあるが NASA 多項式が未取得 |

> Wigner のスピン保存則: Wigner, *Nachr. Ges. Wiss. Göttingen* (1927).

---

## 3. kinetics — 速さ

### 3.1 Langevin 捕獲率(無極性標的)

誘起双極子ポテンシャル

$$V(r) = -\frac{\alpha q^2}{2(4\pi\varepsilon_0)^2 r^4}$$

に対する捕獲断面積は $\sigma \propto 1/v$ となり、率係数が**温度に依存しません**:

$$k_L = 2\pi q \sqrt{\frac{\alpha}{4\pi\varepsilon_0\,\mu}} \;=\; 2.342\times10^{-15}\,\sqrt{\frac{\alpha\,[\mathrm{\AA^3}]}{\mu\,[\mathrm{amu}]}}\ \ \mathrm{m^3/s}$$

$$\mu = \frac{m_1 m_2}{m_1 + m_2}$$

検算: $\mathrm{Ar^+/Ar}$ で $6.7\times10^{-16}\,\mathrm{m^3/s}$。

永久双極子を持つ標的では Su–Chesnavich のパラメータ化に切り替えるべきですが、**本コードは未実装**です。

> 参考: Gioumousis & Stevenson, *J. Chem. Phys.* **29**, 294 (1958);
> Su & Chesnavich, *J. Chem. Phys.* **76**, 5183 (1982).

### 3.2 電子衝突率係数

$$v_e(E) = \sqrt{\frac{2E}{m_e}} = 5.9309\times10^{5}\sqrt{E\,[\mathrm{eV}]}\ \ \mathrm{m/s}$$

$$k(T_e) = \int_0^{\infty} \sigma(E)\, v_e(E)\, f(E; T_e)\, dE$$

$f$ は Maxwell–Boltzmann。**断面積 $\sigma(E)$ を持つ反応のみ**評価できます。

実プラズマの電子エネルギー分布は Maxwell とは限らず(Druyvesteyn 的になる)、厳密には Boltzmann 方程式を解くべきです。本コードは Maxwell を仮定しています。

### 3.3 壁損失頻度

$$\nu_{\text{wall}} = \gamma\,\frac{\bar v}{4}\,\frac{A}{V}, \qquad \bar v = \sqrt{\frac{8 k_B T_g}{\pi m}}$$

$\bar v/4$ は単位面積あたりの壁への流束(Hertz–Knudsen)。$\gamma$ は材料ごとの付着係数。

拡散律速の場合はこれが過大評価になります(実際は $\nu^{-1} = \nu_{\text{wall}}^{-1} + \nu_{\text{diff}}^{-1}$)。**本コードは拡散を見ていません**。

### 3.4 関連度

$$\nu_{\text{upper}} = k \prod_i n_i$$

**片側上限**です。「これより速くはならない」だけを言い、遅いことの証明には使えますが、速いことの証明には使えません。

---

## 4. attestation — 出典

$$\text{attested}(r) \iff \bigl(\text{source\_type}(r) \notin \mathcal{D}\bigr) \;\vee\; \bigl(\text{sig}(r) \in \mathcal{K}\bigr)$$

$\mathcal{D}$ は本コードが自分で導出したものの集合(`bond_breaking`, `formation_enthalpy`, `dissociation_limit`, `ionization_and_bond_energy`, `vibrational_manifold`, `structural`)。**自分自身の証拠にはなりません**。

$\mathcal{K}$ は照合先の索引で、**レジストリは常に含まれます** — curated なチャンネルは論文から読んで査読したものなので、候補がそれに一致すれば新規ではありません。`--known` で渡した公開リストはその上に載ります。

照合は種ごとに係数を合算した化学量論で行うので、$2e$ と $e + e$ は同一と判定されます。

$$\text{sig}(r) = \Bigl(\text{family},\ \text{third\_body},\ \text{surface},\ \textstyle\sum\nu\ \text{per species 両辺}\Bigr)$$

**ラベルであってフィルタではありません** — 出典の沈黙は反応の否定ではないので、何も除きません。

---

## 5. 物性の定義と取得元

### 5.1 物性ごとの取得実績(レジストリ102種)

| 記号 | 物性 | 単位 | 要る判定 | 取得数 | 出どころの内訳 |
|---|---|---|---|---:|---|
| $m$ | 質量 | amu | 1.2, 3.1, 3.3 | **102** | 導出 77 / mendeleev 11 / WebBook 10 / ASD 4 |
| — | NASA7 多項式 | — | 2.9, 3.4 | **83** | cantera 68 / 導出 15 |
| $\Delta_f H$ | 生成エンタルピー(298 K) | eV | 2.1–2.9 | **80** | chemicals 46 / 導出 25 / pyromat 3 / WebBook 2 / ASD 1 / 文献 3 |
| $\mu_D$ | 双極子モーメント | D | 3.1(将来) | **72** | 導出(対称性)43 / chemicals 26 / CCCBDB 2 / 文献 1 |
| $\alpha$ | 分極率 | Å³ | **3.1** | **54** | mendeleev 31 / CCCBDB一覧 20 / CCCBDB手動 3 |
| $IE$ | 電離エネルギー(断熱) | eV | 2.2, 2.4, 2.6 | 35 | mendeleev 18 / 導出 7 / WebBook 6 / ASD 2 / 文献 2 |
| $S$ | 標準エントロピー | J/mol/K | 2.9(将来) | 35 | chemicals 35 |
| $EA$ | 電子親和力 | eV | 1.4, 2.2, 2.6 | 28 | mendeleev 16 / WebBook 8 / 文献 2 / CCCBDB 1 / ASD 1 |
| $\sigma_c$ | 衝突半径 | Å | 3.1(将来) | 27 | chemicals 24 / 工学的推定 3 |
| $\varepsilon/k_B$ | ポテンシャル井戸深さ | K | (未使用) | 27 | chemicals 27 |
| $E_{\text{vib}}$ | 実効振動量子 | eV | 2.7, 2.8 | 20 | chemicals TRC 熱容量からの当てはめ |
| $J, \pi, E^{*}$ | 角運動量・パリティ・準位 | —, eV | 1.5, 2.2, 2.4 | 原子のみ | NIST ASD |
| $\sigma(E)$ | 衝突断面積 | m² | **3.2 のみ** | 93 反応 | LXCat 手動 |
| $\gamma$ | 付着係数 | — | 3.3 | 4 反応 | 文献(`registry/materials/`) |

「導出」は推定ではなく恒等式です。質量77件は組成の和と $\mp m_e$、生成エンタルピー25件は
$\Delta_f H(A^\pm)=\Delta_f H(A)+IE$ / $-EA$ と $\Delta_f H(A^{*})=\Delta_f H(A)+E^{*}$、
NASA 15件は親の多項式の $a_6$ を準位分ずらしたもの、双極子43件は分子対称性からのゼロです。

### 5.2 各データベースの守備範囲

| データベース | 入手方法 | 収録範囲 | 本コードが引くもの | このプロジェクトでの当たり |
|---|---|---|---|---|
| **mendeleev** | pip、オフライン | 元素 118 | $IE$, $EA$, 原子の $\alpha$, 原子質量 | 原子は全件。分子は対象外 |
| **chemicals** | pip、オフライン | TRC気相 $C_p$ 1961種、双極子 942種、LJ 数百種 | $\Delta_f H$, $S$, $\mu_D$, LJ $\sigma/\varepsilon$, $C_p$ | 中性基底57種中 41種 |
| **cantera** | pip、オフライン | 22ファイル、862組成の熱力学多項式 | NASA7 多項式 | 組成+電荷照合で91種、うち NASA7 は68種 |
| **pyromat** | pip、オフライン | 主要気体のみ | $\Delta_f H$ | 3種 |
| **NIST ASD** | HTTP API、キー不要 | 原子・原子イオンの全準位 | $E^{*}, J, \pi$、準安定判定 | 7元素、励起状態27種 |
| **NIST CCCBDB 一覧** | HTTP GET(自動化済) | 実験分極率 261種 | $\alpha$ | 中性基底57種中 35種。**ラジカルはゼロ** |
| NIST CCCBDB 個別 | フォーム POST | 計算値(PM6 / Miller ahc) | (不採用) | 精度不足のため使わない |
| **NIST WebBook** | 手動エクスポート | 熱化学・イオンエネルギー | $\Delta_f H$, $IE$, $EA$, $m$ | 手入力 26件 |
| **LXCat** | 手動エクスポート | 電子衝突断面積 | $\sigma(E)$、閾値 | 93反応 |
| **文献 (DOI)** | 手動入力 | — | 反応チャンネル、閾値、$\gamma$ | 反応 253本 |
| HITRAN (`hapi`) | pip | 分子分光 | **検証専用**、本線外 | — |

### 5.3 取得の優先順位

同じ物性を複数の源が持つとき、次の順で採ります。`rgen adopt` は
**既にレジストリにある値を決して上書きしません**。

| 優先 | 段 | 理由 |
|---:|---|---|
| 1 | curated(文献の手入力) | 人が論文を読んで書き写し査読したもの。自動表がこれを覆す資格はない |
| 2 | 恒等式による導出 | 測定ではなく定義。$\Delta_f H(A^+)=\Delta_f H(A)+IE$ は誤差を持たない |
| 3 | NIST の一次データ(ASD / WebBook / CCCBDB) | 標準参照データ |
| 4 | pip 同梱の編纂(chemicals / cantera / mendeleev) | 一次データの編纂物。オフラインで再現可能 |
| 5 | 相関式・当てはめ(TRC $C_p$ からの振動量子) | 誤差を明示できる範囲で採用 |
| — | 加成則による推定 | **採用しない**(§7.3) |

判定側の優先順位は逆です。**断面積は生成にも篩にも一切使いません** — 生成と棄却は
構造規則と熱化学だけで行い、断面積との照合は attestation のラベルとして最後に置きます。
これは意図的で、断面積を持つ反応だけを生成すると「データベースにある反応リスト」しか
作れず、本コードの目的(DNT+ の計算対象を決める)を果たせないためです。

---

## 6. 反応・状態リストの判定に使う全データベース

| データベース | 判定レイヤー | 本コードでの役割 | 無いとどうなるか | 優先度 |
|---|---|---|---|---|
| **レジストリ**(`registry/`) | 全レイヤー | 種・チャンネル・出典の唯一の正 | 何も動かない | **必須** |
| **mendeleev** | 1.4, 2.2, 2.6, 3.1 | $EA$ で陰イオンの存在を決め、$IE$ で電荷交換を解き、原子 $\alpha$ で Langevin を回す | 陰イオンの存在判定が不能、kinetics がほぼ全滅 | **必須** |
| **chemicals** | 2.1–2.9, 3.1 | $\Delta_f H$ が熱化学の主入力。TRC $C_p$ から振動量子 | thermochemistry の判定率が8割落ちる | **必須** |
| **文献 (DOI)** | 4 | 反応チャンネルそのもの(253本)と出典 | curated バンドルが空になる | **必須** |
| **cantera** | 2.9, 3.4 | NASA7 多項式。逆反応速度と温度依存の平衡定数 | 微視的可逆性が使えない | 高 |
| **NIST ASD** | 1.5, 2.2, 2.4 | 原子の準位・準安定判定・励起閾値 | 準安定が扱えず Penning が書けない | 高 |
| **NIST CCCBDB** | 3.1 | 分子の実験分極率 | kinetics の判定率が半減 | 高 |
| **NIST WebBook** | 2.1–2.6 | chemicals に無い種の熱化学 | 硫黄フッ化物の空白がさらに広がる | 中 |
| **LXCat** | **3.2 のみ** | 断面積。率係数の畳み込みと閾値の整合検査 | 電子衝突の速度が出ない。**生成には影響しない** | 中 |
| `registry/materials/` | 3.3 | 付着係数 $\gamma$ | 壁損失が出ない | 低 |
| pyromat | 2.1 | chemicals の補完(3種) | ほぼ影響なし | 低 |
| HITRAN | — | **検証専用**。本線に載せていない | 影響なし | — |

**「必須」の意味**: レジストリ・mendeleev・chemicals・文献のどれか一つでも欠けると、
リストが小さくなるのではなく**判定そのものが成立しません**。他は判定率が落ちるだけです。

---

## 7. 本コードの限界

判定の物理が正しいことと、リストが正しいことは別です。データを足せば消える限界と、
そうでない限界を分けて書きます。

### 7.1 生成されない反応クラス — 最大の限界

curated レジストリの反応を候補生成器が再現できるかを数えると:

| ケース | 再現 | 率 |
|---|---|---:|
| ar_cf4 | 31 / 53 | **58%** |
| ar_sf6_o2 | 113 / 262 | **43%** |

**自分のレジストリに入っている実在の反応の半分を作れません。** 内訳:

| 欠けている過程 | 状態 | 影響 |
|---|---|---|
| 付着 $e+AB\to A^-+B$ | オプションで OFF | SF6 は付着するから使われる気体。陰イオンが一つも出ない |
| 相互中和・電子脱離 | 陰イオンが無いため連鎖的に欠落 | SF6 で119反応 |
| **解離性再結合** $e+XY^+\to X+Y$ | **族そのものが無い** | $n_e=3\times10^{16}$ で分子イオンの主損失 |
| 会合・成長 $\mathrm{CF_2}+\mathrm{CF_2}\to\mathrm{C_2F_4}$ | 未実装 | C2Fx ポリマー分岐が丸ごと欠落 |
| 準安定のクエンチング $\mathrm{Ar}(4s)+\mathrm{CF_4}$ | 未実装 | Ar/CF4 の主要解離経路 |
| 壁損失 | 提案されない | 2.7 Pa ではラジカルの主損失 |
| 三体 | オプションで OFF | 低圧では確かに遅く、設計判断として妥当 |

これは**データ不足ではなく実装の欠落**です。付着を有効にすると陰イオン化学は復活しますが、
$EA<0$ の親でも励起状態経由でゲートを通る不具合が残っています($EA(\mathrm{Ar})=-11.5$ と
$E^{*}(\mathrm{Ar}\,4s)=+11.6$ が打ち消し合い、`Ar⁻` が提案される)。

### 7.2 リストの構成が組み合わせで決まる

ar_sf6_o2 の 2085反応のうち、振動緩和 928(44.5%)と電荷交換 682(32.7%)で **77%**。
どちらも 振動種 × 重粒子、イオン × 中性 の組み合わせで機械的に増える種類です。

結果として、**リストの大きさが重要な化学ではなく組み合わせ数で決まっています。**
2085行を読む査読者に、どの50行が効くのかを示す手がかりはありません。
一方で §7.1 の重要な過程は数十本規模で欠落しています。

同じ衝突ペアの重要でない方だけが載る例:

```
CF4_v + Ar_4s -> CF4 + Ar_4s      ← ある(振動緩和の第三体扱い)
Ar_4s + CF4  -> Ar + CF3 + F      ← ない(主要解離経路)
```

### 7.3 分極率がラジカルで空白 — 埋める手段が無い

`CF, CF2, CF3, SF, SF2, SF3, SF4, SF5, SO, SOF, SOF3, SOF4, SO2F2, FO` の分極率は
**どのデータベースにも実測値がありません**(8経路を実測、`docs/radical_polarizability.md`)。

加成則を CCCBDB 227種に当てはめると LOO 中央値 4.3% で出せますが、**採用していません**:

- 訓練データは全て閉殻分子、ラジカルはより分極しやすい → 予測は系統的に**低い**
- $k_L \propto \sqrt{\alpha}$ なので率も低く出る
- kinetics の主張は「これより速くならない」という**片側上限**
- **超えられる上限は上限ではない**

推定値を入れると保証が黙って推定に変わるので、レジストリの外に置いています。

### 7.4 判定していない物理

| 制約 | 内容 | 帰結 |
|---|---|---|
| **スピン保存** | Wigner の規則。$\Delta S\neq 0$ の反応は遅い | 一重項–三重項間の反応を通す |
| **活性化障壁** | $E_a$ は $\Delta H$ から決まらない | $\pm0.25$ eV の余裕で代用しているだけ |
| **二体会合の余剰エネルギー** | 放射性会合か三体でなければ成立しない | $A^{+}+B\to AB^{+}$ を通してしまう |
| **微視的可逆性** | 順逆が平衡定数で結ばれる | NASA多項式が入り実装可能になったが未接続 |
| **軌道対称性** | Woodward–Hoffmann | 本系では影響限定的 |

### 7.5 速度判定の仮定

- **Langevin のみ**。永久双極子を持つ標的には Su–Chesnavich を使うべきで、
  極性分子(SOF2, SO2)では現状**過小評価**です。双極子は72種揃っているので実装可能。
- **Maxwell 分布を仮定**。実プラズマの電子エネルギー分布は Druyvesteyn 寄りで、
  厳密には Boltzmann 方程式を解くべきです。
- **拡散を見ていない**。壁損失は $\nu=\gamma\bar v A/4V$ のみで、拡散律速では過大評価
  ($\nu^{-1}=\nu_{\text{wall}}^{-1}+\nu_{\text{diff}}^{-1}$)。
- **片側上限**。遅いことの証明には使えますが、速いことの証明には使えません。

### 7.6 熱化学の解像度

- 記録している $\Delta H$ は**断熱値**で、実測閾値は垂直遷移の起点なので一般に大きい
  (O2 で 7.13 対 8.57 eV)。閾値として使ってはいけません。
- 硫黄フッ化物(SF, SF3, SOF, SOF3, SOF4, SO2F2)は**どの編纂にも生成エンタルピーが無く**、
  ar_sf6_o2 の 2085反応中 933(45%)が判定不能のままです。
- 電子規約と熱電子規約の差 0.064 eV は篩の閾値より小さいので判定は変わりませんが、
  他データとの突き合わせでは効きます。
- 振動量子は多原子分子で**モード平均**であり、最低モードではありません(CF4 で約1.3倍)。

### 7.7 状態の粒度

- 分子の電子励起は `X*` の**一括**で、個別の電子状態に分かれていません。
  $\mathrm{O_2}(a^1\Delta)$ と $\mathrm{O_2}(b^1\Sigma)$ のように化学的挙動が異なる状態は、
  レジストリに明示的にあるものだけが分離されています。
- 振動は $X_v$ 一準位で、$v=1,2,3\ldots$ の梯子ではありません。
  V-V 移動や多段振動励起は表現できません。
- 原子の準安定は NIST ASD から正しく分離できていますが、**分子の準安定**
  (例: $\mathrm{N_2}(A^3\Sigma_u^+)$)は同じ機構では扱えません。

### 7.8 検証の限界

- 反応リストの正しさを検証する外部の gold standard がありません。
  唯一の検算は curated レジストリとの照合で、それが §7.1 の 43–58% です。
- attestation は**ラベルであってフィルタではありません**。出典の沈黙は反応の否定では
  ないので何も除きませんが、逆に言えば**誤った反応を除く仕組みが無い**ということです。
- ar_sf6_o2 には熱力学的に不可能な curated 反応が1件残っています
  ($e+\mathrm{SF_6}\to 2e+\mathrm{F^+}+\mathrm{SF_4}+\mathrm{F}$、閾値 23.0 eV に対し下限 23.8 eV)。
  検出はできていますが、レジストリは意図的に修正していません。

### 7.9 限界の分類

| 種類 | 該当 | 解消の見込み |
|---|---|---|
| **実装の欠落** | §7.1 の反応クラス、§7.4 のスピン保存、Su–Chesnavich | 書けば消える |
| **データの不在** | §7.3 ラジカルの分極率、§7.6 硫黄フッ化物の熱化学 | 量子化学計算か文献の手入力しかない |
| **設計上の割り切り** | §7.7 状態の粒度、断面積を生成に使わないこと、三体 OFF | 目的に照らして意図的 |
| **原理的な限界** | §7.5 の片側上限、§7.8 の gold standard 不在 | 消えない |

---

## 8. 参考文献

1. Kramida, A. et al. *NIST Atomic Spectra Database* (ver. 5.11), NIST (2023).
2. Lias, S. G. et al. *Gas-Phase Ion and Neutral Thermochemistry*, J. Phys. Chem. Ref. Data **17**, Suppl. 1 (1988).
3. Gioumousis, G. & Stevenson, D. P. *Reactions of Gaseous Molecule Ions with Gaseous Molecules V*, J. Chem. Phys. **29**, 294 (1958).
4. Su, T. & Chesnavich, W. J. *Parametrization of the ion–polar molecule collision rate constant*, J. Chem. Phys. **76**, 5183 (1982).
5. Hotop, H. & Niehaus, A. *Reactions of excited atoms and molecules with atoms and molecules*, Z. Physik **228**, 68 (1969).
6. Landau, L. & Teller, E. *Zur Theorie der Schalldispersion*, Phys. Z. Sowjetunion **10**, 34 (1936).
7. Evans, M. G. & Polanyi, M. *Inertia and driving force of chemical reactions*, Trans. Faraday Soc. **34**, 11 (1938).
8. Condon, E. U. *Nuclear motions associated with electron transitions in diatomic molecules*, Phys. Rev. **32**, 858 (1928).
9. McQuarrie, D. A. *Statistical Mechanics*, University Science Books (2000).
10. Lieberman, M. A. & Lichtenberg, A. J. *Principles of Plasma Discharges and Materials Processing*, 2nd ed., Wiley (2005).
11. Bell, M. I. et al. *Electron-impact ionization of SF6*, J. Vac. Sci. Technol. A (2014), doi:10.1116/1.4853675.
