# 02. 주요 MM·프랍 펌은 어디서 돈을 버는가 — 출처로 확인된 사실과 업계 추정의 분리

> 작성 기준일: 2026-11-19
> 범위: 질문 5. Jane Street, Citadel Securities, HRT, Jump, Virtu, Optiver, 그리고 비교용으로 Renaissance와 D.E. Shaw.
> 원칙 (사용자 규칙)
> - 사실을 주장할 때는 모두 출처 URL을 달았고, PDF는 쪽수까지 적었다. 출처가 없으면 **미확인**으로 적었다.
> - **[확인]** = 보도, 공시, 규제기관 결정문, 판결로 확인된 것. 이 문서에서는 작성자가 직접 열어 읽은 원문만 [확인]으로 표시했다.
> - **[추정]** = 업계 추정이나 논평. 출처가 있는 경우에만 적고 출처를 밝혔다.
> - **[해석]** = 작성자의 해석. 사실 주장이 아니다.
> - 법적 사안은 원문을 인용하고 쟁점만 정리했다. 위법 여부에 대한 결론은 내리지 않는다. 예를 들어 "Jane Street가 시장을 조작했다"는 문장은 쓰지 않고, "SEBI가 ~라고 주장·명령했다"로만 쓴다.
>
> **접근 환경상 제약**: 이 세션의 네트워크는 허용 목록 방식이다. 직접 열어 읽을 수 있었던 원문은 다음 다섯 곳뿐이다.
> 1. SEBI 임시명령 원문 (NSE 회람 첨부 PDF)
> 2. indiacorplaw 분석 글
> 3. Institutional Investor (2000)
> 4. Quartr의 D.E. Shaw 글
> 5. Jane Street 블로그와 팟캐스트 Signals and Threads
>
> 그 결과 Citadel Securities, HRT, Jump, Virtu, Optiver의 매출과 점유율 수치는 **대부분 미확인**이다. 차단된 URL은 §5.2에, 검색 결과 요약으로만 본 2차 보도(원문 미열람, 인용 불가)는 §5.3에 따로 모았다.
>
> **추가 (작성 중 갱신)**: hedgeweek 두 기사는 허용 목록이 보정된 뒤 직접 열어 읽었다(§5.1 7–8번). 두 기사의 수치는 모두 **익명 소스 또는 컨설팅사 분석을 인용한 2차 보도**이고, 회사가 공시하거나 확인한 수치가 아니다. 그래서 이 문서에서는 **[보도·익명소스]** 또는 **[업계 추정]**으로 따로 표시했다.

---

## 1. 펌별 요약표

| 펌 | 주요 수익원 | 근거 수준 | 핵심 수치 | 출처 |
|---|---|---|---|---|
| **Jane Street** | 인도 지수옵션 (BANKNIFTY/NIFTY). 기관 대량 ETF 블록 거래(호가창 밖에서 기초자산으로 헤지). 옵션 데스크 | **확인**: 인도 손익은 SEBI 결정문. ETF·옵션 사업이 있다는 사실은 자사 팟캐스트의 진술. **미확인**: 연간 글로벌 매출 | 2023-01-01~2025-03-31 NSE 전 부문 이익 **₹36,502.12 crore**. 이 중 지수옵션 이익 **₹43,289.33 crore**, 주식선물 **-₹7,208.23 crore**, 지수선물 **-₹190.81 crore**, 현물 **-₹288.17 crore**. SEBI가 "부당이득"으로 산정한 금액은 **₹4,843.58 crore** (21거래일) | SEBI 임시명령 p.10 Table 4, p.92 ¶31, p.94–95 Table 44 (PDF는 각 쪽수+2) |
| Jane Street (글로벌 매출) | 주식·ETF·채권·옵션·원자재·FX 유동성 공급. 장기 보유 포지션. 비상장 지분(Anthropic 등) 평가이익 | **보도·익명소스** (회사는 논평 거부) | **2025년 순트레이딩매출 $39.6bn**. 직원 약 3,500명. 2025 상반기·2분기 수치는 미확인 | hedgeweek 2026-04-27 (Reuters 인용) https://www.hedgeweek.com/jane-street-outpaces-rivals-with-record-40bn-trading-haul/ |
| **Citadel Securities** | 리테일 주문 홀세일 (PFOF), 옵션·주식 MM. 기관 대상 서비스로 확장 중 (보도) | 매출은 **보도·익명소스**. 사업 구조와 점유율은 **미확인** | **2025년 트레이딩매출 약 $12.2bn**. 미국 리테일 거래량 점유율은 미확인 | hedgeweek https://www.hedgeweek.com/jane-street-outpaces-rivals-with-record-40bn-trading-haul/, https://www.hedgeweek.com/non-bank-trading-firms-surge-as-jane-street-and-citadel-securities-drive-record-114bn-revenue-pool/ |
| **HRT** | 고빈도·저지연 MM / 프랍 (일반적 서술, 미확인) | 매출은 **보도·익명소스**. 사업 구조는 **미확인** | **2025년 트레이딩매출 약 $12.3bn** | hedgeweek https://www.hedgeweek.com/jane-street-outpaces-rivals-with-record-40bn-trading-haul/. HRT 블로그는 403 |
| **Jump** | 저지연 프랍·MM, 크립토 | **미확인** | 매출: 미확인 | jumptrading.com 접근 불가 |
| **Virtu** | 상장사. 부문은 Market Making과 Execution Services로 알려져 있음 | **미확인** (부문 구조와 "손실일" 통계 모두 원문 미열람) | 미확인 | ir.virtu.com 403, SEC EDGAR 차단 |
| **Optiver** | 옵션·ETF MM | **미확인** | 미확인 | optiver.com 접근 불가 |
| *(업계 전체)* 비은행 트레이딩 펌 | 2025년 매출 풀: 프랍·투자 $84.3bn(약 +60%), MM $30.2bn(+20%) | **업계 추정** (Crisil Coalition Greenwich 분석을 FT 경유로 인용) | 합계 **$114bn**(전년 대비 +45%). 은행 트레이딩 매출 $260.7bn(+13%). 2026년 1분기 Citadel Securities·Jane Street·HRT 합계 약 $27bn | hedgeweek 2026-06-03 https://www.hedgeweek.com/non-bank-trading-firms-surge-as-jane-street-and-citadel-securities-drive-record-114bn-revenue-pool/ |
| *(대조)* **Renaissance** | MM이 아님. 통계 모형 기반 단기 매매. 초기에는 선물 중심 | **확인** (2000년 기사) | Medallion: 1988.3 설정 이후 연 **35.6%**, 1990년대 10년 Sharpe **1.89**, 보수 **5% + 20%** (2000년 기사 기준) | Institutional Investor (2000-11-01) |
| *(대조)* **D.E. Shaw** | MM이 아님. 멀티전략 헤지펀드 (Composite, Oculus, Valence) | **확인** (2차 기업분석 글) | 1996년까지 연평균 **18%**. 1998년 자본 **$1.7bn → $460m**. 2025년 총자본 **$65bn 이상** | Quartr |

---

## 2. 펌별 상세

### 2.1 Jane Street

#### 확인된 사실 (규제기관 결정문과 자사 공개 자료)

**(a) 회사 개요** — SEBI 결정문이 Jane Street의 회사 소개와 소송 서류를 인용한 부분이다.
- "Jane Street employs more than 2,600 people in five offices across the United States, Europe, and Asia and trades in 45 countries … established in the year 2000." (SEBI 임시명령 p.3 ¶2 [PDF p.5])
- 인도에서 규제 대상이 된 4개 법인: JSI Investments Pvt Ltd (인도 법인, 2020년 12월 설립), JSI2 Investments Pvt Ltd (인도 법인, 2024년 9월 설립), Jane Street Singapore Pte Ltd (FPI), Jane Street Asia Trading Ltd (FPI, 홍콩) (p.98 ¶47 [PDF p.100])

**(b) 인도 NSE 손익 구조** — 검사 기간은 2023-01-01부터 2025-03-31까지다. SEBI 결정문 p.10 Table 4와 p.92 ¶31에서 가져왔다.

| 법인 | 총이익 | 지수옵션 | 지수선물 | 주식옵션 | 주식선물 | 현물 |
|---|---|---|---|---|---|---|
| Jane Street Asia Trading | 6,929.56 | 7,650.34 | (85.62) | 34.82 | (668.87) | (1.12) |
| JSI2 Investments | (168.67) | (168.67) | – | – | – | – |
| JSI Investments | 4,104.61 | 4,392.03 | 0.00 | (0.37) | 0.00 | (287.05) |
| Jane Street Singapore | 25,636.62 | 31,415.63 | (105.19) | 865.54 | (6,539.36) | 0.00 |
| **합계 (₹ crore)** | **36,502.12** | **43,289.33** | **(190.81)** | **899.99** | **(7,208.23)** | **(288.17)** |

- 같은 쪽 ¶14.3: "BANKNIFTY options alone contributed INR 17,319.26 Cr, amounting to 40% of the total Index Options profits."
- ¶48 (p.98 [PDF p.100]): 2025년 1~5월 JS 그룹 FPI의 월말 평균 주식 보유액은 **₹311 crore**, 인도 국채 평균 보유액은 **₹15,325 crore**였다. 결정문은 국채를 F&O 증거금 용도로 보고, 이 그룹의 사업을 다음과 같이 서술한다. "their business is to make profits from significant short-term High Frequency Trading (HFT) in the securities market." 이는 SEBI의 서술이다.
- ¶52 (p.99–100): 검사 기간 중 JS 그룹 FPI의 순이익은 **₹32,681 crore**.
- ¶13 (p.9)에서 SEBI는 다음과 같이 스스로 단서를 달았다. "trading profits by themselves are certainly not an indication of any illegality."

**(c) ETF 블록 유동성 공급 (자사 팟캐스트 진술)**
- Signals and Threads, "Trading at the Speed of… Chat?" (https://signalsandthreads.com/trading-at-the-speed-of-chat/). 연금 리밸런싱처럼 거래소 호가창으로는 소화하기 어려운 대량 ETF 주문을 예로 들며 다음과 같이 말한다. "we can do a good job of pricing the ETF off of the underlyings and then we can unwind the trade on our side … getting rid of that risk in the underlyings if there's not enough liquidity in the ETF."
  - 같은 대화에서 익명 거래소 MM이 호가를 넓히는 이유를 이렇게 설명한다. "people post less size … and they post wider spreads … to make up for the fact that occasionally someone comes who knows a lot more than the market maker does."
  - 반면 고객(client) 흐름에 대해서는 "I know exactly why you're coming to trade"라고 해서, 고객 흐름은 정보 비대칭이 작다고 본다.
- Signals and Threads, "Finding Signal in the Noise" (https://signalsandthreads.com/finding-signal-in-the-noise/). 주 정부 연금의 분기 리밸런싱을 예로 들며, 익명 거래소에서 수백만 달러 규모 흐름의 반대편에 서는 것이 "quite disconcerting"하다고 말한다. 그래서 상대방을 알고 사전에 협상하는 거래가 유용하다는 취지다.

**(d) 옵션 데스크**
- "Building Tools for Traders" (https://signalsandthreads.com/building-tools-for-traders/)에서 출연자 Ian Henry는 "Jane Street's options desk"에서 트레이더 도구를 만든다고 소개된다. 옵션 트레이더 한 명이 수백 개 관련 상품을 동시에 고려해야 한다고 설명한다(예: Nvidia 옵션).
- 이 자료에서 옵션 매출 규모는 **미확인**이다.

**(e) 속도·하드웨어**
- "Multicast and the Markets" (https://signalsandthreads.com/multicast-and-the-markets/), Brian Nigito: "Jane Street has always had a large and diversified business and for lots of our business, it's just not super relevant. But in the areas where message rates and competitiveness are a little extreme, it becomes a lot more efficient for us to take some of these programmable pieces of hardware and really specialize."
  - 즉 속도가 사업 전체가 아니라 일부 영역에서만 결정적이라는 자사 진술이다.
  - 같은 에피소드는 크립토가 공용 인터넷 위에서 "WebSockets, and JSON API"로 돌아가 도구 체계가 다르다고 언급한다.
- "Programmable Hardware" (https://signalsandthreads.com/programmable-hardware/): FPGA는 처리량을 "an order of magnitude or more" 높이고, 지연시간을 낮추며, 결정론적(deterministic) 동작을 준다고 말한다.

#### 보도 (익명 소스 인용, 회사 미확인) — hedgeweek, 2026-04-27, Reuters 인용 (https://www.hedgeweek.com/jane-street-outpaces-rivals-with-record-40bn-trading-haul/)
- "The high-frequency trading firm posted $39.6bn in net trading revenue, a record level…" 이 수치는 2025년 기준이다. 근거는 "according to a report by Reuters citing unnamed people familiar with the matter"이고, "Jane Street reportedly declined to comment."
- 사업 범위: "provides liquidity across equities, exchange-traded funds, bonds, options, commodities and currencies on trading venues worldwide. Its also runs a hedge-fund-like operation allowing it to take positions across markets and hold them for extended periods…"
- 매출에 MM 외 요소가 섞여 있음: "benefited from gains tied to stakes in private companies, including artificial intelligence group Anthropic." 따라서 $39.6bn을 순수 MM 수익으로 읽으면 안 된다. 다만 기사는 금액을 분해하지 않았다.
- 자본 구조: "The firm operates without external capital…" 직원 수는 "about 3,500"이다. SEBI 결정문이 Jane Street 측 자료를 인용해 적은 "more than 2,600"과 다르며, 시점 차이로 보인다.

#### 업계 추정 / 미확인
- 2025 상반기 $17.3bn, 2025년 2분기 $10.1bn: **미확인**. Bloomberg 보도로 알려져 있으나 원문 접근 불가다(§5.3).
- 2024년 매출: **미확인**. 사용자가 원문을 제공하면 채울 수 있다.
- 사업부별(ETF, 채권, 옵션, 주식) 매출 비중: **미확인**. 열어 본 어떤 자료에도 분해 수치가 없다.

#### Jane Street v. Millennium (미국 SDNY)
- [확인] 이 소송이 SEBI 조사의 출발점이었다는 사실은 SEBI 결정문이 직접 적고 있다. "Based on media reports titled 'Jane Street-Millennium Suit: 'Secret' Strategy Concerns India, Hearing Reveals' and 'Ex-Jane Street trader pillories claims he stole trade secrets', published during April 2024 wherein it was inter-alia mentioned that Jane Street and its associated entities alleged unauthorised use of their proprietary trading strategies in Indian options markets, SEBI initiated preliminary examination…" (p.2 ¶1 [PDF p.4])
- [확인] 결정문 각주 1은 소장 원문 위치를 "complaint filed by Jane Street Group LLC against Millenium Management LLC before the United States District Court Southern District of New York … https://www.sewkis.com/wp-content/uploads/Jane-Street_amended-complaint.pdf"로 적고 있다 (p.3). 이 소장 PDF 자체는 **접근 불가** (프록시 403)였다.
- **심리에서 드러난 구체 내용은 미확인이다.** 전략 세부, 이익 규모(예: "2023년 약 $1bn"), 퇴사 트레이더의 실명, 2024년 12월 합의 여부가 여기에 해당한다. 원 보도(Bloomberg 2024-04-19)는 접근 불가였다. 대체 보도는 검색 요약으로만 보았다(§5.3).

### 2.2 Citadel Securities

#### 확인된 사실 (공시·판결)
- 이번 세션에서 열어 읽은 1차 문서 중에는 Citadel Securities의 매출, PFOF 규모, 리테일 점유율을 담은 것이 **없다**.

#### 보도 (익명 소스 인용)
- "Citadel Securities recorded around $12.2bn in trading revenue in 2025…" (https://www.hedgeweek.com/jane-street-outpaces-rivals-with-record-40bn-trading-haul/, Reuters 인용)
- 사업 확장: "Some trading firms, notably Citadel Securities, have also begun expanding into more client-facing services…" (https://www.hedgeweek.com/non-bank-trading-firms-surge-as-jane-street-and-citadel-securities-drive-record-114bn-revenue-pool/, FT 인용)

#### 업계 추정 / 미확인
- 미국 리테일 주식 거래량 점유율: **미확인 (출처 접근 불가)**. 회사 홈페이지(citadelsecurities.com)와 SEC EDGAR(Rule 606/605 보고서)는 이 세션에서 접근할 수 없었다. 사용자가 자료를 제공하면 채울 수 있다.
- PFOF 지급액과 수취 규모: **미확인**.
- [업계 추정] 비은행 펌 전반에 대해 hedgeweek는 다음과 같이 적었다. "non-bank firms have expanded into retail flow, exchange-traded products and high-frequency market-making", "particularly in US Treasuries, ETFs and retail execution" (https://www.hedgeweek.com/non-bank-trading-firms-surge-as-jane-street-and-citadel-securities-drive-record-114bn-revenue-pool/, Crisil Coalition Greenwich·FT 인용). 이 서술은 Citadel Securities 개별 수치가 아니다.
- [해석, 사실 아님] 홀세일 MM의 수익원은 정보 비대칭이 작은 리테일 주문을 내부화(internalisation)하는 데 있다는 설명이 통상적이다. 이는 §2.1(c)에서 Jane Street가 말한 "고객 흐름은 왜 거래하는지 안다"는 논리와 같은 구조다. 다만 Citadel Securities에 대해 이를 확인한 출처는 없다.

### 2.3 HRT (Hudson River Trading)

- 확인된 사실 (공시·판결): **없음**. hudsonrivertrading.com과 HRT 블로그(hrtbeat)는 403으로 접근 불가였다.
- [보도·익명소스] "Hudson River Trading generated approximately $12.3bn over the same period"(2025) (https://www.hedgeweek.com/jane-street-outpaces-rivals-with-record-40bn-trading-haul/, Reuters 인용).
- [보도] 2026년 1분기 Citadel Securities·Jane Street·HRT 3사 합계 "around $27bn in trading revenue in the first quarter alone" (https://www.hedgeweek.com/non-bank-trading-firms-surge-as-jane-street-and-citadel-securities-drive-record-114bn-revenue-pool/).
- 시장점유율과 전략 비중(속도·저지연 의존도): **미확인**. HRT 블로그 원문을 사용자가 제공하면 채울 수 있다.

### 2.4 Jump Trading

- 확인된 사실: **없음**. jumptrading.com은 접근 불가였다.
- 매출, 크립토 사업 규모, 관련 규제 사건: **미확인**. 이 세션에서는 CFTC·SEC 문서에도 접근할 수 없었다.

### 2.5 Virtu Financial (상장사)

- 확인된 사실: **없음**. Virtu는 상장사라 10-K와 투자자 자료가 있어 원칙적으로 가장 검증하기 쉬운 펌이다. 그러나 ir.virtu.com(403), SEC EDGAR(연락처 User-Agent 요구로 차단), virtu.com(접근 불가) 모두 열 수 없었다.
- 다음 항목은 모두 **미확인 (출처 접근 불가: https://ir.virtu.com/, https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK=0001592386&type=10-K)**.
  - 부문 구조(Market Making / Execution Services)와 부문별 매출·조정순트레이딩수익
  - IPO 서류에 실린 것으로 널리 알려진 "손실 거래일 수" 통계
  - 연도별 매출
- 후속 검증 방법: 사용자가 직접 EDGAR에 접속해 최근 10-K의 "Segment Information" 주석과 S-1(2014)의 거래일별 손익 분포를 확인한다.

### 2.6 Optiver

- 확인된 사실: **없음**. optiver.com은 접근 불가였다.
- 연간 매출, 옵션·ETF 비중: **미확인**.

### 2.6a 업계 전체 매출 풀 — [업계 추정]

출처: hedgeweek, 2026-06-03, FT 보도의 Crisil Coalition Greenwich 분석 인용. https://www.hedgeweek.com/non-bank-trading-firms-surge-as-jane-street-and-citadel-securities-drive-record-114bn-revenue-pool/
- "revenues across non-bank trading firms rose 45% year-on-year in 2025"
- 합계 $114bn의 내역: 프랍·투자 활동 "climbed almost 60% to $84.3bn", "market-making revenues increased 20% to $30.2bn"
- 은행 트레이딩 매출: "$260.7bn in 2025, up 13%"
- 유보: "it is unclear whether current revenue levels represent a structural shift or a cyclical peak"
- [해석] 이 분류가 맞다면, 이른바 "MM 펌"의 2025년 매출 가운데 순수 MM은 약 1/4($30.2bn / $114bn)이다. 나머지는 자기자본 포지션과 투자 수익이다. 이 비율은 컨설팅사 추정이며, 펌별 분해는 미확인이다.

### 2.7 (대조) Renaissance Technologies — MM이 아니라 통계적 예측

**확인된 사실** — 모두 Institutional Investor, "The Secret World of Jim Simons" (2000-11-01, https://www.institutionalinvestor.com/article/b151340bp779jn/the-secret-world-of-jim-simons)에서 가져왔다. 2000년 시점의 기사다.
- "Since its inception in March 1988, Simons' flagship $3.3 billion Medallion fund, has amassed annual returns of 35.6 percent…"
- 보수: "a management fee of a stunning 5 percent of assets, in addition to … 20 percent of profits."
- "Medallion, which closed to new investors in 1993, is focused chiefly on commodities and futures trading."
- 수익원의 성격: "Renaissance essentially attempts to predict the future movement of financial instruments, within a specific time frame, using statistical models… At Renaissance they're called 'signals.'" 그리고 "The firm made money by simply arbitraging Treasury bills against Treasury futures contracts" (초기 시기).
- 10년 Sharpe 1.89 (1990년대).
- 시사점 [해석]: 2000년 시점 기사가 묘사하는 수익원은 신호 기반의 방향성 예측과 차익거래다. 호가를 제시하고 스프레드를 받는 MM 사업이라는 기술은 없다.

### 2.8 (대조) D.E. Shaw — 멀티전략 헤지펀드

**확인된 사실** — 2차 기업분석 글이다. Quartr, "D. E. Shaw & Co: Inside the Quiet Giant of Quant Finance" (https://quartr.com/insights/company-research/de-shaw-and-co-inside-the-quiet-giant-of-quant-finance).
- 1988년 $28m로 출발했다. "By 1996, D. E. Shaw had delivered average annual returns of 18% since inception … On many trading days, D. E. Shaw's trades accounted for as much as 5% of total volume on the New York Stock Exchange."
- 1998년 위기: "Its fixed-income arbitrage positions … took heavy losses … capital had dropped from $1.7 billion to just $460 million."
- 펀드 구성: Composite (2001), Oculus (2004, 매크로), Valence (2015, 장기·크레딧). "managing over $65 billion in aggregate capital as of 2025."
- "The firm has never disclosed the specifics of its holdings or detailed how its strategies work."
- 시사점 [해석]: 외부 투자자 자본을 받는 헤지펀드 구조이고, 수익원은 전략 포트폴리오 수익률이다. 호가 제시나 주문흐름 사업이라는 서술은 없다.

---

## 3. Jane Street–SEBI 사건 심층 (1차 문서 기준)

**1차 문서**: SEBI 임시명령(ex-parte interim order) No. WTM/AN/MRD/MRD-SEC-3/31516/2025-26, 2025-07-03. 서명자는 Ananth Narayan G. (Whole Time Member)이다. NSE 회람 NSE/INVG/68921 (Circular Ref. 488/2025)에 첨부되어 있다. https://archives.nseindia.com/content/circulars/INVG68921.pdf
- 쪽수 표기: 결정문 하단의 "Page N of 105"를 기준으로 했다. PDF 파일의 쪽 번호는 N+2다(앞의 2쪽이 NSE 회람).
- 아래 내용은 모두 **SEBI가 주장·판단한 내용(prima facie)**이다. 최종 판단이 아니다.

### 3.1 경위 (p.2–3 Table 1)

| 일자 | 사건 (결정문 기재) |
|---|---|
| 2024-04 | Millennium 소송 보도를 근거로 SEBI 분석 착수 |
| 2024-07-23 | NSE에 JS 그룹 매매 검토 요청 |
| 2024-08-20 / 08-30 | SEBI와 JS 면담. JS가 서면 소명 제출 |
| 2024-11-13 | NSE 검토보고서 제출 |
| 2025-02-04 | 조사팀이 "prima facie … in violation of SEBI PFUTP regulations"라고 판단 |
| 2025-02-06 | NSE가 경고서한(caution letter) 발송 |
| 2025-02-06 / 02-21 | JS 회신 |
| 2025-05-15 | 경고 이후에도 대규모 포지션이 계속됐다고 SEBI가 기술 |
| 2025-07-03 | 임시명령 |

### 3.2 SEBI가 설명한 구조적 배경 (C절)

- 만기일 옵션 시장과 기초자산 시장의 규모 비대칭. 2024-01-17 BANKNIFTY 만기일 기준 (p.7 Table 2):
  - 12개 구성종목 현물 거래대금: ₹29,225 crore
  - 구성종목 선물: ₹43,589 crore
  - BANKNIFTY 지수선물: ₹32,607 crore
  - BANKNIFTY 옵션 델타환산 거래대금: **₹1,03,17,127 crore**
  - 옵션 시장은 현물의 **353배**, 현물·선물 합계의 **98배**
- 참여자 수 (p.7–8 Table 3): 상위 3개 구성종목 현물 4,675명, 지수선물 26,593명, 지수옵션 **16,15,011명**.
- SEBI가 제시한 메커니즘 가설 (p.8–9 ¶12): "by aggressively influencing the underlying cash and futures market with significant volumes (relative to those markets), a group of entities … can influence and manipulate the index levels. This in turn can allow them to put on significantly larger and profitable positions in the highly liquid index options market by misleading and enticing large number of smaller individual traders. It could also be used to engineer the closing of the market on expiry day…"

### 3.3 대상일 선정 방법 (D절, p.9–11)

1. 전 부문 손익을 매핑한다(Table 4).
2. 지수옵션을 지수별로 분해한다. BANKNIFTY가 40%였다.
3. BANKNIFTY 옵션 일별 이익 상위 30일 가운데 만기일 19일을 고른다.
4. 분 단위 분석으로 17일을 남기고, 예비검토일 1일을 더해 **18일**로 확정한다.
- 18일 중 15일은 "Intra-day Index Manipulation", 3일은 "Extended Marking the Close"로 분류했다. 검사 기간 이후인 2025년 5월 NIFTY 3일은 따로 추가해 **총 21일**이다 (p.11 ¶14.7, p.96 ¶42).

### 3.4 전략 A — "Intra-day Index Manipulation" (표본일 2024-01-17, BANKNIFTY 만기)

**SEBI가 정리한 흐름 (p.12–13 Table 6)**

| 구간 | JS 행위 (SEBI 기재) | SEBI가 주장한 효과 |
|---|---|---|
| Patch I 09:15–11:46:59 | 하락장에서 BANKNIFTY 구성종목 현물·선물을 **₹4,370.03 crore** 순매수. 같은 시간 지수옵션으로 콜 매도·풋 매수를 해 약 **₹32,114.96 crore**의 약세 포지션을 구축 | 지수가 지지·상승하면서 풋은 싸지고 콜은 비싸진다. 옵션 약세 포지션은 현물·선물 롱의 **7.3배** |
| Patch II 11:49–15:30 | Patch I에서 산 현물·선물을 거의 전량 공격적으로 매도. 매도액은 현물 **₹1,858.78 crore**, 선물 **₹3,513.34 crore** (p.35 ¶15.35) | 지수 하락. 현물·선물에서는 손실, 옵션(롱풋·숏콜)에서는 이익 |

**SEBI 인용 수치**
- Patch I 현물 순매수 ₹1,851.57 crore, 선물 ₹2,518.46 crore. 2위 참여자는 각각 ₹1,042.93 crore, ₹159.15 crore. 주요 종목에서 JS 그룹이 시장 거래대금의 15–25%를 차지했다 (p.17 ¶15.6).
- 가격영향 분해 (LTP 기준, 지수 가중치 반영): JS **+49,047.61**, 그 외 전원 **−49,194.31** (p.22 ¶15.12).
- 개장 8분(09:15–09:22:59) 동안 상위 6종목을 ₹572 crore 매수했다. 같은 시간 옵션으로 쌓은 약세 노출은 **₹8,751 crore**로, 15배가 넘는다 (p.27 ¶15.25). 이 사이 지수는 46,573.93에서 47,176.97로 600pt 넘게 올랐다 (p.23 ¶15.16).
- 델타: 개장 −₹7,311.19 crore에서 11:47에 **−₹39,426.15 crore**가 됐다 (p.31–32 ¶15.27).
- 당일 GTV ₹10,657.33 crore. 전일 ₹2,150.18 crore의 약 5배, 익일 ₹2,583.10 crore의 약 4배다 (p.44 Table 25, ¶15.46).
- 당일 현물·선물 손실 **₹61.6 crore** (p.46 ¶15.50.1). 당일 BANKNIFTY 옵션 이익 **₹734.93 crore** (p.11 ¶14.7).
- 15일 합계: BANKNIFTY 옵션 이익 **₹3,914 crore**, 현물·선물 일중 손실 **₹199.7 crore** (p.50–51 ¶15.56).

**핵심 인용**
- p.46 ¶15.50.1: "There is no economic rationale possible to justify such trading activity on a standalone basis; in fact, given the sheer sizes, manner of trading and transaction costs involved, such activities would invariably tend to end with net trading losses."
- p.46 ¶15.50.2: 일중 반대매매는 인도 법인 JSI Investments가 수행했다. "SEBI (Foreign Portfolio Investors) Regulations, 2019 do not allow FPIs to undertake intraday trades."
  - 관련 서술로 p.92 ¶30: "the incorporation of the aforesaid company in India enabled the JS Group to get around the regulatory prohibition…"
- p.47 ¶15.50.5: "This was a classic case of 'marking-the-close', where an entity with huge options exposures that are expiring shortly, is moving the underlying market aggressively in its favour."

**JS 측 소명 (결정문에 인용된 것만)**
- p.48 ¶15.51.4: "JS, vide its letter to SEBI dated August 30, 2024, has suggested that these trades were to 'remove unwanted delta' or to 'manage overall delta'."
- SEBI는 바로 이어 "These bland statements do not take away from any of the arguments made above"라고 배척했다.

### 3.5 전략 B — "Extended Marking the Close" (표본일 2024-07-10, BANKNIFTY 만기)

- SEBI의 정의 (p.51 ¶16.3): "an entity aggressively places large buy or sell orders in the final moments of a trading session, with the specific intent of influencing the closing price of a security or index to its advantage."
- 구조 (p.51 Table 26):
  - 09:15–14:30 저거래·비방향성
  - 14:30–15:30 지수옵션 포지션을 보유한 상태에서 구성종목 현물·선물과 지수선물로 공격적·방향성 개입
  - 15:30 종가 형성
- 금액 (p.56 ¶16.12): 마지막 구간 매도는 현물 ₹163.33 crore, 종목선물 ₹1,900.57 crore, 지수선물 ₹735.86 crore로 **합계 약 ₹2,800 crore**. SEBI는 이것이 종가 시점의 옵션 약세 포지션 **₹44,153.87 crore**에 이익이 되도록 하려는 의도라고 주장했다.
- 정산 메커니즘 (p.56 ¶16.13): "the Volume Weighted Average Price in the last 30 minutes of trading (between 15:00 and 15:30) is used to compute settlement prices." 같은 문단에 따르면 마지막 60분 종목선물 점유율이 35%를 넘었다.
- 델타 (p.66 ¶16.31): 14:30 −₹27,225.22 crore에서 마감 시 −₹44,153.87 crore로, 1시간 안에 ₹16,928.64 crore 변동.
- p.56 ¶16.14: "these trades were not incidental or part of a normal liquidity-providing role." MM 업무로 볼 수 있느냐는 쟁점에 대한 SEBI의 입장이다.
- 대상일 3일: 2023-10-04, 2024-05-08, 2024-07-10 (p.90 ¶24). 3일 옵션 이익 **₹560 crore** (p.67–68 ¶16.35).

### 3.6 경고서한 이후 — 2025-05-15 NIFTY 만기 (F절)

- NSE 경고서한(2025-02-06) 인용 (p.68–69 ¶17.1): "…concurrent act of taking and then reducing positions in the top constituents of the index through cash market / derivatives over a short period, to artificially influence the price of the index … it is advised to exercise caution and refrain from taking large open positions (delta)."
- 13:26–15:30 종목선물 매수 **₹4,910.96 crore**. 종목별 시장 점유율은 HDFCBANK 22.69%, RELIANCE 21.93% 등 (p.75 ¶17.9).
- 델타: 개장 −₹17,125.75 crore에서 마감 **+₹38,297.01 crore**로, 약 ₹55,422.76 crore 변동 (p.86 ¶17.24).
- p.84 ¶17.18: "this activity was absent in the cash segment, giving an impression of complying with regulatory caution … but actually manipulating the market through futures segment." SEBI의 주장이다.
- 2025년 5월 3일(5/8, 5/15, 5/22) NIFTY 옵션 이익 **₹370 crore** (p.87 ¶17.29).

### 3.7 SEBI가 적용한 법조와 증명 기준

- **적용 조항** (p.87 ¶18, p.94 ¶36): SEBI Act s.12A(a)(b)(c). PFUTP Regulations 2003 reg. 3(a)–(d), 4(1), 4(2)(a), 4(2)(e).
  - 4(2)(a): "knowingly indulging in an act which creates false or misleading appearance of trading"
  - 4(2)(e): "…influencing or manipulating the reference price or bench mark price of any securities" (p.88)
- **증명 기준 표현**: 본문은 일관되게 "by preponderance of probability"(개연성 우위)를 쓴다. 예: p.47 ¶15.51, p.89 ¶22, p.90 ¶26. 결론부 p.91 ¶28은 "The immediate and proximate facts and circumstances, thus, lead to a logical and necessary inference that the large and aggressive trades were not executed in a vacuum or for ordinary hedging or arbitrage operations…"라고 적는다.
- **인용 판례**:
  - SEBI v. Rakhi Trading (SC, 2018-02-08). p.93 ¶32: "if one party consistently makes loss and that too in preplanned and rapid reverse trades, it is not genuine; it is an unfair trade practice." p.93 ¶34: "If the factum of manipulation is established, it will necessarily follow that the investors in the market have been induced … no further proof in this regard is required."
  - SEBI는 이를 근거로 유인(inducement)을 따로 입증할 필요가 없다고 했다 (p.93–94 ¶35).
- **부당이득 산정** (p.94–96 Table 44, ¶37–40):
  - 대상 21일의 **지수옵션 이익**을 합산해 **₹4,843,57,70,168 (약 ₹4,843.58 crore)**으로 정했다.
  - 현물·선물 손실은 상계하지 않았다. 근거는 Immix Trade v. SEBI (SAT, 2023-11-10) 인용과 다음 문장이다. "I find no reason to set off the losses made by the JS Group in the cash/futures market" (p.96 ¶40).
  - 구성: 일중전략 15일 ₹3,914 crore, EMTC 3일 ₹560 crore, 2025년 5월 3일 ₹370 crore. 반올림 합계는 ₹4,844 crore로, Table 44 합계와 일치한다.
- **임시조치 요건** (p.96 ¶41): "existence of a prima facie case, irreparable injury … and a balance of convenience."
- **합법 전략과의 경계에 대한 SEBI 서술** (p.97–98 ¶46): "Making profits while dealing in securities by itself is certainly not objectionable. Genuine trading strategies such as arbitraging or hedging or directional positioning are well accepted and cannot be found fault with. What is, however, unacceptable and illegal, is the use of egregious manipulative practices…"
- **주문 내용** (p.103–105 ¶62):
  - 62.1: ₹4,843.58 crore를 에스크로에 예치 (impound, joint and several)
  - 62.2: 증권시장 접근 금지
  - 62.10: 미결제 파생 포지션은 3개월 또는 만기 중 이른 시점까지 청산 허용
  - 62.11: 62.1을 이행하면 62.2 등 일부 제한이 해제됨
  - 62.12: cease and desist
  - ¶63: 21일 내 회신 가능 (p.105)

### 3.8 쟁점 정리 (결론 없음)

1. **헤지·델타관리인가, 가격 형성 개입인가.** JS는 "remove unwanted delta"를 주장했고(결정문 인용), SEBI는 "no economic rationale"이라고 보았다. 같은 매매가 두 가지로 설명될 수 있다는 점이 핵심 쟁점이다.
2. **의도(intention)의 요건과 증명.** indiacorplaw 분석이 지적하는 문제는 다음과 같다(아래 3.9).
   - reg. 2(1)(c)의 "fraud"는 의도가 필요 없다 (Kanaiyalal Patel).
   - reg. 4(2)(a)는 "knowingly"를 요구한다 (2018 개정, Rakhi Trading 동의의견의 "deliberate").
3. **정황증거만으로 충분한가.** SEBI는 매매 패턴(타이밍, 거래량 비중, LTP 분석, 반복성)을 근거로 삼았다. Balram Garg 판례가 요구한 "매매 패턴 이상의 정황"이 필요한지가 쟁점이다(indiacorplaw 인용).
4. **이득 산정에서 비용 상계 여부.** 현물·선물 손실 ₹201 crore를 상계하지 않았다.
5. **법인 구조.** 인도 법인이 FPI의 일중 현물매매 금지를 우회했는지가 문제다. SEBI는 "without specifically flouting the FPI Regulations"라고 표현했다.
6. **"유동성 공급" 역할과의 관계.** p.56 ¶16.14가 다루는 부분이다.

### 3.9 indiacorplaw 분석 (2차, 논평) — [확인: 글의 내용] / [추정: 저자 견해]

출처: Bhavin Patel & Natasha Aggarwal (TrustBridge Rule of Law Foundation), "Proof of Market Manipulation: The Jane Street Case", 2025-10-10. https://indiacorplaw.in/2025/10/10/proof-of-market-manipulation-the-jane-street-case/

- 사후 경과 (글에 기재된 사실):
  - "Jane Street paid this amount into an escrow account on 14 July 2025 and resumed trading in the Indian securities market on 21 July 2025."
  - "Jane Street has filed an appeal against this interim order, and the next date of hearing at the Securities Appellate Tribunal is 18 November 2025 (SAT order in Appeal 413/2025 dated 9 September 2025)."
  - "Earlier news reports indicated that Jane Street may argue that its actions constituted legitimate arbitrage and not market manipulation."
- 핵심 논지 (저자 견해):
  - "the law itself does not distinguish between arbitrage and manipulation."
  - SEBI는 의도를 기준으로 구분하는 것으로 보인다.
  - reg. 2(1)(c)는 의도 불요(Kanaiyalal Baldev Patel, 2017), reg. 4(2)(a)는 "knowingly"를 요구(2018 개정, Rakhi Trading 동의의견)한다. 이 비일관성이 "troubling"하다고 본다.
- 증거 기준: Kishore R. Ajmera(정황증거로 추론 가능), Chintalapati Srinivasa Raju("foundational facts"), Balram Garg(내부자거래에서 매매 패턴 외 정황 필요)를 소개한다. 또 2021년 RIL 사건에서 판정관(AO)이 쓴 추가 요소 세 가지를 비교 기준으로 든다: 12개 대리인 사용, 헤지 필요 대비 과도한 포지션, 헤지 정책 부재.
- 결론부 (저자 견해): 임시명령은 "well-written, well-structured"하다. 그러나 "it provides no clarity on the difference between arbitrage and manipulation"라고 비판한다.
- 2025-11-18 SAT 심리 이후의 경과와 SEBI 최종명령 여부: **미확인**. 이 세션에서 접근 가능한 원문이 없었다.

---

## 4. Binance→빗썸 교차거래소 MM에 주는 시사점 — **[해석]**

> 아래는 작성자의 해석이다. 위 §2–3의 사실을 근거로 하지만 사실 주장은 아니다.

| 엣지 유형 | 대형 펌의 근거 (위 출처) | 소형 참여자 재현 가능성 [해석] |
|---|---|---|
| **속도 (FPGA, 코로케이션, 멀티캐스트)** | Jane Street는 속도가 "areas where message rates and competitiveness are a little extreme"에서만 결정적이라고 말한다. 크립토는 "WebSockets, and JSON API" 기반이라 도구 체계가 다르다고도 했다 (Multicast and the Markets) | **부분 가능.** 빗썸은 공용 인터넷 API 기반이라 FPGA·마이크로초 경쟁의 의미가 작다. 대신 서울 근접 서버, 웹소켓 파싱 최적화, Binance 피드 수신 경로가 현실적인 경쟁 축이다. 다만 Binance 신호가 빗썸에 반영되는 지연을 노리는 경쟁자 역시 같은 공개 피드를 본다 |
| **흐름 내부화 (client/retail flow)** | Jane Street: 고객 흐름은 "I know exactly why you're coming to trade". Citadel Securities의 리테일 홀세일 수치는 미확인 | **불가.** 빗썸에는 브로커 주문을 홀세일로 받는 구조가 없다. 소형 참여자는 익명 호가창에서 역선택("someone … knows a lot more than the market maker")에 그대로 노출된다 |
| **교차시장 헤지 (ETF↔기초자산, 현물↔파생)** | Jane Street는 ETF 블록을 "pricing the ETF off of the underlyings"한 뒤 기초자산으로 헤지한다 | **부분 가능, 비용 큼.** Binance 무기한선물로 빗썸 재고를 헤지하는 구조는 가능하다. 그러나 KRW↔USDT 자금 이동과 재조정 비용, 그리고 김치 프리미엄 변동이 헤지 오차가 된다 |
| **재고·자본 용량** | SEBI 결정문: JS FPI가 평균 ₹15,325 crore의 국채를 증거금으로 보유 (p.98 ¶48) | **불가에 가까움.** 대규모 재고 노출을 견디는 능력은 자본의 함수다 |

**규제 쟁점과 직접 연결되는 점 [해석]**
- SEBI 사건의 핵심 구조는 이렇다. **유동성이 얕은 시장(현물·선물)에서 공격적으로 매매해 기준가격(지수, 종가 VWAP)을 움직이고, 유동성이 깊은 연계시장(옵션)에서 큰 반대 포지션으로 이익을 낸다.** SEBI가 주장한 이 구조는 결정문 p.8–9 ¶12, p.91 ¶28에 있다.
- 교차거래소 전략에서 "빗썸에서 매매해 가격을 움직이고 Binance 포지션으로 이익을 얻는" 형태가 생기면 이 사건과 같은 쟁점(헤지인가 가격 형성 개입인가)이 제기될 수 있다. 반대 방향 매매도 마찬가지다.
- 반대로 SEBI 스스로도 "Genuine trading strategies such as arbitraging or hedging … are well accepted" (p.97–98 ¶46)라고 적었다. 따라서 **방향(정보는 Binance→빗썸으로 흐르고, 빗썸 가격을 움직여 다른 포지션에서 이익을 취하지 않음)과 규모(해당 시장 거래대금 대비 비중)를 기록으로 남기는 것**이 실무상 쟁점 대응 자료가 된다.
- 국내법(가상자산이용자보호법 등) 적용에 대한 판단은 이 문서의 범위 밖이다.

---

## 5. 참고문헌

### 5.1 직접 열어 읽은 자료 (이 문서의 [확인] 근거)

1. SEBI, Interim Order WTM/AN/MRD/MRD-SEC-3/31516/2025-26, "In the matter of Index manipulation by Jane Street Group", 2025-07-03 (105쪽). NSE Circular NSE/INVG/68921에 첨부. https://archives.nseindia.com/content/circulars/INVG68921.pdf (로컬 사본: `/tmp/claude-0/-home-user-270-Valuation/39a33c33-3d5d-5a30-bcfd-76c26065d849/scratchpad/mm_sources/firms/sebi.pdf`, 변환본 `sebi.txt`)
2. Bhavin Patel & Natasha Aggarwal, "Proof of Market Manipulation: The Jane Street Case", IndiaCorpLaw, 2025-10-10. https://indiacorplaw.in/2025/10/10/proof-of-market-manipulation-the-jane-street-case/
3. Institutional Investor, "The Secret World of Jim Simons", 2000-11-01. https://www.institutionalinvestor.com/article/b151340bp779jn/the-secret-world-of-jim-simons
4. Quartr, "D. E. Shaw & Co: Inside the Quiet Giant of Quant Finance". https://quartr.com/insights/company-research/de-shaw-and-co-inside-the-quiet-giant-of-quant-finance
5. Signals and Threads (Jane Street 팟캐스트)
   - "Trading at the Speed of… Chat?" https://signalsandthreads.com/trading-at-the-speed-of-chat/
   - "Finding Signal in the Noise: Machine Learning and the Markets" https://signalsandthreads.com/finding-signal-in-the-noise/
   - "Multicast and the Markets" https://signalsandthreads.com/multicast-and-the-markets/
   - "Programmable Hardware" https://signalsandthreads.com/programmable-hardware/
   - "Building Tools for Traders" https://signalsandthreads.com/building-tools-for-traders/
6. Jane Street Tech Blog (목록 페이지만 확인했고 매출 관련 내용은 없음). https://blog.janestreet.com/
7. Hedgeweek, "Jane Street outpaces rivals with record $40bn trading haul", 2026-04-27 (Reuters 익명 소스 인용). https://www.hedgeweek.com/jane-street-outpaces-rivals-with-record-40bn-trading-haul/
8. Hedgeweek, "Non-bank trading firms surge as Jane Street and Citadel Securities drive record $114bn revenue pool", 2026-06-03 (FT 및 Crisil Coalition Greenwich 인용). https://www.hedgeweek.com/non-bank-trading-firms-surge-as-jane-street-and-citadel-securities-drive-record-114bn-revenue-pool/

### 5.2 접근 불가 URL (우회하지 않음)

| URL | 상태 | 영향 |
|---|---|---|
| https://www.bloomberg.com/news/articles/2024-04-19/jane-street-s-secret-strategy-concerns-india-hearing-reveals | 403 (지정 차단) | Millennium 심리 세부 내용 미확인 |
| https://www.hudsonrivertrading.com/hrtbeat/ | 403 | HRT 미확인 |
| https://ir.virtu.com/ | 403 | Virtu 부문 구조 미확인 |
| https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK=0001592386&type=10-K | 차단 (연락처 User-Agent 요구) | Virtu 10-K/S-1 미확인 |
| https://www.sewkis.com/wp-content/uploads/Jane-Street_amended-complaint.pdf | 프록시 403 | JS v. Millennium 수정 소장 원문 미열람 (SEBI 결정문 각주 1이 인용) |
| https://www.sebi.gov.in/ , https://www.janestreet.com/ , https://www.citadelsecurities.com/ , https://www.virtu.com/ , https://www.optiver.com/ , https://www.jumptrading.com/ , https://www.courtlistener.com/ , https://www.finra.org/ , https://www.cftc.gov/ , https://www.reuters.com/ | 세션 네트워크 허용 목록 밖 | 각 펌의 1차 공시와 법원 문서 미확인 |

### 5.3 검색 결과 요약으로만 본 2차 보도 (원문 미열람, **인용 불가**, 후속 검증용)

아래 URL에서는 원문을 열지 못했다(허용 목록 밖). 다음 수치는 이 문서에서 **사실로 사용하지 않았다.** 검증 후보로만 남긴다.
- JS 2025 순트레이딩매출 $39.6bn: Reuters 원문 경유본은 미열람이다. 같은 수치를 hedgeweek에서 직접 확인했다(§5.1 7번). https://www.marketscreener.com/news/jane-street-s-40-billion-trading-haul-tops-rivals-sources-say-ce7f59dfdf8ff52d
- JS 2025년 2분기 $10.1bn: https://www.capitalbrief.com/briefing/jane-street-beats-jpmorgan-and-goldman-sachs-with-record-usd101b-trading-haul-c33c4177-7f0a-409d-8177-8c1eea66239e/
- JS v. Millennium 보도 및 2024년 12월 합의 보도: https://www.businesstoday.in/markets/global-markets/story/a-wall-street-giant-is-taking-rival-to-court-for-stealing-trading-secrets-involving-india-426268-2024-04-21 , https://www.claimsjournal.com/news/national/2024/12/09/327780.htm
- SEBI 명령에 대한 JS 입장 보도: https://www.businesstoday.in/markets/stocks/story/committed-to-operating-in-compliance-what-jane-street-says-on-sebi-stock-market-ban-483060-2025-07-04 , https://www.business-standard.com/amp/markets/news/jane-street-to-argue-that-retail-demand-drove-its-india-options-trades-125072900196_1.html
