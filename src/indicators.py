"""
Compute all technical indicators needed by the signal engine.
Uses the `ta` library for standard indicator calculations.
"""

import pandas as pd
import ta

from src.config import (
    BB_PERIOD, BB_STD, MACD_FAST, MACD_SIGNAL, MACD_SLOW,
    RSI_PERIOD, SMA_LONG, SMA_MID, SMA_SHORT,
)


def compute_all(df: pd.DataFrame) -> pd.DataFrame:
    """
    Add all technical indicator columns to the OHLCV DataFrame in-place
    and return it.
    """
    close = df["Close"]
    volume = df["Volume"]

    # ── Moving Averages ──
    df["SMA_20"] = ta.trend.sma_indicator(close, window=SMA_SHORT)
    df["SMA_50"] = ta.trend.sma_indicator(close, window=SMA_MID)
    df["SMA_200"] = ta.trend.sma_indicator(close, window=SMA_LONG)

    # ── Volume Averages ──
    df["AVG_VOL_20"] = volume.rolling(window=20).mean()
    df["AVG_VOL_50"] = volume.rolling(window=50).mean()
    df["VOL_RATIO"] = volume / df["AVG_VOL_20"]

    # ── RSI ──
    df["RSI_14"] = ta.momentum.rsi(close, window=RSI_PERIOD)

    # ── MACD ──
    macd = ta.trend.MACD(close, window_slow=MACD_SLOW, window_fast=MACD_FAST,
                         window_sign=MACD_SIGNAL)
    df["MACD"] = macd.macd()
    df["MACD_SIGNAL"] = macd.macd_signal()
    df["MACD_HIST"] = macd.macd_diff()

    # ── Bollinger Bands ──
    bb = ta.volatility.BollingerBands(close, window=BB_PERIOD, window_dev=BB_STD)
    df["BB_UPPER"] = bb.bollinger_hband()
    df["BB_MID"] = bb.bollinger_mavg()
    df["BB_LOWER"] = bb.bollinger_lband()
    df["BB_WIDTH"] = df["BB_UPPER"] - df["BB_LOWER"]
    df["BB_WIDTH_AVG"] = df["BB_WIDTH"].rolling(window=20).mean()

    return df
