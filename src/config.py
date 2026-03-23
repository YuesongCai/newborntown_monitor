"""
Configuration for 09911.HK Signal Monitoring System.
Static parameters and thresholds per strategy spec v1.0.
"""

TICKER = "9911.HK"
TICKER_DISPLAY = "09911.HK"

# ── Key Price Levels (updated 2026-03-23) ──
KEY_SUPPORT_1 = 7.41
KEY_SUPPORT_2 = 6.15
KEY_RESISTANCE_1_LOW = 8.05
KEY_RESISTANCE_1_HIGH = 8.18
KEY_RESISTANCE_2 = 9.20
# KEY_RESISTANCE_3 is the 200d SMA, calculated dynamically

SUPPORTS = [KEY_SUPPORT_1, KEY_SUPPORT_2]
RESISTANCES = [KEY_RESISTANCE_1_HIGH, KEY_RESISTANCE_2]  # sorted ascending

# ── Volume Thresholds ──
VOLUME_BASELINE = 5_530_000  # 3-month rolling avg as of 2026-03-23
VOLUME_WATCH_RATIO = 2.0     # Signal A1
VOLUME_ALERT_RATIO = 3.0     # Signal A2
VOLUME_SHRINK_RATIO = 0.6    # Signal A3
VOLUME_SHRINK_DAYS = 2       # consecutive days required

# ── RSI Thresholds ──
RSI_PERIOD = 14
RSI_OVERSOLD = 30            # Signal B1
RSI_EXTREME_OVERSOLD = 20    # Signal B2
RSI_DIVERGENCE_LOOKBACK = 20 # trading days for B4/B5

# ── Moving Averages ──
SMA_SHORT = 20
SMA_MID = 50
SMA_LONG = 200

# ── Bollinger Bands ──
BB_PERIOD = 20
BB_STD = 2
BB_SQUEEZE_RATIO = 0.5  # Signal D2: width < 50% of avg width

# ── Support/Resistance Tolerance ──
SR_TEST_TOLERANCE = 0.01   # ±1% for "testing" (C1)
SR_BREAK_TOLERANCE = 0.02  # 2% beyond for "break" (C2/C3)

# ── MACD ──
MACD_FAST = 12
MACD_SLOW = 26
MACD_SIGNAL = 9

# ── Composite Signal Lookback ──
COMPOSITE_DIVERGENCE_LOOKBACK = 10  # days to check if B4/B5 fired recently
COMPOSITE_BUY2_VOLUME_RATIO = 1.5

# ── Data ──
DATA_LOOKBACK_DAYS = 300  # fetch enough history for 200d SMA
SQLITE_DB_PATH = "data/signals.db"
