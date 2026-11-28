# 맥미니 Claude Code 세션 시작 프롬프트

## 준비 (맥 터미널에서 직접)

```bash
xcode-select --install            # git이 없으면 (Command Line Tools)
brew install python@3.14          # Homebrew가 없으면 https://brew.sh 먼저
git clone https://github.com/firefly0731/strategy-hypothesis-lab.git ~/strategy-hypothesis-lab
cd ~/strategy-hypothesis-lab && git checkout feat/live-momentum
claude                            # Claude Code 설치·로그인 후
```

## 프롬프트 (Claude Code에 그대로 붙여 넣기)

```text
이 맥미니를 live_momentum 트레이더(노이즈 밴드 모멘텀, Binance USDⓈ-M BTC/ETH/SOL)의 유일한 운영 서버로 만들 거야.
지금까지는 Windows PC에서 최소 수량 실주문(Phase 3)으로 돌았어. 브랜치는 feat/live-momentum이고 코드는 전부 원격에 있어.

먼저 아래 문서를 읽고 현재 상태와 규칙을 파악해:
1. CLAUDE.md (작업 원칙과 실거래 안전 규칙. 항상 지켜)
2. live_momentum/STATUS.md (운영 현황, 기준 수치, 남은 일)
3. live_momentum/deploy/DEPLOY.md 의 "macOS host (Mac mini)" 절 (이번 작업의 절차서)
4. live_momentum/README.md, crypto_intraday_momentum/README.md, crypto_intraday_momentum/IDEAS_LOG.md

할 일:
A. 호스트 점검과 설정
   - 확인: macOS·CPU, 디스크 여유(데이터 약 0.8 GB 필요), 시계(sntp time.apple.com, 자동 시간 설정 켜짐),
     Binance 접속(curl -s https://fapi.binance.com/fapi/v1/time), 공인 IP(curl -s https://api.ipify.org).
     451이나 403이 나오면 거기서 멈추고 보고해. 우회하지 마.
   - 절전 끄기와 정전 후 자동 재시작: sudo pmset -a sleep 0 disksleep 0 autorestart 1
     이 명령은 내가 실행할게. 실행 후 pmset -g 에서 sleep 0, autorestart 1 인지 확인해.
B. 설치: Python 3.14 venv(.venv)를 만들고 Windows 호스트와 같은 버전을 설치해
   (pandas 3.1.1, numpy 2.5.5, exchange_calendars 4.13.3, websockets 17.4, pyarrow 26.0.1, requests 2.34.2, pytest).
   정확히 같은 버전이 없으면 가장 가까운 버전을 쓰고 어떤 걸 썼는지 보고해.
C. 과거 데이터 받기: 2021-01부터 현재 월까지 BTC/ETH/SOL 1분봉과 펀딩비. 명령은 DEPLOY.md에 있어.
   연구 기준 시작 시점은 2021-01로 고정이야.
D. 테스트는 데이터를 받은 뒤에 돌려:
   PYTHONPATH=. .venv/bin/python -m pytest live_momentum/tests crypto_intraday_momentum/tests -q -rs
   기대값은 Windows와 같은 "134 passed, 0 skipped"야. 데이터가 없으면 parity 테스트가 skip되니까
   skip이 하나라도 있거나 실패가 있으면 원인을 찾아서 보고하고, 다음 단계로 넘어가지 마.
   parity 테스트가 실패하면 이 맥의 신호가 Windows·백테스트와 달라진다는 뜻이야.
E. paper 트레이더와 일일 리포트 설치: sudo live_momentum/deploy/macos/install.sh paper report
   sudo 명령은 정확히 적어서 나한테 실행해 달라고 요청해.
   설치 후 sudo launchctl print system/com.livemomentum.paper, supervisor.log, paper 로그로 정상 기동을 확인해.
   킬 스위치도 paper 설정으로 시험해 봐. status → kill → status → unkill → status 순서로 하나씩 실행하고,
   반드시 unkill로 끝내 (안 그러면 paper가 신규 진입을 계속 막아):
   PYTHONPATH=. .venv/bin/python -m live_momentum.cli status --config live_momentum/deploy/macos/config.paper.toml
   PYTHONPATH=. .venv/bin/python -m live_momentum.cli kill --config live_momentum/deploy/macos/config.paper.toml
   PYTHONPATH=. .venv/bin/python -m live_momentum.cli unkill --config live_momentum/deploy/macos/config.paper.toml
F. 실거래 준비 점검: 아래 "내가 직접 할 일"이 모두 끝났는지 하나씩 나한테 확인받아.
   live.secrets와 live.ack는 존재 여부, 권한 600, 소유자만 확인하고 내용은 절대 열지 마.
   모두 맞으면 실행할 명령을 알려 줘. sudo live_momentum/deploy/macos/install.sh live 는 내가 명시적으로
   승인한 뒤 내가 실행한다.
G. 기동 확인: live.log에서 preflight 통과, reconcile 결과, user data stream 연결, 시계 오차를 확인해.
   비상시 명령(킬 스위치, --flatten, 중지)을 DEPLOY.md 표에서 맥 경로 그대로 정리해서 보여 줘.
   다음 세션 시작(session_start 이벤트)과 첫 세션 종료까지 상태를 보고해.

내가 직접 할 일 (Claude는 대신하지 않음):
1. Binance API 키: 이 맥 전용 새 키를 만들고(선물 거래 권한만, 출금 금지, 이 맥의 공인 IP만 화이트리스트),
   Windows에서 쓰던 키는 삭제한다.
2. live_momentum/runtime/live.secrets 를 nano로 직접 만든다 (umask 077, 권한 600).
3. live_momentum/runtime/live.ack 에 승인 토큰을 직접 넣는다. Claude는 이 값을 만들거나 연장하지 않는다.
4. Windows PC에서 기존 트레이더를 완전히 멈춘다 (PowerShell):
   Stop-ScheduledTask LiveMomentumLive; Disable-ScheduledTask LiveMomentumLive
   Stop-ScheduledTask LiveMomentumPaper; Disable-ScheduledTask LiveMomentumPaper
   Disable-ScheduledTask LiveMomentumReport      # 리포트도 맥이 만들므로 중복 방지
   Get-CimInstance Win32_Process -Filter "Name='python.exe'" | Where-Object CommandLine -match 'run_live|run_paper'
     -> 결과가 비어 있어야 한다. 남아 있으면 Stop-Process -Id <pid>
   [Environment]::SetEnvironmentVariable("LIVE_MOMENTUM_ACK", $null, "User")
5. 계정이 BTCUSDT/ETHUSDT/SOLUSDT 무포지션이고 미체결 주문이 없는지 확인한다.

반드시 지킬 것:
- 한 계정에는 트레이더 하나만 돈다. 위 4번이 끝났다고 내가 확인해 주기 전에는 맥에서 live를 설치하거나
  시작하지 마. 맥의 single-instance 잠금은 다른 호스트를 감지하지 못해.
- 호스트 전환은 세션 사이에만 한다. 세션은 뉴욕 09:30~16:00이니까 전환은 뉴욕 16:00 ~ 다음 날 09:00 사이야
  (지금은 표준시라 한국시간 06:00~23:00, 2027-03-14 서머타임부터는 05:00~22:00).
  다음 세션은 2026-11-30 23:30 KST야. paper 확인까지 포함해서 전환은 그 전에 끝내.
- config.live.toml 은 dry_run = false 라서, live 작업이 설치되고 승인 토큰이 유효하면 실제 주문이 나간다.
  내 승인 토큰이 유일한 관문이야. 실주문 단계는 내가 단계별로 명시적으로 승인한 뒤에만 진행해.
- Windows로 되돌릴 때는 맥에서 먼저 sudo live_momentum/deploy/macos/install.sh remove live 를 하고
  live.ack 를 지운 뒤에 Windows 작업을 다시 켠다. 안 그러면 맥이 재부팅될 때 트레이더가 다시 뜬다.
- API 키와 시크릿은 출력하거나 커밋하거나 로그에 남기지 마. live_momentum/runtime/ 은 커밋하지 마.
- 정리나 검증 스크립트는 보고만 하고, 삭제는 나한테 먼저 물어봐. 다른 프로세스를 내 허락 없이 죽이지 마.
- 코드를 바꾸면 테스트를 통과시킨 뒤, 별도 리뷰를 받고 feat/live-momentum에 커밋·푸시해.
  새 전략 변형은 IDEAS_LOG.md에 기록해.

진행 중에는 단계마다 짧게 결과를 알려 주고, 마지막에 무엇이 돌고 있고 내가 할 일이 뭐가 남았는지 한국어로 정리해 줘.
```

선택: 리포트 기록을 이어 가려면 Windows의 `live_momentum/runtime/live/data/`(수집한 봉과 이벤트 로그, 몇 MB)를
맥의 같은 경로로 복사한다. 무포지션이면 상태 파일은 필요 없다.
