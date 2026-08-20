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

$\mathcal{K}$ は `--known` で渡した索引。照合は種ごとに係数を合算した化学量論で行うので、$2e$ と $e + e$ は同一と判定されます。

$$\text{sig}(r) = \Bigl(\text{family},\ \text{third\_body},\ \text{surface},\ \textstyle\sum\nu\ \text{per species 両辺}\Bigr)$$

**ラベルであってフィルタではありません** — 出典の沈黙は反応の否定ではないので、何も除きません。

---

## 5. 物性の定義と出どころ

| 記号 | 物性 | 単位 | 要る判定 | 出どころ(件数) |
|---|---|---|---|---|
| $q$ | 電荷数 | — | 1.1 | レジストリ(定義) |
| $n_E$ | 元素の原子数 | — | 1.2 | レジストリ(定義) |
| $V$ | 元素の価数 | — | 1.3 | コード内定数 |
| $EA$ | 電子親和力 | eV | 1.4, 2.2, 2.6 | **mendeleev** 16 / NIST WebBook 手動 8 / CCCBDB 1 / ASD 1 / 文献 2 |
| $J, \pi$ | 全角運動量、パリティ | — | 1.5 | **NIST ASD**(API・キー不要) |
| $E^{*}$ | 励起準位 | eV | 1.5, 2.2, 2.4 | **NIST ASD** |
| $\Delta_f H$ | 生成エンタルピー(298 K) | eV | 2.1–2.9 | **chemicals** 46 / **導出** 22 / pyromat 3 / NIST 手動 5 |
| $IE$ | イオン化エネルギー(断熱) | eV | 2.2, 2.4, 2.6 | **mendeleev** 18 / WebBook 手動 6 / ASD 2 / 文献 8 |
| $D_0$ | 結合解離エネルギー | eV | 2.4, 2.6 | **導出**: $\Delta_f H(B)+\Delta_f H(C)-\Delta_f H(BC)$ |
| $E_{\text{vib}}$ | 実効振動量子 | eV | 2.7, 2.8 | **導出**: chemicals TRC $C_p$ から当てはめ(20種) |
| $\alpha$ | 分極率 | Å³ | 3.1 | NIST CCCBDB 手動 **5件のみ** |
| $\mu, m$ | 換算質量、質量 | amu | 3.1, 3.3 | **組成から導出** 75 / mendeleev 11 |
| $\sigma(E)$ | 衝突断面積 | m² | **3.2 のみ** | LXCat 手動。**生成・篩には一切使いません** |
| $\gamma$ | 付着係数 | — | 3.3 | `registry/materials/`(文献) |
| $T_e, T_g, n_e$ | 電子・ガス温度、電子密度 | eV, K, m⁻³ | 3.2–3.4 | `case.yaml`(利用者が指定) |

**pip で自動取得**: mendeleev / chemicals / pyromat
**API で自動**: NIST ASD(`energy1.pl`)
**手動エクスポート**: NIST WebBook / CCCBDB / LXCat
**検証専用**(パイプライン外): HITRAN(`hapi`)、CCCBDB

「導出」は推定ではなく恒等式です。$\Delta_f H$ の22件はイオン(中性+$IE$)と励起状態(基底+$E^*$)、質量75件は組成の和。導出した $IE(\mathrm{Ar_{4s}}) = 4.16\,\mathrm{eV}$ がレジストリの独立した実測閾値と一致することで検算しています。

---

## 6. 参考文献

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
