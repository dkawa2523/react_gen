# Registryの出典・適用条件・再配布

## 1.0の配布範囲

1.0のソース配布物（sdist）には、Registryの状態・反応レコード、数値asset、出典記録とnoticeを収録します。wheelは実行パッケージと結果schemaを収録します。展開したソース配布物のRegistryを `rgen analyze --evidence PATH` で明示できます。[通常利用](../README.md)

この収録はプロジェクト側の配布判断です。第三者資料の利用条件は出典ごとに適用されます。今回、新たに第三者からの許諾を取得した記録はありません。Pateau・Sonの元の反応集成については、包括的な再配布許諾が確認できていません。収録物はプロジェクトの個別レコードと変換済みassetで、原著PDF、原表の画像、取得ページ、外部プログラムは対象外です。個々の数値事実・式と、原資料の説明や創作的な選択・配列には別の検討が必要です。[米国著作権局 Circular 33](https://www.copyright.gov/circs/circ33.pdf)・[NIST SRDの取扱い](https://www.nist.gov/open/copyright-fair-use-and-licensing-statements-srd-data-software-and-technical-series-publications)

配布・受渡しでは、`registry/sources/`、各レコードの原宣言、`registry/data_notes/` の帰属・noticeを対応するデータと一緒に保持します。出典、適用条件、利用資格、再配布条件は別々に確認します。[反応データ帰属記録](../registry/data_notes/reaction_data_attribution.txt)

## 取得元と審査

[取得先台帳](../external_data/source_catalog.yaml)は取得形式と利用条件の確認先を案内します。取得は `acquire`、物理対象との照合は `rgen ingest`、Registryへの書込みは `rgen adopt` です。取得や採用の結果は、状態の存在、係数の適用、機構の妥当性を個別に審査する材料になります。用途への採用には、対象・物理量・参照条件・審査範囲が合う記録を使います。[取得・照合の手順](data_sources.md)・[記録形式](registry_data_guide.md)・[判定の責務](core_design.md)

出典の確認では、元資料の版、URL、元ID、原単位、変換、取得ハッシュを分かる範囲で保持します。追加の外部数表・スナップショット・分析結果を配布する際も、実際に含まれる資料とその条件を確認します。公開閲覧、引用情報、Text and Data Mining用の許諾は、それぞれが示す範囲で扱います。

## 反応数値の出典と適用条件

| 収録記録 | 確認した科学上の適用条件 | 出典・再配布条件 |
|---|---|---|
| CollisionDB D108105 | H(1s)の電子電離でbare H⁺を生成する積分断面積。配布fit由来の500点をcm²からm²に変換した。数表は13.6–100000 eV、宣言fit範囲は13.601–100000 eV。1.3%はfitのRMS偏差で、推薦精度や統計的測定不確かさとは別。 | [CollisionDB専用方針](https://db-amdis.org/collisiondb/licence/)は個別例外を除きCC BY 4.0。元データの個別例外は確認されていない。Janev・Smith、CollisionDB/IAEA、ライセンス、変換を保持する。[取得記録・原本とCSVのSHA-256](../registry/sources/collisiondb_2026.yaml) |
| Pateau 2014 | 原32行（R38–50、R119–137）に対応する167件。汎用式の参加種展開を含む。温度・圧力適用範囲は未確認で、装置の運転点や入力温度から補わない。2→1会合の安定化は未指定。単分子R138の表見出しと次数の次元不整合は未解決で、当該数値は未採用。 | 著者公開proofの表III・VIIと脚注の確認範囲を保持。元の反応集成に対する個別許諾は未確認。[論文DOI](https://doi.org/10.1116/1.4853675)・[AIPの再利用方針](https://publishing.aip.org/resources/researchers/rights-and-permissions/permissions/) |
| Son 2014 | Table 1のR21–60に対応する40件。気体温度700 Kの点に限って使う二次のモデル係数。会合の安定化は未指定。 | 原行・単位換算・出典を保持。出版社は権利照会先を掲示し、元の表の集成に対する個別許諾は未確認。[論文・権利案内](https://link.springer.com/article/10.1007/s11090-013-9513-1)・[本文・Table 1](https://spl.skku.ac.kr/_res/pnpl/etc/2014-02.pdf) |
| Gaucherel・Rowe、Williams、Wildt | Gaucherel・Roweの2件とWildtの自己消光は総過程の係数で、生成物の内部準位別の係数には使わない。測定温度は未確認。Williamsの1件は該当レコードの条件を適用する。 | 個別の数値宣言を記録。[Elsevierの再利用方針](https://www.elsevier.com/about/policies-and-standards/copyright/permissions)は数値から作る新たな表現と原図表の転載を区別する。著者・原単位・変換は[帰属記録](../registry/data_notes/reaction_data_attribution.txt)と個別レコードに保持。 |
| Shuman、Chen | 各1係数。Shumanの熱電子によるSF₅付着は300 Kの値。ChenはO⁺＋O₂の記録。 | 個別の数値宣言と出典を保持する。元記事や集成に対する包括許諾は未確認。[AIPの再利用方針](https://publishing.aip.org/resources/researchers/rights-and-permissions/permissions/) |
| JPL 25-1・19-5 | 現行4式と旧2式。O(¹D)消光で、O₂への式は100–400 K、N₂は100–675 K、CO₂は温度依存fitの採用範囲200–354 K。O₂では総消失率に原資料の分岐割合を掛けた名目値を保持する。O(³P)電子項全体の係数を個別Jや回転振動状態へ配分しない。 | 25-1はCaltechの著作権表示を持つ。収録範囲は少数の評価値・派生式とその出典宣言。25-1原本のSHA-256と原単位・分岐を個別レコードに保持。[原資料のTable 1A・Notes A3/A7/A12](https://science.jpl.nasa.gov/documents/1503/NASA_Data_Evaluation_20.pdf)・[JPLの方針](https://www.jpl.nasa.gov/caltechjpl-privacy-policies-and-important-notices/) |

アブストラクトを確認したWildt、Gaucherel・Roweの記録は、元の測定温度、内部状態人口、生成物分岐を保留しています。Ar(4s)のpoolingはPenning過程に分類し、集約した4準位の人口が未確認のため個別準位のエネルギー・速度を転用しません。これらの扱いは式の保存則や宣言した過程の整合と独立です。[Arの原論文](https://doi.org/10.1088/1361-6595/ac3ba1)

SF₆の中性解離で、SF₅＋FとSF₄＋2Fの値は出典の予想値です。SF₃の検出開始値は複数の出口を含みます。該当する式は調査候補に保持し、予想値と断片の観測は出典注記に置きます。[Christophorou・OlthoffのTable 21](https://srd.nist.gov/jpcrdreprint/1.1288407.pdf)

## 物性と分光の出典

| 収録記録 | 参照・適用条件とnotice |
|---|---|
| NASA TM-4513の気相NASA7・形成量 | 元の気相標準圧は1 bar。Canteraの圧力省略時の1 atmとは区別する。形成量は298.15 Kをfit範囲に含む中性基底種の導出値。電子熱化学規約が未確認のN⁺・O⁺・O₂⁺のfitは `imported` とし、形成量を導出していない。出典、適用温度域、元資料のSHA-256、対象別の採用根拠を保持。[NASA原資料](https://ntrs.nasa.gov/citations/19940013151)・[取得・対象別記録](../registry/sources/nasa_thermochemistry_2026.yaml)・[Cantera BSD notice](../registry/data_notes/Cantera-LICENSE.txt) |
| Ar・O₂の独立したNASA7 | [Cantera 3.2.0 air.yaml](https://github.com/Cantera/cantera/blob/v3.2.0/data/air.yaml)と[同版の参照圧規則](https://cantera.org/3.2/yaml/species.html)で照合した。Arは300–5000 K、O₂は200/1000/3500 Kの区分で、いずれも1 atm。異なるfitは独立記録として保持する。 |
| NIST WebBook・CCCBDB・ASD・Handbook | 収録するのは独立に選んだ数値事実と出典。SRD 69/101/78/108を区別し、元記録で確認できた版を保持する。[WebBookの権利表示](https://webbook.nist.gov/chemistry/contact/)・[CCCBDB](https://cccbdb.nist.gov/)・[ASD](https://www.nist.gov/pml/atomic-spectra-database-contents)・[NIST SRD notice](../registry/data_notes/NIST-SRD-NOTICE.txt) |
| ATcT Thermochemical Network v1.228 | 炭素・酸素・フッ素系、Cl₂とCl、NF₃系、SiH₄系の選択した気相端点に、元素標準状態基準の0 K生成エンタルピーを収録。版、対象、原ID、単位、公表された不確かさを保持する。本文・データベース表・共分散表の収録はない。個別の不確かさから反応差の誤差や信頼区間を推定しない。[Ruscic・Bross、Argonne National Laboratoryの版固定データ](https://atct.anl.gov/Thermochemical%20Data/version%201.228/) |
| chemicals | 熱化学・双極子・衝突半径等の個別値。元のdatabankや版が未記録の旧値には、現在の同値を根拠に出典を補わない。[chemicals MIT notice](../registry/data_notes/chemicals-LICENSE.txt) |
| mendeleev | 原子質量・IE・EA・分極率の値と単位変換。確認したv1.2.0のソフトウェアとデータのMIT noticeをそれぞれ保持する。[ソフトウェア](../registry/data_notes/mendeleev-LICENSE.txt)・[データ](../registry/data_notes/mendeleev-data-LICENSE.txt) |
| PYroMat | CF、CFO、FOの300 K理想気体エンタルピー評価値を3件収録。GPLv3の対象となるプログラムや係数ファイルは配布対象外。元評価の出典と温度を保持する。[PYroMat公式ライセンス](https://raw.githubusercontent.com/chmarti1/PYroMat/master/LICENSE.txt) |

Ar・Ar⁺とO・O⁺の基底準位・IEは、[ArのNIST ASD電離表](https://physics.nist.gov/cgi-bin/ASD/ie.pl?spectra=Ar&units=1)・[OのNIST ASD電離表](https://physics.nist.gov/cgi-bin/ASD/ie.pl?spectra=O&units=1)に照合しています。O(¹D₂)の励起値はASDと[Handbookの準位表](https://physics.nist.gov/PhysRefData/Handbook/Tables/oxygentable5.htm)の対応を確認し、誤差欄が空の宣言は誤差不明として保持します。O₂の基底電子状態は[WebBookの二原子分子定数](https://webbook.nist.gov/cgi/cbook.cgi?ID=C7782447&Units=SI&Mask=1000#Diatomic)が出典です。準位の同定、物性の資格、励起状態の寿命や人口は個別に扱います。

基底O₂の断熱IEはSRD 69の評価値12.0697 ± 0.0002 eVで、基底O₂⁺への電離に適用します。基底O₂から基底O原子2個への解離にはWang・Gong・MoによるD₀ 41269.19 ± 0.10 cm⁻¹を独立の端点差として収録します。どちらも通常同位体の基底端点に対応する個別の数値事実で、元の数表・図や論文本文の収録はありません。SRD 69の帰属とnoticeは上表に従います。[SRD 69評価値](https://webbook.nist.gov/cgi/cbook.cgi?ID=C7782447&Mask=864)・[Wangらの原論文情報](https://pubmed.ncbi.nlm.nih.gov/38647301/)

Cl₂とCl(²P₃/₂)にはATcT v1.228の気相0 K形成量を追加しています。元素標準状態基準であり、核種を指定した解離値や有限温度の係数には適用しません。版、物質ID、公開値とその不確かさの宣言を個別に記録します。[Cl₂](https://atct.anl.gov/Thermochemical%20Data/version%201.228/species/?species_number=11)・[Cl(²P₃/₂)](https://atct.anl.gov/Thermochemical%20Data/version%201.228/species/?species_number=2311)

O₂とF₂の化学式IDに、SRD 69の分子構造と照合したSMILESと出典を記録します。明示した核種や異なる内部状態には転用しません。元構造ファイルは収録せず、SRD 69の帰属とnoticeは上表に従います。[O₂](https://webbook.nist.gov/cgi/cbook.cgi?ID=C7782447)・[F₂](https://webbook.nist.gov/cgi/cbook.cgi?ID=C7782414)

NF₃の基底電離の端点差には、Bentleyらの理論値と分光帰属の再評価を取り込んだATcTを使います。従来の光電子帯の観測開始と、最低の振電状態間の断熱差を区別します。NFのa¹Δ・b¹Σ⁺にはSRD 69の分光バンド原点を使い、微細・回転構造へ値を割り当てません。[Bentleyらの原論文](https://pubmed.ncbi.nlm.nih.gov/40184629/)・[NF二原子分子定数](https://webbook.nist.gov/cgi/cbook.cgi?ID=C13967061&Mask=1000)

SiH₄系には、ATcTの気相0 K形成量と、個別に帰属を確認した電離・光脱離・分光値を収録します。SiH₂の一重項と三重項は別の端点です。SiH₄の断熱電離値は親イオンの観測と最低イオン成分の帰属に対応します。元スペクトルや数表は収録せず、値と適用条件、個別の書誌情報を記録します。[Berkowitzらの光電離](https://doi.org/10.1063/1.452213)・[CoudertらのSiH₂の分光](https://doi.org/10.1039/D5CP00558B)

NF₃のν₂とSiH₄のν₄は、主同位体種の気相振動バンド原点を各1件収録します。個別の回転準位、同位体を指定した候補、状態人口にはその値を転用しません。原資料の帰属と適用範囲を記録します。[NF₃の分光](https://doi.org/10.1155/2013/813249)・[SiH₄の分光](https://doi.org/10.3390/molecules30091992)

Ar Iの4s個別準位、Ar IIの微細構造準位、O Iの³P₁・³P₀・¹S₀は、NIST SRD 108の準位表を出典とし、対応する気相基底準位からの差を使います。集約状態Ar(4s)やO(³P)には個別値を移しません。[Ar I準位表](https://physics.nist.gov/PhysRefData/Handbook/Tables/argontable5.htm)・[Ar II準位表](https://pml.nist.gov/PhysRefData/Handbook/Tables/argontable6.htm)・[O I準位表](https://physics.nist.gov/PhysRefData/Handbook/Tables/oxygentable5.htm)

CF₄、CF₃、COF₂の基底状態には、生成エンタルピーと独立した気相分光の存在根拠を記録します。収録したのは個別の状態同定と書誌情報です。[CF₄の赤外分光](https://doi.org/10.1080/00268976.2022.2093285)・[CF₃のマイクロ波分光](https://doi.org/10.1063/1.444279)・[COF₂のマイクロ波分光](https://doi.org/10.1016/0022-2852(74)90226-4)

量の定義と計算条件は[現行設計](core_design.md)を参照してください。[IUPACのEA](https://goldbook.iupac.org/terms/view/E01977)・[NISTの垂直／断熱IE](https://cccbdb.nist.gov/adiabaticx.asp)・[IUPACの出現エネルギー](https://goldbook.iupac.org/terms/view/A00421)・[NIST気相イオン熱化学規約](https://webbook.nist.gov/chemistry/ion/)

## 未収録資料と確認待ち

- LXCatの数値表は収録対象外です。公式方針は第三者による再配布を一般に認めず、利用者自身の取得と元データの引用を案内しています。[LXCat再配布方針](https://us.lxcat.net/instructions/redistribution.php)
- NIST SRD 107のASCII表と、CC BY-NC 4.0の2026年酸素workbookは参照のみです。NISTの公開SRDには固有の権利表示があります。[SRD 107](https://doi.org/10.18434/T4KK5C)・[酸素workbook](https://doi.org/10.60893/figshare.jpr.30850013)・[NISTのSRD方針](https://www.nist.gov/open/copyright-fair-use-and-licensing-statements-srd-data-software-and-technical-series-publications)
- CollisionDB D2984は解離性励起を扱い、束縛したH₂励起種や生成Hの準位別係数への同定を保留しています。D109777は元宣言と文献の対象が不一致で、数値採用を保留しています。[CollisionDB取得記録](../registry/sources/collisiondb_2026.yaml)

任意依存のRDKitはローカルのSMILES処理に使用します。ソフトウェアやバイナリを別途同梱する場合は、対象バージョンのBSD 3-Clauseと第三者noticeを適用します。[RDKit公式ライセンス](https://raw.githubusercontent.com/rdkit/rdkit/Release_2024_09_6/license.txt)
