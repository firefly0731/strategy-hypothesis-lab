import sys, numpy as np, pandas as pd
sys.stdout.reconfigure(encoding="utf-8")
from crypto_intraday_momentum.run_sizing import build_portfolio
OUT=sys.argv[1]; PPY=252; SYMS=["BTCUSDT","ETHUSDT","SOLUSDT"]
D={s:pd.read_pickle(f"{OUT}/IV_{s}.pkl") for s in SYMS}
T=pd.concat([D[s]["t"]["30m"].assign(sym=s) for s in SYMS]).sort_values(["sym","sess_idx","entry_time"])
T["k"]=T.groupby(["sym","sess_idx"]).cumcount()+1
T["n_day"]=T.groupby(["sym","sess_idx"]).k.transform("max")
T["bp"]=T.ret_notional*1e4
tot=T.bp.sum()
def tab(g):
    return pd.DataFrame(dict(n=g.bp.size(), mean_bp=g.bp.mean().round(1), win=g.apply(lambda x:(x.bp>0).mean()).round(3),
                             share_of_total_pnl=(g.bp.sum()/tot).round(3)))
print("== by ordinal k within symbol-day"); print(tab(T.groupby(np.minimum(T.k,5))))
print("== by entry kind"); print(tab(T.groupby("entry_kind")))
print("== by number of trades that symbol-day (all trades of those days)"); print(tab(T.groupby(np.minimum(T.n_day,5))))
day=T.groupby(["sym","sess_idx","n_day"]).bp.sum().reset_index()
print("== symbol-day total bp by n_day"); print(day.groupby(np.minimum(day.n_day,5)).bp.agg(["size","mean","sum"]).round(1))
# loss attribution: worst days
L=day[day.bp<0]; print("loss days share with n_day>=2:", round(L[L.n_day>=2].bp.sum()/L.bp.sum(),3), " count share", round((L.n_day>=2).mean(),3))
# caps
def mt(r):
    eq=(1+r).cumprod(); dd=eq/eq.cummax()-1
    return dict(cagr=round(eq.iloc[-1]**(PPY/len(r))-1,3), sharpe=round(r.mean()/r.std()*np.sqrt(PPY),3), mdd=round(dd.min(),3))
base=None
for cap in (None,1,2,3,4):
    data={}
    for s in SYMS:
        t=D[s]["t"]["30m"].sort_values(["sess_idx","entry_time"]).copy()
        t["k"]=t.groupby("sess_idx").cumcount()+1
        if cap: t=t[t.k<=cap]
        data[s]=(D[s]["m"], t.drop(columns="k").reset_index(drop=True), D[s]["rv"])
    U=pd.DataFrame({s:t.groupby("sess_idx").ret_notional.sum().reindex(range(D[s]["m"].n)).fillna(0).set_axis(D[s]["m"].dates) for s,(_,t,_) in data.items()}).fillna(0).iloc[91:].mean(axis=1)
    r,_=build_portfolio(data,"rv24","equal",0.25,3.0,0.15,scale_cap=20.0); r=r.iloc[60:]
    if base is None: base=(U,r)
    dU=U-base[0]; dr=r-base[1]
    tU=dU.mean()/dU.std()*np.sqrt(len(dU)) if dU.std()>0 else 0
    print("cap",cap,"trades",sum(len(t) for _,t,_ in data.values()),"unit",mt(U),"prod",mt(r),"t(diff unit) %.2f"%tU)
