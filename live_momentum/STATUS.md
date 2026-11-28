# live_momentum status (as of 2026-11-26)

## Running
- **Host:** Windows PC. Scheduled tasks `LiveMomentumPaper`, `LiveMomentumReport` and `LiveMomentumLive`, all
  at logon.
- **Moving to a Mac mini.** See `deploy/DEPLOY.md`, section "macOS host". The live trader must run on one host
  only. The next session is 2026-11-30 09:30 NY (23:30 KST). 11/26 is Thanksgiving and 11/27 is an early close,
  which is skipped by design.
  - Mac mini progress (2026-11-29): checkout `~/live-momentum` (Python 3.14.10, same package versions as
    Windows), history 2021-01..2026-11-27 cached, tests 134 passed and 0 skipped. Paper smoke run: streams
    connect, clock offset −4 ms. Waiting on the user's sudo steps and the Windows shutdown.
- **Live:** `deploy/windows/config.live.toml`.
  - `size_mode = "min"`: every entry at the exchange minimum, about 61 / 23 / 6 USDT for BTC / ETH / SOL.
  - Account about 27.87 USDT. Gross cap 3.5x and daily loss limit 10% (user decision 2026-11-23).
  - The user set the approval `LIVE_MOMENTUM_ACK=phase3-live:2026-12-20`. Claude never sets or extends it.
  - The code does not set exchange leverage. The account's leverage setting for BTC/ETH/SOL must allow the
    minimum orders (≥ 5x). Check it in the Binance UI.
- **Live record so far:** sessions 11/23, 11/24 and 11/25 had 0 trades. On 11/24 SOL broke the lower band at
  10:30, but the VWAP 0.6σ filter blocked it (0.81% vs the 0.91% needed). On 11/25 SOL came within 0.07% of the
  upper band after the 14:00 cutoff. The backtest expects 0 trades on about 36% of days.
- **Health:** no data gaps and no order errors. The clock is within 0.2 s of Binance. A public-stream reconnect
  storm on 11/24 00:49–01:01 KST recovered by itself.

## Backtest reference numbers (production configuration, 2021-05..2026-10)
- Sharpe 1.43, CAGR 29.4%, vol 19.3%, MDD −16.2%. About 7.3 entries a week across 3 coins, and at least one coin
  trades on 64% of days.
- CPCV (1x unit size): PBO 0.53, OOS path SR 0.92–1.22, selection inflation about 0.2. Treat a realistic
  expectation as SR around 1, not 1.43. Details are in `crypto_intraday_momentum/IDEAS_LOG.md` (seminar
  re-check, #12–#15).

## Open items
1. Finish the Mac mini move (user steps in DEPLOY.md: IP whitelist or a new key, `live.secrets`, `live.ack`,
   stop and disable the Windows tasks).
2. Recompute the "수익원 ① 시간대" slide t-values clustered by day. The current pooled t overstates significance.
3. Log the `premarket/` side studies (ETF, 24h futures, weekend) in IDEAS_LOG after re-running them.
4. Fade strategy F from `crypto_range` (forward test only, paper): not started.
5. Re-test IDEAS #13 (15-min entries, 30-min exits) once enough live data exists. It does not justify a change now.

## Seminar material
- Deck sources: `docs/seminar_2026-11/deck/`. The published deck (private claude.ai artifact) and the Korean talk
  script are linked in the owner's claude.ai account.
- Experiment scripts and results: `crypto_intraday_momentum/experiments/2026-11_seminar/`.
