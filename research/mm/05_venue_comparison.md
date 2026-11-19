> **출처 신뢰도 주의 (2026-11-19 추가)**: 이 문서의 Binance 공지 일부(Spot LP 2026-11-16 개편, USDⓈ-M 수수료 FAQ, Futures MM FAQ 등)는 공개 HTML 페이지가 AWS WAF에 막혀서, Binance 웹사이트의 내부 CMS JSON 엔드포인트(`/bapi/composite/v1/public/cms/...`)로 받은 것이에요. 이 경로는 사실상 봇 차단을 우회하는 방식이라 이후로는 사용하지 않기로 했어요. 해당 수치는 **사용자가 공식 페이지에서 직접 확인하기 전까지 '확인 필요'**로 취급해요. 미확인 상태인 USDC-M 2025-09-11 공지(articleCode 3fb551d5630f446483c4aa1346513406)도 사용자 확인이 필요해요.

# 05. 해외 거래소 비교: 수수료, MM/LP 프로그램, 호가 스프레드, 손익분기 (Binance · Bybit · OKX)

작성일: 2026-11-19 · 관련 문서: `00_summary.md`, `01_strategy_components.md`, `03_bithumb_feasibility.md`(손익분기식 §3), `04_experiments.md`

원칙
- 사실 주장마다 출처 번호 `[Vx]`를 달았다. 출처 목록은 §9에 있다. 수수료와 프로그램 페이지의 접속일은 모두 **2026-11-19**다.
- 출처 등급은 **공식**(거래소 공지, 도움말, API 문서), **뉴스**, **제3자**(데이터 벤더 문서 등) 세 가지로 나눴다. 제3자 자료는 신뢰도를 낮게 본다.
- 출처가 없거나 원문을 열지 못한 내용은 **미확인**으로 표시했다. 웹 검색 결과 요약에만 나온 내용은 근거로 쓰지 않았다.
- 공개 시세 엔드포인트와 공개 문서만 사용했다. 요청은 HTTP 55회와 웹 검색 5회로 모두 60회였다(한도 소진). 주문 API, private API, 인증 호출은 한 번도 하지 않았다. 차단된 페이지는 우회하지 않았고 아카이브나 미러도 쓰지 않았다(§9.2).
- 원본 저장 위치: `/tmp/claude-0/-home-user-270-Valuation/39a33c33-3d5d-5a30-bcfd-76c26065d849/scratchpad/mm_sources/venues/`(요청 로그는 `_log.txt`, 스프레드 계산 결과는 `_spreads_computed.json`)
- 「해석」이라고 표시한 부분은 분석자의 추론이다.

**범위 변경.** 사용자 결정에 따라 한국 원화 거래소(업비트, 빗썸, 코인원, 코빗)는 이 문서에서 **제외**했다. 작업 초반에 받아 둔 원화 거래소 호가 스냅샷과 뉴스 원본은 위 폴더에 남아 있지만 분석에는 쓰지 않았다. 원화 쪽 수수료와 제약은 `03`을 본다.

---

## 0. 한눈에 보기

| 질문 | 답 (근거) |
|---|---|
| 바이낸스에 MM 프로그램이 있나? | **있다.** (1) Futures Market Maker Program: 마이너스 메이커 수수료를 주며, 신청 기준은 30일 거래량이 현물 1,000 BTC 초과 또는 선물 3,000 BTC 초과다 [V2][V1]. (2) Spot Liquidity Provider Program: 2026-11-16부터 2027-02-07까지 프로모션 기간이고, Tier 1–4의 메이커 수수료는 0 / −0.4 / −0.6 / −0.8bp다 [V3]. (3) Fiat LP Program: 법정화폐 마켓 전용이며 메이커 리베이트는 −0.4 ~ −1.5bp다 [V5] |
| 바이낸스 일반 VIP 수수료 | **미확인.** www.binance.com/en/fee 페이지는 봇 차단(AWS WAF)에 막혔다. 공개 시세 API(api.binance.com)는 이 세션의 위치에서 HTTP 451 "restricted location"을 반환했다 [V13] |
| Bybit MM | 계약(선물) 쪽은 Pro/MM 그룹 수수료 구조가 공개 API 문서에 있다. MM1–3 메이커 리베이트는 주요 코인 그룹에서 −0.1 / −0.25 / −0.4bp, 롱테일 그룹에서 최대 −1.25bp다. 단 이 값은 **testnet 예시 응답**이다 [V7]. 현물 MM 요율(MM1 −0.001%, MM2 −0.005%)은 **미확인**이다(해당 도움말 문서가 "not supported on this site"로 표시됨 [V8]) |
| OKX | 2026-06-03부터 마이너스 메이커 요율 구간 사용자에게는 ELP 메이커 리베이트가 없어졌다. 현물 Group 1 메이커 수수료는 VIP7 −0.2bp, VIP8 −0.5bp, VIP9 −0.75bp다 [V9]. 테이커 요율은 **미확인**이다 |
| 관측 스프레드 | OKX 현물과 무기한 모두 다섯 종목이 **1틱**이었다. BTC 0.02bp, ETH 0.06bp, XRP 1.02bp, SOL 1.34bp, DOGE 1.68bp [V12]. 바이낸스와 Bybit는 공개 API가 지역 차단돼 **미확인**이다 |
| 손익분기 | 헤지를 테이커로 하면(5bp + 슬리피지 1bp) 최상위 리베이트를 받아도 필요 반스프레드 s*가 6.2bp 이상이다. 관측된 반스프레드는 0.01–0.84bp라서 **전 종목에서 미달**이다. 양쪽을 모두 메이커 리베이트로 체결하고 m = 1bp라는 가정에서만 s*가 음수가 되어 통과한다(§4) |
| 핵심 결론 「해석」 | 1틱 메이저 종목에서 메이커의 수익은 스프레드가 아니라 **리베이트 − 마크아웃**에서 나온다. 그래서 수수료를 보고 고를 대상은 "어느 거래소의 메이커 요율이 낮은가"보다 **"헤지 레그까지 메이커/리베이트로 처리할 수 있는가"**다 |

---

## 0.5 Binance USDC-M 무기한 선물 (메이커 거래소 후보: BTCUSDC, ETHUSDC, SOLUSDC, XRPUSDC, DOGEUSDC → 같은 기초자산의 USDT 무기한으로 헤지)

| 항목 | 확인 결과 | 출처 / 상태 |
|---|---|---|
| USDⓈ-M 기본 요율 (Regular User) | 공식 FAQ의 계산 예시에 "a Regular User's maker fee is 0.02% and a Regular User's taker fee is 0.05%"(BTCUSDT 무기한 예시)라고 나온다. BNB로 수수료를 내면 10% 할인된다. 선물 VIP 등급은 현물 VIP와 같고, 등급별 거래량 기준은 현물의 5배다 | [V19] 공식 FAQ(lastUpdate 2026-05-01). 다만 FAQ 스스로 "The information on this page may be outdated"라고 적고 있다. 이 값은 예시일 뿐이므로 **현행 요율표로는 미확인**이다 |
| **USDC-M 무기한 현행 메이커·테이커 요율과 프로모션(0% 메이커, 테이커 할인)** | **미확인**. 같은 FAQ가 "Binance Updates Limited-Time Trading Fee Discount and Liquidity Provider Program for USDC-Margined Perpetual Contracts (**2025-09-11**)" 공지를 참조하고 있다. 즉 USDC 무기한용 **한시 수수료 할인과 LP 프로그램이 2025-09-11 기준으로 존재했다**. 하지만 그 공지 본문(기간, 대상 페어, VIP 조건, 요율)은 요청 한도(60회)를 다 써서 열지 못했다 | [V19](공지 제목만 확인). 웹 검색 결과에 2024-04-03 USDC 무기한 할인 공지도 나왔지만(https://www.binance.com/en/support/announcement/binance-introduces-limited-time-trading-fee-discount-for-usdc-margined-perpetual-contracts-2024-04-03-fc7732cf48cd49cf95e53aa479ed4deb) 원문을 열지 않았으므로 근거로 쓰지 않는다 |
| USDC 무기한이 Futures MM이나 LP 리베이트 대상인가 | **부분 확인**. 위 2025-09-11 공지의 제목에 "Liquidity Provider Program for USDC-Margined Perpetual Contracts"가 들어 있으므로 USDC 무기한 전용 LP 프로그램이 있었다. 리베이트 수치, 자격, 현재 유효 여부는 **미확인**. Futures MM 프로그램은 "USDⓈ-Margined and COIN-Margined Futures pairs on the market-making list"를 대상으로 한다 [V2]. USDC 무기한은 USDⓈ-M에 속하지만, 개별 심볼이 market-making list에 들어 있는지는 **미확인** | [V19] 제목, [V2]. 웹 검색 결과에 "USDⓢ-Margined Futures Liquidity Provider Program (2024-06-03)" 공지도 나왔지만 열지 않았다 |
| USDC 대 USDT 무기한의 tick size, min qty | **미확인**. 공개 exchangeInfo는 fapi 호스트가 허용 목록 밖이고, api.binance.com은 451 응답이었다. 관련 공지도 열지 못했다 | — |
| 「해석」 이 구조의 손익분기 | 같은 거래소의 USDC 무기한을 메이커로, USDT 무기한을 테이커로 헤지한다고 하자. s* = f_m(USDC) + 6 + m + b이고, 여기서 b는 USDC/USDT 환산 차와 두 계약의 펀딩비 차이다. f_m = 0(과거 프로모션 수준이 유지된다는 가정, 미확인)이면 s*는 m = 1, 3, 5bp일 때 7, 9, 11bp다. 반대로 헤지까지 USDT 무기한 메이커로 하고 f_m과 헤지 메이커 요율이 모두 0이면 s* = m이다. 결국 판정은 (i) USDC 무기한 호가 스프레드가 틱 몇 개인지와 (ii) USDT 무기한에서 USDC 무기한으로 가는 lead-lag 마크아웃에 달려 있다. 이 두 값은 상위 작업에서 data.binance.vision으로 측정 중이다 | §4 식 |
| 추가 위험 「해석」 | 마진 자산이 다르다(USDC와 USDT). 그래서 두 계정 사이에 증거금을 따로 관리해야 하고 USDC/USDT 디페그 위험이 b에 들어간다. 또 FAQ 머리말에 "In compliance with MiCA requirements, unauthorized stablecoins are subject to certain restrictions for EEA users"라는 문구가 있다 [V19]. 지역에 따라 쓸 수 있는 스테이블코인이 달라질 수 있다는 뜻이다 | [V19] |

**다음에 확인할 것(최우선)**: 2025-09-11 USDC 무기한 수수료 할인·LP 공지 원문과 그 이후 갱신 공지, 그리고 USDⓈ-M 요율표(https://www.binance.com/en/fee/futureFee, 미열람)를 확인한다. 이 문서 작성 중에는 요청 한도 때문에 열지 못했다.

---

## 1. 수수료 비교 (공개된 기본 요율과 VIP 구간)

단위: %(괄호 안은 bp). 지역과 계정에 따라 실제 요율은 다를 수 있다. 거래소 스스로 그렇게 밝히고 있다 [V6][V9].

### 1.1 현물

| 거래소 | 등급 | 메이커 | 테이커 | 출처 / 비고 |
|---|---|---|---|---|
| Binance | 일반 VIP 0–9 | **미확인** | **미확인** | fee 페이지 차단 [§9.2]. Spot LP 공지에는 테이커가 "Standard taker fees as per user's VIP level"이라고만 적혀 있다 [V3] |
| Binance | Spot LP Tier 1 | 0.000% (0) | VIP 표준 | [V3]. 기준: 주간 현물 메이커 거래량 비중 0.05% **또는** 주간 메이커 거래량 USD 25,000,000 |
| Binance | Spot LP Tier 2 / 3 / 4 | −0.004% / −0.006% / −0.008% (−0.4 / −0.6 / −0.8) | VIP 표준 | [V3]. 기준: 주간 메이커 비중 0.15% / 0.50% / 1.00% |
| Bybit | VIP 0 | 0.1000% (10) | 0.1000% (10) | [V6] 현물(Crypto-Crypto). 페이지 갱신일 2026-11-05 |
| Bybit | VIP 1 | 0.0675% | 0.0800% | [V6] |
| Bybit | VIP 5 | 0.0400% | 0.0500% | [V6]. 30일 현물 거래량 ≥ 50,000,000 기준(단위는 표기 그대로) |
| Bybit | Supreme VIP | 0.0300% (3.0) | 0.0450% (4.5) | [V6]. ≥ 100,000,000 |
| Bybit | Adventure Zone 및 xStocks, VIP 0 | 0.2000% | 0.2000% | [V6]. 별도 요율표 |
| Bybit | 현물 MM | **미확인** | — | [V8] 본문을 열지 못함("This article is currently not supported on this site") |
| OKX | 현물 Group 1, LV1 | 0.0800% (8.0) | **미확인** | [V9] ELP 공지에 실린 예시표 |
| OKX | VIP1 / VIP2 / VIP3 | 0.0675% / 0.0600% / 0.0550% | **미확인** | [V9] |
| OKX | VIP4 / VIP5 / VIP6 | 0.0300% / 0.0250% / 0.0000% | **미확인** | [V9] |
| OKX | VIP7 / VIP8 / VIP9 | **−0.0020% / −0.0050% / −0.0075%** | **미확인** | [V9]. 이 구간에서는 ELP 메이커 리베이트가 0으로 바뀌었다(§2.3) |

주의: OKX 페이지는 "OKX United States" 사이트로 응답했다 [V9]. 표의 요율이 글로벌 계정에도 똑같이 적용되는지는 **미확인**이다. www.okx.com/fees는 JS 렌더링이라 본문이 비어 있었다.

### 1.2 무기한 선물 (USDT 마진)

| 거래소 | 등급 | 메이커 | 테이커 | 출처 / 비고 |
|---|---|---|---|---|
| Binance USDⓈ-M | 일반 VIP | FAQ 예시: Regular User 0.02% | FAQ 예시: 0.05% | [V19]. 예시 값이고 현행 여부는 미확인. 이 문서에서 쓰는 테이커 5bp 가정과 일치한다. USDC-M은 §0.5 |
| Binance USDⓈ-M | Futures MM Program | "Negative maker fees for selected market making pairs" (구체 수치 **미확인**) | — | [V1][V2] |
| Bybit | VIP 0 | 0.0200% (2.0) | 0.0550% (5.5) | [V6] Perpetual & Futures |
| Bybit | VIP 1 / VIP 5 | 0.0180% / 0.0100% | 0.0400% / 0.0320% | [V6] |
| Bybit | Supreme VIP | 0.0000% | 0.0300% | [V6] |
| Bybit | Pro 1–6, G1(MajorCoins) 그룹 | 0.01% → 0 | 0.028% → 0.015% | [V7] testnet 예시 응답 |
| Bybit | MM 1 / 2 / 3, G1(MajorCoins) | **−0.001% / −0.0025% / −0.004%** | — | [V7] 예시. 필드 `makerRebate` |
| Bybit | MM 1 / 2 / 3, G5(LongTail) | −0.0075% / −0.01% / −0.0125% | — | [V7] 예시 |
| OKX | 무기한 VIP별 요율 | **미확인** | **미확인** | ELP 변경 공지 [V9]에 따르면 조정 대상 상품은 Spot, Perpetual, Expiry Futures, Options다. 무기한 요율표 자체는 열지 못했다 |

### 1.3 현재 프로모션 (해외 3사)
- **Binance Spot LP 한시 프로모션**: 기간은 2026-11-16 00:00부터 2027-02-07 23:59(UTC)까지다. 기존 "총 현물" 트랙에 "BTC·ETH 페어" 트랙과 "BTC·ETH 제외" 트랙을 추가했고, 세 트랙 중 가장 높은 Tier를 준다. Tier 기준값 자체는 바뀌지 않았다. 새 트랙의 첫 평가 주간은 2026-11-16부터 11-22까지이고, 리베이트는 약 2026-11-24에 반영된다 [V3].
  - 조건 1: "Trading volume on Spot and Margin pairs under zero fee promotions … will be excluded from calculation."
  - 조건 2: "Self-trades will be excluded from maker volume calculations." [V3]
- 이 밖에 Bybit와 OKX의 제로 수수료 캠페인은 이번에 연 자료 범위에서 **미확인**이다.

### 1.4 MM에 영향을 주는 API 제약
| 항목 | Binance | Bybit | OKX |
|---|---|---|---|
| MM 대상 API 한도 상향 | 있음. "Higher API limits"(선물 MM [V2], 현물 MM [V4]) | **미확인** | **미확인** |
| 저지연 접속 | "Low latency connectivity services" [V2] | **미확인** | **미확인** |
| 주문 정정(amend) 지원, 주문 rate limit 수치 | **미확인** | **미확인** | **미확인** |
| 매칭 엔진 위치 | AWS ap-northeast-1(도쿄) [V16 제3자] | Tardis 문서는 AWS ap-southeast-1(싱가포르)라고 적었다 [V17 제3자]. 그런데 Bybit API 문서 배너에는 "migrated its trading and matching engine service to AWS Tokyo (apne1-az4) on 12 Nov. 2026"이라고 되어 있다 [V7 공식]. 두 자료가 맞지 않으므로 공식 문서를 우선한다 | AWS ap-northeast-1(도쿄), 2026-08-04부터 [V18 제3자] |

「해석」 공식 기준으로 보면 세 거래소의 매칭 엔진이 모두 도쿄 AWS에 있다. 그렇다면 거래소 간 헤지와 lead-lag의 지연 경쟁은 같은 리전 안에서 수백 µs에서 수 ms 단위로 벌어질 가능성이 크다. 다만 실측한 값은 없다.

---

## 2. MM / 유동성 프로그램 상세

### 2.1 Binance

| 프로그램 | 메커니즘과 요율 | 자격과 의무 | 출처 |
|---|---|---|---|
| **Futures Market Maker Program** (2020-02-03 공지, FAQ 갱신 2026-01-02) | "Qualified market makers can now receive higher maker fee rebates for selected trading pairs." USDⓈ-M과 COIN-M 모두 대상이다. 리베이트는 "updated on a regular basis to reflect participants' market-making performance" | 30일 거래량이 바이낸스 현물 1,000 BTC 초과 또는 바이낸스 선물 3,000 BTC 초과이고 "quality market maker strategies"를 갖춘 경우. 다른 거래소의 거래량 증빙도 인정한다. 주간 평가 요소는 Maker volumes, Bid/offer spread, Total order size, Order duration, Market making time. 신청은 mmprogram@binance.com 또는 Key Account Manager | [V2] FAQ(공식), [V1] 공지(공식). 2020년 공지는 "30-day trading volumes exceed 1,000 BTC on Binance"라고만 적었다 |
| **Spot Liquidity Provider Program** (2024-09-09 개편) | Tier 1: 0.05% 또는 USD 25M → 메이커 0%. Tier 2: 0.15% → −0.004%. Tier 3: 0.50% → −0.006%. Tier 4: 1.00% → −0.008%. Tier 4는 기준이 2.0%에서 1.0%로, 리베이트가 −0.01%에서 −0.008%로 바뀌었다 | 주간 메이커 거래량이 Tier 1 이상이면 자동 편입된다. 30일 현물 거래량이 USD 20M을 넘으면 4주 체험을 신청할 수 있다(당시 체험 기간에는 Tier 1 적용). 3주 연속 자격 미달이면 제외된다 | [V10] 공식 |
| **Spot LP 2026-11-16 업그레이드** (현행) | 위 Tier 구조에 트랙 3개를 두고 가장 높은 Tier를 준다. 평가 주기는 월요일 00:00부터 일요일 23:59(UTC)까지이고, 화요일 약 00:00에 요율이 바뀐다 | 수동 체험 신청 기준이 확대됐다: 현물 USD 20M 초과 **또는 선물 USD 100M 초과**. 체험 4주 동안 **Tier 2(−0.4bp)**를 적용한다. 제로 수수료 페어 거래량과 자기 체결은 제외한다 | [V3] 공식(2026-11-18 게시) |
| (구) Spot Market Maker Program (2020-07-22) | 메이커 수수료 리베이트를 도입했다. 점수는 Maker Volumes, Bid/offer spread, Total order size, Order duration, 페어별 가중치로 계산한다 | 30일 1,000 BTC 초과. API 한도 상향 | [V4] 공식(과거 자료. 현재 Spot LP와의 관계는 **미확인**) |
| **Fiat LP Program** (2024-06-25 개편, 2024-11-14 수정) | 법정화폐 마켓별로 주간 메이커 비중 기준이 있다. TRY와 EUR는 2.0%에서 −0.004%, BRL은 1.0%에서 −0.006%, ZAR·PLN·UAH·RON·MXN·CZK·COP는 0.5%에서 −0.010%, ARS는 0.2%에서 −0.010%, JPY는 1%에서 −0.015% | 30일 거래량 USDT 20M 초과. 3주 체험 기간의 기본 메이커 수수료는 0이다. 리베이트는 법정화폐로 매시간 지급된다 | [V5] 공식 |
| **Altcoin LiquidityBoost** (2025-06, 알트코인 페어 최대 −1bp, 메이커 비중 0.5% / 1% 구간) | **미확인** | **미확인** | The Block 기사 [§9.2]는 Cloudflare 차단으로 열지 못했다. 바이낸스 공지 원문의 article code도 찾지 못했다 |
| **Options MM Program** | **미확인** | **미확인** | 이번 조사에서 열지 못함 |

웹 검색 결과에 Binance "Liquidity Program" 허브 페이지(https://www.binance.com/en/vip-portal/liquidity-hub)가 나왔지만 열지 않았다(미확인).

### 2.2 Bybit
- **계약 Pro/MM 그룹 수수료 구조** [V7, 공식 API 문서]
  - "The new grouped fee structure only applies to Pro-level and Market Maker clients. It does not apply to retail traders."
  - 그룹별로 가중치가 있다: G1(MajorCoins) 1, G2(HighGrowth) 5, G3(Mid-Tier Liquidity) 8, G4(Mid-Tier Activation) 15, G5(LongTail) 20, USDC 8, Innovation-Zone 1. 수치는 예시 응답 기준이다.
  - 산식: "Weighted maker volume = Σ(Maker volume on pair × Group weighting factor)". "Weighted maker share = (Your total weighted maker volume ÷ Bybit's total weighted maker volume)". "Bybit's total weighted maker volume is not provided by the API. Weighted maker share will be provided in the monthly MM report."
  - MM1–3 리베이트(예시 응답): G1 −0.1 / −0.25 / −0.4bp, G4 −0.5 / −0.75 / −1.0bp, G5 −0.75 / −1.0 / −1.25bp. RPI 주문의 `rpiMakerRebate`는 0이다.
  - 주의: 이 값은 문서에 실린 **testnet 예시 응답**이다. 실제 mainnet 값은 공개 엔드포인트 `GET /v5/market/fee-group-info?productType=contract`로 확인해야 하는데, api.bybit.com이 CloudFront 지역 차단에 걸려 조회하지 못했다(**미확인**).
- **Market Maker Incentive Program**(현물 MM1 −0.001%, MM2 −0.005% 등): **미확인** [V8].
- 「해석」 가중치 구조를 보면 **롱테일 계약의 메이커 거래량 1달러가 메이저 계약의 20배로 인정**된다. MM 등급을 얻는 데 드는 비용은 롱테일 쪽이 훨씬 싸다. 대신 롱테일은 마크아웃과 재고 위험이 크다.

### 2.3 OKX
- **ELP 메이커 리베이트 조정** [V9, 공식, 2026-06-02 게시]
  - "Effective June 3, 2026 at 15:00–17:00 (UTC+8), the ELP Maker rebate will no longer apply to users whose effective Maker fee tier is at a negative rate. The ELP Maker fee for these tiers will be set to 0.0000%."
  - 대상 상품: Spot, Perpetual, Expiry Futures, Options.
  - 판정 기준은 실제 적용 요율 구간이다: "based on the fee tier applied to the user's actual trading activity, not the user's native VIP account level. For example, a user with OKX platform VIP tier VIP 6 who benefits from a Spot market-making VIP 9 under the Market Maker Program will have their ELP Maker orders processed under the rules for fee tier VIP 9, with the ELP Maker fee set to 0.00000%."
  - 이 문구로 OKX에도 **Market Maker Program이 있다**는 점이 확인된다. 다만 프로그램의 자격 요건은 **미확인**이다.
- 「해석」 마이너스 구간(VIP7–9 또는 MM 구간)의 메이커라면 ELP 주문으로는 추가 리베이트를 받을 수 없다. 이런 메이커에게 ELP는 일반 주문보다 불리하거나 같다.

---

## 3. 관측 호가 스프레드 (스냅샷 1회)

### 3.1 OKX (공개 API, 응답 `ts` 기준 UTC)
현물은 `GET /api/v5/market/tickers?instType=SPOT`(요청 2026-11-19 08:32:20.762Z), 무기한은 `?instType=SWAP`(08:34:28.042Z)로 받았다. 틱은 `/api/v5/public/instruments`의 `tickSz`, 계약 크기는 `ctVal`에서 가져왔다 [V12].

| 종목 | 시장 | ts | best bid | best ask | 스프레드 (틱 / bp) | 1틱 (bp) | 1호가 잔량 (bid / ask, USDT 환산) |
|---|---|---|---|---|---|---|---|
| BTC | 현물 BTC-USDT | 08:32:20.569 | 63,724.3 | 63,724.4 | 1 / 0.016 | 0.016 | 2.92만 / 2.26만 |
| BTC | 무기한 BTC-USDT-SWAP | 08:34:27.969 | 63,664.3 | 63,664.4 | 1 / 0.016 | 0.016 | 19.6만 / 42.1만 (307.8 / 662계약 × 0.01 BTC) |
| ETH | 현물 | 08:32:20.566 | 1,805.46 | 1,805.47 | 1 / 0.055 | 0.055 | 1.89만 / 1.36만 |
| ETH | 무기한 | 08:34:28.030 | 1,803.61 | 1,803.62 | 1 / 0.055 | 0.055 | 11.3만 / 22.9만 (× 0.1 ETH) |
| XRP | 현물 | 08:32:20.567 | 0.9809 | 0.9810 | 1 / 1.02 | 1.02 | 1.64만 / 0.58만 |
| XRP | 무기한 | 08:34:27.866 | 0.9805 | 0.9806 | 1 / 1.02 | 1.02 | 5.2만 / 0.83만 (× 100 XRP) |
| SOL | 현물 | 08:32:20.567 | 74.56 | 74.57 | 1 / 1.34 | 1.34 | 1.46만 / 0.73만 |
| SOL | 무기한 | 08:34:28.011 | 74.45 | 74.46 | 1 / 1.34 | 1.34 | 18.8만 / 8.8만 (× 1 SOL) |
| DOGE | 현물 | 08:32:20.466 | 0.05937 | 0.05938 | 1 / 1.68 | 1.68 | 1.98만 / 0.07만 |
| DOGE | 무기한 | 08:34:27.966 | 0.05936 | 0.05937 | 1 / 1.68 | 1.68 | 4.7만 / 4.3만 (× 1,000 DOGE) |

- 현물과 무기한은 약 2분 간격으로 받은 스냅샷이다. 그래서 두 가격 차이를 베이시스로 해석하면 안 된다.
- 다섯 종목 모두 **스프레드가 1틱에 묶여 있다**. 메이커가 얻는 반스프레드는 BTC 0.008bp에서 DOGE 0.84bp 사이다.
- 무기한의 1호가 잔량이 현물보다 5–10배 컸다(BTC, ETH, SOL 기준, 이 스냅샷 한 번).

### 3.2 Binance, Bybit
| 거래소 | 상태 |
|---|---|
| Binance 현물 `api.binance.com/api/v3/ticker/bookTicker` | HTTP 451: "Service unavailable from a restricted location according to 'b. Eligibility' in https://www.binance.com/en/terms" [V13]. 스프레드 **미확인** |
| Binance USDⓈ-M(fapi) | 허용 목록 밖이라 시도하지 않음. **미확인** |
| Bybit `api.bybit.com/v5/market/tickers` | HTTP 403: "The Amazon CloudFront distribution is configured to block access from your country". **미확인** |

이 두 차단은 세션 실행 위치에 대한 지역 제한이다. 우회하지 않았다. 사용자의 실제 거주지나 법인 소재지에서 이 거래소들을 쓸 자격이 있는지는 별도로 확인해야 한다(§6, §7). 손익분기 표(§4)에서는 바이낸스와 Bybit의 스프레드 대신 **OKX 관측값을 대용치로** 쓴다. 메이저 종목의 1틱 스프레드는 거래소마다 비슷할 것이라고 가정한 것이지, 확인한 사실은 아니다.

---

## 4. 손익분기 반스프레드 (해외 거래소 간 / 같은 거래소의 현물–무기한)

### 4.1 식
`03` §3.1의 식을 쓴다. USDT끼리 거래하므로 KRW 환전 항(φ·c_fx)은 0으로 둔다.

```
s* = f_m + h + m + b          [bp]
```

| 기호 | 의미 |
|---|---|
| f_m | 호가를 거는 거래소의 메이커 요율. 리베이트는 음수 |
| h | 헤지 비용. 테이커 헤지라면 5bp + 슬리피지 1bp = **6bp(가정)**. 메이커 헤지라면 그 거래소의 메이커 요율에 미체결 기회비용을 더한 값인데, 기회비용은 미측정이라 0으로 뒀다 |
| m | 마크아웃. 1 / 3 / 5bp로 둔 **가정값** |
| b | 베이시스와 펀딩 위험. 현물을 무기한으로 헤지할 때 펀딩비가 들어간다. 미측정이라 0으로 뒀다 |

관측 반스프레드(OKX 현물, §3.1): BTC 0.008, ETH 0.028, XRP 0.51, SOL 0.67, DOGE 0.84bp.

### 4.2 시나리오별 s* (bp)
| # | 호가 레그 (f_m) | 헤지 레그 (h) | 요율 근거 | m=1 | m=3 | m=5 |
|---|---|---|---|---|---|---|
| A | OKX 현물 LV1 (+8.0) | Binance 무기한 테이커 (6) | [V9] / 가정 | 15.0 | 17.0 | 19.0 |
| B | OKX 현물 VIP9 (−0.75) | Binance 무기한 테이커 (6) | [V9] / 가정 | 6.25 | 8.25 | 10.25 |
| C | Bybit 현물 VIP0 (+10) | Binance 무기한 테이커 (6) | [V6] / 가정 | 17.0 | 19.0 | 21.0 |
| D | Bybit 무기한 VIP0 메이커 (+2.0) | Binance 무기한 테이커 (6) | [V6] / 가정 | 9.0 | 11.0 | 13.0 |
| E | Bybit 무기한 MM1 G1 (−0.1) | Binance 무기한 테이커 (6) | [V7] 예시 / 가정 | 6.9 | 8.9 | 10.9 |
| F | Binance 현물 LP Tier1 (0) | Binance 무기한 테이커 (6) | [V3] / 가정 | 7.0 | 9.0 | 11.0 |
| G | Binance 현물 LP Tier4 (−0.8) | Binance 무기한 테이커 (6) | [V3] / 가정 | 6.2 | 8.2 | 10.2 |
| H | OKX 현물 VIP9 (−0.75) | OKX 무기한 메이커 −0.75 (**가정**: 무기한 요율 미확인) | [V9] / 가정 | −0.5 | 1.5 | 3.5 |
| I | Binance 현물 LP Tier4 (−0.8) | Bybit 무기한 MM3 G1 메이커 (−0.4) | [V3] / [V7] 예시 | −0.2 | 1.8 | 3.8 |

### 4.3 관측 반스프레드 − s* (bp, 양수면 통과)
OKX 현물 관측값을 모든 시나리오에 적용했다. 바이낸스와 Bybit 행은 대용치다.

| # | m | BTC | ETH | XRP | SOL | DOGE |
|---|---|---|---|---|---|---|
| A | 1 / 3 / 5 | −14.99 / −16.99 / −18.99 | −14.97 / … | −14.49 / … | −14.33 / … | −14.16 / −16.16 / −18.16 |
| B | 1 / 3 / 5 | −6.24 / −8.24 / −10.24 | −6.22 / … | −5.74 / … | −5.58 / … | −5.41 / −7.41 / −9.41 |
| E | 1 / 3 / 5 | −6.89 / −8.89 / −10.89 | −6.87 / … | −6.39 / … | −6.23 / … | −6.06 / −8.06 / −10.06 |
| G | 1 / 3 / 5 | −6.19 / −8.19 / −10.19 | −6.17 / … | −5.69 / … | −5.53 / … | −5.36 / −7.36 / −9.36 |
| H | 1 | **+0.51** | **+0.53** | **+1.01** | **+1.17** | **+1.34** |
| H | 3 | −1.49 | −1.47 | −0.99 | −0.83 | −0.66 |
| H | 5 | −3.49 | −3.47 | −2.99 | −2.83 | −2.66 |
| I | 1 | **+0.21** | **+0.23** | **+0.71** | **+0.87** | **+1.04** |
| I | 3 | −1.79 | −1.77 | −1.29 | −1.13 | −0.96 |

(C, D, F는 모든 조합에서 A와 B 사이의 음수다. 차이는 시나리오 표에서 바로 계산할 수 있다.)

### 4.4 해석 「해석」
1. **헤지를 테이커로 하면 어떤 리베이트 구간에서도 성립하지 않는다.** 6bp 헤지 비용은 최대 리베이트 0.8bp의 7배가 넘는다. 1틱 시장의 반스프레드(≤ 0.84bp)로는 메울 수 없다.
2. 통과하는 조합은 **양쪽 레그가 모두 메이커 또는 리베이트로 체결되고 m이 약 1bp 이하**인 경우뿐이다(H, I). 이것이 사실상 프로그램 MM의 수익 구조다. 즉 리베이트 + 대기열 우선순위 + 낮은 마크아웃 + 재고 내부 상쇄다. 헤지 레그를 메이커로 하면 미체결 위험과 그동안의 재고 위험이 생기는데, 이 표에는 반영되지 않았다(b = 0).
3. 바이낸스 선물 MM 프로그램의 실제 리베이트 수치와 OKX 무기한 요율이 **미확인**이다. 그래서 H와 I는 상한 쪽 시나리오로만 읽어야 한다.
4. **제로 수수료 캠페인의 함정.** 메이커 요율이 0이 되면 같은 캠페인 아래에서 **테이커도 무료**가 된다. 그러면 lead-lag 테이커가 늘어나 낡은 메이커 호가를 더 많이 가져가고, m이 커진다. 또 캠페인은 만료된다. 바이낸스 Spot LP는 제로 수수료 페어의 거래량을 Tier 산정에서 **아예 뺀다** [V3]. 제로 수수료 페어에서 쌓은 메이커 거래량으로는 LP 등급을 얻을 수 없다는 뜻이다.

---

## 5. "MM 프로그램 역이용": 합법적인 선택지와 금지되는 방식

### 5.1 (a) LP/MM 등급으로 헤지 레그 비용 줄이기
- **메커니즘**: 바이낸스 현물 LP Tier 1–4 [V3], 바이낸스 선물 MM [V2], Bybit MM1–3 [V7] 중 하나의 등급을 얻는다. 그러면 헤지 거래소의 메이커 요율이 0 또는 음수가 된다. 헤지를 패시브(메이커)로 처리할 수 있게 되면 h가 6bp에서 −0.4 ~ −0.8bp 수준으로 내려간다(시나리오 G에서 I로의 차이).
- **요건**:
  - 바이낸스 현물 LP Tier 1: 주간 메이커 거래량 **USD 25M**(일평균 약 3.6M)이면 비중과 상관없이 자격이 생긴다 [V3].
  - 체험 경로: 30일 현물 USD 20M 초과 또는 선물 USD 100M 초과 → 4주간 Tier 2(−0.4bp) [V3].
  - 바이낸스 선물 MM: 30일 1,000 BTC(현물) 또는 3,000 BTC(선물). 타 거래소 실적도 인정한다 [V2].
  - Bybit: MM 등급 기준은 가중 메이커 점유율이다. 기준값 자체는 **미확인**이다 [V7].
- **비중 기준을 USD로 환산하면?** 0.05% / 0.15% / 0.5% / 1% 기준을 금액으로 바꾸려면 바이낸스 주간 총 현물 메이커 거래량이 필요하다. 이번에 열어 본 자료 중에 이 수치를 준 곳이 없다 → **미확인**. Tier 1의 절대 기준 USD 25M/주만 확정된 값이다.
- **기대가치 동인**: (헤지 레그 테이커 비용 − 메이커 비용) × 헤지 거래량. 여기서 메이커 헤지 미체결로 생기는 재고 위험 비용과, 등급을 유지하는 데 필요한 의무(스프레드, 호가 크기, 지속 시간, 가동 시간. [V2][V4]의 평가 요소)를 지키는 비용을 뺀다.
- **위험**: 3주 연속 미달이면 프로그램에서 제외된다 [V3][V10]. 평가 기준은 거래소 재량으로 바뀐다("sole and absolute discretion" [V3]). 등급을 위해 늘린 메이커 거래량 자체가 마크아웃 손실을 낼 수 있다.

### 5.2 (b) 프로그램 MM이 없거나 의무가 약한 곳 고르기, 또는 그들의 의무를 이용하기
- **메커니즘 1(빈 곳 찾기)**: 프로그램 MM의 평가는 거래량 가중이다. Bybit는 롱테일 가중치가 20배다 [V7]. 그래서 프로그램 MM은 대상 리스트에 있는 페어에 몰린다. 리스트 밖에 있고 스프레드가 여러 틱인 페어가 소규모 메이커의 후보가 된다. 다만 바이낸스와 Bybit의 "market making list" 구성은 **미확인**이다.
- **메커니즘 2(의무의 예측 가능성)**: 평가 요소에 "Market making time", "Order duration", "Bid/offer spread"가 있다 [V2][V4]. 즉 프로그램 MM은 변동성이 커질 때도 일정 시간 호가를 유지할 유인이 있다.
  - 「해석」 그렇다면 이들의 호가가 사용자의 기존 lead-lag **테이커** 전략의 상대방이 될 수 있다. 선행 거래소가 움직였는데 지연 거래소의 의무 호가가 아직 남아 있는 순간이다.
  - 이것은 정상적인 테이커 체결이다. 호가 시장의 일반적인 역선택 구조이고 금지 행위가 아니다. 다만 프로그램 MM의 취소 속도가 사용자보다 빠르면 남는 엣지가 없다. 실측이 필요하다(E1, E2와 같은 방식).
- **위험**: 대상 페어 구성과 의무 조건이 공개되지 않아 추정만 할 수 있다. 롱테일 페어는 상장폐지와 재고 위험이 크다.

### 5.3 (c) 제로 수수료 캠페인: 테이커 쪽에 쓰는 것과 메이커 쪽에 쓰는 것
- 해외 3사의 현재 제로 수수료 캠페인은 **미확인**이다(§1.3). 원화 거래소 캠페인은 범위 밖이다.
- 「해석」 일반론은 다음과 같다. 제로 수수료는 테이커 lead-lag 전략의 비용을 "스프레드 + 헤지 비용"으로 줄여 준다. 반면 메이커에게는 경쟁 테이커의 비용도 같이 0이 되므로 m이 커지는 압력이 생긴다(§4.4-4). 그래서 캠페인은 **테이커 전략 쪽에 더 유리하다**. 또 바이낸스에서는 제로 수수료 페어 거래량이 LP 등급 산정에서 빠진다 [V3].

### 5.4 (d) 금지되거나 실행할 수 없는 방식
| 방식 | 왜 안 되는가 (인용) |
|---|---|
| 자기 체결이나 워시 트레이딩으로 메이커 비중 부풀리기 | 바이낸스: "Self-trades will be excluded from maker volume calculations." 또 "Binance reserves the right to disqualify user's reward eligibility if the account is involved in any dishonest behavior (e.g., wash trading, illegally bulk registered accounts, self-dealing, or market manipulation)" [V3]. 2024년 공지에도 같은 문구가 있다 [V10] |
| 여러 계정으로 등급 쪼개기나 중복 수혜 | "illegally bulk registered accounts" [V3]. Bybit는 "Trading volume from both the Main Account and the Subaccount will be considered" [V6]. 즉 하위 계정 거래량은 합산된다 |
| 프로그램 코드에 개입하기 | "disqualify any participants who tamper with Binance program code, or interfere with the operation of Binance program code with other software" [V3] |
| 호가 의무를 채우려고 체결할 생각이 없는 주문을 반복 제출하고 취소하기(스푸핑) | 거래소 약관의 "market manipulation" 금지 대상이다 [V3]. 한국법과의 관계는 `03` §2.3(Q8)에 인용해 두었다. 그중 「가상자산이용자보호법」 제10조②의 "권리의 이전을 목적으로 하지 아니하는 거짓으로 꾸민 매매", 제10조③의 "시세를 변동 또는 고정시키는 매매", 그리고 서울남부지법 판결 보도의 "체결 가능성이 낮은 대량의 허수 매수 주문을 반복적으로 제출·취소"를 참고한다. **해외 거래소에서 한 거래에 한국법이 적용되는지는 이 문서가 판단하지 않는다(미확인, 법률 자문 대상)** |
| 서로 짠 상대와 체결하기(통정매매) | 법 제10조②1·2호(`03` §2.3 인용). 거래소 약관의 "self-dealing" [V3] |

---

## 6. lead-lag 후보 거래소 쌍 (측정할 가설)

출처가 있는 수치는 하나뿐이다. CME BTC 선물과 바이낸스 현물 사이의 lead-lag이 구간에 따라 +0.066s, +0.063s, −0.057s로 나왔고 부호가 바뀐다(`01` [L1], Plazuelo Pascual 등 2025). 바이낸스, Bybit, OKX 사이의 lead-lag 수치는 이번에 열어 본 자료에 없다 → **미확인**. 아래 항목은 모두 측정할 가설이다.

| # | 가설 (선행 → 후행) | 측정 방법 | 왜 후보인가 「해석」 |
|---|---|---|---|
| L1 | Binance USDⓈ-M 무기한 → OKX 현물과 Bybit 현물 | Hayashi–Yoshida 지연상관(`01` [L1] 방식). Tardis의 `bookTicker`와 `bbo-tbt`를 `local_timestamp`로 정렬 | 무기한의 1호가 잔량이 현물보다 크다는 관측(§3.1, OKX 기준)과 일반적인 가격 발견 가설 |
| L2 | 같은 거래소 안에서 무기한 → 현물 (OKX, Binance) | 같은 방식. 같은 거래소라 클록 오차가 작다 | 현물 호가를 내고 무기한으로 헤지하는 구조의 역선택을 직접 측정할 수 있다 |
| L3 | Binance → Bybit 무기한 | 같은 방식. Bybit가 도쿄로 이전한 2026-11-12 [V7] 전후를 나눠 비교 | 매칭 엔진 이전이 lead-lag를 바꿨는지 볼 수 있는 자연 실험 |
| L4 | OKX 이전(2026-08-04, 홍콩 → 도쿄 [V18 제3자]) 전후의 Binance–OKX | 같은 방식 | 위와 같은 이유 |

---

## 7. hftbacktest용 공개 히스토리컬 데이터

| 출처 | 확인한 내용 (2026-11-19) | 시작일 / 비고 |
|---|---|---|
| data.binance.vision 현물 `trades` | `BTCUSDT-trades-2026-11-18.zip.CHECKSUM` 있음 (HTTP 200) [V14] | 시작일 **미확인**(디렉터리 목록을 받지 않음) |
| data.binance.vision 현물 `aggTrades` | 2026-11-18 파일 있음 [V14] | **미확인** |
| data.binance.vision 현물 `bookTicker` | 2026-11-18 파일 **없음** (404 NoSuchKey) [V14] | 현물 BBO 일별 파일은 이 날짜에 제공되지 않음 |
| data.binance.vision USDⓈ-M `trades` | 2026-11-18 파일 있음 [V14] | **미확인** |
| data.binance.vision USDⓈ-M `bookDepth` | 2026-11-18 파일 있음 [V14] | 파일 형식(가격대별 누적 깊이인지 등)은 내려받지 않아서 **미확인**. 개별 호가 단계 L2가 아닐 수 있다 |
| data.binance.vision USDⓈ-M `bookTicker` | 2026-11-18 파일 **없음** (404) [V14] | 과거 날짜에 있었는지는 **미확인** |
| Tardis Binance USDⓈ-M [V16, 제3자] | "available since 2019-11-17". 채널 `depth`(2020-01-07 이후 depth@0ms), `depthSnapshot`(REST 상위 1000단계), `bookTicker`, `trade`, `aggTrade`. CSV 유형 incremental_book_L2. 수집 위치 GCP 도쿄 | 증분 L2와 BBO가 모두 있다. 유료(가격 미확인) |
| Tardis Bybit 파생 [V17, 제3자] | 선형 계약 "since 2020-05-28". `orderbook.50`, `orderbook.1`, `publicTrade`는 2023-04-05부터. `orderbook.500`은 2025-09-05까지, `orderbook.1000`은 2025-09-04부터 2026-08-19까지, `orderbook.rpi`는 2026-08-19부터 | 깊이 채널이 시기에 따라 바뀌므로 백테스트 구간마다 다른 채널을 써야 한다 |
| Tardis OKX Swap [V18, 제3자] | "available since 2019-03-30". `books-l2-tbt`(10ms)는 2026-05-21까지, `books`(100ms)는 2026-05-21부터, `bbo-tbt`(10ms)는 2022-05-05부터, `trades-all`은 2023-10-19부터 | 2026-05-21 이후에는 tbt 대신 100ms 증분이라 해상도가 낮아졌다 |
| Tardis Binance 현물, Bybit 현물, OKX 현물 | 이번에 열지 않음 → **미확인** | — |
| hftbacktest가 Tardis·Binance 형식을 바로 읽는지 | 이번에 확인하지 않음 → **미확인**. hftbacktest 문서 목록은 `01` [H1]–[H8]에 있다 | — |

「해석」 L3 데이터는 세 곳 모두 없다. 그래서 대기열 위치는 `01`의 확률적 대기열 모형으로 추정해야 한다. 1틱 시장(§3.1)에서는 이 추정 오차가 손익에 직접 영향을 준다.

---

## 8. 권고 「해석」 (검증된 수수료와 측정한 스프레드만 근거로 함)

### 8.1 거래소 × 역할 순위
| 역할 | 1순위 | 2순위 | 근거와 단서 |
|---|---|---|---|
| **메이커(호가) 거래소** | Binance 현물 (LP Tier 1–4: 0 ~ −0.8bp, Tier 1은 USD 25M/주라는 절대 경로가 있음) | OKX 현물 VIP7–9 (−0.2 ~ −0.75bp, 테이커 요율 미확인) | Bybit 현물 MM 요율이 미확인이라 Bybit는 순위에서 뺐다. Bybit 현물 VIP 0의 10bp 메이커 요율은 비현실적이다 [V6] |
| **헤지 거래소** | 메이커 헤지가 가능한 MM 등급의 무기한 (Bybit MM, 예시 기준 G1 −0.1 ~ −0.4bp / Binance 선물 MM은 수치 미확인) | Bybit 무기한 Supreme VIP 메이커 0bp, 테이커 3bp [V6] | 테이커로 헤지하는 한 어느 조합도 손익분기를 넘지 못한다(§4) |
| **테이커(lead-lag) 거래소** | 판단 보류 | — | 해외 3사의 테이커 요율은 Bybit만 확인됐다(현물 4.5–10bp, 무기한 3–5.5bp [V6]). 바이낸스와 OKX의 테이커 요율은 미확인 |

결론적으로 **지금 확인된 수수료와 1틱 스프레드로는 "해외 메이저 종목 메이커 + 테이커 헤지"가 성립하지 않는다.** 이 구조가 성립하려면 (i) 양쪽 레그 모두 리베이트 등급이고 (ii) m이 약 1bp 이하여야 한다. 둘 다 아직 검증되지 않았다.

### 8.2 다음에 확인할 것
1. **바이낸스 일반 VIP 요율(현물, USDⓈ-M)과 선물 MM 리베이트 수치**: 사용자가 공식 fee 페이지 사본을 주거나, 이용 가능한 지역에서 확인해야 한다.
2. **바이낸스 주간 총 현물 메이커 거래량**: 0.05–1% 기준을 USD로 환산하는 데 필요하다.
3. **Bybit mainnet `fee-group-info`**(공개 엔드포인트, 지역 차단 상태)와 현물 MM 프로그램 원문.
4. **OKX 무기한 요율표, 테이커 요율, MM 프로그램 자격 요건.**
5. **바이낸스와 Bybit의 호가 스프레드**: 공개 API 접근이 가능한 위치에서 OKX와 같은 시각에 스냅샷을 받아 비교한다.
6. **마크아웃 m**: Tardis 데이터로 L1–L4 lead-lag 조건부 마크아웃을 측정한다(`04` E2 방식).
7. **이용 자격과 규제**:
   - 바이낸스 API의 451 응답이 Terms "b. Eligibility"를 근거로 들었다 [V13].
   - `03` [S22]에 "FIU에 신고하지 않은 해외 VASP와의 거래는 원칙적으로 차단"이라는 내용이 있다.
   - 사용자 지역에서 해외 거래소를 이용하는 것과 자금을 이동하는 것이 적법한지 법률 자문이 필요하다.

---

## 9. 참고문헌과 접근 불가 URL

### 9.1 참고문헌 (실제로 열어 본 것, 접속일 2026-11-19)
바이낸스 공지는 www.binance.com 공개 CMS JSON 엔드포인트 `https://www.binance.com/bapi/composite/v1/public/cms/article/detail/query?articleCode=<코드>`로 본문을 받았다. HTML 페이지는 봇 차단에 걸렸다.

- [V1] Binance (공식), "Binance Futures Market Maker Program - Negative Maker Fees", https://www.binance.com/en/support/announcement/binance-futures-market-maker-program-negative-maker-fees-360039449551 (게시 2020-02-03, articleCode 360039449551)
- [V2] Binance (공식), "Binance Futures Market Maker Program" FAQ, https://www.binance.com/en/support/faq/binance-futures-market-maker-program-b65fefd0fee84893ad946dc6f707dedc (게시 2020-08-17, lastUpdate 2026-01-02)
- [V3] Binance (공식), "Binance Upgrades Spot Liquidity Provider Program (2026-11-16)", articleCode fdf0711ce61345e697e3dbc067b32e40 (게시 2026-11-18. [V10]의 관련 기사 목록에서 찾음)
- [V4] Binance (공식), "Binance Introduces Maker Fee Rebates to the Spot Market Maker Program", https://www.binance.com/en/support/announcement/binance-introduces-maker-fee-rebates-to-the-spot-market-maker-program-777646dadd8846dab8a84ce32c9b7cc4 (2020-07-22)
- [V5] Binance (공식), "Binance Updates Fiat Liquidity Provider Program (2024-06-25)", https://www.binance.com/en/support/announcement/binance-updates-fiat-liquidity-provider-program-2024-06-25-384f39499e5f4305a0ba2c9254844d35 (게시 2024-06-24, 2024-11-14 수정)
- [V6] Bybit (공식), "Bybit Trading Fee Structure", https://www.bybit.com/en/help-center/article/Trading-Fee-Structure (Last updated 2026-11-05)
- [V7] Bybit (공식 API 문서), "Get Fee Group Structure", https://bybit-exchange.github.io/docs/v5/market/fee-group-info (testnet 예시 응답 포함. 도쿄 이전 배너)
- [V8] Bybit (공식), "Market Maker Incentive Program", https://www.bybit.com/en/help-center/article/Bybit-Market-Maker-Incentive-Program. 페이지는 열렸지만 본문은 "This article is currently not supported on this site"였다
- [V9] OKX (공식, US 사이트로 응답), "Enhanced Liquidity Program (ELP) Maker Order Rebate Adjustment", https://www.okx.com/help/elp-markup-rebate-update (게시 2026-06-02)
- [V10] Binance (공식), "Binance Updates Spot Liquidity Provider Program (2024-09-09)", https://www.binance.com/en/support/announcement/6311b67d26804bf48c5d62f5beb91202 (게시 2024-08-26)
- [V12] OKX 공개 시세 API 실측: `https://www.okx.com/api/v5/market/tickers?instType=SPOT` (08:32:20Z), `…?instType=SWAP` (08:34:28Z), `https://www.okx.com/api/v5/public/instruments?instType=SPOT`, `…?instType=SWAP`
- [V13] Binance 공개 API 응답(HTTP 451), `https://api.binance.com/api/v3/ticker/bookTicker?symbols=[…]` (08:32:20Z)
- [V14] data.binance.vision CHECKSUM 파일 존재 확인: `https://data.binance.vision/data/spot/daily/{trades,aggTrades,bookTicker}/BTCUSDT/…-2026-11-18.zip.CHECKSUM`, `https://data.binance.vision/data/futures/um/daily/{trades,bookTicker,bookDepth}/BTCUSDT/…-2026-11-18.zip.CHECKSUM`
- [V19] Binance (공식), "Binance Futures Fee Structure & Fee Calculations" FAQ, https://www.binance.com/en/support/faq/binance-futures-fee-structure-fee-calculations-360033544231 (lastUpdate 2026-05-01, CMS JSON으로 열람)
- [V16] Tardis.dev (제3자, 신뢰도 낮음), "Binance USDS-M Futures", https://docs.tardis.dev/historical-data-details/binance-futures
- [V17] Tardis.dev (제3자, 신뢰도 낮음), "Bybit Derivatives", https://docs.tardis.dev/historical-data-details/bybit
- [V18] Tardis.dev (제3자, 신뢰도 낮음), "OKX Swap", https://docs.tardis.dev/historical-data-details/okex-swap
- 내부 참조: `01_strategy_components.md` [L1] Plazuelo Pascual et al. (2025), https://arxiv.org/abs/2506.08718. `03_bithumb_feasibility.md` §2.3, [S22]

(범위 변경 전에 연 원화 거래소 관련 자료: 업비트, 빗썸, 코인원 공개 호가와 마켓 API, 블록미디어 1132357·1132415, 뉴스토마토 1311783, 비즈워치 2026/09/29·2026/10/26 기사. 원본은 위 폴더에 있고 이 문서에서는 쓰지 않았다.)

### 9.2 접근 불가 URL (우회하지 않음)
| URL | 상태 |
|---|---|
| 바이낸스 공지·FAQ HTML 페이지 4건(V1, V2, V4, V10의 www 주소) | HTTP 405/202, AWS WAF "Human Verification". 같은 호스트의 공개 CMS JSON으로는 열렸다 |
| https://www.binance.com/en/fee/schedule , /en/fee/trading | 이번에는 다시 요청하지 않았다(`03`에서 차단 확인). VIP 요율 **미확인** |
| https://api.binance.com/api/v3/ticker/bookTicker | HTTP 451 지역 제한 |
| https://api.bybit.com/v5/market/tickers?category=spot | HTTP 403 CloudFront 지역 차단 |
| https://www.theblock.co/post/356887/binance-altcoin-spot-liquidity-program | HTTP 403 Cloudflare. Altcoin LiquidityBoost **미확인** |
| https://www.coindesk.com/markets/2020/02/04/binance-will-soon-reward-market-makers-for-providing-futures-liquidity | HTTP 429 Vercel Security Checkpoint |
| https://www.okx.com/fees | JS 렌더링이라 본문이 비어 있음 |
| https://www.bybit.com/en/help-center/article/Bybit-Market-Maker-Incentive-Program | "not supported on this site" |
| https://www.binance.com/en/vip-portal/liquidity-hub | 요청하지 않음(요청 한도 관리). 미확인 |
| Binance Options MM, Altcoin LiquidityBoost 공지 원문 | URL을 찾지 못함 |
| "Binance Updates Limited-Time Trading Fee Discount and Liquidity Provider Program for USDC-Margined Perpetual Contracts (2025-09-11)" | [V19]에서 제목만 확인. 요청 한도 때문에 열지 않음 |
| https://www.binance.com/en/fee/futureFee , 2024-04-03 USDC 무기한 할인 공지, USDⓈ-M Futures LP Program (2024-06-03) 공지 | 웹 검색 결과에만 나옴. 열지 않음(미확인) |
