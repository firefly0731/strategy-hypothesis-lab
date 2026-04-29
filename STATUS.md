# 작업 진행 상태

> 이 파일은 **휘발성 작업 상태**를 기록합니다. 안정적 사실(API 스펙, 컨벤션 등)은
> Claude Code memory(`~/.claude/projects/.../memory/`)에 저장돼 있습니다.

## 마지막 업데이트
2026-04-28 19:10 KST

---

## 🔄 현재 진행 중

### 24-hour 라이브 capture (KRW-XRP)
- **Run dir**: `data/run-24h-2026-04-28T10-07-59/` (gitignored)
- **시작 (KST)**: 2026-04-28 19:08
- **완료 예정 (KST)**: 2026-04-29 19:08 (24h 후)
- **PID**: 60485 (run.sh) + 60508 (observer.main) — `nohup`으로 데몬화 (세션 종료에도 살아남음)
- **목적**: 가설 1 (Trade Velocity Filter) 통계적 검증력 확보
  - 1h 데이터에서 own-fills test underpowered (n_adverse=5)
  - 24h 후 own-fills test 통계 가능 (예상 n_adverse ~120)

### 진행 상황 확인 명령
```bash
RID=$(cat /tmp/observer-current-run-id) && \
  ps -p 60485 -p 60508 2>&1 | head && \
  wc -l "data/$RID/"*.jsonl 2>/dev/null
```

### 캡처 완료 후 분석 (내일 19:08 이후)
```bash
RID=$(cat /tmp/observer-current-run-id)

# Parquet 변환 (1-3분)
.venv/bin/python -m observer.convert "data/$RID"

# Public-tape 분석 (n≈50,000 예상)
.venv/bin/python scripts/analyze_h1_public.py "data/$RID"
.venv/bin/python scripts/analyze_h1_public.py "data/$RID" --sweep

# Own-fills 분석 (n≈700 예상, 통계 유의)
.venv/bin/python scripts/analyze_h1.py "data/$RID"
.venv/bin/python scripts/sweep_h1.py "data/$RID"

# Sensitivity (다른 파라미터)
.venv/bin/python scripts/sensitivity_h1.py "data/$RID"
```

---

## ✅ 완료된 마일스톤

1. **Sub-project #1 코드 완성** (24/24 task) — 32 tests passing, Bithumb v2 API 호환
2. **1h 라이브 capture 완료** — `data/run-1h-2026-04-28T06-23-07/` (gitignored)
3. **가설 1 1h 분석 완료** — public-tape LIFT +44.9pp, 95% CI [+39.5, +50.4], Fisher p<0.001 (n=2,139)
4. **분석 도구 일괄 작성** — analyze_h1, analyze_h1_public, sensitivity_h1, sweep_h1

---

## ⏭️ 다음 단계 후보

### 24h 캡처 완료 후 즉시
- `convert.py` 실행
- `analyze_h1_public.py` + `analyze_h1.py` 실행 → own-fills 통계 검정
- 1h 결과와 24h 결과 비교 (regime stability)

### 가설 1 보강
- Random sample timestamp 대조군 검정 (auto-correlation 통제)
- mid-price 기반 adverse 측정 (orderbook 활용 — 현재는 trade tape mean만)
- 시간대별 stratification (24h 데이터 활용)

### 다음 sub-project 진입 옵션
- **#2 (백테스트 엔진)**: 캡처 데이터로 호가창 재구성, 큐 포지션 시뮬레이션
- **#3 (전략 모듈)**: Velocity filter 알고리즘 모듈화
- **#4 (리포팅)**: 시나리오 매트릭스 + 자동 리포트

### 가설 2 (Lead-Lag Filter)
- Binance KRW-XRP에 해당하는 USDT 페어 (BTC/XRP, ETH/XRP) 데이터 조달
- 시간 동기화된 cross-exchange 분석

---

## 📁 핵심 파일 위치

| 종류 | 경로 |
|---|---|
| Spec (확정) | `docs/superpowers/specs/2026-04-28-data-pipeline-design.md` |
| Plan (24-task) | `docs/superpowers/plans/2026-04-28-bithumb-observer.md` |
| Observer 코드 | `src/observer/` |
| 테스트 | `tests/` (32 passing) |
| 분석 도구 | `scripts/analyze_h1*.py`, `sensitivity_h1.py`, `sweep_h1.py` |
| Probe (진단) | `scripts/probe_*.py` |
| 운영 스크립트 | `scripts/run.sh`, `smoke.sh`, `redact.py` |
| 1h 결과 (로컬, gitignored) | `data/run-1h-2026-04-28T06-23-07/` |
| 24h 결과 (진행 중) | `data/run-24h-2026-04-28T10-07-59/` |

---

## 🔧 환경 quirks

- `.env`: `BITHUMB_API_KEY` + `BITHUMB_SECRET_KEY` (NOT `BITHUMB_API_SECRET`). 코드는 둘 다 받음.
- 기본 시장: `KRW-XRP` (사용자 봇 활동 가장 많음). USDT는 sparse.
- Bithumb v2 myOrder는 `codes` 필터 필수 — 없으면 silent ignore.
- 자세한 API quirks: Claude Code memory의 `reference_bithumb_v2_api.md` 참조.
