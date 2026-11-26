# strategy-hypothesis-lab: Claude Code project rules

Research and trading code for crypto strategy hypotheses. The active work is the intraday noise-band momentum
strategy:
- research and backtest: `crypto_intraday_momentum/`
- live and paper trader: `live_momentum/`, on branch `feat/live-momentum`

Read these first:
1. `live_momentum/STATUS.md`: what is running now and the open items
2. `crypto_intraday_momentum/README.md` and `IDEAS_LOG.md`: rules, and every idea tried, adopted or rejected
3. `live_momentum/README.md` and `live_momentum/deploy/DEPLOY.md`: modules, deployment and operation
4. `HANDOFF_live_trading_momentum.md`: the original live-trading spec (phases, safety rules)

## Working style
- Answer the user in Korean.
- Verify before you claim anything: run the tests and quote the numbers. Report failures and skipped steps as
  they are.
- Keep authoring and review in separate passes. Get an independent reviewer or verifier before you commit a
  non-trivial change.
- Every code change passes `PYTHONPATH=. .venv/bin/python -m pytest live_momentum/tests crypto_intraday_momentum/tests -q`
  before you commit and push to the working branch.
- Log every new strategy variant in `crypto_intraday_momentum/IDEAS_LOG.md`, including rejected ones, and update
  the total variant count. The research history start stays at 2021-01.
- Cleanup or validation scripts only report. Test on a known-good file first, and ask before you delete anything.
- Do not stop or kill the user's other processes without asking.

## Safety rules for live trading (user's standing instructions, always in force)
- 실주문은 단계별로 사용자가 명시적으로 승인한 뒤에만 해. 기본값은 `DRY_RUN=true`.
- 승인 토큰 `LIVE_MOMENTUM_ACK`는 사용자가 직접 설정한다. Claude는 이 값을 설정하거나 연장하지 않는다.
- API 키: 선물 거래 권한만 주고 출금 권한은 금지해. 서버 IP 화이트리스트도 걸어. 키는 환경변수나 권한 600인
  별도 파일(`live_momentum/runtime/live.secrets`)에 둬. 저장소에 커밋하거나 로그에 출력하지 마.
  Claude는 키 파일을 열거나 키 값을 출력하지 않는다.
- 필수 리스크 한도는 설정 파일로 관리한다:
  - 일일 최대 손실(초과 시 당일 신규 진입 중단 + 전량 청산)
  - 종목별 최대 명목금액, 총 레버리지 상한
  - 데이터 지연 감시: 시세가 N초 이상 멈추면 신규 주문 중단
  - 킬 스위치: 파일이나 명령 하나로 전체 주문 취소 + 전량 청산
- one-way 포지션 모드를 쓰고, 청산 주문은 `reduceOnly`로 내. 모든 주문에 `newClientOrderId`를 붙여서 중복
  주문을 막아. 체결은 user data stream으로 받고, 재시작할 때 REST로 포지션과 미체결 주문을 대조(reconcile)해.
- Binance 이용 자격과 관할 규정 확인은 사용자 책임이야. 접속이 지역 제한으로 막히면 우회하지 말고 보고해.
- 키, 수집 데이터(`live_momentum/runtime/`), 실거래 로그의 민감 정보는 커밋하지 마.
- 실거래는 한 계정에 한 호스트에서만 돌린다. 호스트를 옮길 때는 계정이 무포지션인 세션 사이에, 이전 호스트를
  먼저 멈추고 비활성화한 뒤 시작한다.
