# Bithumb USDT/KRW Live Capture Pipeline — 가설 1 검증용

**Spec ID**: `2026-04-28-data-pipeline-design`
**Sub-project**: #1 (전체 4개 중 첫 단계)
**작성일**: 2026-04-28
**대상**: 시니어 퀀트 1인

## 0. 한 줄 요약

Bithumb USDT/KRW에서 4시간 동안 Public 시장 데이터(L2 호가 + 체결)와 Private 자기 주문/체결 이벤트를 시각 동기화하여 무손실로 캡처하고, 가설 1(Trade Velocity Filter)을 라이브 트레이딩 결과에 대해 반사실(counterfactual) 검증할 수 있는 데이터 파이프라인을 구축한다.

## 1. 컨텍스트 및 동기

### 1.1 전체 프로젝트 분해 (참고)

| # | Sub-project | 산출물 | 의존 |
|---|---|---|---|
| **1 (이 spec)** | **데이터 수집 & 저장 파이프라인** | Bithumb L2 + trade + 자기 주문/체결을 정규화·저장 | — |
| 2 | 백테스트 엔진 (event-driven simulator) | 호가창 재구성, 큐 포지션 추정, 체결 시뮬레이션 | 1 |
| 3 | 전략 모듈 (Baseline MM + Velocity filter + Lead-Lag filter) | 엔진에 꽂히는 전략 인터페이스 | 2 |
| 4 | 실험 러너 & 리포팅 | 시나리오 매트릭스, 체결률·역선택·PnL 비교 | 3 |

각 sub-project는 자체 spec → plan → 구현 사이클.

### 1.2 이 spec의 동기

마켓메이킹(MM) 전략의 역선택(adverse selection) 리스크를 방어하는 두 가설 중 **가설 1만** 1차로 검증한다:

> **가설 1 — Trade Velocity Filter**: 특정 순간의 매도 체결 가속도(intensity) 급증은 가격 하락의 선행 지표이므로, 이를 트리거로 Maker 주문을 취소/조정해야 한다.

기존 백테스트 접근(시뮬레이션 fill 모델)은 큐 포지션·레이턴시 추정 오차가 가설 검증의 노이즈가 된다. 본 spec은 사용자가 **이미 라이브로 운용 중인 MM 봇**의 실제 주문/체결 결과와 시장 데이터를 동시 캡처하여, "velocity 시그널이 켜진 시점에 주문을 취소했더라면 adverse fill을 피했을까?"를 **반사실로 평가**하는 데 필요한 데이터 인프라를 만든다.

### 1.3 기존 라이브 봇과의 격리

- 사용자의 MM 봇은 **별도 서버에서 별도 API 키**로 운용 중. observer는 봇과 절대 간섭하면 안 된다 (spec의 절대 제약).
- 격리 구조: observer는 사용자 macOS에서 **별 IP**, **별 read-only API v2 키**로 동작. Bithumb의 Private WebSocket은 **연결 후 스트림 데이터에 rate-limit 비적용** ([공식 changelog](https://apidocs.bithumb.com/changelog/%EC%97%85%EB%8D%B0%EC%9D%B4%ED%8A%B8-private-websocket-%EC%98%A4%ED%94%88-myorder-myasset-%EC%A7%80%EC%9B%90-%EC%95%88%EB%82%B4)).
- 격리 차원: API 키 / IP / 권한(read-only) / rate-limit budget / WS 동시연결 — 5축 모두 분리됨.
- 잔여 위험 (계정 단위 글로벌 limit 가능성)은 §7.4의 5분 dry-run으로 사전 검증.

## 2. 요구사항

### 2.1 기능 요구사항

| ID | 요구사항 |
|---|---|
| F-1 | Bithumb Public WebSocket의 `orderbookdepth` 채널을 USDT_KRW 심볼로 구독, 모든 메시지 무손실 기록 |
| F-2 | Bithumb Public WebSocket의 `transaction` 채널을 USDT_KRW 심볼로 구독, 모든 체결 이벤트 무손실 기록 |
| F-3 | Bithumb Private WebSocket(v2)의 `myOrder` 채널 구독, 본인 모든 주문 상태 변화 기록 |
| F-4 | Bithumb Private WebSocket(v2)의 `myAsset` 채널 구독, 본인 자산 변동 기록 |
| F-5 | 모든 이벤트에 삼중 타임스탬프(server_ts_ms / recv_monotonic_ns / recv_utc_ms) 부착 |
| F-6 | 캡처 시간 기본 4시간(설정 가능), 정상 종료 시 graceful shutdown |
| F-7 | WS 끊김 시 자동 재연결 (지수 backoff, cap 30초) |
| F-8 | 프로세스 비정상 종료 시 외부 supervisor가 최대 10회 자동 재시작 |
| F-9 | 캡처 종료 후 JSONL → Parquet 변환 스크립트로 분석 친화적 컬럼 추출 |
| F-10 | 갭(reconnect 시간), 재시작 횟수, 채널별 이벤트 카운트를 `meta.json`에 기록 |

### 2.2 비기능 요구사항

| 항목 | 목표 |
|---|---|
| 무손실 capture window | 4시간 연속 |
| WS 재연결 후 재구독 시간 | < 5초 |
| 디스크 사용량 (압축 전) | < 5 GB / 4h (USDT/KRW 호가 빈도 고려) |
| CPU 사용률 | < 10% (단일 코어) |
| 봇에 미치는 영향 | 0 (관찰적 검증 가능: 봇 활동 메트릭 정상) |
| 시각 동기화 정밀도 | observer 프로세스 내 monotonic_ns 단위 (네트워크 jitter 분리) |

### 2.3 절대 제약

- 라이브 운용 중인 MM 봇에 어떤 식으로든 영향을 주면 안 된다.
- API 키 권한은 read-only만 사용. 거래/출금 권한 키는 절대 이 코드베이스에 들이지 않는다.

## 3. 범위 외 (Out of Scope)

명시적으로 본 spec에서 다루지 않는 것 (다른 sub-project 또는 향후 결정 사항):

- 가설 2 (Lead-Lag Signal Filter) 검증, Binance 데이터 수집
- USDT/KRW 외 다른 페어/거래소
- 백테스트 엔진 자체 (sub-project #2)
- 전략 모듈 / 시나리오 비교 (sub-project #3, #4)
- Production-grade 운영 (durable queue, 메시지 큐, 24/7 모니터링) — sub-project 진척 후 별도 결정
- 과거 데이터 백필 / 벤더 구매
- CI/CD 파이프라인

## 4. 아키텍처

### 4.1 토폴로지

```
[macOS observer host (사용자 노트북)]
            │
            └── observer 프로세스 (Python asyncio)
                  │
                  ├── Public WS connection (1개)
                  │    └── 채널 2개 구독: orderbookdepth, transaction
                  │
                  ├── Private WS connection (1개, JWT auth, v2 read-only key)
                  │    └── 채널 2개 구독: myOrder, myAsset
                  │
                  ├── 4개 비동기 writer task → 채널별 JSONL 파일
                  │    (시간당 롤테이션: <channel>_<UTC-hour>.jsonl)
                  │
                  └── supervisor 루프 (shell 스크립트로 외부 래핑)
                       프로세스 비정상 종료 시 자동 재시작 (max 10회)

[봇 서버] ─────── 관여 없음 (별 키, 별 IP)
```

### 4.2 핵심 설계 결정

1. **단일 프로세스 + 2 WS connection**. Bithumb WS는 한 connection 위 다중 채널 구독 가능 → public 1, private 1로 충분. 4 connection 분리는 reconnect 복잡도만 증가.
2. **삼중 타임스탬프 기록** (모든 이벤트):
   - `server_ts_ms` — Bithumb 서버가 찍은 시각 (이벤트 단위 절대 시간)
   - `recv_monotonic_ns` — observer 프로세스의 monotonic clock (단일 프로세스 내 절대 순서·delta 측정용; 가설 1 velocity 계산의 기준)
   - `recv_utc_ms` — observer wall clock UTC (디버깅·재해석용)
   - 분석 시 `recv_monotonic_ns` 우선. 서버↔클라 clock drift, 네트워크 jitter 영향 분리 가능.
3. **JSONL append-only + 시간당 롤테이션**. 정시(UTC hour 경계)에 새 파일로 전환. 크래시 시 손실은 최대 미동기화된 1시간 분량의 부분 라인. Parquet 변환은 캡처 종료 후 1회 실행.
4. **Supervisor는 Python 외부**. `scripts/run.sh`가 `observer.main`을 호출하고, exit code != 0이면 backoff 후 최대 10회 재시작.
5. **macOS sleep 방지**. `caffeinate -i`로 supervisor를 감싸서 4시간 동안 노트북 sleep 차단.

## 5. 컴포넌트

### 5.1 디렉터리 구조

```
strategy-hypothesis-lab/
├── pyproject.toml
├── .env                    # API 키 (gitignored)
├── .env.example            # 키 이름만 적힌 템플릿 (커밋)
├── .gitignore
├── src/observer/
│   ├── __init__.py
│   ├── main.py             # entry point, asyncio orchestration
│   ├── config.py           # env 로딩, 런타임 파라미터
│   ├── clock.py            # 삼중 타임스탬프 helper
│   ├── ws_public.py        # Public WS client
│   ├── ws_private.py       # Private WS client (JWT auth)
│   ├── writer.py           # 채널별 JSONL writer + 시간당 롤테이션
│   └── convert.py          # JSONL → Parquet 변환 (캡처 후 1회)
├── tests/
│   ├── fixtures/           # 실 페이로드 샘플 (민감정보 마스킹)
│   ├── conftest.py         # mock WS server
│   ├── test_clock.py
│   ├── test_writer.py
│   ├── test_convert.py
│   ├── test_payloads.py
│   ├── test_jwt.py
│   ├── test_backoff.py
│   └── test_integration.py
├── scripts/
│   ├── run.sh              # caffeinate + supervisor + observer 호출
│   ├── smoke.sh            # 5분 dry-run + 검증
│   └── redact.py           # fixture 민감정보 마스킹
├── data/<run-id>/          # 캡처 산출물 (run-id = 시작시각 ISO)
│   ├── public_orderbook_<UTC-hour>.jsonl
│   ├── public_trade_<UTC-hour>.jsonl
│   ├── my_order_<UTC-hour>.jsonl
│   ├── my_asset_<UTC-hour>.jsonl
│   ├── meta.json           # 런 메타데이터
│   ├── errors.log          # 파싱/스키마 예외
│   ├── run.log             # 콘솔 로그
│   └── parquet/            # 변환 결과 (post-capture)
└── docs/superpowers/specs/
    └── 2026-04-28-data-pipeline-design.md  ← 이 파일
```

### 5.2 모듈 책임

| 모듈 | 책임 | 핵심 인터페이스 | 의존 |
|---|---|---|---|
| `config.py` | `.env` 로드, 캡처 파라미터 검증 | `Config(api_key, api_secret, run_dir, duration_sec, max_restarts, symbol)` (dataclass) | python-dotenv |
| `clock.py` | 삼중 타임스탬프 부착 | `stamp(server_ts_ms, raw) -> EventEnvelope` | stdlib (`time.monotonic_ns`, `time.time_ns`) |
| `ws_public.py` | Public WS 연결·구독·재연결 | `async run(channels, on_event_cb, stop_event)` | `websockets`, `orjson` |
| `ws_private.py` | Private WS 연결·JWT 발급·구독·재연결 | `async run(api_key, api_secret, channels, on_event_cb, stop_event)` | `websockets`, `PyJWT`, `orjson` |
| `writer.py` | 비동기 큐 + JSONL append + 시간당 롤테이션 + 종료 시 fsync | `Writer(channel, run_dir).enqueue(envelope) / await close()` | `aiofiles`, `orjson` |
| `main.py` | 4 task 동시 실행, asyncio.gather, signal handler | CLI: `python -m observer.main --duration 14400 --run-dir data/<id>` | 위 모듈 + asyncio |
| `convert.py` | JSONL → Parquet, 시간 정렬 검증 리포트 | CLI: `python -m observer.convert <run-dir>` | `polars` |
| `run.sh` | caffeinate + 무한루프 supervisor (재시작 ≤10회) | shell | macOS `caffeinate` |

### 5.3 통일 이벤트 envelope

JSONL 한 줄:

```json
{
  "channel": "orderbookdepth",
  "server_ts_ms": 1714287000123,
  "recv_monotonic_ns": 4503599627370496,
  "recv_utc_ms": 1714287000130,
  "raw": { /* Bithumb 원본 페이로드 그대로, 변형 없음 */ }
}
```

**원칙**: capture 단계에서는 **원본 페이로드를 절대 변형/필드 추출하지 않음**. 분석 친화 컬럼 추출은 `convert.py`에서 수행.

### 5.4 의존성 (`pyproject.toml`)

```toml
[project]
dependencies = [
  "websockets>=13",
  "PyJWT>=2.8",
  "orjson>=3.10",
  "aiofiles>=24",
  "polars>=1.0",
  "python-dotenv>=1.0",
]

[project.optional-dependencies]
dev = [
  "pytest>=8",
  "pytest-asyncio>=0.24",
  "freezegun>=1.5",
  "pytest-cov>=5",
]
```

### 5.5 환경 변수 (`.env.example`)

```
BITHUMB_API_KEY=your_v2_read_only_access_key_here
BITHUMB_API_SECRET=your_v2_secret_here
OBSERVER_RUN_DIR=./data
OBSERVER_DURATION_SEC=14400      # 4시간
OBSERVER_MAX_RESTARTS=10
OBSERVER_SYMBOL=USDT_KRW
```

## 6. 데이터 흐름

### 6.1 부트스트랩 (T=0)

```
1. run.sh 시작 → caffeinate -i 으로 macOS sleep 차단
2. run.sh → python -m observer.main 호출
3. main.py:
   a. Config 로드 (.env 검증, run_dir 생성, run-id 생성)
   b. signal handler 등록 (SIGINT/SIGTERM → stop_event.set)
   c. 4개 Writer 인스턴스 생성 (채널별 큐 + 파일 핸들)
   d. asyncio.gather(public_ws_task, private_ws_task, duration_timer_task, *writer_tasks)
4. duration_timer_task = asyncio.sleep(duration_sec) → 만료 시 stop_event.set()
```

### 6.2 Public WS 흐름 (의사코드)

```python
async def run(channels, on_event_cb, stop_event):
    backoff = ExponentialBackoff(start=0.5, cap=30.0, sustain_reset=60.0)
    while not stop_event.is_set():
        try:
            async with websockets.connect(
                "wss://pubwss.bithumb.com/pub/ws", ping_interval=30
            ) as conn:
                # 채널 2개 구독
                await conn.send(orjson.dumps({"type": "orderbookdepth", "symbols": ["USDT_KRW"]}))
                await conn.send(orjson.dumps({"type": "transaction", "symbols": ["USDT_KRW"]}))
                backoff.mark_connected()
                async for raw_msg in conn:
                    payload = orjson.loads(raw_msg)
                    envelope = clock.stamp(server_ts_ms=parse_ts(payload), raw=payload)
                    await on_event_cb(payload["type"], envelope)
        except (ConnectionClosed, OSError) as e:
            log("public WS dropped, reconnecting", error=e)
            await asyncio.sleep(backoff.next())
```

**구독 직후**: Bithumb은 `orderbookdepth` 구독 시 첫 메시지로 현재 호가 스냅샷(~30 levels), 이후 delta 푸시. Observer는 둘 다 그대로 envelope에 담아 기록.

### 6.3 Private WS 흐름 (의사코드)

```python
async def run(api_key, api_secret, channels, on_event_cb, stop_event):
    backoff = ExponentialBackoff(start=0.5, cap=30.0, sustain_reset=60.0)
    while not stop_event.is_set():
        try:
            jwt_token = make_jwt(api_key, api_secret)
            async with websockets.connect(
                "wss://ws-api.bithumb.com/websocket/v1/private",
                additional_headers={"Authorization": f"Bearer {jwt_token}"},
                ping_interval=30,
            ) as conn:
                await conn.send(orjson.dumps([
                    {"ticket": "observer"},
                    {"type": "myOrder"},
                    {"type": "myAsset"},
                    {"format": "DEFAULT"},
                ]))
                backoff.mark_connected()
                async for raw_msg in conn:
                    payload = orjson.loads(raw_msg)
                    envelope = clock.stamp(server_ts_ms=parse_ts(payload), raw=payload)
                    await on_event_cb(payload["type"], envelope)  # myOrder | myAsset
        except (ConnectionClosed, OSError, AuthError) as e:
            if isinstance(e, AuthError):
                log_critical("private auth failed, aborting private stream")
                return  # 즉시 종료, public은 계속
            log("private WS dropped, reconnecting", error=e)
            await asyncio.sleep(backoff.next())
```

JWT는 connection마다 새로 발급(nonce 고유성). 인증 실패 시에는 재시도 의미 없으므로 즉시 abort (public은 영향 없음).

### 6.4 Writer 흐름 (채널별 동일)

```python
async def run(self):
    while True:
        envelope = await self.queue.get()
        if envelope is _SENTINEL_CLOSE:
            break
        current_hour = utc_hour_now()
        if current_hour != self.open_hour:
            await self._rollover(current_hour)
        line = orjson.dumps(envelope) + b"\n"
        await self.file.write(line)
        self.queue.task_done()
    await self.file.fsync()
    await self.file.close()
```

- **Append-only mode** + **줄 단위 쓰기**.
- **fsync는 시간당 롤테이션 시점과 종료 시점**.
- **롤테이션 결정 기준**: `recv_utc_ms` (envelope 생성 시각) → 결정론적.

### 6.5 종료 흐름

```
1. duration_timer 만료 OR SIGINT/SIGTERM → stop_event.set()
2. ws_public, ws_private 의 reconnect 루프가 stop_event 확인 후 정상 종료
3. main.py가 모든 writer queue 에 _SENTINEL_CLOSE 인큐
4. queue.join() (잔여 envelope 모두 디스크 기록 대기)
5. 각 writer: fsync + close
6. meta.json 작성: {start_utc, end_utc, restart_count, gaps, channel_event_counts}
7. exit code 0
8. run.sh: exit code 0 → 재시작 안 함, supervisor 루프 종료
```

### 6.6 비정상 종료 → 재시작 흐름

| 케이스 | 동작 |
|---|---|
| Python 내부 catastrophic exception | exit code 1 → run.sh가 backoff 후 재호출 (max 10) → 같은 run-dir에 append, 시간당 파일이라 자연스레 분리 또는 같은 hour 파일 append |
| SIGKILL | fsync 보장 안 됨 → 마지막 hour 파일 끝 줄이 truncated 가능 → `convert.py`가 자동 skip |
| WS 끊김 | reconnect 루프가 backoff 후 자동 복구 (process 안 죽음). 갭은 `meta.json`에 기록 |

### 6.7 Post-capture 변환

```
$ python -m observer.convert data/<run-id>

→ 채널별로:
  1. 모든 *_<hour>.jsonl 읽기 (truncated line skip)
  2. 시간순 정렬 (recv_monotonic_ns 기준)
  3. raw payload에서 분석 친화 컬럼 추출
  4. parquet/<channel>.parquet 로 출력 (zstd 압축)
  5. 검증 리포트 출력 (갭 통계, 카운트, 시간 스팬)
```

추출 컬럼:

| 채널 | Parquet 컬럼 |
|---|---|
| `transaction` (public trades) | `recv_monotonic_ns, server_ts_ms, side(buy/sell), price, qty` ← 가설 1의 velocity 계산 입력 |
| `orderbookdepth` | `recv_monotonic_ns, server_ts_ms, side, price, qty, action(add/update/remove)` |
| `myOrder` | `recv_monotonic_ns, server_ts_ms, order_uuid, state, side, price, qty, filled_qty, avg_fill_price` ← adverse fill 라벨링 grounding truth |
| `myAsset` | `recv_monotonic_ns, server_ts_ms, currency, balance, locked` |

원본 JSONL은 그대로 보관 (재처리·검증용).

## 7. 에러 처리

### 7.1 실패 모드 매트릭스

| # | 실패 모드 | 탐지 | 즉시 대응 | 사용자 개입 | 데이터 영향 |
|---|---|---|---|---|---|
| 1 | WS idle 끊김 (Bithumb 120s timeout) | `ConnectionClosed` | 지수 backoff 재연결 | 없음 | reconnect 시간(보통 < 5초) 갭, meta.json에 기록 |
| 2 | 네트워크 일시 단절 | `OSError`/`TimeoutError` | 동일 backoff 재연결 | >1분 지속 시 알림 고려 | 끊긴 시간 갭 |
| 3 | Bithumb 서버 5xx / 일시 장애 | handshake 실패 | backoff 후 재시도 (cap 30s) | 10분 지속 시 알림 | 장애 시간 갭 |
| 4 | Auth 실패 (JWT 거부, 키 폐기) | private handshake 실패 메시지 | **즉시 abort private**, public 계속 | 키 확인 필요 | private 스트림 손실 |
| 5 | Public/Private 한쪽만 죽음 | task gather 한쪽만 exception | 다른 task 계속, 죽은 쪽만 reconnect 루프 | 5회 연속 실패 시 알림 | 한 채널만 갭 |
| 6 | 디스크 풀/권한 오류 | `IOError` on write | **즉시 abort** (무결성 우선) | 디스크 정리 후 재시작 | 마지막 envelope 손실 가능 |
| 7 | 프로세스 OOM/알 수 없는 예외 | exit code != 0 | run.sh 외부 supervisor가 재시작 (max 10) | 10회 도달 시 종료, 조사 필요 | 재시작 사이 짧은 갭 |
| 8 | 예상치 못한 페이로드 스키마 | envelope 생성 시 KeyError | `errors.log`에 raw_msg dump 후 계속 | 캡처 후 errors.log 확인 | 해당 메시지만 손실 |
| 9 | macOS sleep 진입 | 네트워크 단절로 위장 | `caffeinate`가 차단해야 정상 | 사용자 환경 문제 | sleep 시간 전체 갭 |
| 10 | NTP step adjustment | `recv_utc_ms` 점프, monotonic 정상 | 분석 시 monotonic 우선 | 없음 | 데이터 정상, utc 해석만 주의 |
| 11 | Bithumb 계정 단위 글로벌 limit (잔여 위험) | 직접 감지 불가, 봇 거래 메트릭 이상 | dry-run에서 사전 검증 (§7.4) | 봇 이상 시 즉시 observer 중단 | dry-run 단계만 |

### 7.2 Backoff 정책

```
attempt 1: 0.5s
attempt 2: 1.0s
attempt 3: 2.0s
attempt 4: 4.0s
attempt 5: 8.0s
attempt 6: 16.0s
attempt 7+: 30.0s (cap)

reset 조건: 연결이 60초 이상 지속되면 attempt counter = 0
```

### 7.3 로깅

| 로그 | 위치 | 내용 |
|---|---|---|
| stderr (콘솔) | `data/<run-id>/run.log` (run.sh가 tee) | 모든 INFO/WARN/ERROR |
| `errors.log` | `data/<run-id>/errors.log` | 파싱 실패 raw_msg, 스키마 예외, auth 실패 |
| `meta.json` | `data/<run-id>/meta.json` | 시작/종료 시각, 재시작 횟수, 갭 인터벌, 채널별 카운트 |

`meta.json` 예시:

```json
{
  "run_id": "2026-04-28T07:00:00Z",
  "started_utc_ms": 1714287000000,
  "ended_utc_ms": 1714301400000,
  "duration_planned_sec": 14400,
  "restart_count": 1,
  "gaps": [
    {"channel": "public", "start_monotonic_ns": ..., "end_monotonic_ns": ..., "duration_ms": 3200, "reason": "ws_disconnect"},
    {"channel": "private", "start_monotonic_ns": ..., "end_monotonic_ns": ..., "duration_ms": 1100, "reason": "ws_disconnect"}
  ],
  "event_counts": {
    "orderbookdepth": 1284372,
    "transaction": 38214,
    "myOrder": 8421,
    "myAsset": 8439
  }
}
```

### 7.4 본 캡처 전 5분 dry-run (필수 절차)

본 4시간 캡처 시작 전에 반드시 거치는 검증 단계.

```
1. observer 5분간 캡처 (실 Bithumb endpoint, 실 v2 read-only 키)
2. 사용자가 봇 서버 측에서:
   - 봇의 주문 빈도가 평소 대비 정상인지
   - 응답 지연·rate-limit 에러 메시지가 없는지
   를 육안 확인
3. 정상이면 → 본 4시간 캡처 진행
4. 이상 신호면 → spec 재검토 (B 방식 조정 또는 fallback)
```

이는 §1.3의 "잔여 위험 (계정 단위 글로벌 limit)"에 대한 능동 검증.

### 7.5 캡처 품질 임계값

`convert.py`가 자동 계산하여 출력하는 메트릭과 판정 기준:

| 메트릭 | OK | 경계 | 캡처 무효 (재실행 권장) |
|---|---|---|---|
| 누적 갭 시간 | < 60초 / 4h | 60–300초 | > 300초 |
| 가장 긴 단일 갭 | < 30초 | 30–120초 | > 120초 |
| Public/Private 동시 갭 | 없음 | 분산 | 동시 갭 > 60초 |
| Auth 실패 | 0회 | — | 1회 이상 |
| Schema 예외 비율 | < 0.01% | 0.01–0.1% | > 0.1% |

판정은 자동, **재실행 결정은 사용자 수동**.

## 8. 테스트

### 8.1 테스트 피라미드

```
              ┌──────────────────────┐
              │  Live smoke (5분)    │  ← 본 캡처 직전 manual
              ├──────────────────────┤
              │  Integration (~10)   │  ← mock WS, asyncio
              ├──────────────────────┤
              │  Unit (~30)          │  ← 순수 로직
              └──────────────────────┘
```

연구용 도구이므로 **데이터 무결성 직결 모듈만 빡빡하게**.

### 8.2 Unit tests (~30개)

| 모듈 | 핵심 케이스 |
|---|---|
| `clock.py` | envelope 4개 키 모두 존재, monotonic_ns 단조증가, freezegun으로 utc 검증 |
| `writer.py` | 큐 → 파일 라인 1대1, 시간 경계(06:59:59.999 → 07:00:00.001) 시 새 파일 분리, fsync 호출 회수 |
| `convert.py` | 정상 JSONL → Parquet 컬럼 일치, **truncated 마지막 라인 skip**, 갭 통계 정확성, 빈 파일 처리 |
| `ws_private.py::_make_jwt()` | 알려진 key/secret/nonce → 결정론적 JWT, exp 미포함(Bithumb 스펙) 검증 |
| `backoff` helper (in `ws_*.py`) | 0.5→1→2→4→8→16→30 시퀀스, 60초 sustain 시 reset |
| 페이로드 파싱 (in `ws_public.py`/`ws_private.py`) | 5종 샘플 페이로드 fixture → envelope 정상, **알 수 없는 필드 추가돼도 안 깨짐** (forward compat) |

### 8.3 Integration tests (~10개)

`tests/conftest.py`에 mock WS 서버(asyncio.Server) 정의 후 다음 시나리오:

| 시나리오 | 검증 |
|---|---|
| 정상 connect → 메시지 5개 → JSONL 5라인 | end-to-end happy path |
| connect → 강제 disconnect → 자동 재연결 → 추가 메시지 정상 기록 | reconnect, 갭 메타 |
| stop_event.set() → 모든 task 5초 안에 종료, queue.join() 잔여 처리 | graceful shutdown |
| 시간당 롤테이션 경계에서 메시지 → 두 파일 분배 | rotation race-free |
| 스키마 깨진 페이로드 → errors.log 기록, 다른 메시지 계속 | resilience |
| 디스크 IOError 시뮬레이션 → 즉시 abort, exit code 1 | fail-fast on integrity |
| Auth 실패 응답 (private) → 즉시 abort, public 계속 | partial failure 격리 |
| backoff 시퀀스가 freezegun 시간 경과대로 트리거 | 회복 정책 |
| meta.json 갭 인터벌이 정확한 monotonic_ns 페어 | 갭 추적 정확성 |
| 10번 재시작 후 supervisor 종료 (run.sh 단위, bats) | 무한루프 방지 |

### 8.4 Live smoke test (`scripts/smoke.sh`)

본 캡처 직전 1회 실행 (§7.4의 dry-run과 동일).

```
1. observer 5분 가동 (실 endpoint, 실 v2 read-only 키)
2. 자동 검증:
   - 4 채널 모두 이벤트 카운트 > 0
   - 시간 스팬이 4-5분 사이
   - convert.py 정상 실행 → Parquet 4개 생성
   - errors.log 줄 수 < 10
3. 통과하면 본 4시간 캡처 진행
```

봇 서버 로그는 사용자가 곁눈으로 확인.

### 8.5 Fixtures

`tests/fixtures/`에 실제 Bithumb 페이로드 샘플 (smoke test에서 캡처):

```
tests/fixtures/
├── orderbookdepth_snapshot.json
├── orderbookdepth_delta_001~005.json
├── transaction_001~005.json
├── myOrder_placed.json
├── myOrder_filled.json
├── myOrder_cancelled.json
├── myAsset_balance_change.json
└── error_unknown_payload.json
```

**민감정보 마스킹 절차**: `scripts/redact.py`로 `myOrder`/`myAsset` 샘플의 잔액·주문 ID·계좌 식별자 자동 치환 → 커밋 전 사람이 한 번 육안 확인.

### 8.6 도구

```toml
[project.optional-dependencies]
dev = [
  "pytest>=8",
  "pytest-asyncio>=0.24",
  "freezegun>=1.5",
  "pytest-cov>=5",
]
```

타입 체크는 옵션 (도입 시 `pyright` 로컬 사전체크).

### 8.7 CI 미도입 (이유)

- 1인 연구 도구, 단발성 캡처 목적
- pytest 로컬 수동 실행이 충분
- 향후 sub-project #2~#4 확장 시 GitHub Actions 검토

### 8.8 "본 캡처 진행 가능" 게이트

```
$ pytest                              # 모든 unit + integration 통과
$ ./scripts/smoke.sh                  # 5분 live smoke 통과
$ # 봇 서버 로그 평소 대비 정상 (사용자 육안 확인)
→ 본 4시간 캡처 진행 가능
```

## 9. 구현 전 검증 항목

다음은 **구현 단계 직전**에 공식 docs 또는 짧은 probe로 한 번 더 확인해야 할 사항:

| 항목 | 확인 방법 | 영향 |
|---|---|---|
| Public WS endpoint URL (`wss://pubwss.bithumb.com/pub/ws`) | apidocs.bithumb.com 최신 reference | 잘못되면 connect 실패 |
| Private WS endpoint URL (`wss://ws-api.bithumb.com/websocket/v1/private`) | apidocs.bithumb.com 최신 reference | 잘못되면 connect 실패 |
| 심볼 코드 (`USDT_KRW`) | docs 또는 5초 probe | 잘못되면 빈 스트림 |
| `orderbookdepth` 첫 메시지 깊이 (~30 levels 추정) | probe | 깊이 가정 검증 |
| Private WS JWT payload 정확한 필드 (`access_key`, `nonce`, query_hash 필요 여부) | apidocs.bithumb.com v2.x reference | 잘못되면 auth 실패 |
| Private WS 구독 메시지 정확한 형식 (`ticket`/`type` 배열 형식) | apidocs.bithumb.com | 잘못되면 구독 실패 |
| `myOrder`/`myAsset` 페이로드 필드 이름 (state, side, price, qty 등) | probe 또는 docs | convert.py 컬럼 추출에 영향 |
| 계정 단위 rate-limit 존재 여부 | 5분 dry-run + 봇 모니터링 (§7.4) | observer 격리성 |

위 항목 중 하나라도 spec과 다르게 발견되면 spec을 patch한 뒤 구현을 진행한다.

## §9.1 — Verified findings (2026-04-28 live probe)

Live WS probe against real Bithumb endpoints revealed the following (all items verified ✓):

| 항목 | 검증 결과 |
|---|---|
| Public WS URL | `wss://ws-api.bithumb.com/websocket/v1` ✓ (spec의 pubwss URL은 구버전) |
| Private WS URL | `wss://ws-api.bithumb.com/websocket/v1/private` ✓ |
| Public 채널 이름 | `orderbook` (not `orderbookdepth`), `trade` (not `transaction`) |
| Private 채널 이름 | `myOrder`, `myAsset` (unchanged) |
| 구독 메시지 형식 | 단일 JSON 배열 1회 전송 (Upbit-compatible). 채널별 별도 메시지 아님 |
| `myOrder` codes 필터 | **필수** — `"codes": ["KRW-USDT"]` 없으면 메시지 미전달 |
| `myAsset` codes 필터 | 불필요 (account-wide) |
| 심볼 형식 | `KRW-USDT` (하이픈 구분, Upbit 형식). 기존 spec의 `USDT_KRW`는 v1 형식 |
| 페이로드 구조 | Flat top-level (no `content` wrapper). `timestamp` 필드가 최상위에 ms-since-epoch int |
| `trade` 주요 필드 | `ask_bid` (`"ASK"`/`"BID"`), `trade_price`, `trade_volume` |
| `orderbook` 주요 필드 | `orderbook_units[].ask_price/bid_price/ask_size/bid_size` |
| `myOrder` 주요 필드 | `uuid`, `state`, `ask_bid`, `order_type`, `volume`, `executed_volume`, `remaining_volume`, `paid_fee`, `executed_funds`, `trade_timestamp`, `order_timestamp` |
| `myAsset` 주요 필드 | `assets[].currency/balance/locked` (배열 구조) |

**영향**: `ws_public.py`, `ws_private.py`, `convert.py`, `main.py`, 모든 fixture/테스트를 v2 스키마로 재작성 완료.

## 10. 성공 기준

이 sub-project가 "완료"로 판정되는 조건:

1. ✅ `pytest`가 모든 단위·통합 테스트를 통과한다.
2. ✅ `scripts/smoke.sh`가 5분 dry-run에 통과하고 봇이 정상이다.
3. ✅ 본 4시간 캡처가 §7.5의 "OK" 임계값 안에서 종료된다 (누적 갭 < 60초, 단일 갭 < 30초, auth 실패 0).
4. ✅ `convert.py`가 4개 Parquet 파일을 생성하고 검증 리포트를 출력한다.
5. ✅ Parquet 데이터가 가설 1 분석에 필요한 4개 컬럼셋을 모두 포함한다 (§6.7).
6. ✅ MM 봇이 캡처 기간 동안 평소 대비 이상 신호 없이 운용됐음을 사용자가 확인한다.

## 11. 향후 작업 (다음 sub-projects)

이 spec 완료 후 진행될 sub-project들:

- **#2** — Backtest engine: 캡처된 Parquet을 입력으로 받아 호가창 재구성, 큐 포지션 추정, fill 시뮬레이션. 단, 본 spec의 라이브 검증 결과가 충분하다면 #2를 건너뛰고 바로 #4로 갈 수도 있음.
- **#3** — Velocity filter 알고리즘 모듈 (intensity 정의, 임계값, 시그널 발생 로직).
- **#4** — 가설 1 검증 리포트: 캡처 데이터에서 "velocity 시그널 발생 시점"과 "myOrder의 adverse fill 시점" 반사실 join → 회피 가능성·체결률·역선택 발생 횟수·최종 PnL 영향 정량화.

가설 2 (Lead-Lag)는 별도 sub-project 계열로 분리.
