# 작업 진행 상태

> 휘발성 작업 상태 기록. 안정적 사실은 Claude Code memory에 저장.

## 마지막 업데이트
2026-04-29 23:56 KST

---

## 🔄 현재 진행 중 — 3-Market 24h Capture

미드프리퀀시 전략 일반화를 위해 KRW-XRP/DOGE/SOL 3개 시장 동시 캡처.
가설 1을 multi-market에서 재검증 + cross-market 패턴 분석 목적.

| Market | PID | Run dir |
|---|---|---|
| KRW-XRP | 30118 | `data/run-24h-KRW-XRP-2026-04-29T14-55-43` |
| KRW-DOGE | 30146 | `data/run-24h-KRW-DOGE-2026-04-29T14-55-43` |
| KRW-SOL | 30172 | `data/run-24h-KRW-SOL-2026-04-29T14-55-43` |

- **시작 (KST)**: 2026-04-29 23:55
- **완료 예정 (KST)**: 2026-04-30 23:55
- 모두 nohup + caffeinate, 세션 끊겨도 생존
- 디스크: 146GB 여유, 3 markets × 24h ≈ 10GB 예상 (충분)

### 진행 상황 확인
```bash
for SYM in XRP DOGE SOL; do
  PID=$(cat /tmp/observer-$(echo $SYM | tr A-Z a-z)-pid)
  DIR="data/run-24h-KRW-${SYM}-2026-04-29T14-55-43"
  echo "[$SYM] PID=$PID $(ps -p $PID -o stat= 2>/dev/null || echo DEAD)"
  wc -l $DIR/*.jsonl 2>/dev/null | tail -1
done
```

### 캡처 완료 후 분석 (2026-04-30 23:55 이후)
```bash
for SYM in XRP DOGE SOL; do
  RD="data/run-24h-KRW-${SYM}-2026-04-29T14-55-43"
  echo "=== $SYM ==="
  .venv/bin/python -m observer.convert "$RD"
  .venv/bin/python scripts/analyze_h1_public.py "$RD"
  .venv/bin/python scripts/analyze_h1.py "$RD"
done
```

---

## ✅ 완료된 마일스톤

1. **Sub-project #1 코드 완성** (24/24 task) — 32 tests passing, Bithumb v2 호환
2. **1h KRW-XRP capture + 분석** (2026-04-28 15:23 KST)
   - 결과: `data/run-1h-2026-04-28T06-23-07/`
   - Public LIFT +43.5pp [+38.0, +49.0], n=2,139, Fisher p<0.001
   - Own LIFT +34.2pp (n=29, **underpowered**, p=0.19)
3. **24h KRW-XRP capture + 분석** (2026-04-28 19:08 → 2026-04-29 19:08 KST)
   - 결과: `data/run-24h-2026-04-28T10-07-59/`
   - meta.json: gaps=0, restart_count=0 (완벽)
   - event_counts: orderbook 447,254 / trade 35,847 / myOrder 1,260 / myAsset 5,434
   - **Public LIFT +25.5pp [+24.1, +27.1], n=35,846, Fisher p<10⁻²⁶⁷**
   - **Own LIFT +31.3pp [+13.0, +48.9], n=596, n_adv=31, Fisher p=0.0003** ← 통계적 유의 확정
   - **봇 own adverse rate 5.2% < public 12.6%** → 봇 이미 절반 가량 방어 중
4. **분석 도구 일괄 작성** — analyze_h1, analyze_h1_public, sensitivity_h1, sweep_h1, probe_*

## 🔑 가설 1 검증 결론 요약

**Trade Velocity Filter는 KRW-XRP에서 통계적으로 유의함 (p<0.001)**
- 시장 전체 (public tape): 매도 가속도 상위 분위 시점 후 가격 하락 확률 +25.5pp 증가
- 봇 자체 fills (24h): 이 시그널이 켜진 시점에 fill됐을 때 adverse 발생률 +31pp 증가
- 봇이 이미 부분적 방어 중이지만 velocity filter로 추가 50%+ 회피 가능

---

## ⏭️ 다음 단계 후보

### 3-market 캡처 완료 후 (2026-04-30 23:55 이후)
- 각 시장 convert.py + analyze_h1*.py
- Cross-market 비교: LIFT 안정성 (XRP에서 봤던 +25pp가 DOGE/SOL에서도?)
- Mid-frequency 전략 설계 (multi-market velocity filter)

### 가설 1 보강
- Random sample timestamp 대조군 검정 (auto-correlation 통제)
- Mid-price 기반 adverse 측정 (orderbook 활용 — 현재는 trade tape mean)
- 시간대별 stratification (24h 데이터 활용)

### 다음 sub-project 진입 옵션
- **#2 백테스트 엔진**: 호가창 재구성, 큐 포지션 시뮬레이션
- **#3 전략 모듈**: Velocity filter 알고리즘 모듈화 + multi-market dispatch
- **#4 리포팅**: 시나리오 매트릭스 + 자동 리포트

### 가설 2 (Lead-Lag)
- Binance KRW-XRP 대응 페어 (XRP/USDT) 데이터 조달
- Cross-exchange 시간 동기화 검정

---

## 📁 핵심 파일 위치

| 종류 | 경로 |
|---|---|
| Spec | `docs/superpowers/specs/2026-04-28-data-pipeline-design.md` |
| Plan | `docs/superpowers/plans/2026-04-28-bithumb-observer.md` |
| Observer 코드 | `src/observer/` |
| 테스트 (32 passing) | `tests/` |
| 분석 도구 | `scripts/analyze_h1*.py`, `sensitivity_h1.py`, `sweep_h1.py` |
| Probe (진단) | `scripts/probe_*.py` |
| 운영 스크립트 | `scripts/run.sh`, `smoke.sh`, `redact.py` |

데이터(gitignored): `data/run-1h-*`, `data/run-24h-*`

---

## 🔧 환경 quirks

- `.env`: `BITHUMB_API_KEY` + `BITHUMB_SECRET_KEY` (NOT `BITHUMB_API_SECRET`). 코드는 둘 다 받음.
- 기본 시장: `KRW-XRP` (사용자 봇 활동 기준 가장 활발)
- Bithumb v2 myOrder는 `codes` 필터 필수
- 자세한 API quirks: Claude Code memory의 `reference_bithumb_v2_api.md` 참조
