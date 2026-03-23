"""
Composite (trade-decision-level) signals that combine multiple dimensions.

COMPOSITE-BUY-1:  卖压衰竭 + 超卖反弹
COMPOSITE-BUY-2:  趋势反转确认
COMPOSITE-SELL-1: 破位加速
COMPOSITE-SELL-2: 顶背离 + 出货
"""

from __future__ import annotations

import pandas as pd

from src.config import (
    COMPOSITE_BUY2_VOLUME_RATIO, COMPOSITE_DIVERGENCE_LOOKBACK,
    RSI_OVERSOLD, SR_BREAK_TOLERANCE, SR_TEST_TOLERANCE,
    SUPPORTS, RESISTANCES, TICKER_DISPLAY, VOLUME_ALERT_RATIO,
    VOLUME_SHRINK_DAYS, VOLUME_SHRINK_RATIO, VOLUME_WATCH_RATIO,
)
from src.signals import (
    Alert, _check_bearish_divergence, _check_bullish_divergence,
    _count_consecutive_shrink_days,
)


def check_composite_signals(df: pd.DataFrame, recent_alerts: list[Alert]) -> list[Alert]:
    """
    Evaluate composite signals given the full DataFrame and any alerts
    already triggered in the current run.
    """
    alerts = []

    buy1 = _check_composite_buy_1(df)
    if buy1:
        alerts.append(buy1)

    buy2 = _check_composite_buy_2(df)
    if buy2:
        alerts.append(buy2)

    sell1 = _check_composite_sell_1(df, recent_alerts)
    if sell1:
        alerts.append(sell1)

    sell2 = _check_composite_sell_2(df, recent_alerts)
    if sell2:
        alerts.append(sell2)

    return alerts


# ──────────────────────────────────────────────
#  COMPOSITE-BUY-1: 卖压衰竭 + 超卖反弹
# ──────────────────────────────────────────────

def _check_composite_buy_1(df: pd.DataFrame) -> Alert | None:
    today = df.iloc[-1]
    yesterday = df.iloc[-2] if len(df) > 1 else None
    close = today["Close"]
    rsi = today["RSI_14"]
    bb_lower = today.get("BB_LOWER")

    if pd.isna(rsi) or yesterday is None:
        return None

    prev_rsi = yesterday["RSI_14"]
    if pd.isna(prev_rsi):
        return None

    # Condition 1: RSI < 30 and rising
    if not (rsi < RSI_OVERSOLD and rsi > prev_rsi):
        # Also accept: just exited oversold (prev < 30, today > 30, rising)
        if not (prev_rsi < RSI_OVERSOLD and rsi > prev_rsi):
            return None

    # Condition 2: Consecutive shrink days
    shrink_days = _count_consecutive_shrink_days(df)
    if shrink_days < VOLUME_SHRINK_DAYS:
        return None

    # Condition 3: Near a key support (±2%)
    near_support = None
    for sup in SUPPORTS:
        if abs(close - sup) / sup <= SR_BREAK_TOLERANCE:
            near_support = sup
            break
    if near_support is None:
        return None

    # Condition 4: Not below BB lower, or just re-entered
    if bb_lower is not None and not pd.isna(bb_lower):
        prev_bb = yesterday.get("BB_LOWER")
        below_and_not_recovering = (
            close < bb_lower
            and (prev_bb is None or pd.isna(prev_bb) or yesterday["Close"] < prev_bb)
        )
        if below_and_not_recovering:
            return None

    vol_ratio = today["VOL_RATIO"] if not pd.isna(today.get("VOL_RATIO", float("nan"))) else 0
    stop_loss = round(near_support * 0.97, 2)
    target = min(r for r in RESISTANCES if r > close) if any(r > close for r in RESISTANCES) else RESISTANCES[-1]

    return Alert(
        signal_id="COMPOSITE-BUY-1",
        signal_name="卖压衰竭+超卖反弹",
        level="TRADE_SIGNAL",
        message=(
            f"[{TICKER_DISPLAY}] 复合买入信号: RSI超卖回升({rsi:.1f}) + "
            f"缩量企稳({vol_ratio:.2f}x) + 支撑位 {near_support:.2f} 附近。"
            f"Short-term bounce 概率较高。"
        ),
        suggested_action=(
            f"考虑试探性建仓，止损设在 {stop_loss}，目标 {target:.2f}"
        ),
    )


# ──────────────────────────────────────────────
#  COMPOSITE-BUY-2: 趋势反转确认
# ──────────────────────────────────────────────

def _check_composite_buy_2(df: pd.DataFrame) -> Alert | None:
    today = df.iloc[-1]
    close = today["Close"]
    sma_20 = today.get("SMA_20")
    macd_hist = today.get("MACD_HIST")
    vol_ratio = today.get("VOL_RATIO")

    if any(v is None or (isinstance(v, float) and pd.isna(v))
           for v in [sma_20, macd_hist, vol_ratio]):
        return None

    # Condition 1: Bullish divergence in the last N days
    lookback_df = df.tail(COMPOSITE_DIVERGENCE_LOOKBACK + 15)
    bull_div = _check_bullish_divergence(lookback_df)
    if bull_div is None:
        return None

    # Condition 2: Close above 20d SMA
    if close <= sma_20:
        return None

    # Condition 3: Volume > 1.5x avg
    if vol_ratio < COMPOSITE_BUY2_VOLUME_RATIO:
        return None

    # Condition 4: MACD histogram turns positive
    if macd_hist <= 0:
        return None
    # Check it was negative yesterday
    if len(df) > 1:
        prev_hist = df.iloc[-2].get("MACD_HIST")
        if prev_hist is not None and not pd.isna(prev_hist) and prev_hist > 0:
            # Not a fresh crossover — still valid if histogram is positive and rising
            pass

    recent_low = df.tail(20)["Low"].min()
    stop_loss = round(recent_low * 0.97, 2)
    target = RESISTANCES[-1] if RESISTANCES else close * 1.15

    return Alert(
        signal_id="COMPOSITE-BUY-2",
        signal_name="趋势反转确认",
        level="TRADE_SIGNAL",
        message=(
            f"[{TICKER_DISPLAY}] 趋势反转信号: RSI底背离确认 + "
            f"站上20d MA ({sma_20:.2f}) + 放量 + MACD转正。中期底部可能确立。"
        ),
        suggested_action=(
            f"较高确信度的反转信号，可加大仓位。止损 {stop_loss}，目标 {target:.2f}"
        ),
    )


# ──────────────────────────────────────────────
#  COMPOSITE-SELL-1: 破位加速
# ──────────────────────────────────────────────

def _check_composite_sell_1(df: pd.DataFrame, recent_alerts: list[Alert]) -> Alert | None:
    today = df.iloc[-1]
    close = today["Close"]
    rsi = today["RSI_14"]
    bb_lower = today.get("BB_LOWER")
    vol_ratio = today.get("VOL_RATIO", 0)

    if pd.isna(rsi):
        return None

    # Condition 1: Broke a key support (C2 active)
    broken_support = None
    for sup in SUPPORTS:
        if close < sup * (1 - SR_BREAK_TOLERANCE):
            broken_support = sup
            break
    if broken_support is None:
        return None

    # Condition 2: Volume > 2x
    if pd.isna(vol_ratio) or vol_ratio < VOLUME_WATCH_RATIO:
        return None

    # Condition 3: RSI < 40 and falling
    if rsi >= 40:
        return None
    if len(df) > 1:
        prev_rsi = df.iloc[-2]["RSI_14"]
        if not pd.isna(prev_rsi) and rsi >= prev_rsi:
            return None  # RSI not falling

    # Condition 4: Close below BB lower
    if bb_lower is None or pd.isna(bb_lower) or close >= bb_lower:
        return None

    next_sup = None
    for s in sorted(SUPPORTS):
        if s < broken_support:
            next_sup = s
    if next_sup is None:
        next_sup = broken_support * 0.85  # estimate

    return Alert(
        signal_id="COMPOSITE-SELL-1",
        signal_name="破位加速",
        level="TRADE_SIGNAL",
        message=(
            f"[{TICKER_DISPLAY}] 复合卖出/止损信号: 放量跌破 {broken_support:.2f} + "
            f"RSI({rsi:.1f})持续走弱 + 布林下轨外运行。下行风险加大。"
        ),
        suggested_action=(
            f"如有持仓应考虑减仓或止损。下一支撑 {next_sup:.2f}。"
        ),
    )


# ──────────────────────────────────────────────
#  COMPOSITE-SELL-2: 顶背离 + 出货
# ──────────────────────────────────────────────

def _check_composite_sell_2(df: pd.DataFrame, recent_alerts: list[Alert]) -> Alert | None:
    today = df.iloc[-1]
    close = today["Close"]
    open_ = today["Open"]
    vol_ratio = today.get("VOL_RATIO", 0)

    # Condition 1: Bearish divergence present
    bear_div = _check_bearish_divergence(df)
    if bear_div is None:
        return None

    # Condition 2: Huge volume + bearish candle
    if pd.isna(vol_ratio) or vol_ratio < VOLUME_ALERT_RATIO:
        return None
    if close >= open_:
        return None  # not a bearish candle

    # Condition 3: Near resistance without breaking
    near_resistance = None
    for res in RESISTANCES:
        if abs(close - res) / res <= SR_BREAK_TOLERANCE * 2:
            near_resistance = res
            break
    if near_resistance is None:
        return None

    return Alert(
        signal_id="COMPOSITE-SELL-2",
        signal_name="顶背离+出货",
        level="TRADE_SIGNAL",
        message=(
            f"[{TICKER_DISPLAY}] 顶部出货信号: RSI顶背离 + 天量收阴 + "
            f"阻力位 {near_resistance:.2f} 压制。Rally可能终结。"
        ),
        suggested_action="如有持仓考虑获利了结。如无仓位不建议追高。",
    )
