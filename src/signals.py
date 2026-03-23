"""
Signal detection engine for 09911.HK.

Implements Signals A (Volume), B (RSI/Momentum), C (Support/Resistance),
D (Bollinger Bands) as defined in the strategy spec v1.0.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import pandas as pd

from src.config import (
    BB_SQUEEZE_RATIO, KEY_SUPPORT_2, RSI_DIVERGENCE_LOOKBACK,
    RSI_EXTREME_OVERSOLD, RSI_OVERSOLD, SR_BREAK_TOLERANCE,
    SR_TEST_TOLERANCE, SUPPORTS, RESISTANCES, TICKER_DISPLAY,
    VOLUME_ALERT_RATIO, VOLUME_SHRINK_DAYS, VOLUME_SHRINK_RATIO,
    VOLUME_WATCH_RATIO,
)

logger = logging.getLogger(__name__)


@dataclass
class Alert:
    signal_id: str
    signal_name: str
    level: str  # "INFO", "WATCH", "ALERT", "TRADE_SIGNAL"
    message: str
    context: dict = field(default_factory=dict)
    suggested_action: Optional[str] = None


# ──────────────────────────────────────────────
#  Signal A: Volume Anomaly
# ──────────────────────────────────────────────

def check_volume_signals(df: pd.DataFrame) -> list[Alert]:
    alerts = []
    today = df.iloc[-1]
    vol = today["Volume"]
    avg_vol = today["AVG_VOL_20"]
    ratio = vol / avg_vol if avg_vol > 0 else 0
    close = today["Close"]
    open_ = today["Open"]
    pct_change = (close / df.iloc[-2]["Close"] - 1) * 100 if len(df) > 1 else 0

    ctx = _base_context(today)

    # A2: 天量警报 (check first — higher priority)
    if ratio >= VOLUME_ALERT_RATIO:
        body_pct = abs(close - open_) / open_ * 100 if open_ > 0 else 0
        if close > open_ and body_pct >= 0.5:
            interpretation = "资金强势进场"
        elif close < open_ and body_pct >= 0.5:
            interpretation = "大规模出货/恐慌抛售"
        else:
            interpretation = "多空激烈博弈，方向待确认"

        direction = "上涨" if close > open_ else "下跌" if close < open_ else "平盘"
        alerts.append(Alert(
            signal_id="A2",
            signal_name="天量警报",
            level="ALERT",
            message=(
                f"[{TICKER_DISPLAY}] 天量警报: {vol / 1e6:.2f}M = {ratio:.1f}x 均量。"
                f"价格{direction}。疑似 {interpretation}。"
            ),
            context=ctx,
        ))

    # A1: 放量预警
    elif ratio >= VOLUME_WATCH_RATIO:
        alerts.append(Alert(
            signal_id="A1",
            signal_name="放量预警",
            level="WATCH",
            message=(
                f"[{TICKER_DISPLAY}] 成交量异动: {vol / 1e6:.2f}M vs 20d均量 "
                f"{avg_vol / 1e6:.2f}M ({ratio:.1f}x)，收盘价 {close:.2f}，"
                f"涨跌幅 {pct_change:+.2f}%"
            ),
            context=ctx,
        ))

    # A3: 缩量信号 (during downtrend)
    if close < today.get("SMA_20", close):
        shrink_days = _count_consecutive_shrink_days(df)
        if shrink_days >= VOLUME_SHRINK_DAYS:
            alerts.append(Alert(
                signal_id="A3",
                signal_name="下跌中缩量",
                level="INFO",
                message=(
                    f"[{TICKER_DISPLAY}] 下跌中缩量: 连续{shrink_days}天量能低于均量60%，"
                    f"卖压可能减弱。"
                ),
                context=ctx,
            ))

    return alerts


def _count_consecutive_shrink_days(df: pd.DataFrame) -> int:
    """Count consecutive days from the end where volume < SHRINK_RATIO * avg."""
    count = 0
    for i in range(len(df) - 1, -1, -1):
        row = df.iloc[i]
        avg = row.get("AVG_VOL_20")
        if avg is None or pd.isna(avg) or avg == 0:
            break
        if row["Volume"] < VOLUME_SHRINK_RATIO * avg:
            count += 1
        else:
            break
    return count


# ──────────────────────────────────────────────
#  Signal B: RSI & Divergence
# ──────────────────────────────────────────────

def check_rsi_signals(df: pd.DataFrame) -> list[Alert]:
    alerts = []
    today = df.iloc[-1]
    yesterday = df.iloc[-2] if len(df) > 1 else None
    rsi = today["RSI_14"]
    ctx = _base_context(today)

    if pd.isna(rsi):
        return alerts

    prev_rsi = yesterday["RSI_14"] if yesterday is not None and not pd.isna(yesterday["RSI_14"]) else None

    # B2: 极端超卖
    if rsi < RSI_EXTREME_OVERSOLD:
        alerts.append(Alert(
            signal_id="B2",
            signal_name="RSI极端超卖",
            level="ALERT",
            message=(
                f"[{TICKER_DISPLAY}] RSI极端超卖: RSI={rsi:.1f}。"
                f"历史上该水平出现反弹概率较高，关注量能是否配合。"
            ),
            context=ctx,
        ))
    # B1: 超卖
    elif rsi < RSI_OVERSOLD:
        alerts.append(Alert(
            signal_id="B1",
            signal_name="RSI进入超卖区",
            level="WATCH",
            message=(
                f"[{TICKER_DISPLAY}] RSI进入超卖区: RSI={rsi:.1f}。"
                f"注意：超卖不等于见底，需配合量能信号确认。"
            ),
            context=ctx,
        ))

    # B3: RSI脱离超卖
    if prev_rsi is not None and prev_rsi < RSI_OVERSOLD and rsi > RSI_OVERSOLD and rsi > prev_rsi:
        alerts.append(Alert(
            signal_id="B3",
            signal_name="RSI脱离超卖区",
            level="INFO",
            message=(
                f"[{TICKER_DISPLAY}] RSI脱离超卖区: RSI从 {prev_rsi:.1f} 回升至 {rsi:.1f}。"
                f"若配合缩量企稳，可能形成短期底部。"
            ),
            context=ctx,
        ))

    # B4: Bearish divergence
    bear_div = _check_bearish_divergence(df)
    if bear_div:
        alerts.append(Alert(
            signal_id="B4",
            signal_name="RSI顶背离",
            level="ALERT",
            message=(
                f"[{TICKER_DISPLAY}] RSI顶背离: 价格新高 {bear_div['new_high']:.2f} vs "
                f"前高 {bear_div['prev_high']:.2f}，但RSI {bear_div['rsi_new']:.1f} < "
                f"{bear_div['rsi_prev']:.1f}。上涨动能衰竭，警惕回调。"
            ),
            context=ctx,
        ))

    # B5: Bullish divergence
    bull_div = _check_bullish_divergence(df)
    if bull_div:
        alerts.append(Alert(
            signal_id="B5",
            signal_name="RSI底背离",
            level="ALERT",
            message=(
                f"[{TICKER_DISPLAY}] RSI底背离: 价格新低 {bull_div['new_low']:.2f} vs "
                f"前低 {bull_div['prev_low']:.2f}，但RSI {bull_div['rsi_new']:.1f} > "
                f"{bull_div['rsi_prev']:.1f}。下跌动能衰竭，关注反转。"
            ),
            context=ctx,
        ))

    return alerts


def _find_peaks(series: pd.Series, order: int = 3) -> list[int]:
    """Simple local peak detection. Returns indices of peaks."""
    peaks = []
    values = series.values
    for i in range(order, len(values) - order):
        if all(values[i] >= values[i - j] for j in range(1, order + 1)) and \
           all(values[i] >= values[i + j] for j in range(1, order + 1)):
            peaks.append(i)
    return peaks


def _find_troughs(series: pd.Series, order: int = 3) -> list[int]:
    """Simple local trough detection. Returns indices of troughs."""
    troughs = []
    values = series.values
    for i in range(order, len(values) - order):
        if all(values[i] <= values[i - j] for j in range(1, order + 1)) and \
           all(values[i] <= values[i + j] for j in range(1, order + 1)):
            troughs.append(i)
    return troughs


def _check_bearish_divergence(df: pd.DataFrame) -> Optional[dict]:
    """Check for RSI bearish divergence in the lookback window."""
    window = df.tail(RSI_DIVERGENCE_LOOKBACK + 10)  # extra buffer for peak detection
    if len(window) < 10:
        return None

    peaks = _find_peaks(window["High"], order=2)
    if len(peaks) < 2:
        return None

    # Compare the two most recent peaks
    recent = peaks[-1]
    prior = peaks[-2]
    price_new = window["High"].iloc[recent]
    price_prev = window["High"].iloc[prior]
    rsi_new = window["RSI_14"].iloc[recent]
    rsi_prev = window["RSI_14"].iloc[prior]

    if pd.isna(rsi_new) or pd.isna(rsi_prev):
        return None

    if price_new > price_prev and rsi_new < rsi_prev:
        return {
            "new_high": price_new,
            "prev_high": price_prev,
            "rsi_new": rsi_new,
            "rsi_prev": rsi_prev,
        }
    return None


def _check_bullish_divergence(df: pd.DataFrame) -> Optional[dict]:
    """Check for RSI bullish divergence in the lookback window."""
    window = df.tail(RSI_DIVERGENCE_LOOKBACK + 10)
    if len(window) < 10:
        return None

    troughs = _find_troughs(window["Low"], order=2)
    if len(troughs) < 2:
        return None

    recent = troughs[-1]
    prior = troughs[-2]
    price_new = window["Low"].iloc[recent]
    price_prev = window["Low"].iloc[prior]
    rsi_new = window["RSI_14"].iloc[recent]
    rsi_prev = window["RSI_14"].iloc[prior]

    if pd.isna(rsi_new) or pd.isna(rsi_prev):
        return None

    if price_new < price_prev and rsi_new > rsi_prev:
        return {
            "new_low": price_new,
            "prev_low": price_prev,
            "rsi_new": rsi_new,
            "rsi_prev": rsi_prev,
        }
    return None


# ──────────────────────────────────────────────
#  Signal C: Support / Resistance
# ──────────────────────────────────────────────

def check_sr_signals(df: pd.DataFrame) -> list[Alert]:
    alerts = []
    today = df.iloc[-1]
    yesterday = df.iloc[-2] if len(df) > 1 else None
    close = today["Close"]
    low = today["Low"]
    ctx = _base_context(today)

    sma_200 = today.get("SMA_200")

    # C1 / C2: Support tests and breaks
    all_supports = sorted(SUPPORTS, reverse=True)
    for i, sup in enumerate(all_supports):
        next_sup = all_supports[i + 1] if i + 1 < len(all_supports) else KEY_SUPPORT_2

        # C2: break below support
        if close < sup * (1 - SR_BREAK_TOLERANCE):
            pct = (sup - close) / sup * 100
            alerts.append(Alert(
                signal_id="C2",
                signal_name="跌破支撑位",
                level="ALERT",
                message=(
                    f"[{TICKER_DISPLAY}] 跌破支撑位 {sup:.2f}: 收盘 {close:.2f}，"
                    f"跌破幅度 {pct:.1f}%。下一支撑 {next_sup:.2f}。"
                ),
                context=ctx,
            ))
        # C1: testing support
        elif low <= sup * (1 + SR_TEST_TOLERANCE):
            distance = (close - sup) / sup * 100
            alerts.append(Alert(
                signal_id="C1",
                signal_name="测试支撑位",
                level="WATCH",
                message=(
                    f"[{TICKER_DISPLAY}] 测试支撑位 {sup:.2f}: 最低价 {low:.2f}，"
                    f"距支撑 {distance:+.1f}%。关注是否站稳。"
                ),
                context=ctx,
            ))

    # C3: Resistance breakout
    for res in RESISTANCES:
        if close > res * (1 + SR_BREAK_TOLERANCE):
            alerts.append(Alert(
                signal_id="C3",
                signal_name="突破阻力位",
                level="ALERT",
                message=(
                    f"[{TICKER_DISPLAY}] 突破阻力位 {res:.2f}: 收盘 {close:.2f}。"
                    f"若配合放量确认，趋势可能反转。"
                ),
                context=ctx,
            ))

    # C4: 200d SMA cross
    if yesterday is not None and sma_200 is not None and not pd.isna(sma_200):
        prev_close = yesterday["Close"]
        prev_sma = yesterday.get("SMA_200")
        if prev_sma is not None and not pd.isna(prev_sma):
            crossed_below = prev_close > prev_sma and close < sma_200
            crossed_above = prev_close < prev_sma and close > sma_200
            if crossed_below or crossed_above:
                direction = "跌破" if crossed_below else "站上"
                alerts.append(Alert(
                    signal_id="C4",
                    signal_name="200日均线交叉",
                    level="ALERT",
                    message=(
                        f"[{TICKER_DISPLAY}] {direction}200日均线: 收盘 {close:.2f}，"
                        f"200d MA={sma_200:.2f}。中期趋势信号变化。"
                    ),
                    context=ctx,
                ))

    return alerts


# ──────────────────────────────────────────────
#  Signal D: Bollinger Bands
# ──────────────────────────────────────────────

def check_bb_signals(df: pd.DataFrame) -> list[Alert]:
    alerts = []
    today = df.iloc[-1]
    yesterday = df.iloc[-2] if len(df) > 1 else None
    close = today["Close"]
    ctx = _base_context(today)

    bb_lower = today.get("BB_LOWER")
    bb_mid = today.get("BB_MID")
    bb_upper = today.get("BB_UPPER")
    bb_width = today.get("BB_WIDTH")
    bb_width_avg = today.get("BB_WIDTH_AVG")

    if any(pd.isna(v) for v in [bb_lower, bb_mid, bb_upper] if v is not None):
        return alerts

    # D1: Below lower band
    if bb_lower is not None and close < bb_lower:
        alerts.append(Alert(
            signal_id="D1",
            signal_name="跌破布林下轨",
            level="WATCH",
            message=(
                f"[{TICKER_DISPLAY}] 跌破布林下轨: 收盘 {close:.2f}，"
                f"下轨 {bb_lower:.2f}，中轨 {bb_mid:.2f}。"
                f"超跌但可能继续沿下轨运行。"
            ),
            context=ctx,
        ))

    # D2: Band squeeze
    if bb_width is not None and bb_width_avg is not None and not pd.isna(bb_width_avg):
        if bb_width_avg > 0 and bb_width < bb_width_avg * BB_SQUEEZE_RATIO:
            alerts.append(Alert(
                signal_id="D2",
                signal_name="布林带收窄",
                level="INFO",
                message=(
                    f"[{TICKER_DISPLAY}] 布林带收窄: 当前带宽 {bb_width:.3f} vs "
                    f"均值 {bb_width_avg:.3f}。波动率压缩，可能酝酿大幅波动。"
                ),
                context=ctx,
            ))

    # D3: Re-entering band from below
    if yesterday is not None and bb_lower is not None:
        prev_close = yesterday["Close"]
        prev_bb_lower = yesterday.get("BB_LOWER")
        if prev_bb_lower is not None and not pd.isna(prev_bb_lower):
            if prev_close < prev_bb_lower and close > bb_lower and close < bb_mid:
                alerts.append(Alert(
                    signal_id="D3",
                    signal_name="回归布林通道",
                    level="INFO",
                    message=(
                        f"[{TICKER_DISPLAY}] 价格回到布林通道内: 从下轨外回归，"
                        f"目标中轨 {bb_mid:.2f}。"
                    ),
                    context=ctx,
                ))

    return alerts


# ──────────────────────────────────────────────
#  Helpers
# ──────────────────────────────────────────────

def _base_context(row: pd.Series) -> dict:
    """Build the standard context dict from a row."""
    ctx = {}
    mapping = {
        "close": "Close",
        "open": "Open",
        "high": "High",
        "low": "Low",
        "volume": "Volume",
        "volume_ratio": "VOL_RATIO",
        "rsi_14": "RSI_14",
        "sma_20": "SMA_20",
        "sma_200": "SMA_200",
        "bb_lower": "BB_LOWER",
        "bb_upper": "BB_UPPER",
        "bb_mid": "BB_MID",
        "macd_histogram": "MACD_HIST",
    }
    for key, col in mapping.items():
        val = row.get(col)
        if val is not None and not (isinstance(val, float) and np.isnan(val)):
            ctx[key] = round(float(val), 4) if isinstance(val, (float, np.floating)) else int(val)
    # Add nearest S/R
    close = row["Close"]
    supports_below = [s for s in SUPPORTS if s < close]
    resistances_above = [r for r in RESISTANCES if r > close]
    ctx["nearest_support"] = max(supports_below) if supports_below else min(SUPPORTS)
    ctx["nearest_resistance"] = min(resistances_above) if resistances_above else max(RESISTANCES)
    return ctx


def run_all_signals(df: pd.DataFrame) -> list[Alert]:
    """Run all signal checks and return combined alerts."""
    alerts = []
    alerts.extend(check_volume_signals(df))
    alerts.extend(check_rsi_signals(df))
    alerts.extend(check_sr_signals(df))
    alerts.extend(check_bb_signals(df))
    return alerts
