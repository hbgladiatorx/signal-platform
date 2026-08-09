"""50 genuinely-distinct LONG-ONLY archetypes, robustness-gated from the start.

Each strategy -> a 0/1 (flat/long) position series on OHLCV. Sim: enter/exit next
bar at open with slip+fee (round-trip ~30bps). Tested on 12 liquid majors x {1h,4h},
each scored full / H1 / H2. SURVIVOR GATE: net return > 0 in BOTH halves (not just
full-window) on a meaningful share of tickers. Reads pre-dumped CSVs (no DB load).

  docker compose run --rm -w /app -e PYTHONPATH=/app \
    -v /home/signal/app/scripts/matrix50_robust.py:/tmp/v.py \
    -v /home/signal/app/logs:/app/logs backtest_worker python /tmp/v.py
"""
import json
import numpy as np
import pandas as pd

ID2BASE = {15:"ADA",44:"AVAX",12:"BCH",14:"BNB",1:"BTC",20:"DOGE",
           46:"DOT",2:"ETH",53:"LINK",13:"LTC",6:"SOL",11:"XRP"}
FEE_BPS, SLIP_BPS = 10.0, 5.0
COST_SIDE = (FEE_BPS + SLIP_BPS) / 1e4         # per side (entry or exit)
BARS_PER_YEAR = {"1h": 365*24, "4h": 365*6}

# ---------- indicators (all return pd.Series aligned to df.index) ----------
def ema(s, n): return s.ewm(span=n, adjust=False).mean()
def sma(s, n): return s.rolling(n).mean()
def rsi(s, n=14):
    d = s.diff(); up = d.clip(lower=0); dn = -d.clip(upper=0)
    rs = up.ewm(alpha=1/n, adjust=False).mean() / dn.ewm(alpha=1/n, adjust=False).mean()
    return 100 - 100/(1+rs)
def atr(df, n=14):
    h, l, c = df.high, df.low, df.close
    tr = pd.concat([h-l, (h-c.shift()).abs(), (l-c.shift()).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1/n, adjust=False).mean()
def stoch_k(df, n=14):
    ll = df.low.rolling(n).min(); hh = df.high.rolling(n).max()
    return 100*(df.close-ll)/(hh-ll)
def willr(df, n=14):
    hh = df.high.rolling(n).max(); ll = df.low.rolling(n).min()
    return -100*(hh-df.close)/(hh-ll)
def cci(df, n=20):
    tp = (df.high+df.low+df.close)/3
    ma = tp.rolling(n).mean(); md = (tp-ma).abs().rolling(n).mean()
    return (tp-ma)/(0.015*md)
def macd(s, f=12, sl=26, sig=9):
    m = ema(s, f) - ema(s, sl); return m, ema(m, sig)
def boll(s, n=20, k=2):
    m = sma(s, n); sd = s.rolling(n).std()
    return m-k*sd, m, m+k*sd
def adx_di(df, n=14):
    up = df.high.diff(); dn = -df.low.diff()
    plus = np.where((up > dn) & (up > 0), up, 0.0)
    minus = np.where((dn > up) & (dn > 0), dn, 0.0)
    tr = atr(df, n)
    pdi = 100*pd.Series(plus, index=df.index).ewm(alpha=1/n, adjust=False).mean()/tr
    mdi = 100*pd.Series(minus, index=df.index).ewm(alpha=1/n, adjust=False).mean()/tr
    dx = 100*(pdi-mdi).abs()/(pdi+mdi)
    return dx.ewm(alpha=1/n, adjust=False).mean(), pdi, mdi
def aroon(df, n=25):
    au = df.high.rolling(n+1).apply(lambda x: 100*(n-(n-np.argmax(x)))/n, raw=True)
    ad = df.low.rolling(n+1).apply(lambda x: 100*(n-(n-np.argmin(x)))/n, raw=True)
    return au, ad
def obv(df):
    return (np.sign(df.close.diff()).fillna(0)*df.volume).cumsum()
def mfi(df, n=14):
    tp = (df.high+df.low+df.close)/3; rmf = tp*df.volume
    pos = rmf.where(tp > tp.shift(), 0.0).rolling(n).sum()
    neg = rmf.where(tp < tp.shift(), 0.0).rolling(n).sum()
    return 100 - 100/(1+pos/neg)
def cmf(df, n=20):
    mfm = ((df.close-df.low)-(df.high-df.close))/(df.high-df.low).replace(0, np.nan)
    return (mfm*df.volume).rolling(n).sum()/df.volume.rolling(n).sum()
def vwap_roll(df, n=24):
    tp = (df.high+df.low+df.close)/3
    return (tp*df.volume).rolling(n).sum()/df.volume.rolling(n).sum()
def keltner(df, n=20, k=2):
    m = ema(df.close, n); a = atr(df, n); return m-k*a, m, m+k*a
def roc(s, n=12): return s.pct_change(n)
def trix(s, n=15): return ema(ema(ema(s, n), n), n).pct_change()
def supertrend(df, n=10, k=3):
    a = atr(df, n); hl2 = (df.high+df.low)/2
    up = hl2 - k*a; dn = hl2 + k*a
    c = df.close.values; upv = up.values.copy(); dnv = dn.values.copy()
    dv = np.ones(len(df))
    for i in range(1, len(df)):
        upv[i] = max(upv[i], upv[i-1]) if c[i-1] > upv[i-1] else upv[i]
        dnv[i] = min(dnv[i], dnv[i-1]) if c[i-1] < dnv[i-1] else dnv[i]
        if c[i] > dnv[i-1]: dv[i] = 1
        elif c[i] < upv[i-1]: dv[i] = -1
        else: dv[i] = dv[i-1]
    return pd.Series(dv, index=df.index)
def heikin_green(df):
    ha_c = (df.open+df.high+df.low+df.close)/4
    return ha_c > ha_c.shift()
def fisher(df, n=10):
    hl2 = (df.high+df.low)/2
    mn = hl2.rolling(n).min(); mx = hl2.rolling(n).max()
    v = 2*((hl2-mn)/(mx-mn).replace(0, np.nan)-0.5)
    v = v.clip(-0.999, 0.999).fillna(0)
    return np.arctanh(v)
def vortex(df, n=14):
    tr = pd.concat([df.high-df.low, (df.high-df.close.shift()).abs(),
                    (df.low-df.close.shift()).abs()], axis=1).max(axis=1)
    vp = (df.high-df.low.shift()).abs().rolling(n).sum()/tr.rolling(n).sum()
    vm = (df.low-df.high.shift()).abs().rolling(n).sum()/tr.rolling(n).sum()
    return vp, vm
def stochrsi(s, n=14):
    r = rsi(s, n); mn = r.rolling(n).min(); mx = r.rolling(n).max()
    return (r-mn)/(mx-mn).replace(0, np.nan)

# ---------- 50 strategies: each -> 0/1 position series ----------
def S(df):
    c, h, l, v, o = df.close, df.high, df.low, df.volume, df.open
    out = {}
    out["01_sma_cross_20_50"]   = (sma(c,20) > sma(c,50)).astype(float)
    out["02_ema_cross_12_26"]   = (ema(c,12) > ema(c,26)).astype(float)
    out["03_price_gt_sma200"]   = (c > sma(c,200)).astype(float)
    md, sg = macd(c)
    out["04_macd_gt_signal"]    = (md > sg).astype(float)
    out["05_donchian_bo_20"]    = (c > h.rolling(20).max().shift()).astype(float)
    out["06_roc_pos_12"]        = (roc(c,12) > 0).astype(float)
    out["07_tsmom_24"]          = (c/c.shift(24)-1 > 0.0).astype(float)
    adx, pdi, mdi = adx_di(df)
    out["08_adx_trend"]         = ((adx>25)&(pdi>mdi)).astype(float)
    au, ad = aroon(df)
    out["09_aroon_up"]          = (au > ad).astype(float)
    out["10_supertrend"]        = (supertrend(df)>0).astype(float)
    out["11_keltner_bo"]        = (c > keltner(df)[2]).astype(float)
    out["12_triple_ema"]        = ((ema(c,8)>ema(c,21))&(ema(c,21)>ema(c,55))).astype(float)
    out["13_heikin_trend"]      = (heikin_green(df)&heikin_green(df).shift().fillna(False)).astype(float)
    vp, vm = vortex(df)
    out["14_vortex"]            = (vp > vm).astype(float)
    out["15_donchian_bo_55"]    = (c > h.rolling(55).max().shift()).astype(float)
    # --- mean reversion (hold while condition, exit on recovery) ---
    def mr(entry, exit_):
        pos = np.zeros(len(df)); p = 0
        ev = entry.fillna(False).values; xv = exit_.fillna(False).values
        for i in range(len(df)):
            if p==0 and ev[i]: p=1
            elif p==1 and xv[i]: p=0
            pos[i]=p
        return pd.Series(pos, index=df.index)
    out["16_rsi_30_50"]         = mr(rsi(c)<30, rsi(c)>50)
    out["17_rsi2_connors"]      = mr(rsi(c,2)<10, rsi(c,2)>70)
    out["18_bb_lower"]          = mr(c<boll(c)[0], c>boll(c)[1])
    z = (c-sma(c,20))/c.rolling(20).std()
    out["19_zscore_n2"]         = mr(z<-2, z>0)
    out["20_stoch_20"]          = mr(stoch_k(df)<20, stoch_k(df)>50)
    out["21_willr_80"]          = mr(willr(df)<-80, willr(df)>-50)
    out["22_cci_100"]           = mr(cci(df)<-100, cci(df)>0)
    out["23_dist_ema"]          = mr(c<ema(c,20)*0.95, c>ema(c,20))
    out["24_mfi_20"]            = mr(mfi(df)<20, mfi(df)>50)
    out["25_rsi_mr_trend"]      = mr((rsi(c)<35)&(c>sma(c,200)), rsi(c)>55)
    pctb = (c-boll(c)[0])/(boll(c)[2]-boll(c)[0])
    out["26_pctb_0"]            = mr(pctb<0, pctb>0.5)
    out["27_fisher_low"]        = mr(fisher(df)<-1.5, fisher(df)>0)
    sr = stochrsi(c)
    out["28_stochrsi_cross"]    = mr(sr<0.1, sr>0.5)
    # --- volatility ---
    out["29_atr_breakout"]      = (c > c.shift()+1.0*atr(df)).astype(float)
    bw = (boll(c)[2]-boll(c)[0])/boll(c)[1]
    out["30_bb_squeeze_bo"]     = ((bw.shift()<bw.rolling(50).quantile(0.25).shift())&(c>boll(c)[2])).astype(float)
    atrpct = atr(df)/c
    out["31_lowvol_trend"]      = ((atrpct<atrpct.rolling(100).median())&(sma(c,20)>sma(c,50))).astype(float)
    kl, km, ku = keltner(df); bl, bm, bu = boll(c)
    squeeze = (bl>kl)&(bu<ku)
    out["32_ttm_squeeze"]       = ((squeeze.shift())&(c>bm)).astype(float)
    rng = (h-l)
    nr7 = rng == rng.rolling(7).min()
    out["33_nr7_breakout"]      = ((nr7.shift())&(c>h.shift())).astype(float)
    # --- volume ---
    out["34_obv_trend"]         = (obv(df) > sma(obv(df),20)).astype(float)
    out["35_vol_spike_up"]      = ((v>2*sma(v,20))&(c>o)).astype(float)
    out["36_vwap_cross"]        = (c > vwap_roll(df,24)).astype(float)
    out["37_cmf_pos"]           = (cmf(df) > 0).astype(float)
    vwma = (c*v).rolling(20).sum()/v.rolling(20).sum()
    out["38_vwma_cross"]        = (c > vwma).astype(float)
    adl = (((c-l)-(h-c))/(h-l).replace(0,np.nan)*v).cumsum()
    out["39_adline_rising"]     = (adl > sma(adl,20)).astype(float)
    # --- price action / structure ---
    out["40_hh_hl"]             = ((h>h.shift())&(l>l.shift())).astype(float)
    inside = (h<h.shift())&(l>l.shift())
    out["41_inside_bar_bo"]     = ((inside.shift())&(c>h.shift())).astype(float)
    eng = (c>o)&(c.shift()<o.shift())&(c>o.shift())&(o<c.shift())
    out["42_bull_engulf"]       = mr(eng, c<ema(c,10))
    out["43_three_up"]          = ((c>c.shift())&(c.shift()>c.shift(2))&(c.shift(2)>c.shift(3))).astype(float)
    out["44_breakout_prevhigh"] = (c > h.shift(5).rolling(1).max()).astype(float) if False else (c>h.rolling(10).max().shift()).astype(float)
    piv = (h.shift()+l.shift()+c.shift())/3
    out["45_pivot_bounce"]      = mr(c<piv*0.99, c>piv)
    # --- oscillator combos / other ---
    hist = md-sg
    out["46_macd_hist_turn"]    = ((hist>0)&(hist.shift()<0)).astype(float).pipe(lambda s: mr(s>0, hist<0))
    out["47_stochrsi_os"]       = mr((sr<0.2)&(sr>sr.shift()), sr>0.8)
    out["48_dual_rsi"]          = mr((rsi(c,14)<40)&(rsi(c,28)<45), rsi(c,14)>60)
    out["49_trix_pos"]          = (trix(c) > 0).astype(float)
    out["50_mom_lowvol"]        = ((roc(c,12)>0)&(atrpct<atrpct.rolling(100).median())).astype(float)
    return out

def simulate(pos, c, tf, a, b):
    pos = pos.iloc[a:b].fillna(0).clip(0,1)
    ret = c.iloc[a:b].pct_change().fillna(0)
    # enter next bar: position effective from t+1 on signal at t
    eff = pos.shift(1).fillna(0)
    cost = eff.diff().abs().fillna(eff.abs())*COST_SIDE
    sr = eff*ret - cost
    eq = (1+sr).cumprod()
    fin = eq.iloc[-1]
    trades = int((eff.diff().abs()>0).sum()/1)  # transitions (entries+exits ~ 2*trades)
    ann = BARS_PER_YEAR[tf]
    sd = sr.std()
    sharpe = sr.mean()/sd*np.sqrt(ann) if sd>0 else 0.0
    peak = eq.cummax(); dd = ((eq-peak)/peak).min()*100
    expo = float(eff.mean())
    return dict(ret=(fin-1)*100, sharpe=float(sharpe), maxdd=float(dd),
                trades=trades, expo=expo)

def main():
    results = []
    for tf in ["1h","4h"]:
        df0 = pd.read_csv(f"/app/logs/xr_{tf}.csv")
        df0["bucket"] = pd.to_datetime(df0["bucket"], utc=True)
        for iid, base in ID2BASE.items():
            d = df0[df0.instrument_id==iid].sort_values("bucket").set_index("bucket")
            d = d[["open","high","low","close","volume"]].astype(float)
            if len(d) < 500: continue
            T = len(d); mid = T//2
            sigs = S(d)
            slabs = [("full",0,T),("h1",0,mid),("h2",mid,T)]
            for name, pos in sigs.items():
                r = {}
                for tag,aa,bb in slabs:
                    r[tag] = simulate(pos, d.close, tf, aa, bb)
                results.append(dict(tf=tf, base=base, strat=name,
                                    full=r["full"], h1=r["h1"], h2=r["h2"]))
    # aggregate per (strat, tf): survivor = h1.ret>0 AND h2.ret>0
    out = open("/app/logs/matrix50_robust.jsonl","w")
    for r in results: out.write(json.dumps(r, default=float)+"\n")
    out.close()
    rows = pd.DataFrame([{
        "tf":r["tf"],"strat":r["strat"],"base":r["base"],
        "full":r["full"]["ret"],"h1":r["h1"]["ret"],"h2":r["h2"]["ret"],
        "sharpe":r["full"]["sharpe"],"dd":r["full"]["maxdd"],
        "trades":r["full"]["trades"],"expo":r["full"]["expo"],
        "surv": (r["h1"]["ret"]>0 and r["h2"]["ret"]>0)} for r in results])
    # buy-and-hold benchmark per base/tf
    print("\n================ SURVIVOR SUMMARY (net of ~30bps round-trip) ================")
    print("survivor = net-positive in BOTH halves. Showing strat-level pass rate across 12 coins.\n")
    for tf in ["1h","4h"]:
        sub = rows[rows.tf==tf]
        g = sub.groupby("strat").agg(
            pass_rate=("surv","mean"), med_full=("full","median"),
            med_h1=("h1","median"), med_h2=("h2","median"),
            med_sharpe=("sharpe","median"), med_dd=("dd","median"),
            med_trades=("trades","median")).reset_index()
        g = g.sort_values(["pass_rate","med_sharpe"], ascending=False)
        print(f"\n----- {tf} : top 15 by (pass_rate, sharpe) -----")
        print(f"{'strat':24}{'pass%':>6}{'medFull':>9}{'medH1':>8}{'medH2':>8}{'shrp':>6}{'medDD':>7}{'trd':>6}")
        for _,x in g.head(15).iterrows():
            print(f"{x.strat:24}{x.pass_rate*100:>5.0f}%{x.med_full:>+8.1f}%{x.med_h1:>+7.1f}%{x.med_h2:>+7.1f}%"
                  f"{x.med_sharpe:>6.2f}{x.med_dd:>+6.0f}%{x.med_trades:>6.0f}")
        nsurv = (g.pass_rate>=0.5).sum()
        print(f"  strategies passing on >=50% of coins: {nsurv}/50")
    print("\n-> logs/matrix50_robust.jsonl", flush=True)

if __name__ == "__main__":
    main()
