# 01. 마켓메이킹 전략 구성요소: 공정가치 · 호가정책 · 역선택 · 체결 현실성

작성일: 2026-11-19 · 범위: Binance→Bithumb lead-lag 테이커 전략을 Bithumb KRW 현물 메이커 호가(cross-exchange MM)로 확장할 때 필요한 이론/측정 구성요소
표기 규칙: 모든 사실 주장에 출처 URL을 붙임. 논문이 **증명·측정한 것**과 필자의 **해석**(「해석」 표시)을 구분. 출처를 찾지 못한 항목은 **미확인**.
원문 확인 방식: PDF를 내려받아 `pdftotext`로 본문(수식·가정·표)을 직접 읽음. 2차 출처로만 확인한 항목은 "(2차 출처)"로 표시.

---

## 0. 요약 표

| 구성요소 | 핵심 수식 | 필요한 파라미터 | 추정법 | 예측 지평 / 감쇠 (문헌 수치) | 출처 |
|---|---|---|---|---|---|
| Weighted mid / L1 imbalance | $I=\frac{Q^b}{Q^b+Q^a}$, $M^w = I P^a + (1-I)P^b$ | 최우선 호가 잔량 | 직접 계산 | Stoikov: 노이즈 크고 마팅게일 아님, 반직관적 사례 존재 | [S1] |
| Micro-price (Stoikov) | $P^{micro}_t=\lim_i E[M_{\tau_i}\mid\mathcal F_t]=M_t+\sum_k g^k(I_t,S_t)$ | 이산화한 (imbalance, spread) 상태의 전이행렬 $Q,R^1,R^2$ | 마르코프 체인 흡수확률, $g^1=(1-Q)^{-1}R^1k$ | 1·5·10분 뒤 mid 변화 평균과 비교 검증, "horizon independent"라고 주장(BAC/CVX 2011-03) | [S1] |
| Multi-level imbalance / VAMP | $\frac{\sum_i^N Q^i_b-\sum_i^N Q^i_a}{\sum_i^N Q^i_b+\sum_i^N Q^i_a}$, VAMP 등 | 깊이 N(가격 %), 표준화 윈도 | rolling z-score | 정량 감쇠 수치 미제시(튜토리얼) → **미확인** | [H4] |
| OFI (Cont–Kukanov–Stoikov) | $e_n$ 이벤트 기여 합 $OFI_k=\sum e_n$, $\Delta P_k=\beta\,OFI_k+\epsilon_k$, $\beta=c/AD^\lambda$ | 깊이 AD, β | 30분 창 OLS | **동시점(contemporaneous)** 설명력 평균 $R^2\approx65\%$(Δt=10s); 이벤트 자기상관 ~10초 내 소멸 | [O1] |
| Multi-level OFI | $\Delta P=\sum_m \beta_m OFI^{(m)}+\epsilon$ | 레벨별 β | Ridge | 동시점 OOS RMSE가 대형틱 65–75%, 소형틱 15–30% 개선 | [O2] |
| Integrated / cross-asset OFI | 다층 OFI의 1주성분 | PCA 가중치 | 30분 창 OLS | 동시점 $R^2$ 71.16%→87.14%; **1분 선행 OOS $R^2$는 음수**, 교차자산 lag 효과는 단기에서만, 지평 증가 시 빠르게 감쇠 | [O3] |
| Lead-lag fair value (leading venue) | $\text{fair}=P^{lead}_t+\overline{\text{basis}}_{W}$ (hftbacktest basis 예제) | basis 이동평균 윈도, 환율 | rolling mean | 암호화폐 CME 선물↔Binance 현물 Hayashi–Yoshida lead-lag ≈ ±60 ms(구간별 부호 상이) | [H6], [L1] |
| AS (2008) | $r=s-q\gamma\sigma^2(T-t)$, $\delta^a+\delta^b=\gamma\sigma^2(T-t)+\frac{2}{\gamma}\ln(1+\frac{\gamma}{\kappa})$ | σ, A, κ, γ, T | λ(δ)=Ae^{-κδ} 적합 | 유한 지평 T | [A1] |
| GLFT (2013) | $\delta^{b}_\infty\approx\frac1\gamma\ln(1+\frac\gamma k)+\frac{2q+1}{2}\sqrt{\frac{\sigma^2\gamma}{2kA}(1+\frac\gamma k)^{1+k/\gamma}}$ | σ, A, k, γ, Q | 거래 데이터로 σ,A,k 보정, γ는 선택 | T→∞ 점근(정상상태) | [G1], [H3] |
| Cartea–Donnelly–Jaimungal 불확실성 | $\delta^{\pm*}_q=(1/\kappa^\pm - h_{q\mp1}+h_q)^+$; drift 모호성 ⇔ running penalty $\phi\sigma^2q^2$ | κ±, λ±, φ_α, φ_λ, φ_κ | 수치 ODE | — | [C2] |
| Cartea–Donnelly–Jaimungal imbalance MM | 체제 $Z_t\in\{1..n_Z\}$, 스프레드 $\Delta_t$ 마르코프 체인, 최우선 호가에만 게시 | λ(Z,Δ), 전이확률, φ | 반일 단위 재귀 예측 | MO 후 10 ms 가격 변화로 측정(100 ms까지 결과 불변) | [C1] |
| Markout | $dr_\tau(o)=\text{sgn}(o)\left(\frac{\mu_{t_0+\tau}}{p_{t_0}}-1\right)\cdot10^4$ bp (μ = micro-price) | 지평 τ | 자체 체결 기록 | Binance BTC 무기한: 앞쪽 큐 −0.296 bp vs 뒤쪽 큐 −1.157 bp | [M1] |
| VPIN | $VPIN_t=\frac1W\sum_{\tau}\frac{|\hat V^B_\tau-\hat V^S_\tau|}{V_\tau}$, BVC $\hat V^B=V\Phi(\Delta p/\sigma_{\Delta p})$ | 버킷 크기, 윈도 W | BVC 분류 | 비판: 단기 변동성 예측력 약함, 거래강도와 기계적 연관(2차 출처) | [V1](2차), [V2](2차) |
| 큐 위치 모델 (L2) | $p=f(\text{back})/(f(\text{back})+f(\text{front}))$, $f=x^n$ 또는 $\ln(1+x)$ | n | 실거래 대비 백테스트 보정 | 수치 정확도 미제시 → **미확인** | [H1], [H2] |
| 지연 모델 | feed / order entry / order response 3분해 | 각 지연 분포 | 미체결 주문 제출로 실측 | ETHUSDT 5일: 주문지연 가정에 따라 SR −0.20 ~ +1.54 ~ −0.38 | [H5], [H7] |

---

## Q1. 공정가치(fair value)

### 1.1 Mid, weighted mid, micro-price (Stoikov)

**정의·가정 (슬라이드 본문, [S1])**
- Mid $M=(P^b+P^a)/2$: 마팅게일이 아님(bid-ask bounce), 저빈도 신호, 잔량 정보 미사용.
- Weighted mid $M^w=IP^a+(1-I)P^b$, $I=Q^b/(Q^b+Q^a)$ (Gatheral–Oomen 2009 인용): 마팅게일 아님, 노이즈 큼. 반례: ask 1주 취소 시 2차 호가가 최우선이 되면서 $M^w$가 32.179→32.1725로 **하락**("ask 취소 후 공정가가 내려간다?").
- 정의: $P^{micro}_t=\lim_{i\to\infty}P^i_t$, $P^i_t=E[M_{\tau_i}\mid\mathcal F_t]$, $\tau_i$ = mid가 바뀌는 (확률적) 시각.
- 가정 1: 정보 $\mathcal F_t=(M_t,I_t,S_t)$가 3차원 마르코프. 가정 2: 동학이 $M_t$ 수준과 독립, $E[M_{\tau_1}-M_t\mid M,I,S]=g^1(I,S)$.
- 정리: $P^i_t=M_t+\sum_{k=1}^i g^k(I_t,S_t)$, $g^{i+1}(I,S)=E[g^i(I_{\tau_1},S_{\tau_1})\mid I,S]$.
- 이산 추정: 상태 $X=(I,S)$ ($n$개 imbalance 구간 × $m$개 spread), 비흡수 전이 $Q_{ij}=P(\Delta M=0\wedge X_{t+1}=j\mid X_t=i)$, 흡수 $R^1_{ik}=P(\Delta M=k\mid X_t=i)$, $R^2$ = mid 변화 시 다음 imbalance 상태.
  $g^1=(1-Q)^{-1}R^1k$, $B=(1-Q)^{-1}R^2$, $g^{i+1}=Bg^i$. $B$가 양의 원소이고 $Wg^1=0$이면 수렴. 대칭화($g^1(i_I,i_S)=-g^1(n-i_I,i_S)$ 형태)로 수렴 조건 확보.
- 데이터·검증: BAC(대형틱), CVX(소형틱) 2011년 3월; 3월 1일로 추정한 $G^*=P^{micro}-M$을 이후 일자의 $M_{t+60}-M_t$, $M_{t+300}-M_t$, $M_{t+600}-M_t$ (초 단위 1·5·10분) 평균과 비교.
- 주장: "micro-price is horizon independent", 고정 지평 평균보다 적은 데이터로 수렴, bid–ask 사이에 위치하는 경향.
- 원 논문(SSRN 2970694)은 접근 불가 → 슬라이드 기준. 감쇠 속도에 대한 정량치(반감기 등)는 슬라이드에 **미제시 → 미확인**.

**후속 확장 [S2]**: Blakely(2024)는 Stoikov micro-price에 상위 호가 레벨 imbalance 기반 보정항(−2~+2 tick 분류)을 Tsetlin machine으로 추가. Databento L3 데이터, TSLA·TEM 2024년 9월 6거래일, N-step 뒤 가격에 대한 L2 오차가 "roughly 10–20 percent improvement". 스프레드가 좁을 때(오후)는 기본 micro-price와 성능이 같다고 보고.

### 1.2 Multi-level imbalance (실무형 정의) [H4]
hftbacktest "Market Making with Alpha – Order Book Imbalance" 튜토리얼:
- Static OBI $=\frac{\sum_i^N Q^i_{bid}-\sum_i^N Q^i_{ask}}{\sum_i^N Q^i_{bid}+\sum_i^N Q^i_{ask}}$; 표준화 버전은 분자만 rolling z-score.
- $VAMP_{bbo}=\frac{P_{bb}Q_{ba}+P_{ba}Q_{bb}}{Q_{bb}+Q_{ba}}$ (가격·수량 교차곱), $VAMP_N$은 mid의 ±1% 등 가격 깊이 N까지.
- Weighted-depth price는 고정 누적수량(예: 500)까지 같은 쪽 가격×수량.
- 사용 방식: `fair_price = mid_price + c1 * alpha`, alpha = 1시간 윈도 표준화 imbalance (예제 BTCUSDT 2023-05, `looking_depth` 비율 깊이).
- 예측 지평·감쇠의 정량치는 튜토리얼에 없음 → **미확인**.

### 1.3 OFI (Cont–Kukanov–Stoikov) [O1]
**정의 (본문 §2)**: 최우선 호가 이벤트 $n$마다
- bid 가격 불변·수량 증가: $e_n=q^B_n-q^B_{n-1}$ (감소도 동일식, 시장가 매도/취소 구분 없음); bid 가격 상승: $e_n=q^B_n$; 하락: $e_n=-q^B_{n-1}$. ask는 부호 반대.
- $OFI_k=\sum_{n=N(t_{k-1})+1}^{N(t_k)}e_n$, $\Delta P_k=(P_k-P_{k-1})/\delta$ (tick 단위).
- 양식화 모형(모든 레벨 깊이 D 동일): $\Delta P=\frac{OFI}{2D}+\epsilon$. 실증 사양 $\Delta P_k=\beta_i OFI_k+\epsilon_k$, $\beta_i=\frac{c}{AD_i^\lambda}+\nu_i$ (양식화 모형은 λ=1).

**측정 결과**: NYSE TAQ 50종목, Δt = 10초, 30분 창별 OLS → 평균 $R^2=65\%$; 종목·시간스케일(10 quote update ≈ 0.5초 미만 ~ 10분)에 걸쳐 결과 유지, Δt가 클수록 적합도 상승. 이벤트 단위 자기·교차상관은 "typically vanish after 10 seconds". 거래량 기반 관계보다 OFI 관계가 덜 노이즈.
**중요**: 이 관계는 **동시점** 설명 회귀이며 예측 회귀가 아님.

**Multi-level OFI [O2]**: Nasdaq 6종목(2016), 레벨 m별 OFI 벡터를 동시점 Δmid에 회귀. OLS는 다중공선성으로 과적합 → Ridge 사용 시 깊은 레벨 계수도 유의. 레벨 추가 시 OOS RMSE가 대형틱 65–75%, 소형틱 15–30% 개선.

**Integrated / cross-asset OFI [O3]**: Nasdaq ITCH(LOBSTER), S&P100 구성종목 2017–2019, 1분 단위.
- 동시점: best-level OFI $R^2$ 71.16% → 다층 OFI 1주성분(integrated OFI) 87.14%; 교차자산 항 추가 시 증분 0.71%p로 미미.
- 예측(1분 선행): OOS $R^2$가 음수(예: FPI[1] −0.37, FCI[1] −0.10; 표 주석에 단위 명시 없음). 교차자산 lag OFI 모형이 유의하게 우수. 저자: 음의 $R^2$이 경제적 무의미를 뜻하지는 않음 → 예측기반 전략 PnL로 제시. 지평 1·3·10·30분 PnL 곡선에서 교차자산 우위는 단기에 집중되고 지평이 길어질수록 더 빨리 감소.

「해석」 문헌상 OFI는 "같은 구간의 가격 변화를 설명"하는 신호로 가장 강하고, 1분 이상 선행 예측력은 매우 약하다. 메이커 호가에서는 OFI를 **수 초 이내 quote skew·취소 트리거**로 쓰는 것이 문헌과 정합적이며, 초 이하 감쇠 속도는 Bithumb 데이터로 직접 측정해야 한다(문헌 수치는 미국 주식).

### 1.4 선행 거래소(leading venue) 가격 결합
- hftbacktest "Market Making with Alpha – Basis" [H6]: Binance 현물·USDM 선물 book_ticker(L1)로 basis = (선물 mid − 현물 mid)의 rolling mean을 계산하고 "fair price is calculated as the spot price + the rolling average of the basis"; basis를 정상(stationary)으로 보고 MA/AR/ARMA 적용 가능하다고 기술. 호가는 `fair_px*(1 ∓ (half_spread ± skew*normalized_position))`.
- 지연 규모 [L1]: Plazuelo Pascual 등(2025) Hayashi–Yoshida 지연상관 $\hat\rho(\ell)=\frac{\sum_{i,j}r^X_ir^Y_j1\{O^\ell_{ij}\neq\emptyset\}}{\sqrt{\sum_i(r^X_i)^2\sum_j(r^Y_j)^2}}$ (비동기 틱 데이터용)를 사용. CME BTC 선물 vs Binance 현물 구간별 lead-lag 시간 +0.066 s(LLR 1.15), +0.063 s(LLR 1.36), −0.057 s(LLR 0.97) 보고 — 부호가 구간마다 바뀜.
- Binance→Bithumb(KRW) 특정 lead-lag 수치를 주는 1차 문헌은 이번 조사에서 찾지 못함 → **미확인**.

「해석」 cross-exchange 공정가치 후보:
$$\hat P^{fair}_{Bithumb}(t)=P^{mid/micro}_{Binance}(t-\ell)\times FX_t\times(1+\bar\pi_W(t)) \;+\; \beta_1\,\widetilde{OBI}_{Bithumb}(t)$$
여기서 $\bar\pi_W$ = 김치 프리미엄의 W-윈도 rolling 평균(hftbacktest basis 예제의 KRW 버전), $\ell$ = 측정된 전파지연, FX는 USDT/KRW 또는 USD/KRW. $\beta_1$과 $\ell$, W는 사용자 기존 lead-lag 연구에서 추정한 값을 재사용. 이 식 자체는 어떤 논문도 검증하지 않음.

---

## Q2. 호가 정책(quoting policy)

### 2.1 Avellaneda–Stoikov (2008) [A1] — 본문 가정·결과
**가정**
1. Mid: $dS_u=\sigma dW_u$ (산술 BM, drift·자기상관 없음; GBM 대신 효용 유한성 위해 선택).
2. CARA 효용, 유한 지평 T: $u(s,x,q,t)=\max_{\delta^a,\delta^b}E_t[-\exp(-\gamma(X_T+q_TS_T))]$.
3. 체결: 매수 시장가가 ask를 $\lambda^a(\delta^a)$의 포아송 강도로 체결. 시장가 크기 멱법칙 $f^Q(x)\propto x^{-1-\alpha}$ ($\alpha$=1.53/1.4/1.5 인용)와 로그 충격 $\Delta p\propto\ln Q$에서 $\lambda(\delta)=Ae^{-\kappa\delta}$, $A=\Lambda/\alpha$, $\kappa=\alpha K$ 유도 ($\Lambda$ = 시장가 빈도; 일 거래량/평균 시장가 크기로 추정 가능). 멱충격이면 $\lambda=B\delta^{-\alpha/\beta}$.
4. 호가는 비용 없이 연속 갱신 가능, 1단위.

**결과**
- Frozen-inventory 무차별가: $r^{a/b}=s+(1\mp2q)\frac{\gamma\sigma^2(T-t)}{2}$, 평균 $r(s,q,t)=s-q\gamma\sigma^2(T-t)$.
- 무한지평 정상판: $\bar r^{a}=s+\frac1\gamma\ln\!\left(1+\frac{(1-2q)\gamma^2\sigma^2}{2\omega-\gamma^2q^2\sigma^2}\right)$ (b는 $1+2q$), $\omega>\frac12\gamma^2\sigma^2q^2$ → $\omega=\frac12\gamma^2\sigma^2(q_{max}+1)^2$가 자연스러운 선택(재고 상한 의미).
- HJB → 지수 ansatz $u=-e^{-\gamma x}e^{-\gamma\theta(s,q,t)}$, q에 대한 점근전개 + 체결항 1차 선형화 → **근사해**
$$r(s,t)=s-q\gamma\sigma^2(T-t),\qquad \delta^a+\delta^b=\gamma\sigma^2(T-t)+\frac2\gamma\ln\!\left(1+\frac\gamma\kappa\right)$$
 스프레드는 지수 강도 가정 때문에 재고와 무관.
- 시뮬레이션: $s=100,T=1,\sigma=2,dt=0.005,q_0=0,\gamma=0.1,\kappa=1.5,A=140$, 1000회.
 | γ | 전략 | 평균 스프레드 | 이익 | std(이익) | 최종 q | std(최종 q) |
 |---|---|---|---|---|---|---|
 | 0.1 | inventory | 1.49 | 65.0 | 6.6 | 0.08 | 2.9 |
 | 0.1 | symmetric | 1.49 | 68.4 | 12.7 | 0.26 | 8.4 |
 | 0.01 | inventory | 1.35 | 68.6 | 8.7 | 0.12 | 5.1 |
 | 1 | inventory | 3.02 | 31.4 | 5.0 | 0.02 | 1.7 |
 | 1 | symmetric | 3.02 | 44.0 | 11.0 | 0.00 | 5.1 |
 (재고 전략은 평균 이익은 약간 낮고 분산이 크게 낮음.) 또한 dt는 일반 tick 간격보다 커야 한다고 언급(너무 잦은 갱신은 체결을 못 봄).

### 2.2 GLFT (Guéant–Lehalle–Fernandez-Tapia) [G1] — 추가된 것
- **재고 제약** $q\in\{-Q,\dots,Q\}$ 추가, $q=\pm Q$에서는 한쪽만 호가.
- 변수변환으로 HJB를 **선형 ODE 계** $\dot v_q=\alpha q^2v_q-\eta(v_{q-1}+v_{q+1})$, $v_q(T)=1$로 환원; $\alpha=\frac k2\gamma\sigma^2$, $\eta=A(1+\frac\gamma k)^{-(1+k/\gamma)}$. 검증정리 제공(원 AS 해의 admissibility는 열린 문제였다고 지적).
- 최적 호가(정확해): $\delta^{b*}=\frac1k\ln\frac{v_q}{v_{q+1}}+\frac1\gamma\ln(1+\frac\gamma k)$, $\delta^{a*}=\frac1k\ln\frac{v_q}{v_{q-1}}+\frac1\gamma\ln(1+\frac\gamma k)$.
- **점근(T→∞)**: 행렬 M의 최소고유값 고유벡터 $f^0$로 표현; 연속화(조화진동자) $\tilde f^0(x)\propto\exp(-\frac12\sqrt{\alpha/\eta}\,x^2)$ → **닫힌형 근사**
$$\delta^{b*}_\infty(q)\simeq\frac1\gamma\ln\!\left(1+\frac\gamma k\right)+\frac{2q+1}{2}\sqrt{\frac{\sigma^2\gamma}{2kA}\left(1+\frac\gamma k\right)^{1+\frac k\gamma}},\quad
\delta^{a*}_\infty(q)\simeq\frac1\gamma\ln\!\left(1+\frac\gamma k\right)-\frac{2q-1}{2}\sqrt{\cdots}$$
$$\psi^*_\infty\simeq\frac2\gamma\ln\!\left(1+\frac\gamma k\right)+\sqrt{\frac{\sigma^2\gamma}{2kA}\left(1+\frac\gamma k\right)^{1+\frac k\gamma}}$$
 즉 AS와 달리 스프레드가 σ에 √ 비례하고 시간 T에 의존하지 않음.
- 확장: drift μ ($\beta=k\mu$ 항, 근사식에 $\pm\mu/(\gamma\sigma^2)$ 이동), **market impact / adverse selection** $dS_t=\sigma dW_t+\xi dN^a_t-\xi dN^b_t$ → $\delta^{b}_\infty\simeq\frac1\gamma\ln(1+\frac\gamma k)+\frac\xi2+\frac{2q+1}2e^{k\xi/4}\sqrt{\cdots}$, 스프레드에 $+\xi$ 및 $e^{k\xi/4}$ 배수.
- 예시 파라미터: σ=0.3 Tick·s^{-1/2}, A=0.9 s^{-1}, k=0.3 Tick^{-1}, γ=0.01 Tick^{-1}, T=600 s.
- 백테스트 실무(§7): 호가를 가장 가까운 tick으로 반올림; ATS(평균 거래크기) 주문을 Δt 동안 유지; "σ, A and k can be calibrated on trade-by-trade limit order book data while γ has to be chosen"; 실무상 A,k는 시장 스프레드의 함수여야 함; γ는 하루 재고가 ±10 ATS 안에 머물도록 임의 선택; 체결 가정 = 호가 이상 가격에 거래 발생 시 전량 체결(France Telecom, 2012-03-15).

### 2.3 Cartea–Jaimungal 계열 — 추가된 것
**(a) Cartea–Donnelly–Jaimungal, "Algorithmic Trading with Model Uncertainty" (SIFIN 2017) [C2]**
- 기준모형: $dS=\alpha dt+\sigma dW$, 시장가 도착 포아송 $\lambda^\pm$, 체결확률 $p^\pm(y)=e^{-\kappa^\pm y}$ → 체결강도 $\lambda^\pm e^{-\kappa^\pm\delta^\pm}$. MM은 **위험중립**이되 재고 상·하한, 목표 $E[X_T+q_T(S_T-\ell(q_T))]$.
- 해: $H=x+qS+h_q(t)$, $\delta^{\pm*}_q(t)=\left(\frac1{\kappa^\pm}-h_{q\mp1}(t)+h_q(t)\right)^+$. 1/κ = 무한지평·무제약 위험중립 최적 깊이.
- 모호성: drift(φ_α)·MO 도착(φ_λ)·체결확률(φ_κ) 각각에 대한 상대엔트로피형 벌점. **drift 모호성은 running inventory penalty $\phi\sigma^2\int q^2$와 동치($\phi=\frac12\varphi_\alpha$)** — 즉 실무의 φ 패널티에 이론적 근거 부여. σ는 φ_α>0일 때만 전략에 영향.
- 시뮬레이션(참 모형: short-term alpha $d\alpha=-\beta_\alpha\alpha dt+\epsilon^+dM^+-\epsilon^-dM^-$, 상호여기 Hawkes 도착, 평균회귀 κ): drift 모호성 증가로 Sharpe가 "considerably increased", 도착/체결 모호성은 Sharpe 거의 일정하게 기대이익 증가. 그림 예시 파라미터 κ=15, λ=2, σ=0.01, θ=0.01, q∈[−3,3], T=10 s.

**(b) Cartea–Donnelly–Jaimungal, "Enhancing Trading Strategies with Order Book Signals" [C1]** — alpha/imbalance 신호 결합
- $\rho_t=\frac{V^b-V^a}{V^b+V^a}$; buy-heavy $\rho>1/3$, sell-heavy $\rho<-1/3$.
- 실증(Nasdaq 2014, 11종목): MO의 91.6–99.9%가 최우선 호가 잔량만으로 체결(INTC/ORCL은 깊은 레벨 체결이 약 0.1%). 최우선에 항상 양방향 게시하는 zero-intelligence MM은 중간가 청산을 허용해도 **기대이익 음수**(역선택). MO 직후 10 ms 중간가 변화 분포가 imbalance 체제에 따라 뚜렷이 다름(100 ms 창에서도 결과 불변). 거래일의 0.5% 미만에 해당하는 MO 직후 50 ms에 전체 LO 이벤트의 약 40–90%가 집중.
- 모형: 가격·imbalance 체제 $Z_t$·스프레드 $\Delta_t$가 이중확률 포아송 랜덤측도로 동시 점프, $(Z,\Delta)$는 연속시간 마르코프 체인; 대형틱 가정으로 **최우선에만 게시**(깊이가 아닌 post 여부가 제어변수), 목표 $E[X_T+q_T(S_T-\ell(q_T,\Delta_T))-\phi\int q^2]$.
- OOS(2014-07~12, 1375개 30분 구간, Q=50): $n_Z=3,5$가 $n_Z=1$보다 우수, φ 증가 시 평균 PnL↑·표준편차↓.
- 「해석」 이 논문의 핵심 메시지는 "연속 깊이 δ를 최적화하는 AS/GLFT는 대형틱에서 사실상 '항상 최우선 게시'로 퇴화"한다는 것. Bithumb KRW 현물도 종목별 상대 tick이 크면 같은 문제가 생긴다(종목별 tick/가격 비율 확인 필요).

**(c) Cartea–Jaimungal–Ricci 단기 alpha 모형**: CDJ(2017)가 참 모형으로 인용하는 수준만 확인, 원문 미열람 → 세부 **미확인**.

**(d) 기타 열람 자료**
- Pulido–Rosenbaum–Sfendourakis [P1]: 효율가격 BM + uncertainty-zone(η) 중간가, MM은 가격이 아니라 **수량**을 제어. 아래 Q3.3 참조.
- Wang–Ventre–Polukarov(2025) [R1]: 적대적 RL MM에 "호가 안 함" 행동 추가 시 수익/Sharpe 개선을 보고(초록·서론 수준 확인).
- Asadulaev(2026) [R2]: AS 구조 유지 + 체제추정 $\xi_t=(\sigma_t,A^b_t,A^a_t,\kappa^b_t,\kappa^a_t,c^b_t,c^a_t)$ ($c$=국소 역선택 비용). hftbacktest로 BTCUSDT(2025-01, 약 1,260만 이벤트, 855.56분) 백테스트, power-prob 큐 모델·post-only·부분체결 없음. GLFT grid/AS grid 수익 −0.001782/−0.001752 (Sharpe −27.88/−27.26), 제안 기법 +0.002167(Sharpe 28.57), 일 거래수 4637.82/4531.08/477.85. 지연 데이터: 50,090건, entry 중앙값 ≈570.6 ms, response ≈427.9 ms.

### 2.4 파라미터 추정 실무
**hftbacktest GLFT 튜토리얼 [H3]** (ETHUSDT, 2022-10)
1. 100 ms마다 시장 체결의 mid 대비 도달 깊이(최대 거리)를 기록 → 10분(6,000 step) 창에서 "우리 호가 위치 δ보다 깊이 도달한 체결 수"로 λ(δ) 계산(같은 가격은 제외, 큐 위치 무시).
2. $\log\lambda=-k\delta+\log A$ 선형회귀; 전체 범위 적합은 근처에서 과대·깊은 곳에서 과소 추정 → **가까운 범위로 재적합**.
3. $\sigma=\text{std}(\Delta mid_{100ms})\times\sqrt{10}$ (tick/√s).
4. Guéant(Optimal market making) 식 (4.6)(4.7)을 사용: $c_1=\frac1{\xi\Delta}\ln(1+\frac{\xi\Delta}k)$, $c_2=\sqrt{\frac{\gamma}{2A\Delta k}(1+\frac{\xi\Delta}k)^{\frac k{\xi\Delta}+1}}$, half spread $=c_1+\frac\Delta2\sigma c_2$, skew $=\sigma c_2$; GLFT는 Δ=1, ξ=γ. bid = fair − (half spread + skew·q), ask = fair + (half spread − skew·q).
5. 수치 예: half_spread ≈ 20.47 tick, skew ≈ 9.76 → 해당 깊이에 도달하는 시장 체결은 step당 약 1.86%; 무보정 백테스트 SR −246.4 → 조정계수 adj1, adj2 도입. 튜토리얼 자체 주석: 강도 함수가 tick이 아닌 **half-tick 단위로 잘못 계산**되어 있음(결과 보존 위해 미수정).
 (Guéant "Optimal market making" 원문은 이번에 직접 열람하지 않음 → 식은 튜토리얼 인용 기준.)

**Hummingbot AS 구현 [HB1][HB2][HB3]** (master 소스)
- `q = (base_balance − q_target)/inventory`: **정규화된 재고**.
- 예약가 `r = mid − q·γ·vol·time_left_fraction`, 스프레드 `γ·vol·τ + (2/γ)·ln(1+γ/κ)` — 원 논문의 σ²(T−t) 대신 **σ(표준편차)** 사용; 주석에서 단위 불일치를 이유로 의도적 변경이라 설명. 무한지평 모드는 논문 식에 "mistakes"가 있다며 `time_left_fraction=1` 고정으로 대체. 최소 스프레드로 클램프.
- κ, α(=A) 추정: 각 체결의 직전 mid 스냅샷 대비 거리 $|p_{trade}-mid|$를 가격레벨로, 레벨별 **체결 수량 합**을 λ로 하여 `curve_fit(a·exp(−b·t), dogbox, bounds≥0)`; 샘플 버퍼 30.
- 변동성: `InstantVolatilityIndicator` = $\sqrt{\sum(\Delta p)^2/n}$ (평균 제거 없는 tick 간 변화).
- 「해석」 Hummingbot의 λ 적합은 "그 깊이 이상 도달한 시장가 빈도(생존함수)"가 아니라 "그 거리에서 발생한 체결 수량"에 맞추므로 AS의 정의와 다르며, 시간 정규화도 없다. 그대로 쓰면 κ가 왜곡될 수 있음.

**γ 선택**: GLFT는 재고 범위 기준 임의 선택 [G1], hftbacktest도 "arbitrarily chosen" [H3]. 체계적 γ 추정 절차는 **미확인**.

---

## Q3. 역선택(adverse selection)

### 3.1 Markout 측정
**정의 (Albers–Cucuringu–Howison–Shestopaloff, Binance BTCUSDT 무기한 실거래 실험 [M1])**
- 부호: sgn(o)=+1 매수, −1 매도; 양수 = 유리(favorable), 음수 = 불리(adverse).
- 즉시 drift: 체결 시각 $t_0+\tau_0$(매칭엔진 처리 직후) 기준, mid가 불변이면 **signed micro-price 수익률** $\text{sgn}(o)(\mu_{t_0+\tau_0}/p_{t_0}-1)\cdot10^4$, mid가 변했으면 mid 수익률.
- 지평 τ: $dr_\tau(o)=\text{sgn}(o)\left(\frac{\mu_{t_0+\tau}}{p_{t_0}}-1\right)\cdot10^4$ bp — **기준가는 micro-price μ**, $p_{t_0}$는 메이커의 경우 near-side 최우선가(= 지정가).
- 결과 섹션의 markout은 "limit price vs midprice one second after" (1초, mid 기준).
- 실험: 2024-02-12~19, 최소수량 메이커 주문 232,897건(체결 127,051, 취소 105,846); 수수료 maker −0.5 bp(리베이트), taker 1.5 bp; tick ≈0.03 bp.
- 결과: near-side 큐 큼·opposite 작음(불리한 imbalance) — 앞쪽 큐(0–10%) **−0.296 bp**, 뒤쪽(75–100%) **−1.157 bp**; near 작음·opposite 큼 — −0.539 vs −0.763 bp(큐가 작으면 위치 차이 무의미). 체결확률과 체결 후 수익 사이 **음의 상관**("fundamental trade-off") → imbalance에 **역행(contrarian)** 하는 메이커만 유효한 경우가 많다고 결론.
- 체결확률 회귀: $z=\beta_0+\beta_1Q^{near}+\beta_2Q^{opp}+\beta_3\,imb$, $R^2=0.946$, $\beta=(0.5649,0.0159,0.1013,-0.3166)$.
- 특징량 지평: 100 ms, 1 s, 5 s, 30 s, 300 s.

**Negative drift [M2]**: DeLise(2024)는 이산 모형에서 "limit order fills are caused by and coincide with adverse price movements"(체결 자체가 불리한 가격 이동과 동시 발생)을 증명하고, 10년 국채선물 시뮬레이션으로 확인.

「해석」 실무 markout 규약 제안: (i) 기준가를 mid와 micro-price 둘 다 기록, (ii) 지평 {0+, 100 ms, 1 s, 5 s, 30 s, 300 s}, (iii) 부호는 메이커 관점 sgn·(ref_{t+τ} − fill_px), (iv) 수수료·리베이트 차감 전/후 분리, (v) Bithumb 체결가 기준 + Binance 선행가 기준을 병행해 "lead-lag에 의해 이미 결정된 손실"을 분해. 이 규약은 문헌의 정의를 조합한 것으로 별도 검증 없음.

### 3.2 VPIN과 비판
- 정의(2차 출처, Karpman–Basu–Easley [V1]): $VPIN_t=\frac1W\sum_{\tau=t-W+1}^t\frac{|\hat V^S_\tau-\hat V^B_\tau|}{V_\tau}$, BVC $\hat V^B_t=V_t\,\Phi(\Delta p_t/\sigma_{\Delta p})$, $\hat V^S=V-\hat V^B$. 원 정의는 **거래량 버킷(volume clock)** 기반.
- 원 논문(Easley–López de Prado–O'Hara, RFS 2012): SSRN·NYU Stern 사본 모두 이 세션에서 접근 불가 → 버킷 크기·일 50버킷 등 권장값 **미확인**.
- 비판(Andersen–Bondarenko, JFM 2014): 원문 접근 불가. 2차 출처 [V2]에 따르면 거래강도·내재변동성 등 실시간 관측 지표를 통제한 공식 검정에서 유의성을 유지하지 않으면 의미 없다고 주장했고, 버킷 크기·time bar·거래분류·이동평균 길이의 상호작용이 VPIN의 수준과 동학을 좌우한다고 지적. 검색 요약에는 "VPIN 사상 최고치가 flash crash **이후**에 나왔다", "예측력은 주로 거래강도와의 기계적 연관"이라는 내용이 있으나 원문 미확인 → **미확인(원문 기준)**.
- 「해석」 Bithumb은 체결 메시지에 매수/매도 구분이 있으면 BVC가 불필요하고 실제 aggressor 부호로 VPIN 유사 지표(버킷별 |매수−매도|/V)를 만들 수 있음. 다만 위 비판대로 거래강도·실현변동성 대비 증분 정보가 있는지 먼저 검정해야 함.

### 3.3 "Imbalance is the worst-kept secret" [P1]
- 문구 출처: 저자들이 Sasha Stoikov의 2014년 세미나 발언으로 인용.
- 모형: 효율가격 $dS=\sigma dW$ (Bachelier), tick δ, 중간가는 uncertainty-zone 모형(η)으로 점프, **유일 MM이 효율가격을 알고 최우선 bid/ask 수량** $q^a,q^b$를 제어(가격은 반 tick 고정, 대형틱). 시장가는 효율가격–mid 거리 $Y=S-P$에 의존하는 강도, 거래량 표지 포함. CARA 효용.
- 증명: 결합 HJB PDE 계의 고전해 존재·유일성, 연속 재고에서 최적제어 유일성.
- 수치결과(T=3600, δ=0.01, η=0.2, $\bar Q=50$, 선형 강도): 최적 게시 수량이 만드는 imbalance가 Y의 단조함수 → **imbalance가 예측적이 되는 것이 최적 반응**임을 내생적으로 보임. 단, 관계가 **MM의 재고 $Q_t$에 의존**(외부 관찰자는 모름).
- η 추정: $\hat\eta=N^c/(2N^a)$ (continuation/alternation 수).
- 실증 수치(예측 정확도 등)는 이 논문에 없음(이론 논문). 「해석」 imbalance는 상대 MM의 재고 상태에 오염된 신호이며, 정보 우위가 있는 MM이 볼륨으로 "말하는" 결과일 수 있다 → Bithumb에서 imbalance를 따라가면 그 MM의 재고 조정에 역선택당할 수 있음. 또한 [M1]의 "contrarian 메이커" 결과와 함께 보면, imbalance 방향으로 quote를 기울이는 단순 규칙은 체결확률-역선택 trade-off 때문에 손실 가능.

---

## Q4. 체결 현실성(fill realism)

### 4.1 큐 위치 모델 (hftbacktest, L2 = Market-By-Price) [H1][H2]
- 문서: "If an exchange doesn't provide Market-By-Order, you have to guess it by modeling. HftBacktest currently only supports Market-By-Price that is most crypto exchanges provide."
- **RiskAverseQueueModel**: 취소/정정에 의한 수량 감소는 항상 큐 꼬리에서 발생 → 내 앞 수량은 **같은 가격 거래로만** 감소. 가장 보수적. (소스: `front_q_qty -= trade_qty`, 깊이 감소 시 `min(front, new_qty)`.)
- **ProbQueueModel**: 레벨 수량 감소 chg(거래분 차감 후)가 내 앞/뒤에 확률적으로 배분:
 $$\text{front}'=\min\!\Big(\text{front}-(1-p)\,chg+\min(\text{back}-p\,chg,0),\;\text{new\_qty}\Big)$$
 $p$ = "내 **뒤**에서 감소가 일어날 확률":
 - PowerProbQueueFunc: $p=\frac{f(back)}{f(back)+f(front)}$, $f(x)=x^n$
 - PowerProbQueueFunc2: $p=\frac{f(back)}{f(back+front)}$
 - PowerProbQueueFunc3: $p=1-f\!\left(\frac{front}{front+back}\right)$
 - LogProbQueueFunc(2): $f(x)=\ln(1+x)$ — 레벨 총수량에 따라 확률 프로파일이 달라짐
 - 조건: 큐 맨 앞이면 p(0)=0, 맨 뒤면 p(1)=1. 수량 증가는 앞 수량에 영향 없음. 체결은 front가 음수가 되는 만큼(lot 반올림).
 - 근거 문헌: rigtorp.se 블로그, quant.stackexchange, Almgren 강의자료 (이번에 직접 열람 안 함).
- 체결 규칙(NoPartialFillExchange): 매수 주문은 가격 ≥ best ask, 또는 가격 > 매도 체결가, 또는 큐 맨 앞 & 가격 = 체결가일 때 전량 체결. 리플레이 방식이라 **자기 주문의 시장충격 없음** — 소량 가정.
- L3 FIFO 모델(L3FIFOQueueModel): 가격-시간 우선 FIFO로 직접 추적; 단 Pro-Rata 등 비FIFO 매칭이면 L3라도 오차.
- 정확도: Probability Queue 튜토리얼은 모델별 누적수익 곡선만 제시하고 "proper queue position modeling by comparing backtest and real trading results"를 권고. Level-3 튜토리얼(CME BTC 선물, Databento MBO)은 L3에서 L2를 재구성해 L3 FIFO vs L2(power_prob_queue_model3(3.0)) 비교 — "for some strategies, Level-2 estimation may be sufficiently accurate, while for others, it may not be", L3도 implied order 미포함 등으로 실거래 검증 필요. **L2 추정의 정량 오차(예: 체결률 x% 차이)는 문서에 수치 없음 → 미확인**.
- Albers 등 [M1]: "with Binance's L2 data, accurately tracking an order's queue position—and thus its outcome—is impossible"; LA/LB(앞·뒤 수량)는 L3가 필요하나 "not available on the main cryptocurrency exchanges". 그래서 저자들은 합성주문 대신 **실거래 실험**을 택함. 큐 위치 $QP=LA/(LA+LB)$, 0=맨 앞.

### 4.2 지연 모델 [H2][H5][H7]
- 3분해: **feed latency**(거래소 이벤트 송출→로컬 수신; exch_ts vs local_ts 두 타임스탬프로 처리), **order entry latency**(요청→매칭엔진 처리), **order response latency**(처리→로컬 응답 수신; 체결 통보도 영향).
- 모델: ConstantLatency; IntpOrderLatency(실측 (req_ts, exch_ts, resp_ts) 보간; "most accurate … if you have the data with a fine time interval", 실측은 **체결 불가능한 가격의 주문을 주기적으로 제출/취소**해서 수집); 실측이 없으면 feed latency에 배수·오프셋을 곱해 생성(예: entry = 4×feed, response = 3×feed). 음수 지연 = 거래소 거부(과부하 등) 표시.
- 영향 수치(Impact of Order Latency 튜토리얼, ETHUSDT 2023-04-01~05, GLFT grid): 주문지연=feed지연 가정 SR −0.198 (수익 −0.001021); **실측 live order latency** SR +1.536 (수익 +0.007814); 증폭(4×/3×) SR −0.377 (수익 −0.002163). → 동일 전략도 지연 가정만으로 Sharpe 부호가 바뀜.
- [R2]의 BTCUSDT 데이터: entry 중앙값 ≈570.6 ms, response ≈427.9 ms(1초 상한 처리).

### 4.3 L2 vs L3 오차 정리
| 항목 | L2(MBP)에서 가능? | 근거 |
|---|---|---|
| 앞 수량 초기값 | 가능(게시 시점 레벨 수량) | [H2] 소스 |
| 취소가 내 앞/뒤 중 어디서 났는지 | 불가 → 확률 모델 가정 | [H1][H2] |
| 정확한 큐 위치·체결 여부 | 불가("impossible") | [M1] |
| L2 오차 크기(정량) | **미확인** | [H8] 정성 서술만 |

---

## 5. 빗썸 적용 시 시사점 (전부 「해석」)

1. **공개 L2(WebSocket orderbook/transaction)로 추정 가능**: weighted mid·multi-level OBI·VAMP, L1/다층 OFI(레벨 수량 변화로 $e_n$ 근사; 단 스냅샷 간격이 이벤트보다 거칠면 OFI는 순 변화로만 잡힘), 실현 σ(Δmid), 체결의 aggressor 부호 기반 순주문흐름·VPIN 유사지표, 시장가 도달깊이 기반 λ(δ)=Ae^{-κδ}(hftbacktest 방식, 생존함수 정의 유지), Stoikov micro-price 전이행렬, Binance 대비 lead-lag ℓ(Hayashi–Yoshida)과 프리미엄 rolling basis.
2. **L2로는 근사만 가능**: 큐 위치(Power/Log prob 모델 필요, n은 실거래 대비 보정), 따라서 λ(δ)를 "우리 주문 기준 체결강도"로 바꾸는 것, 앞쪽/뒤쪽 큐별 markout 분해.
3. **L3 또는 자기 체결(private fills) 필요**: 실제 체결확률·큐 위치별 markout([M1]식), 주문 지연 분포(IntpOrderLatency용 req/exch/resp 타임스탬프), 거부·레이트리밋 영향, 자기 주문의 시장충격. Bithumb이 MBO(L3)를 제공하는지는 이 문서 범위 밖(별도 파일 참조) → 여기서는 **미확인**. 결국 [M1]처럼 **소액 실거래 실험**(최소수량 양방향 최우선 게시)으로 체결·markout·지연 데이터를 직접 모으는 것이 가장 신뢰도 높은 경로.
4. **모형 선택**: Bithumb 종목의 상대 tick이 크면(스프레드 1 tick이 잦으면) [C1]의 지적대로 AS/GLFT 연속 깊이는 "최우선 게시 여부" 문제로 퇴화 → imbalance/lead-lag 신호로 **게시/취소·skew**를 결정하는 이산 정책([C1]의 구조)이 적합. tick이 작은 종목은 GLFT 닫힌형 + fair = Binance 선행가 기반이 출발점.
5. **역선택이 핵심 리스크**: 기존 테이커 전략이 이용하던 lead-lag 정보가 그대로 메이커 호가의 역선택 원천이 됨(Binance가 먼저 움직이면 Bithumb 메이커 호가는 낡은 호가가 되어 picked off). 따라서 메이커 확장의 성패는 (Binance 이벤트 → Bithumb 호가 취소) 왕복 지연이 경쟁 테이커의 (Binance 이벤트 → Bithumb 테이크) 지연보다 짧은지에 달림. 이 비교 수치는 문헌에 없음 → 실측 필요.
6. **백테스트 신뢰도**: hftbacktest 예시처럼 지연 가정만으로 SR 부호가 바뀌므로, Bithumb 실측 지연 없이 낸 메이커 백테스트 결과는 의사결정 근거로 쓰기 어려움.

---

## 6. 참고문헌 (직접 열람한 URL)

- [A1] Avellaneda & Stoikov (2008), High-frequency trading in a limit order book — https://math.nyu.edu/~avellane/HighFrequencyTrading.pdf
- [G1] Guéant, Lehalle & Fernandez-Tapia, Dealing with the Inventory Risk (arXiv 1105.3115v5) — https://arxiv.org/abs/1105.3115 , PDF https://arxiv.org/pdf/1105.3115
- [C1] Cartea, Donnelly & Jaimungal, Enhancing Trading Strategies with Order Book Signals — https://ora.ox.ac.uk/objects/uuid:006addde-3a03-4d75-89c1-04b59026e1c0/files/me4008e0ecca779b45d59231ebca3e69c
- [C2] Cartea, Donnelly & Jaimungal (2017), Algorithmic Trading with Model Uncertainty, SIFIN 8 — https://ora.ox.ac.uk/objects/uuid:32248d98-3e1a-499a-ae2f-8cddd64beb4c/files/mfad4d8e1e746ae46c316870ff219aa74
- [S1] Stoikov, The Micro-Price (Gatheral60 슬라이드) — https://www.ma.imperial.ac.uk/~ajacquie/Gatheral60/Slides/Gatheral60%20-%20Stoikov.pdf
- [S2] Blakely (2024), High resolution microprice estimates … Tsetlin Machines — https://arxiv.org/abs/2411.13594
- [P1] Pulido, Rosenbaum & Sfendourakis, Understanding the worst-kept secret of high-frequency trading — https://arxiv.org/abs/2307.15599
- [R1] Wang, Ventre & Polukarov (2025), Robust Market Making: To Quote, or not To Quote — https://arxiv.org/abs/2508.16588
- [R2] Asadulaev (2026), Zero-shot adaptation to order book dynamics — https://arxiv.org/abs/2605.21707
- [O1] Cont, Kukanov & Stoikov, The price impact of order book events — https://arxiv.org/abs/1011.6402
- [O2] Xu, Gould & Howison, Multi-Level Order-Flow Imbalance in a Limit Order Book — https://arxiv.org/abs/1907.06230
- [O3] Cont, Cucuringu & Zhang, Cross-Impact of Order Flow Imbalance in Equity Markets — https://arxiv.org/abs/2112.13213
- [M1] Albers, Cucuringu, Howison & Shestopaloff, The Market Maker's Dilemma — https://arxiv.org/abs/2502.18625
- [M2] DeLise (2024), The Negative Drift of a Limit Order Fill — https://arxiv.org/abs/2407.16527
- [L1] Plazuelo Pascual et al. (2025), Price Discovery in Cryptocurrency Markets — https://arxiv.org/abs/2506.08718
- [V1] Karpman, Basu & Easley (2022), Learning Financial Networks with High-frequency Trade Data (VPIN/BVC 정의, 2차 출처) — https://arxiv.org/abs/2208.03568
- [V2] An Empirical Analysis on Financial Markets: Insights from the Application of Statistical Physics (Andersen–Bondarenko 요약, 2차 출처) — https://arxiv.org/abs/2308.14235
- [H1] hftbacktest, Order Fill — https://hftbacktest.readthedocs.io/en/latest/order_fill.html
- [H2] hftbacktest 소스 queue.rs — https://raw.githubusercontent.com/nkaz001/hftbacktest/master/hftbacktest/src/backtest/models/queue.rs ; latency.rs — https://raw.githubusercontent.com/nkaz001/hftbacktest/master/hftbacktest/src/backtest/models/latency.rs ; README — https://raw.githubusercontent.com/nkaz001/hftbacktest/master/README.rst
- [H3] hftbacktest, GLFT Market Making Model and Grid Trading — https://hftbacktest.readthedocs.io/en/latest/tutorials/GLFT%20Market%20Making%20Model%20and%20Grid%20Trading.html
- [H4] hftbacktest, Market Making with Alpha – Order Book Imbalance — https://hftbacktest.readthedocs.io/en/latest/tutorials/Market%20Making%20with%20Alpha%20-%20Order%20Book%20Imbalance.html
- [H5] hftbacktest, Latency Models — https://hftbacktest.readthedocs.io/en/latest/latency_models.html ; Order Latency Data — https://hftbacktest.readthedocs.io/en/latest/tutorials/Order%20Latency%20Data.html
- [H6] hftbacktest, Market Making with Alpha – Basis — https://hftbacktest.readthedocs.io/en/latest/tutorials/Market%20Making%20with%20Alpha%20-%20Basis.html
- [H7] hftbacktest, Impact of Order Latency — https://hftbacktest.readthedocs.io/en/latest/tutorials/Impact%20of%20Order%20Latency.html
- [H8] hftbacktest, Level-3 Backtesting — https://hftbacktest.readthedocs.io/en/latest/tutorials/Level-3%20Backtesting.html ; Probability Queue Position Models — https://hftbacktest.readthedocs.io/en/latest/tutorials/Probability%20Queue%20Models.html ; 문서 홈 — https://hftbacktest.readthedocs.io/
- [HB1] Hummingbot AS 전략 — https://raw.githubusercontent.com/hummingbot/hummingbot/master/hummingbot/strategy/avellaneda_market_making/avellaneda_market_making.pyx
- [HB2] Hummingbot trading intensity — https://raw.githubusercontent.com/hummingbot/hummingbot/master/hummingbot/strategy/__utils__/trailing_indicators/trading_intensity.pyx
- [HB3] Hummingbot instant volatility — https://raw.githubusercontent.com/hummingbot/hummingbot/master/hummingbot/strategy/__utils__/trailing_indicators/instant_volatility.py
- The Microstructure Lab, Microstructure Essentials: Avellaneda… — https://themicrostructurelab.substack.com/p/microstructure-essentials-avellaneda (열람 가능했으나 본문은 도입부만 노출되어 인용하지 않음)

## 7. 접근 불가 URL

- https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2970694 (Stoikov micro-price 원 논문, SSRN 403 — 슬라이드로 대체)
- https://www.cambridge.org/9781107091146 (Cartea–Jaimungal–Penalva 교재, 403)
- https://github.com/nkaz001/hftbacktest , https://github.com/hummingbot/hummingbot (GitHub 웹 UI, 403 — raw 파일로 대체)
- https://raw.githubusercontent.com/nkaz001/hftbacktest/master/README.md (404 — README.rst로 대체)
- https://raw.githubusercontent.com/hummingbot/hummingbot/master/hummingbot/strategy/__utils__/trailing_indicators/instant_volatility.pyx (404 — .py로 대체)
- https://docs.rs/hftbacktest/latest/hftbacktest/backtest/models/ (프록시 거부 — raw 소스로 대체)
- https://www.stern.nyu.edu/sites/default/files/assets/documents/con_035928.pdf (Easley–López de Prado–O'Hara VPIN 원문 사본, 세션 네트워크 허용 목록 밖)
- https://papers.ssrn.com/abstract=1695596 (VPIN 원문 SSRN — SSRN 차단 지시에 따라 시도 안 함)
- https://repec.econ.au.dk/repec/creates/rp/11/rp11_50.pdf (Andersen–Bondarenko 워킹페이퍼, 프록시 거부)
- https://export.arxiv.org/api/query (arXiv 검색 API, 프록시 거부)
