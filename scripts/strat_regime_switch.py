"""Axis C strategies (long-only/flat, spot-deployable):

RegimeSwitch — an ADX trend detector gates between a TREND rule (when ADX>thr:
hold long while close>SMA) and a MEAN-REVERSION rule (when ADX<=thr: RSI dip-buy,
exit on RSI recovery). ADX is computed in-strategy on a bounded trailing window
(not in the indicator lib) to keep it O(window) per bar.

DeleverNull — the de-leverage baseline: the MR rule ONLY, run ALWAYS at a fixed
exposure (position_pct). Proves whether the SWITCH adds edge beyond just trading
less / lower average exposure. Both must clear 2yr both-halves + DSR.
"""
from __future__ import annotations

from pydantic import BaseModel, Field

from packages.strategy.base import Strategy
from packages.strategy.context import BarContext


def _adx(b, n):
    """ADX on the trailing window of an OHLCV DataFrame `b` (pandas methods only,
    no import). Returns (adx, plus_di, minus_di) floats or None."""
    if b is None or len(b) < n * 3:
        return None
    w = b.tail(n * 6 + 5)
    h, l, c = w["high"], w["low"], w["close"]
    up = h.diff()
    dn = -l.diff()
    plus_dm = ((up > dn) & (up > 0)).astype(float) * up.fillna(0.0)
    minus_dm = ((dn > up) & (dn > 0)).astype(float) * dn.fillna(0.0)
    tr = (h - l)
    tr2 = (h - c.shift()).abs()
    tr3 = (l - c.shift()).abs()
    tr = tr.where(tr >= tr2, tr2).where(lambda x: x >= tr3, tr3)
    a = 1.0 / n
    atr = tr.ewm(alpha=a, adjust=False).mean()
    pdi = 100.0 * plus_dm.ewm(alpha=a, adjust=False).mean() / atr.replace(0.0, float("nan"))
    mdi = 100.0 * minus_dm.ewm(alpha=a, adjust=False).mean() / atr.replace(0.0, float("nan"))
    dx = 100.0 * (pdi - mdi).abs() / (pdi + mdi).replace(0.0, float("nan"))
    adx = dx.ewm(alpha=a, adjust=False).mean()
    v = adx.iloc[-1]
    if v != v:  # NaN
        return None
    return float(v), float(pdi.iloc[-1]), float(mdi.iloc[-1])


class SwitchParams(BaseModel):
    model_config = {"extra": "forbid"}
    rsi_period: int = Field(default=14, ge=2, le=100)
    sma_period: int = Field(default=200, ge=20, le=1000)
    adx_period: int = Field(default=14, ge=5, le=50)
    adx_thr: float = Field(default=25.0, ge=10, le=50,
                           description="ADX above this = trending regime.")
    entry_long: float = Field(default=43.0, ge=1, le=50)
    exit_long: float = Field(default=55.0, ge=50, le=99)
    take_profit_pct: float = Field(default=0.03, ge=0, le=0.5)
    stop_loss_pct: float = Field(default=0.06, ge=0, le=0.5)
    position_pct: float = Field(default=90.0, gt=0, le=100)


class RegimeSwitch(Strategy[SwitchParams]):
    PARAMS_MODEL = SwitchParams

    def on_init(self) -> None:
        self.symbol = self.symbols[0]
        self.state["entry_px"] = None

    def on_bar(self, ctx: BarContext) -> None:
        sym = self.symbol
        p = self.params
        price = ctx.close(sym)
        rsi = ctx.rsi(sym, p.rsi_period)
        sma = ctx.sma(sym, p.sma_period)
        if price is None or rsi is None or sma is None or float(price) <= 0:
            return
        adxv = _adx(ctx.bars(sym), p.adx_period)
        if adxv is None:
            return
        adx, pdi, mdi = adxv
        r = float(rsi); px = float(price); sv = float(sma)
        pos = ctx.position(sym)
        trending = adx > p.adx_thr

        if pos == 0:
            qty = (p.position_pct / 100.0) * ctx.cash / price
            if qty <= 0:
                return
            if trending:                       # TREND rule: enter long in uptrend
                if px > sv and pdi > mdi:
                    ctx.signal("trend_long", value=adx, symbol=sym)
                    ctx.submit_buy_market(sym, qty)
                    self.state["entry_px"] = px
            else:                              # MR rule: dip-buy
                if r < p.entry_long and px > sv:
                    ctx.signal("mr_long", value=r, symbol=sym)
                    ctx.submit_buy_market(sym, qty)
                    self.state["entry_px"] = px
        else:
            ep = self.state["entry_px"]
            tp_hit = p.take_profit_pct > 0 and ep is not None and px >= ep * (1 + p.take_profit_pct)
            sl_hit = p.stop_loss_pct > 0 and ep is not None and px <= ep * (1 - p.stop_loss_pct)
            if trending:                       # TREND exit: trend breaks down
                exit_now = (px < sv) or (mdi > pdi) or sl_hit
            else:                              # MR exit: RSI recovers / TP
                exit_now = (r > p.exit_long) or tp_hit or sl_hit
            if exit_now:
                ctx.signal("regime_exit", value=adx, symbol=sym)
                ctx.submit_sell_market(sym, pos)
                self.state["entry_px"] = None


class NullParams(BaseModel):
    model_config = {"extra": "forbid"}
    rsi_period: int = Field(default=14, ge=2, le=100)
    sma_period: int = Field(default=200, ge=20, le=1000)
    entry_long: float = Field(default=43.0, ge=1, le=50)
    exit_long: float = Field(default=55.0, ge=50, le=99)
    take_profit_pct: float = Field(default=0.03, ge=0, le=0.5)
    stop_loss_pct: float = Field(default=0.06, ge=0, le=0.5)
    position_pct: float = Field(default=45.0, gt=0, le=100,
                               description="Fixed (de-levered) exposure; the null lever.")


class DeleverNull(Strategy[NullParams]):
    """MR rule only, always on, at a fixed (de-levered) exposure."""
    PARAMS_MODEL = NullParams

    def on_init(self) -> None:
        self.symbol = self.symbols[0]
        self.state["entry_px"] = None

    def on_bar(self, ctx: BarContext) -> None:
        sym = self.symbol
        p = self.params
        price = ctx.close(sym)
        rsi = ctx.rsi(sym, p.rsi_period)
        sma = ctx.sma(sym, p.sma_period)
        if price is None or rsi is None or sma is None or float(price) <= 0:
            return
        r = float(rsi); px = float(price); sv = float(sma)
        pos = ctx.position(sym)
        if pos == 0:
            qty = (p.position_pct / 100.0) * ctx.cash / price
            if qty <= 0:
                return
            if r < p.entry_long and px > sv:
                ctx.signal("mr_long", value=r, symbol=sym)
                ctx.submit_buy_market(sym, qty)
                self.state["entry_px"] = px
        else:
            ep = self.state["entry_px"]
            tp_hit = p.take_profit_pct > 0 and ep is not None and px >= ep * (1 + p.take_profit_pct)
            sl_hit = p.stop_loss_pct > 0 and ep is not None and px <= ep * (1 - p.stop_loss_pct)
            if r > p.exit_long or tp_hit or sl_hit:
                ctx.signal("mr_exit", value=r, symbol=sym)
                ctx.submit_sell_market(sym, pos)
                self.state["entry_px"] = None
