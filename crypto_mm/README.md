# crypto_mm: USDC-M perp market-making research

| 파일 | 역할 |
|---|---|
| `pilot.py` | data.binance.vision 아카이브로 USDC vs USDT 무기한 예비 분석 (`research/mm/06`) |
| `collector.py` | **Binance USD-M 공개 시장데이터 수집기**. 출력 형식이 hftbacktest 원본 형식과 호환돼요 |
| `collector.toml` | 수집 대상 설정. 기본값은 USDC 5종목 전체 호가 + USDT 5종목 체결·최우선호가 |
| `convert_day.py` | 하루치 수집 파일을 hftbacktest `.npz`로 바꾸고 피드 품질을 보고해요 |
| `tests/test_collector.py` | 가짜 Binance(WebSocket + REST)로 하는 통합 테스트. hftbacktest 변환까지 검증해요 |

## 수집기 동작
- **입력**: `wss://fstream.binance.com/stream`의 combined stream이에요.
  - USDC 종목: `depth@0ms`(호가 증분), `trade`, `bookTicker`
  - USDT 종목: `trade`, `bookTicker`
  - **공개 엔드포인트만 쓰고 API 키는 필요 없어요.**
- **출력**: `<out>/<YYYYMMDD>/<symbol>.gz`이고, 한 줄 형식은 `수신시각_ns(19자리) 원본JSON`이에요.
  - hftbacktest의 `binancefutures.convert()`가 그대로 읽어요.
  - REST 호가 스냅샷(`/fapi/v1/depth?limit=1000`)도 같은 파일에 기록돼요. 기록되는 시점은 세 가지예요: 접속·재접속 시, 증분 순번(`pu` ≠ 직전 `u`)이 끊겼을 때, 매시간.
  - 변환기는 스냅샷을 DEPTH_CLEAR + DEPTH_SNAPSHOT 이벤트로 바꿔요.
- **안정성**
  - 23시간마다 미리 재연결해요(Binance는 24시간 뒤 연결을 끊어요).
  - 끊기면 지수 백오프로 재연결해요. 30초 동안 데이터가 없으면 재연결해요.
  - SIGTERM을 받으면 파일을 정상적으로 닫아요.
  - append 모드 gzip이라 재시작해도 같은 날 파일에 이어서 써요.
- **보조 기록**
  - 하루 한 번 `exchangeInfo.json`을 저장해요. 호가 단위와 최소 수량은 백테스트 설정에 필요해요.
  - 1분마다 로그를 남겨요: 스트림별 msg/s, 수신−거래소 지연 중앙값, 끊김 횟수, 재연결 횟수, 기록량(MB).

## 서버 배포
1. **위치**
   - 실제 MM 지연과 비슷한 조건으로 수집하려면 **AWS ap-northeast-1(도쿄)**을 권장해요. Binance 매칭 엔진의 위치 근거는 `research/mm/05` §6에 있어요.
   - Binance 서비스가 허용되는 관할에서 실행하고, Binance 이용약관을 확인하세요. 이 개발 환경(미국)에서는 `api.binance.com`이 451 응답을 주고, fapi는 지역 제한으로 막혀 있어요.
2. **시계 동기화가 필수예요.**
   - `sudo apt install chrony`로 설치하고, AWS라면 Amazon Time Sync(169.254.169.123)를 쓰세요.
   - 로그의 "recv-E latency"는 시계 오차를 포함해요. 이 값이 음수이면 시계가 틀린 거예요.
3. **설치**
   ```bash
   python3 -m venv ~/mmenv && source ~/mmenv/bin/activate
   pip install -r crypto_mm/requirements.txt
   python -m pytest crypto_mm/tests -q        # 동작 확인
   ```
4. **상시 실행 (systemd)**: `/etc/systemd/system/mm-collector.service`
   ```ini
   [Unit]
   Description=Binance USD-M market data collector
   After=network-online.target
   [Service]
   WorkingDirectory=/home/ubuntu/270-Valuation
   ExecStart=/home/ubuntu/mmenv/bin/python -m crypto_mm.collector --config crypto_mm/collector.toml --out /data/md_raw
   Restart=always
   RestartSec=5
   [Install]
   WantedBy=multi-user.target
   ```
   등록과 로그 확인은 `sudo systemctl enable --now mm-collector`와 `journalctl -u mm-collector -f`로 해요.
5. **디스크**
   - 기록량을 미리 알 수는 없어요(미확인). 첫날 로그의 "MB written"으로 하루 용량을 확인하세요.
   - 참고로 아카이브 기준 BTCUSDT bookTicker는 하루 약 267MB(zip)였어요. 증분 호가(`depth@0ms`)는 이보다 클 수 있어요.
   - 디스크가 부족하면 `collector.toml`에서 종목이나 스트림을 줄이세요.
6. **일별 변환 (cron, UTC 00:30)**
   ```bash
   30 0 * * * cd /home/ubuntu/270-Valuation && /home/ubuntu/mmenv/bin/python -m crypto_mm.convert_day --raw /data/md_raw --day $(date -u -d yesterday +\%Y\%m\%d) --out /data/md_npz >> /data/convert.log 2>&1
   ```

## 알려진 한계
- 스냅샷은 수신 시각 기준으로 적용돼요. 스냅샷 직후에 도착한 증분 중 `u < lastUpdateId`인 오래된 증분이 있으면 해당 가격대가 잠시 틀릴 수 있어요. 증분은 절대 수량을 덮어쓰는 방식이라 다음 갱신 때 자동으로 바로잡혀요. 이 문제는 hftbacktest 기본 수집 방식과 같아요.
- L3(주문 단위) 데이터는 Binance가 제공하지 않아요. 대기열 위치는 백테스트에서 모델(RiskAverse 등)로 가정해야 해요.
- 주문 지연은 수집으로는 측정할 수 없어요. 실주문 없이는 가정값으로 백테스트해요(`research/mm/04` E4).
