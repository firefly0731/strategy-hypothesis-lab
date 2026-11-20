# crypto_dirty_carry: 팩터 중립 더티 캐리 (Binance USDⓈ-M 무기한)

펀딩비가 높은 종목은 숏, 낮은 종목은 롱해서 양쪽에서 펀딩을 받으려는 전략이야. 달러 중립과 BTC 베타 중립을 맞춰서 방향성 노출을 줄여.
기본 유니버스는 Binance **USDC 마진 무기한**이야. `--quote USDT`로 바꾸면 USDT 마진 무기한으로도 돌릴 수 있어.

> 상태: 파이프라인과 검증 테스트만 있어. `RESEARCH_PROTOCOL.md`의 채택 관문은 아직 하나도 통과하지 않았어(문헌 정리, 홀드아웃, CPCV, 연도별 분해).

## 구조

| 파일 | 역할 |
|---|---|
| `config.py` | `StrategyConfig`, `CostConfig`. 창 길이는 막대 수가 아니라 기간(`"30D"`)으로 지정해. |
| `data.py` | `MarketData`(입력 검증, `snapshot(t)`), Binance 로더 `from_binance`, 유니버스 `binance_universe` |
| `factors.py` | 펀딩 캐리 시그널, 롤링 변동성, 리지·축소 베타 |
| `portfolio.py` | 바스켓 선정 → 역변동성 → 달러 중립 → 팩터 중립(투영 또는 헤지 레그) → 변동성 타깃 → 한도 |
| `backtest.py` | 결정 일정, 막대 단위 시뮬레이션, 손익 분해, 성과 지표, 사후 베타 |
| `run.py` | 실데이터 실행 (raw와 hedged를 같은 결정 일정으로 비교) |

## 데이터·상태 흐름

```
MarketData ──snapshot(t)──▶ compute_targets ──▶ Targets(w_raw, w, 노출 전/후)
 (t 이전 행만 담긴 뷰)        │ 1 적격성: 가격, 이력, 유동성, 변동성, 베타
                              │ 2 시그널: 펀딩 캐리(일 단위)
                              │ 3 숏 상위 K / 롱 하위 K
                              │ 4 역변동성 가중, 각 측 ∓ gross/2
                              │ 5 팩터 중립화, 6 변동성 타깃, 7 한도
compute_schedule ── 결정 시각 t마다 위 과정 반복
orders_from_schedule ── t + exec_lag 막대 종가에 체결
simulate ── 막대 j마다: 가격 드리프트 → 펀딩 정산 → 결측 종목 청산 → 체결(수수료+슬리피지)
run_backtest ── 지표, 손익 분해, 노출 리포트, 사후 베타
```

## 시간·부호 규약

- **막대**: 인덱스는 막대의 **종가 시각** t야. `close[t]`는 (t−Δ, t] 구간의 마지막 가격이고 t에 확정돼. Binance 캔들의 `open_time` T는 T+Δ로 바꿔서 써.
- **결정**: 시각 t의 결정은 `snapshot(t)`만 봐. 이 뷰에는 t 이후 행이 물리적으로 들어 있지 않아.
- **체결**: 결정 t, 체결 t + `exec_lag_bars`(기본 1막대) 종가.
- **펀딩 부호**(Binance 규약): rate > 0이면 롱이 숏에게 지급해. 보유자의 현금흐름은 `−notional(s) × rate`야(notional은 롱 +, 숏 −). 그래서 양수 펀딩은 숏이, 음수 펀딩은 롱이 받아.
- **정산 귀속**: 정산 s는 t_{j−1} < s ≤ t_j인 막대 j에 속해. 막대 j 동안 보유한 포지션(t_{j−1} 체결 이후)에 적용돼. s에 체결한 거래는 그 정산 **이후**라서 그 정산을 받지도 내지도 않아. 정산이 막대 중간에 있으면(예: 4h 막대에 1h 정산) 막대 시작 시점의 notional을 써. 1h 막대에서는 오차가 없어.
- **시그널**: `carry = Σ rate_j / (s_n − s_0)`(일 단위). s_0는 창 직전 정산이라서, 1h·4h·8h 주기가 섞여도 정확해.
- **회전율**: `0.5 × Σ|w_target − w_drift|`. 비용은 거래한 notional `Σ|Δw| × equity`에 (수수료 + 슬리피지)를 곱한 값이야.
- **비용 기본값**: USDC-M 테이커 4bp(사용자 제공, `research/mm/06` §7) + 슬리피지 1bp. USDT-M은 `CostConfig.binance("USDT")`로 테이커 5bp를 써.

## 팩터 중립화: 두 방식과 그 한계

`neutral_mode`로 골라.

- `"projection"`(기본값): `Σw = 0`과 `B'w = target`을 동시에 만족하면서 `w_raw`에 가장 가까운 가중치를 찾아(가중 최소제곱, 활성집합).
  - `|w| ≤ max_weight`를 지키고, 바스켓 종목의 방향은 바뀌지 않아(`keep_sign`).
  - **한계**: 숏 바스켓이 전부 고베타이고 롱 바스켓이 전부 저베타이면, 두 제약을 함께 만족하는 해는 0뿐이야. 이때 BTC 헤지 레그(β = 1)를 추가해도 해가 생기지 않아. 그래서 펀딩 순위와 베타가 강하게 겹치면 포지션이 줄어들어. 노출 리포트의 `gross_raw`와 `gross`를 비교해서 확인해.
- `"hedge"`: 바스켓은 그대로 두고 헤지 레그(기본 `BTCUSDC`)를 더해 `B'w = target`을 맞춰. 대신 순 달러 노출이 헤지 레그 크기만큼 생기고, 리포트의 `net`에 나와.

`exposures` 표에 결정마다 `BTC_raw`(중립화 전 `B'w_raw`)와 `BTC_hedged`(후)가 나와. `run_backtest(..., use="raw")`로 같은 일정을 중립화 없이 돌리면 사후 베타를 직접 비교할 수 있어.

## 실데이터 입력 스펙 (`MarketData`)

모든 시각은 tz-aware UTC야.

| 인자 | 형식 | 예시 |
|---|---|---|
| `close` | DataFrame. 인덱스는 **규칙적인** 막대 종가 시각 격자, 열은 심볼. 결측은 NaN(상장 전, 상장 폐지 후). | `close.loc["2024-03-01 09:00+00:00", "SOLUSDC"] = 132.4` (08:00~09:00 막대의 종가) |
| `funding` | long 형식 DataFrame: `time`(정산 시각), `symbol`, `rate`(정산된 비율, 소수). `(time, symbol)`은 중복되면 안 돼. | `2024-03-01 08:00+00:00, SOLUSDC, 0.000125` (0.0125%) |
| `factors` | DataFrame. 인덱스는 `close`와 같아. 열은 팩터 이름이고, 값은 해당 막대의 **단순 수익률**이야. | `factors["BTC"] = close["BTCUSDC"].pct_change()` |
| `quote_volume` | (선택) `close`와 인덱스·열이 같은 DataFrame. 막대 안 거래대금이야. | `1.2e6` |

```python
import pandas as pd
from crypto_dirty_carry import MarketData, StrategyConfig, run_backtest

idx = pd.date_range("2024-01-01 01:00", periods=24 * 400, freq="1h", tz="UTC")
close = ...      # idx × symbols, float
funding = pd.DataFrame({"time": [...], "symbol": [...], "rate": [...]})
factors = pd.DataFrame({"BTC": close["BTCUSDC"].pct_change(fill_method=None)})
data = MarketData(close=close, funding=funding, factors=factors, quote_volume=qv)
res = run_backtest(data, StrategyConfig(hedge_instruments=("BTCUSDC",)))
res.metrics, res.attribution, res.exposures, res.betas
```

알트 바스켓 팩터는 `data.equal_weight_factor(close, exclude=["BTCUSDC"])`로 만들어 `factors`에 열로 추가하면 돼. 그다음 `StrategyConfig(factors=("BTC", "ALT"), ...)`로 지정해. 이때 `neutral_mode="hedge"`를 쓰려면 헤지 종목이 팩터 수만큼 있어야 해.

Binance에서 바로 받으려면:

```python
from crypto_dirty_carry.data import binance_universe, from_binance
syms = list(binance_universe("USDC")["symbol"])      # 현재 상장 + 정산 중 종목
data = from_binance(syms, "2024-01", "2026-10", bar="1h", factor_map={"BTC": "BTCUSDC"})
```

로더 동작:
- 캔들은 data.binance.vision의 월별 아카이브를 쓰고, 이번 달은 일별 아카이브를 써.
- 펀딩은 월별 아카이브를 쓰고, 아카이브에 아직 없는 기간은 REST(`/fapi/v1/fundingRate`)로 받아.
- 3막대 이하의 짧은 결측은 직전 가격으로 채우고 거래대금은 0으로 둬. 그보다 긴 결측은 NaN이라서 해당 포지션은 청산돼.
- 캐시 위치는 `crypto_dirty_carry/data_cache/`이고 git에서 제외돼.

## 실행

```bash
# 테스트 (저장소 루트에서)
python -m pytest crypto_dirty_carry/tests -q

# 실데이터 (USDC 기본: 사양대로 숏은 펀딩 > 0, 롱은 펀딩 < 0)
python -m crypto_dirty_carry.run --quote USDC --start 2024-01 --end 2026-10
# 부호 조건 없이 상대 캐리(숏 상위 K, 롱 하위 K)
python -m crypto_dirty_carry.run --quote USDC --start 2024-01 --end 2026-10 --relative
# 헤지 레그 방식
python -m crypto_dirty_carry.run --quote USDC --start 2024-01 --end 2026-10 --relative --mode hedge
# USDT 마진 (표본이 더 길고 수수료는 5bp)
python -m crypto_dirty_carry.run --quote USDT --start 2021-01 --end 2026-10
```

결과는 `crypto_dirty_carry/results/`에 저장되고 git에서 제외돼.

필요 패키지: `pandas numpy pyarrow requests pytest`(Python 3.12에서 테스트함).

## 알려진 한계

- **생존 편향**: `exchangeInfo`는 현재 거래 중이거나 정산 중인 계약만 보여줘. 이미 상장 폐지된 USDC 무기한은 유니버스에 없어.
- **USDC 표본**: 대부분 2024년 이후 상장했어. 2024-01 기준 5종목에서 시작해 현재 41종목이고, 횡단면이 얇아.
- **음수 펀딩 희소**: 상승장에서는 모든 종목의 펀딩이 양수라서, 사양대로라면 롱 바스켓이 비어 포지션을 잡지 않아. 노출 리포트의 `status = flat:baskets`로 확인할 수 있어.
- **체결**: 모든 거래를 종가 테이커 체결로 가정해. 시장 충격, 펀딩 상한·하한, 청산 위험, 증거금, 베이시스(현물 대비)는 모델에 없어.
- **베타 중립**: BTC 베타만 기본으로 넣었어. 알트 팩터는 직접 추가해야 해.
