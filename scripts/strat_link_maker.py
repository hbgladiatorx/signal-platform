"""LINK regime-MR (long/short) MAKER variant: same signals as the deployed
RegimeReversion, but entries and RSI/TP exits post as LIMIT (maker) orders at
close*(1∓offset) with expiry; stop-loss exits stay MARKET. Realistic maker
frictions (maker fee, through-margin non-fill, adverse selection) are applied by
the engine via BacktestConfig.

Order management: one working order at a time (tracked via state + position
changes + on_order_expired), expiry > 1 bar so the engine's expiration phase
doesn't cancel it before the fill phase. taker_fallback resubmits a missed
maker order as a market order the bar it's detected as expired."""
from __future__ import annotations

from pydantic import BaseModel, Field, model_validator

from packages.strategy.base import Strategy
from packages.strategy.context import BarContext


class MakerRegimeParams(BaseModel):
    model_config = {"extra": "forbid"}
    rsi_period: int = Field(default=14, ge=2, le=100)
    sma_period: int = Field(default=200, ge=20, le=1000)
    entry_long: float = Field(default=43.0, ge=1, le=50)
    exit_long: float = Field(default=55.0, ge=50, le=99)
    entry_short: float = Field(default=57.0, ge=50, le=99)
    exit_short: float = Field(default=45.0, ge=1, le=50)
    take_profit_pct: float = Field(default=0.03, ge=0, le=0.5)
    stop_loss_pct: float = Field(default=0.06, ge=0, le=0.5)
    position_pct: float = Field(default=90.0, gt=0, le=100)
    offset_bps: float = Field(default=5.0, ge=0, le=100)
    expiry_bars: int = Field(default=3, ge=2, le=20)
    taker_fallback: bool = Field(default=False)

    @model_validator(mode="after")
    def _check(self) -> "MakerRegimeParams":
        if self.entry_long >= self.entry_short:
            raise ValueError("entry_long must be below entry_short")
        return self


class MakerRegime(Strategy[MakerRegimeParams]):
    PARAMS_MODEL = MakerRegimeParams

    def on_init(self) -> None:
        if len(self.symbols) != 1:
            raise ValueError("MakerRegime supports exactly one symbol")
        self.symbol = self.symbols[0]
        self.state.update(entry_px=None, working=False, last_pos=0.0, missed=None)

    def on_order_expired(self, order) -> None:
        # A maker order failed to fill. Free the slot; remember it for taker fallback.
        self.state["working"] = False
        if self.params.taker_fallback:
            self.state["missed"] = (str(order.side.value), float(order.quantity))

    def on_bar(self, ctx: BarContext) -> None:
        sym = self.symbol
        p = self.params
        price = ctx.close(sym)
        rsi = ctx.rsi(sym, p.rsi_period)
        sma = ctx.sma(sym, p.sma_period)
        if price is None or rsi is None or sma is None or float(price) <= 0:
            return
        r = float(rsi); px = float(price); sv = float(sma)
        off = p.offset_bps / 1e4
        pos = float(ctx.position(sym))

        # Detect a fill (position changed) -> free the working slot, set entry/exit state.
        if pos != self.state["last_pos"]:
            self.state["working"] = False
            self.state["missed"] = None
            self.state["entry_px"] = px if pos != 0 else None
            self.state["last_pos"] = pos

        # Taker fallback: a maker order expired unfilled and the signal regime persists.
        if p.taker_fallback and self.state.get("missed") is not None and not self.state["working"]:
            side, qty = self.state["missed"]
            self.state["missed"] = None
            if side == "buy":
                ctx.submit_buy_market(sym, qty)
            else:
                ctx.submit_sell_market(sym, qty)
            self.state["working"] = True
            return

        if self.state["working"]:
            return  # one order at a time

        if pos == 0:
            qty = (p.position_pct / 100.0) * ctx.cash / price
            if qty <= 0:
                return
            if r < p.entry_long and px > sv:
                ctx.signal("regime_long", value=r, symbol=sym)
                ctx.submit_buy_limit(sym, qty, price * (1 - off), expires_after_bars=p.expiry_bars)
                self.state["working"] = True
                self.state["entry_px"] = px
            elif r > p.entry_short and px < sv:
                ctx.signal("regime_short", value=r, symbol=sym)
                ctx.submit_sell_limit(sym, qty, price * (1 + off), expires_after_bars=p.expiry_bars)
                self.state["working"] = True
                self.state["entry_px"] = px
        elif pos > 0:
            ep = self.state["entry_px"]
            tp_hit = p.take_profit_pct > 0 and ep is not None and px >= ep * (1 + p.take_profit_pct)
            sl_hit = p.stop_loss_pct > 0 and ep is not None and px <= ep * (1 - p.stop_loss_pct)
            if sl_hit:
                ctx.signal("regime_long_stop", value=r, symbol=sym)
                ctx.submit_sell_market(sym, pos)
                self.state["working"] = True
            elif r > p.exit_long or tp_hit:
                ctx.signal("regime_long_exit", value=r, symbol=sym)
                ctx.submit_sell_limit(sym, pos, price * (1 + off), expires_after_bars=p.expiry_bars)
                self.state["working"] = True
        else:
            ep = self.state["entry_px"]
            tp_hit = p.take_profit_pct > 0 and ep is not None and px <= ep * (1 - p.take_profit_pct)
            sl_hit = p.stop_loss_pct > 0 and ep is not None and px >= ep * (1 + p.stop_loss_pct)
            if sl_hit:
                ctx.signal("regime_short_stop", value=r, symbol=sym)
                ctx.submit_buy_market(sym, -pos)
                self.state["working"] = True
            elif r < p.exit_short or tp_hit:
                ctx.signal("regime_short_exit", value=r, symbol=sym)
                ctx.submit_buy_limit(sym, -pos, price * (1 - off), expires_after_bars=p.expiry_bars)
                self.state["working"] = True
