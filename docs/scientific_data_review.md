# 科学データの個別審査記録

2026-10-12更新。以下は対象データを個別に照合した結果です。物性・速度データの確認を、参加状態の存在承認や機構全体の妥当性へ広げません。

## O(1D) + O2の二つの生成物チャネル

[NASA/JPL Evaluation 20、JPL Publication 25-1（2025）のTable 1A（p. 1-7）とNotes A2/A3（pp. 1-15–1-16）](https://science.jpl.nasa.gov/documents/1503/NASA_Data_Evaluation_20.pdf)を2026-10-12に取得し、表と注記の全該当ページを画像・本文で照合しました。PDFのSHA-256は `835496c8fd180b29ff9fc456e038dc8fd34e829e5f6e00346b0837ad71b4169c` です。以前の19-5検索索引だけの確認を、この全文審査で置き換えます。

総O(1D)消失率は `k_total=3.3e-11 exp(55/T) cm3/s` です。Table 1Aの104–424 Kは実験データの範囲であり、Note A3が推奨する式の適用範囲は100–400 Kです。両者を分け、後者を新datasetの`validity`へ記録しました。採用分岐はb1Sigmaが `0.80±0.20`、a1Deltaが `0.20`（範囲0–0.40）で、後者は前者の残りです。b1Sigmaは振動準位を合計した電子状態yieldであり、v別の係数ではありません。

原資料のO生成物はO(3P)電子項全体であり、RegistryのO(3P2)個別準位を決めません。新しい`O_3P`は既存のlumped電子項表現で両者を区別します。固定の励起エネルギー、縮退度、人口重み、形成量、NASAを補いません。従来のO(3P2)生成物候補と原転記は残しますが、datasetは`total_process`としてその個別Jチャネルには利用不可です。新しい項全体の二つのチャネルだけが数値係数を返します。

Registryではnominal分岐を総率へ掛けた二つの係数を`derived`として保持します。標準式 `k=A(T/Tref)^b exp[-Ea/(kBT)]` に対し、`b=0`、`Ea/kB=-55 K`、`Tref=298 K`、速度次数2を明示しました。Trefは正規化の表記上の選択で、b=0なので値に影響しません。`1 cm3=1e-6 m3`によりAはそれぞれ `2.64e-17`、`6.6e-18 m3/s`です。

原資料の総A、分岐の誤差・範囲、総率の表記 `f(298 K)=1.10, g=10` は出典宣言として保存します。分岐間の相関と総率の不確かさを独立誤差と仮定して合成していません。出力係数はnominal値で、完全なチャネル係数の誤差分布は未確定です。二つのnominal率の和、単位、温度範囲内外を回帰例で確認します。

## O(1D) + N2、CO2の電子項単位の消光

同じEvaluation 20のTable 1A（pp. 1-7–1-8）、Note A7（pp. 1-18–1-19）、Note A12（pp. 1-20–1-21）を全文・画像で確認しました。N2では `k=2.15e-11 exp(110/T) cm3/s`、推奨100–675 K、O(3P)+N2への消光yield 1です。Tableの104–673 Kは実験データ範囲として別に残しました。第三体によるN2O形成は別の速度則であり、この係数へ混ぜません。

CO2では `k=7.5e-11 exp(115/T) cm3/s`、O(3P)+CO2生成物の推奨nominal yield 1です。Note A12が温度依存fitに使ったと明記する200–354 Kへ、今回の採用範囲を限定しました。Tableの実験範囲195–370 Kと、Noteで一致が確認された195 Kの測定点は別に保持し、推奨式の全適用範囲と見なしません。CO3中間体を通る同位体交換、微小なCO+O2経路が記載されているため、単なる非反応衝突の実証や厳密な単一生成物確率1とは扱いません。

二つとも`O_3P`生成物と分子の電子種という原資料のscopeに対応させ、個別J・回転振動準位の速度へ転用しません。係数は既存の共通Arrhenius評価で返し、SIのAはそれぞれ `2.15e-17`、`7.5e-17 m3/s`、`Ea/kB=-110/-115 K`、二次速度則です。298 Kではfitの結果が原表の丸めた `3.1e-11`、`1.1e-10 cm3/s`に一致することを確認します。

原資料の`f(298 K)`と`g`は宣言として保存し、全温度で同じ誤差倍率には置き換えません。根拠のmethod、provider `NASA_JPL`、collection `evaluated_gas_kinetics`、release `25-1`、native record `A3/A7/A12`を独立に保持し、通常の共通データ選択へ対応させました。利用者温度がない場合は気体温度不足、範囲外なら係数を返しません。気体温度から未測定の状態人口、反応発生率、濃度予測を決めません。

Evaluationの本文にはCaltechのcopyrightが記載されています。原PDF・ページ画像・全文・原表は配布物へ追加せず、必要な少数の事実値・派生式と出典宣言だけを記録しました。F+H2（E118）とF+CH4（E121）の表・全文注記も確認しましたが、HF等の内部準位別生成物分岐を確認できないため、ground/v=0のexact生成物係数として追加していません。Pateauの条件不足をこの資料の温度範囲で補うこともしません。

## O2(a1Delta)のO2による自己消光

[Wildtらの1988年論文の一次abstract](https://www.sciencedirect.com/science/article/abs/pii/0301010488800272)には、自己消光係数 `(1.5±0.2)e-18 cm3/s` が記載されています。直接openは403でしたが、同じ出版社URLの検索索引でabstractを確認しました。SI値 `1.5e-24 m3/s` と絶対誤差 `2.0e-25 m3/s` を保存します。誤差の信頼水準はabstractから決められません。

abstractで確認できた測定量は、O2圧力を変えたときのa→X（1270 nm、0→0帯）の時間減衰から得た励起状態の自己消光係数です。二つのO2基底状態生成物を状態別に直接測定した係数とは確認できないため、`channel_scope=total_process`とします。候補式は保持しますが、その完全なexact-stateチャネルの根拠は`needs_review`です。数値転記の資格と絶対誤差は独立に保存し、測定精度全体を承認したとは扱いません。

測定温度の数値、圧力範囲、生成物の状態別分岐は確認できていません。従来の`room_temperature`注記は未確認の履歴として残し、300 Kへ置き換えません。利用者が300 Kや700 Kを入力しても、生成物scopeが未確認なので先に`DataUse=unavailable`となり、総消光係数はこの生成物チャネルを決めないという理由を返します。宣言値・絶対誤差・未確認の温度適用条件は保存・再読込みで保持します。

## 希薄プラズマjetの電荷移行・解離性再結合

[Gaucherel・Roweの1977年論文の一次abstract](https://www.sciencedirect.com/science/article/abs/pii/0020738177800508)を、同じ出版社URLの検索索引で確認しました。abstractは希薄プラズマjetで測定した`Ar+ + O2 → Ar + O2+`の`6.3e-11 cm3/s`と、`O2+ + e → O + O`の`8.2e-9 cm3/s`を報告しています。元の数値・単位を残し、SI値はそれぞれ`6.3e-17`、`8.2e-15 m3/s`、報告された二体係数の次数2として保存します。

abstractは内部準位別の生成物分岐を明示しません。両datasetは`total_process`として扱い、数値転記の既存品質を維持しつつ、完全なexact-state候補式の根拠を`needs_review`とします。電子・イオン・気体の測定温度、反応ごとの運動エネルギー分布、親の内部状態人口、生成物準位別分岐は未確認です。温度依存を示唆する記述を、全温度で使える定数や分布関数へ置き換えません。700 K等の利用者条件でも、総過程係数から当該生成物チャネル係数は返しません。式の保存則の整合は成立しても、チャネルの発生・不存在・速度は決まりません。

3係数とも出版社のabstract・本文・DOIへの直接アクセスは失敗し、原著本文や著者公開版は取得できませんでした。確認範囲は公式検索索引の一次abstractであり、全文の測定条件・精度を審査したという意味ではありません。

## 会合の実効式とArのpooling

[Sonらの2014年論文、p. 242とTable 1（pp. 244–245）](https://swb.skku.edu/_res/pnpl/etc/2014-02.pdf)は、R21–R60の重粒子係数を700 Kで採用すると明示しています。初回は六つの会合だけを確認しました。追加審査では40件すべての式・原数値・`cm3/s`から`m3/s`への換算を照合し、二次のmodel係数として700 Kの点へ適用を揃えました。従来未指定だった34件の条件を修復した範囲で、電子係数や機構全体の運転条件を承認していません。

八つの会合（R21/32/35/36/37/42/57/60）は放射・第三体の安定化を指定していないため、`stabilization=unspecified` を保持します。700 Kで値を返せても、素過程・一般的温度依存・エネルギー散逸機構は決まりません。300 K等へ外挿せず、温度未入力なら`gas_temperature`不足を返します。

[Gudmundssonらの原論文、Table 1とsection 2](https://doi.org/10.1088/1361-6595/ac3ba1)では、原子イオンを生成するpoolingをPenning過程として扱い、metastable/radiativeを分けています。既存Ar4s式は `penning_ionization` に修正しました。式の保存則と過程パターンは成立しますが、四準位を含むumbrellaの人口重みは未確認です。exactなlumpedチャネルの根拠は `needs_review` とし、代表エネルギー11.6 eVから固定した放出エネルギーを撤去しました。member別の速度をumbrellaへ転用していません。

## Pateauのモデル係数と反応分類

[Pateauらの原論文](https://doi.org/10.1116/1.4853675)は直接取得できませんでした。[共著者Mohamed Boufnichelが公開したproof copy](https://www.researchgate.net/publication/259780759_Modeling_of_inductively_coupled_plasma_SF6O-2Ar_plasma_discharge_Effect_of_O-2_on_the_plasma_kinetic_properties)の検索索引本文でTable III（proof p. 4）、Table VII（p. 7）と脚注を確認しました。原PDFや最終typeset版を取得した範囲ではありません。

既存167係数の式・原数値・単位換算・二次次数を照合しました。R38/48/50は表の汎用式と指定参加種からの展開です。個別チャネルを独立に測定した167件の実験証拠とは扱いません。温度・圧力適用範囲と不確かさは表から決まらず、引用された実験・評価資料の追加審査が必要です。論文のreactor計算点を個別係数の`validity`へ転用しません。利用者が700 K等を入力しても、これらは`dataset_applicability_conditions`不足を保持します。

R130/131/133/134/135/136のO・O(1D)各式は、Table VIIと脚注aに対応する2→1式です。12件を`reactive_scattering`から`association`へ修正しました。既存12会合を含め、安定化は`unspecified`です。分類の整合は成立しますが、光子・第三体・励起中間体を補った素過程や条件依存は決まりません。

R138は単分子式`SOF4 → SOF3 + F`ですが、proofには`1.0e-12`が共通の`cm3/s`見出しで記載されています。これは一体の減衰係数の次元を確定できず、従来の二次転記の競合を含めて数値datasetは未採用のままです。値を`1/s`へ読み替えたり、colliderを追加したりしていません。

今回追加したのは既存宣言の照合結果と不足の記録です。原表・全文を新規同梱せず、公開閲覧を原PDFや下位資料の再配布許諾と見なしません。追加取得・採用は[source license policy](source_license_policy.md)に従い、対象の測定量と条件を個別に確認します。

## 族と過程の式パターン

[IUPACのdissociation定義](https://goldbook.iupac.org/terms/view/D01801)には単分子分離が含まれ、[association定義](https://goldbook.iupac.org/terms/view/A00472)と逆の関係で説明されています。両公式ページの直接取得は403でしたが、公式検索索引の定義本文を確認しました。この用語上の範囲を踏まえ、現行実装では電子衝突解離と、自由電子を伴わないneutral/ionの単分子解離を参加者から区別します。同じ`dissociation`という名前だけで電子式を適用しません。

一般会合の式検査は、自由電子を伴わない重粒子2→1と保存則の対応を確認します。第三体が明示される式はその別の過程を検査します。`consistency=pass`は宣言した族・過程・式の対応であり、安定化、活性化機構、生成物へのエネルギー配分、反応速度の証明ではありません。未定義の族・過程は`unknown`、定義した式パターンへの矛盾は`fail`とし、未対応を現象不存在へ読み替えません。

[IUPACのmolecularity](https://goldbook.iupac.org/terms/view/M03989)は素反応の微視的事象の参加数を表し、[反応次数](https://goldbook.iupac.org/terms/view/O04322)とは段階反応で一般に一致しません。これらも公式検索索引で確認しました。今回の二次model係数は原資料の式・測定量・単位から記録するもので、2→1分類から任意の実効速度則を導く規則ではありません。

## Ar/Ar+の基底状態と個別物性

[NIST ASDのAr基底準位・イオン化エネルギー表](https://physics.nist.gov/cgi-bin/ASD/ie.pl?at_num_out=on&biblio=on&e_out=0&el_name_out=on&level_out=on&seq_out=on&shells_out=on&spectra=Ar&unc_out=on&units=1)で、Arの1S0とAr+の2P°3/2を確認しました。存在根拠を状態に、イオン化エネルギーとその不確かさを別propertyに記録しました。値はそれぞれ15.7596119±0.0000005 eV、27.62967±0.00012 eVです。状態の確認によって形成エンタルピー等をreviewedにしていません。励起人口とlifetimeもこの表からは決めません。

Ar基底状態のNASA7だけを[Cantera 3.2.0のair.yaml](https://github.com/Cantera/cantera/blob/v3.2.0/data/air.yaml)と係数・300–5000 K範囲・気相の対応で照合し、[公式reference-pressure規則](https://cantera.org/stable/yaml/species.html)による1 atmを明示しました。これは配布されたfitの同定と採用資格の審査です。元測定精度、他種・励起種・イオンのNASAを一括承認していません。単原子理想気体のCp/R=5/2と、領域境界を跨ぐエンタルピー・エントロピー関係を確認しました。

電子衝突Arイオン化の旧閾値15.75961 eVは、同じNIST値を粗く丸めた宣言でした。内部エネルギーのモデル閾値を15.7596119 eVへ揃え、出典と範囲を明示しました。断面積の実測開始点・recoil補正は取得していません。IEの不確かさ範囲と宣言閾値が重なる場合はunknownを返し、誤差範囲を絶対的な現象の禁止には使いません。

## O/O+、O(1D2)、O2の個別資格

[NIST ASD 5.12のOイオン化表](https://physics.nist.gov/cgi-bin/ASD/ie.pl?at_num_out=on&biblio=on&e_out=0&el_name_out=on&level_out=on&seq_out=on&shells_out=on&spectra=O&unc_out=on&units=1)と[O I準位表](https://physics.nist.gov/cgi-bin/ASD/energy1.pl?de=0&spectrum=O+I&units=1&format=3&output=0&page_size=15&multiplet_ordered=0&conf_out=on&term_out=on&level_out=on&unc_out=on&j_out=on&g_out=on&biblio=on&temp=&submit=Retrieve+Data)、[O II準位表](https://physics.nist.gov/cgi-bin/ASD/energy1.pl?de=0&spectrum=O+II&units=1&format=3&output=0&page_size=15&multiplet_ordered=0&conf_out=on&term_out=on&level_out=on&unc_out=on&j_out=on&g_out=on&biblio=on&temp=&submit=Retrieve+Data)を取得し、基底配置・term・J・parity・g・存在根拠を状態ごとに確認しました。Oは3P2、even、g=5、O+は4S°3/2、odd、g=4です。IEはそれぞれ`13.618055±0.000007 eV`、`35.12112±0.00006 eV`として独立にreviewedとしました。各基底準位から次のイオンの基底準位への量であり、励起標的の閾値ではありません。Oのg=5から3P全fine-structureの人口配分を決めません。

O(1D2)の励起エネルギーを、ASDの`1.9673642 eV`へscalar・Propertyともに訂正しました。[NIST Handbookの15867.862 cm−1](https://physics.nist.gov/PhysRefData/Handbook/Tables/oxygentable5.htm)とのSI換算も確認しています。ASDの誤差欄が空であることはnote-onlyの不明誤差として保存し、ゼロにしません。旧形成エンタルピーとNASAはimportedを維持し、基底Oのfitへ丸めたenthalpy-only shiftを足した履歴では励起種の熱容量や温度参照を確認できない理由を残しました。準位の存在・エネルギー確認から寿命・人口・熱化学を昇格しません。

O2のX3Σg−基底電子状態の存在は[NIST WebBookの二原子分子定数表](https://webbook.nist.gov/cgi/cbook.cgi?ID=C7782447&Units=SI&Mask=1000#Diatomic)で確認しました。気相中性O2のNASA7は[Cantera v3.2.0 air.yamlのTPIS89](https://github.com/Cantera/cantera/blob/v3.2.0/data/air.yaml)に対して全14係数と200/1000/3500 Kの区分を照合し、[同版の標準圧力規則](https://cantera.org/3.2/yaml/species.html)による101325 Paを明示してreviewedとしました。これは配布fitの対応確認で、原測定精度、独立scalar物性、O2(a/b)のNASAの承認ではありません。298.15 Kの標準形成エンタルピー、正の熱容量、dH/dTとT dS/dTの対応、領域境界を回帰確認しました。

## IE・EA・Penningの宣言エネルギー判定

[IUPACの電子親和力（EA）の定義](https://goldbook.iupac.org/terms/view/E01977)は、中性種への電子付加で放出するエネルギーと、単価陰イオンからの電子脱離に必要なエネルギーを対応させています。[IUPACのPenning ionizationの定義](https://goldbook.iupac.org/terms/view/12520)は、励起した中性種から別の中性種へのエネルギー移動によるイオン化を、化学変化を伴わない過程として示しています。両公式ページへの直接取得は403でした。同じ公式URLの検索索引で定義本文を確認した範囲であり、引用元の勧告論文全文の照合や個別反応の実証を行ったという意味ではありません。

IE・EA・励起エネルギーの不等式は、値・単位・数値資格を持つ個別Propertyの宣言範囲から評価します。不確かさの宣言がない値は宣言された点として扱いますが、誤差が不明と明記されたnote-only宣言や不正な範囲をゼロ誤差へ置き換えません。中心値が同等で幅の異なる宣言には、全区間を包むenvelopeを用います。別の中心値や同定の競合はunknownです。測定を平均した値、統計的な合成誤差、信頼水準、相関、絶対的な物理禁止を導いていません。

イオン化では、基底親のIE範囲と宣言閾値の範囲を比較します。閾値の下端がIEの上端以上なら下限関係は成立、閾値の上端が換算精度で区別できるIEの下端未満なら宣言の不整合、その間や換算精度の境界はunknownです。不確かさが未宣言ならその側は名目点であり、測定誤差ゼロではありません。EAからの束縛推論は、同じ相・構造に対応する中性基底親と基底陰イオンに限定します。正負を区間全体で決められない場合はunknownです。この関係だけでは、他の分解経路に対する安定性、寿命、人口、反応速度は決まりません。励起陰イオンへの付加を基底EAで否定しません。

EAの`qualifier: unbound`は、対応する基底陰イオンが電子脱離に対して非束縛であるという明示宣言として扱います。解釈する語の大文字小文字・前後空白を同じ科学意味として比較し、原宣言の文字列は保存します。数値EAを併記した場合はその範囲との整合も必要です。正の範囲全体と`unbound`が同一または別記録で併存する場合は当該EAの競合として保持し、束縛判定をunknownにし、EAを使う数値差からも除外します。ゼロを含む範囲、不正な不確かさ、誤差不明の注記は否定へ読み替えません。数値のない審査済み`unbound`は明示の非束縛宣言として評価し、未審査・scope外・拒否された宣言からは結論を出しません。状態と直接付着はこの同じ規則を使います。正のEAによる束縛支持だけでは、付着反応の安定化・速度・発生を確定しません。

[NIST CCCBDBのEAの符号規約](https://cccbdb.nist.gov/elecaff1x.asp)では、正のEAは電子束縛を表します。一方、[IUPACのunstable](https://goldbook.iupac.org/terms/view/U06569)は比較基準に対する熱力学的不安定、[transient species](https://goldbook.iupac.org/terms/view/T06451)は観測時間尺度に対する短寿命です。これらの語は電子非束縛を意味しないため、EAの正負を上書きしません。状態の`existence: transient`も非束縛共鳴へ読み替えず、単独では束縛状態の支持・否定をunknownにします。独立した`confirmed/unbound`宣言や適格なEAの束縛根拠との競合を作らず、それぞれが決める命題を保持します。IUPAC定義は公式検索索引、NISTは公式ページで2026-10-12に確認しました。符号・単位・ゼロ跨ぎ・同一記録内の矛盾・複数出典の入力順・資格・独立量の保持をsynthetic境界例で検証しました。

Penningの現行エネルギー式は、気相のresolvedな中性励起供与体と中性基底標的から、対応する中性基底供与体、単価基底イオン、電子を生成する場合に限定します。励起・構造変更を伴う生成物やlumped人口へ、基底IEと代表励起エネルギーを転用しません。励起エネルギー範囲からIE範囲を引き、明示された相対衝突エネルギーがあれば加えます。全範囲で必要エネルギーを満たす場合だけpass、全範囲で不足し衝突エネルギーも指定されている場合だけ宣言条件のfail、それ以外はunknownです。気体温度を最大衝突エネルギーと見なしません。出力の中心差 `penning_available_energy_eV` は励起エネルギーとIEの宣言中心値の差であり、衝突エネルギーや電子の実測運動エネルギーを含みません。passでも発生確率や実際の発生は未確定です。

同等中心値の照合では、異なる単位の換算に生じるroundoffだけに相対許容差 `1e-12` を使います。同一単位の異なる宣言を平均・採用する規則ではなく、不確かさ区間の拡大・縮小にも使いません。区間の重なり、同じ中心値の異なる誤差、異単位換算、実生成物との対応、数値overflowを回帰確認しました。

## エネルギー定義と命題の適用対象（0.7.4）

2026-10-12に[IUPACのionization energy](https://goldbook.iupac.org/terms/view/I03199)、[adiabatic ionization](https://goldbook.iupac.org/terms/view/A00143)、[appearance energy](https://goldbook.iupac.org/terms/view/A00421)の公式検索索引と、[NIST CCCBDBの垂直・断熱IEの説明](https://cccbdb.nist.gov/adiabaticx.asp)の本文を確認しました。IUPACへの直接取得は403であり、勧告論文全文の確認ではありません。断熱値は対応する基底イオンへの量、垂直値は構造緩和前の量で、出現エネルギーは観測したイオンの生成に関する量です。単位の一致だけでは同じ命題の入力になりません。

現行の基底IE/EA関係は気相の同じ構造・対応する電荷状態を対象にし、分子の垂直値や定義未指定値を断熱値へ読み替えません。原子の既存値は原子量として扱い、取得記録にはatomicを明記します。基底IEは同じ対象の励起イオン生成への下限に使えても、励起終状態とのエネルギー差を確定しません。appearance_energyは保存しますが、channel_thresholdの比較へ自動転用しません。自由qualifierのupper/lower limitやapproximateは点値として評価せず、量に依存する結論だけを保留します。

thresholdとproducts-minus-reactants差は、同じPropertyで定義・資格・出典・宣言誤差を量別に保持します。差の宣言範囲と、同じ対象から導く電荷交換欠損の範囲の共通部分がある場合は宣言上の不整合なし、離れている場合は当該関係の不整合です。測定誤差の相関・統計的有意性は判断しません。上限注記、別相・構造、分子の未定義/垂直値、反応閾値の両側誤差、同一記録のeV/J換算、同じ命題の状態/反応表示、未対応モデルと真の値不足の区別を合成境界例で検証しました。

## 形成量の共通参照と電子熱化学規約

2026-10-12に[NIST WebBookのGas-Phase Ion Thermochemistry](https://webbook.nist.gov/chemistry/ion/)を確認しました。
形成量は共通の参照温度・元素基準で比較する必要があり、0 KのIE/EAを有限温度の形成量へ足すだけでは
温度補正は確定しません。有限温度のIon ConventionとElectron Conventionはイオンの形成量が異なり、
両者を混在させると反応差が崩れます。電子の熱項が相殺されない反応にはその寄与が必要です。
NISTはBoltzmannとFermi-Diracの扱いも区別しています。本コードは電子熱モデルを無言で選ばず、
規約と必要な電子形成量を明示する場合だけ比較します。NISTの特定温度の推奨値を全温度の式へ転用しません。

現行Propertyの`formation_reference`は温度、`standard_elements`の基準、標準圧、必要な電子規約と
電子形成量を共通型へ保存します。参照不足・不一致は形成量によるΔHだけを保留し、独立したNASA ΔG/Kや
IE/EAの関係は保持します。参照0 Kでは両電子規約が一致し、有限温度のElectron Conventionでは電子形成量0、
Ion Conventionでは反応前後の電子項が変わるときに明示値を必要とします。標準圧・参照温度の一致検査は、
実際の反応発生や障壁・速度の判定ではありません。ΔHの参照温度は気体の計算温度と別に出力します。
比較には対象の電荷を使い、中性形成量の電子規約・電子形成量を無関係な差にしません。有限温度の
イオンでは、規約を明示した同値の適格記録を規約未定の記録で隠さず、後者の原宣言は未定のまま保存します。
異なる明示イオン規約の無言選択は止めます。0 Kの一致と、この不足・不要情報の境界を別々に検証しました。
電子形成量も、相殺されない反応でだけ選択・比較します。同値・同基準のIon Convention記録で
未宣言と明示電子項が併存する場合は、前提を満たすProperty全体を使用し未定記録は保全します。
Electron Conventionの未宣言と0は定義上同義です。異なる明示電子項は依存するΔHだけを保留し、
相殺される電子項をHf自体の矛盾や熱化学表現の不存在へ読み替えません。
必要電子項の完備度で絞る前に一般Hf値・参照の競合を検査します。補助量不足を理由に、同じ基準の
別の審査済みHf反対値を消さないことも、入力順・資格tierの組合せで確認しました。

[chemicalsの公式Hfg実装](https://chemicals.readthedocs.io/_modules/chemicals/reaction.html)で、
Hfgの提供元テーブルと選択順、使用する`Hfg`列を確認しました。
[ATcT version 1.112の公式一覧](https://atct.anl.gov/Thermochemical%20Data/version%201.112/)は直接取得できず、
同じ公式URLの検索索引で0 Kと298.15 Kの二列とCF4の対応値を確認しました。ローカルchemicals同梱表にも
`Hfg_0K`と`Hfg`が別列であることを確認しました。
[chemicalsのCRC標準表説明](https://chemicals.readthedocs.io/chemicals.heat_capacity.html)は298.15 Kを明示しています。
新しい熱化学取得ではHfg/S0gを供給した実際のテーブルを指定して読み、collection、package版、CASと量の原IDを
保持します。ATCT_G/CRCの形成量には確認できた298.15 Kと標準元素基準を記録し、確認していない参照圧・
電子規約・元測定情報は補いません。package名だけの旧Registry値へ新しい出典・参照条件・審査を付けていません。

解像準位からの形成量offsetは親の明示0 K参照に限定します。元の親Property宣言、level値・出典・参照を保存し、
有限温度の振動・回転等の熱寄与差を電子level energyから推測しません。
`tests/test_formation_reference.py`は単位換算、反応方向、係数、参照不足・不一致、電子規約、相殺される電子項、
不正入力、独立NASA値の保持、入力順、正規化・ingest/adoptの往復を合成値で確認します。これらは比較規則と
保存の検証であり、同梱形成量の原資料審査や実験精度の検証ではありません。

## 継続するデータ不足

数値断面積表の取得・再配布条件、残る状態同定・物性・NASA、Pateau係数の引用元における条件、会合の安定化、umbrella人口重みは未解決です。今回の修復で全候補の速度や機構の予測精度が揃ったとは結論しません。必要な対象・測定量ごとに本記録と同じ粒度で原資料を審査します。
