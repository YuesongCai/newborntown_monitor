"""
Fetch OHLCV data for 09911.HK from Yahoo Finance.
"""

import logging
from datetime import datetime, timedelta

import pandas as pd
import yfinance as yf

from src.config import TICKER, DATA_LOOKBACK_DAYS

logger = logging.getLogger(__name__)


def fetch_ohlcv(lookback_days: int = DATA_LOOKBACK_DAYS) -> pd.DataFrame:
    """
    Fetch daily OHLCV data for the configured ticker.

    Returns a DataFrame with columns:
        Open, High, Low, Close, Volume
    indexed by Date (timezone-naive).
    """
    end = datetime.now()
    start = end - timedelta(days=int(lookback_days * 1.5))  # buffer for non-trading days

    logger.info("Fetching %s data from %s to %s", TICKER, start.date(), end.date())

    ticker = yf.Ticker(TICKER)
    df = ticker.history(start=start.strftime("%Y-%m-%d"), end=end.strftime("%Y-%m-%d"))

    if df.empty:
        raise ValueError(f"No data returned for {TICKER}")

    # Normalize: drop Dividends/Stock Splits if present, ensure tz-naive index
    for col in ("Dividends", "Stock Splits"):
        if col in df.columns:
            df = df.drop(columns=[col])

    if df.index.tz is not None:
        df.index = df.index.tz_localize(None)

    df = df.sort_index()

    # Keep only last `lookback_days` trading days
    df = df.tail(lookback_days)

    logger.info("Fetched %d trading days, latest: %s", len(df), df.index[-1].date())
    return df
