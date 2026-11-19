# 서버 세션 인계 프롬프트 (수집기 설치·가동·점검)

AWS 도쿄 EC2에서 실행하는 새 Claude Code 세션에 아래 내용을 그대로 붙여 넣으세요.

---

# 작업: Binance USDC-M 무기한 선물 공개 시장데이터 수집기를 이 서버에서 설치·가동·점검

## 배경
- 이 서버는 AWS 도쿄(ap-northeast-1) EC2(Ubuntu)야. 목적은 Binance USDC-M 무기한 선물에서 양방향 메이커 MM 전략을 검증할 백테스트 데이터를 1~2주간 직접 수집하는 거야.
- 저장소: 270-Valuation, 브랜치 `claude/sharp-cannon-qxbvty`. 지금까지의 리서치와 코드는 모두 이 브랜치에 있어.
- 먼저 읽을 문서
  - `crypto_mm/README.md`: 수집기 구조, 배포 절차, 디스크·보관 정책
  - `research/mm/06_usdc_perp_pilot.md`: 대상 종목 선정 근거. 후보는 ETH, SOL, XRP이고, 수수료는 메이커 0bp, 테이커 4bp
  - `research/mm/04_experiments.md`: 수집 데이터로 할 실험 E1~E4
- 수집 대상(`crypto_mm/collector.toml`)
  - ETHUSDC, SOLUSDC, XRPUSDC: depth@0ms + trade + bookTicker
  - ETHUSDT, SOLUSDT, XRPUSDT: trade + bookTicker

## 규칙
- **공개 시장데이터만** 받아. API 키, 주문, 계좌 관련 호출은 절대 하지 마.
- Binance 접속이 지역 제한(restricted location)으로 막히면 우회(VPN·프록시)하지 말고 바로 멈춘 뒤 보고해.
- 시스템 설정(systemd, cron, chrony, 패키지 설치)을 바꾸기 전에는 무엇을 바꿀지 한 줄로 알리고 진행해.
- 코드를 고치면 테스트를 통과시킨 뒤 이 브랜치에 커밋·푸시해. 수집 데이터(`md_raw`, `md_npz`)는 절대 커밋하지 마.

## 단계
1. **환경 점검**
   - `python3 --version`(3.11 이상), `df -h`(여유 100GB 이상 권장), `nproc`, `free -h`를 확인해.
   - `curl -sS https://fapi.binance.com/fapi/v1/time`이 serverTime을 반환하는지 확인해. 지역 제한 메시지가 나오면 즉시 중단하고 보고해.
2. **시계 동기화**
   - chrony를 설치·활성화해. AWS라면 Amazon Time Sync(169.254.169.123)를 써.
   - `chronyc tracking`의 오프셋이 1ms 미만인지 확인해.
3. **설치와 테스트**
   ```bash
   python3 -m venv ~/mmenv && source ~/mmenv/bin/activate
   pip install -r crypto_mm/requirements.txt
   python -m pytest crypto_mm/tests -q      # 3개 통과해야 함
   ```
4. **경로 설정**
   - `collector.toml`에서 `out_dir = "/data/md_raw"`, `converted_dir = "/data/md_npz"`로 바꿔.
   - `/data`가 충분한 디스크에 있는지 확인해.
5. **시험 수집 10분**
   - `python -m crypto_mm.collector --config crypto_mm/collector.toml`를 포그라운드로 실행해.
   - 1분 통계 로그에서 확인할 것
     - 6개 종목·스트림별 msg/s가 모두 0보다 큰지
     - depth gap이 0이거나 매우 드문지
     - 수신−거래소 지연 중앙값이 양수이고 수 ms~수십 ms인지(음수면 시계 문제)
     - 스냅샷 3건(USDC 종목별 1건)과 exchangeInfo.json이 저장됐는지
   - 10분 동안의 MB written으로 하루 용량을 추정해.
6. **상시 실행 등록**
   - README의 systemd 유닛(`mm-collector.service`)을 실제 사용자명과 경로로 수정해서 등록해(`enable --now`).
   - `journalctl -u mm-collector -f`로 정상 동작을 확인해.
7. **일별 변환 등록**
   - README의 cron 줄(UTC 00:30, `convert_day --out /data/md_npz`)을 등록해.
   - 시험 수집 파일로 `convert_day`를 한 번 수동 실행해서 npz가 생성되는지 확인해.
8. **1시간 후 점검**
   - 재연결 횟수, gap 수, 종목별 MB/시간, 수신 지연 p50을 확인해.
   - 하루·2주 용량을 다시 추정해.

## 보고할 것 (표로)
- 환경: 리전, 인스턴스 사양, 디스크 여유, Python 버전, chrony 오프셋
- Binance 접속 결과(serverTime 또는 오류 원문)
- 종목·스트림별 msg/s, 수신 지연 p50, gap 수, 재연결 수
- 하루 원본 용량 추정, npz 크기(변환 테스트 결과), 7일 보관 정책 기준 필요 디스크
- 발생한 오류와 조치, 변경해서 커밋한 파일
- 다음 단계 제안. 수집이 1~2주 쌓이면 E1~E3 측정(지연 분포, markout, κ·A 추정)을 한 뒤 hftbacktest로 양방향 메이커 GLFT 백테스트(E4)를 진행할 계획이야.
