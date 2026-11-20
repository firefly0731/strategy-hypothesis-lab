"""Accounting tests on small synthetic histories (DESIGN.md §2–3)."""
import numpy as np
import pandas as pd
import pytest

from crypto_cash_carry.engine import Band, Costs, Market, simulate

C = Costs()
B = Band()


def mkt(spot, perp=None, high=None, funding=None, mmr=0.004, symbols=("AAA",)):
    spot = np.asarray(spot, float).reshape(len(spot), -1)
    perp = spot.copy() if perp is None else np.asarray(perp, float).reshape(spot.shape)
    high = perp.copy() if high is None else np.asarray(high, float).reshape(spot.shape)
    fund = np.zeros(spot.shape) if funding is None else np.asarray(funding, float).reshape(spot.shape)
    idx = pd.date_range("2024-01-01 01:00", periods=len(spot), freq="1h", tz="UTC")
    return Market(index=idx, symbols=list(symbols), spot=spot, perp=perp, liq_high=high,
                  funding=fund, mmr=np.full(spot.shape[1], mmr))


def run(m, enter_at=0, close_at_end=False, slots=1, **kw):
    return simulate(m, {enter_at: list(m.symbols)}, slots=slots, costs=kw.pop("costs", C), band=B,
                    close_at_end=close_at_end, **kw)


def entry_equity(cash=1.0, costs=C):
    return cash / (1 + 0.75 * (costs.c_s + costs.c_p))


def test_entry_costs_fee_and_slippage_per_side():
    r = run(mkt([100.0, 100.0]))
    e = entry_equity()
    b = r.bars.iloc[0]
    assert b["fee"] == pytest.approx(0.75 * e * (0.0010 + 0.0005), abs=1e-15)
    assert b["slippage"] == pytest.approx(0.75 * e * 0.0002 * 2, abs=1e-15)
    assert b["equity"] == pytest.approx(e, abs=1e-12)
    s = r.state_after[0]["AAA"]
    assert s["qs"] * 100 == pytest.approx(0.75 * e) and s["qp"] * 100 == pytest.approx(0.75 * e)
    assert s["M"] == pytest.approx(0.25 * e)
    assert s["qp"] * 100 / s["M"] == pytest.approx(3.0)


@pytest.mark.parametrize("rate", [0.0001, -0.0003])
def test_funding_cashflow_sign_on_short(rate):
    f = [0, 0, rate]
    r = run(mkt([100.0, 100.0, 100.0], funding=f))
    qp = r.state_after[0]["AAA"]["qp"]
    assert r.bars["funding"].iloc[2] == pytest.approx(qp * 100 * rate, abs=1e-15)
    assert np.sign(r.bars["funding"].iloc[2]) == np.sign(rate)   # r>0: longs pay the short
    assert r.bars["equity"].iloc[2] - r.bars["equity"].iloc[1] == pytest.approx(qp * 100 * rate, abs=1e-15)


def test_settlement_in_entry_bar_is_not_received():
    # position is opened at the close of bar 0, after bar 0's settlement
    r = run(mkt([100.0, 100.0], funding=[0.01, 0.0]))
    assert r.bars["funding"].iloc[0] == 0.0


@pytest.mark.parametrize("move", [1.05, 0.95])
def test_hedged_against_price_moves(move):
    r = run(mkt([100.0, 100.0 * move]))
    b = r.bars.iloc[1]
    assert b["spot_pnl"] == pytest.approx(-b["perp_pnl"], abs=1e-15)
    assert r.bars["equity"].iloc[1] == pytest.approx(r.bars["equity"].iloc[0], abs=1e-12)
    assert b["n_rebal"] == 0


@pytest.mark.parametrize("move, expect", [(1.10, 0), (1.12, 1), (0.90, 0), (0.88, 1)])
def test_leverage_band_triggers_rebalance_back_to_target(move, expect):
    r = run(mkt([100.0, 100.0 * move]))
    assert r.bars["n_rebal"].iloc[1] == expect
    s = r.state_after[1]["AAA"]
    lev = s["qp"] * 100 * move / s["M"]
    if expect:
        assert lev == pytest.approx(3.0, abs=1e-9)
        assert s["qs"] * 100 * move == pytest.approx(s["qp"] * 100 * move)   # spot = short notional
    else:
        assert 2.0 <= lev <= 5.0
    assert r.n_rebalances == expect


def test_rebalance_costs_solve_fixed_point():
    r = run(mkt([100.0, 112.0]))
    b = r.bars.iloc[1]
    pre = r.bars["equity"].iloc[0]                 # no PnL: spot gain = perp loss
    a = r.state_after[0]["AAA"]["qs"] * 112
    bb = r.state_after[0]["AAA"]["qp"] * 112
    e1 = b["equity"]
    cost = C.c_s * abs(0.75 * e1 - a) + C.c_p * abs(0.75 * e1 - bb)
    assert e1 == pytest.approx(pre - cost, abs=1e-13)
    assert b["fee"] + b["slippage"] == pytest.approx(cost, abs=1e-13)


def test_exit_proceeds_and_costs():
    r = run(mkt([100.0, 100.0, 100.0]), close_at_end=True)
    e = r.bars["equity"].iloc[0]
    last = r.bars.iloc[-1]
    exit_cost = 0.75 * e * (C.c_s + C.c_p)
    assert last["equity"] == pytest.approx(e - exit_cost, abs=1e-13)
    assert last["cash"] == pytest.approx(last["equity"]) and last["n_active"] == 0


def test_equity_identity_on_random_path_with_basis_and_funding():
    rng = np.random.default_rng(1)
    n = 2000
    s = 100 * np.exp(np.cumsum(rng.normal(0, 0.01, (n, 2)), axis=0))
    p = s * (1 + rng.normal(0, 0.001, (n, 2)))
    hi = p * (1 + np.abs(rng.normal(0, 0.003, (n, 2))))
    f = np.where(np.arange(n)[:, None] % 8 == 0, rng.normal(1e-4, 2e-4, (n, 2)), 0.0)
    m = mkt(s, p, hi, f, symbols=("AAA", "BBB"))
    r = simulate(m, {0: ["AAA", "BBB"]}, slots=2, costs=C, band=B, close_at_end=True)
    b = r.bars
    parts = b["spot_pnl"] + b["perp_pnl"] + b["funding"] - b["fee"] - b["slippage"] - b["liq_loss"]
    np.testing.assert_allclose(b["equity"].diff().iloc[1:], parts.iloc[1:], atol=1e-9)
    assert r.n_rebalances > 0
    total = b["equity"].iloc[-1] - 1.0
    assert total == pytest.approx(parts.sum() - 0.0, abs=1e-9)   # entry costs are inside bar 0


def test_intrabar_liquidation_then_rehedge():
    # +40% intrabar high on the perp with no rebalance in between: worst futures equity < mmr·notional
    m = mkt([100.0, 101.0], perp=[100.0, 101.0], high=[100.0, 140.0], mmr=0.004)
    r = run(m)
    b = r.bars.iloc[1]
    s0 = r.state_after[0]["AAA"]
    qp, M0 = s0["qp"], s0["M"]
    p_liq = (M0 + qp * 100) / (qp * 1.004)
    assert b["n_liq"] == 1
    assert b["liq_loss"] == pytest.approx(0.004 * qp * p_liq, rel=1e-12)
    assert b["perp_pnl"] == pytest.approx(-qp * (p_liq - 100), rel=1e-12)
    s1 = r.state_after[1]["AAA"]                   # re-hedged at the close of the same bar
    assert s1["qp"] * 101 / s1["M"] == pytest.approx(3.0)
    assert b["n_rebal"] == 1


def test_no_liquidation_when_high_stays_inside():
    r = run(mkt([100.0, 101.0], high=[100.0, 115.0]))
    assert r.bars["n_liq"].iloc[1] == 0


def test_outage_holds_and_marks_on_return():
    m = mkt([100.0, np.nan, 103.0], perp=[100.0, np.nan, 103.0])
    r = run(m)
    assert r.bars["n_rebal"].sum() == 0
    assert r.bars["spot_pnl"].iloc[1] == 0 and r.bars["spot_pnl"].iloc[2] != 0
    assert r.state_after[1]["AAA"]["qs"] == r.state_after[0]["AAA"]["qs"]


def test_delisted_leg_closes_sleeve_at_last_price():
    m = mkt([100.0, 100.0, 100.0, 100.0], perp=[100.0, 100.0, np.nan, np.nan])
    r = run(m)
    assert r.bars["n_active"].iloc[1] == 0 and r.bars["n_exits"].iloc[1] == 1
    assert r.bars["cash"].iloc[1] == pytest.approx(r.bars["equity"].iloc[1])


def test_entries_sized_at_equity_over_slots_and_cash_limited():
    m = mkt(np.full((3, 3), 100.0), symbols=("A", "B", "C"))
    r = simulate(m, {0: ["A"], 1: ["A", "B", "C"]}, slots=2, costs=C, band=B, close_at_end=False)
    # bar 0: A gets 1/2; bar 1: only one slot is free, B gets min(E/2, cash) and C is not entered
    s = r.state_after[1]
    assert set(s) == {"A", "B"}
    e_a = r.bars["equity"].iloc[0] - 0.5                       # A's sleeve after its entry costs
    assert r.bars["cash"].iloc[1] == pytest.approx(0.5 - (0.5 + e_a) / 2, abs=1e-12)
    assert r.bars["n_active"].max() <= 2


def test_exit_blocked_by_stale_price_is_retried_and_slots_hold():
    px = np.full((6, 4), 100.0)
    px[2, 1] = np.nan                                   # B has no spot price at the decision bar
    m = mkt(px, symbols=("A", "B", "C", "D"))
    r = simulate(m, {0: ["A", "B"], 2: ["C", "D"]}, slots=2, costs=C, band=B, close_at_end=False)
    assert r.bars["n_active"].max() <= 2
    assert set(r.state_after[2]) == {"B", "C"}          # A out; B stuck; only one slot for C/D
    assert set(r.state_after[3]) == {"C"}               # B leaves on the first fresh bar (3)
    assert r.bars["n_exits"].iloc[3] == 1


def test_missing_high_falls_back_to_close_for_liquidation():
    m = mkt([100.0, 200.0], high=[100.0, np.nan])       # +100% close, no high
    r = run(m)
    assert r.bars["n_liq"].iloc[1] == 1 and r.stats["n_high_fallback"] == 1


def test_liquidation_after_outage_never_books_a_gain():
    # perp jumps during an outage of the high and the spot; M is far below maintenance afterwards
    m = mkt([100.0, np.nan, 100.0], perp=[100.0, 150.0, 100.0], high=[100.0, np.nan, 150.0])
    r = run(m, check_liq=True)
    liq_rows = r.bars[r.bars["n_liq"] > 0]
    assert len(liq_rows) == 1 and (liq_rows["perp_pnl"] <= 1e-15).all()



def test_bad_inputs_raise():
    with pytest.raises(AssertionError, match="inf"):
        mkt([100.0, np.inf])
    with pytest.raises(AssertionError, match="non-positive"):
        mkt([100.0, -1.0])
