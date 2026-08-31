import os
import asyncio
import datetime
import math

import pandas as pd
import yfinance as yf
import ta
from telegram import Bot

from news_filter import check_news
from daily_report import save_signal, get_report
from signal_memory import allow_new_signal
from trade_memory import save_trade, save_last_signal
from live_price import get_live_gold_price
from support_resistance import find_support_resistance
from entry_filter import check_entry
from smart_score import calculate_score
from no_trade_filter import apply_no_trade_filter


# ============================================================
# QuantumGold AI Signal Bot
# ADAPTIVE SCALPING V4 + MICROSTRUCTURE
#
# GainzAlgo V2 Essential + GainzAlgo Pro integrated
# Smart Money confirmations = SOFT / BONUS
# ============================================================


TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")


# ============================================================
# HARD FILTERS
# ============================================================

MIN_AI_SCORE = 80
MIN_QUALITY_SCORE = 80
MIN_ADX = 25

# Design target only - NOT guaranteed
TARGET_WIN_RATE = 85


# ============================================================
# GAINZALGO SETTINGS
# ============================================================

GAINZ_V2_STABILITY = 0.50
GAINZ_V2_RSI = 70
GAINZ_V2_DELTA = 4

GAINZ_PRO_STABILITY = 0.50
GAINZ_PRO_RSI = 50
GAINZ_PRO_DELTA = 5

GAINZ_V2_BONUS = 10
GAINZ_PRO_BONUS = 10


# ============================================================
# MARKETS
# ============================================================

CRYPTO_ENABLED = True

# V4 architecture
H4_ENABLED = True
M1_ENABLED = True
REGIME_ENABLED = True
ACCOUNT_BALANCE = float(os.getenv("ACCOUNT_BALANCE", "1000"))
BASE_RISK_PCT = float(os.getenv("BASE_RISK_PCT", "1.0"))
MICRO_ACCOUNT_THRESHOLD = float(os.getenv("MICRO_ACCOUNT_THRESHOLD", "10"))
MICRO_RISK_PCT = float(os.getenv("MICRO_RISK_PCT", "1.0"))
MAX_RISK_PCT = float(os.getenv("MAX_RISK_PCT", "1.0"))
MIN_REGIME_ADX = 18

MARKETS = [
    ("GC=F", "XAU/USD"),
    ("EURUSD=X", "EUR/USD"),
    ("GBPUSD=X", "GBP/USD"),
    ("USDJPY=X", "USD/JPY"),
    ("USDCHF=X", "USD/CHF"),
    ("AUDUSD=X", "AUD/USD"),
    ("USDCAD=X", "USD/CAD"),
    ("NZDUSD=X", "NZD/USD"),
]


CRYPTO_MARKETS = [
    ("BTC-USD", "BTC/USD"),
    ("ETH-USD", "ETH/USD"),
    ("SOL-USD", "SOL/USD"),
    ("BNB-USD", "BNB/USD"),
]


# ============================================================
# STRUCTURE SETTINGS
# ============================================================

SWING_LOOKBACK = 3
STRUCTURE_LOOKBACK = 40
LIQUIDITY_LOOKBACK = 30


# ============================================================
# BASIC HELPERS
# ============================================================

def is_valid_number(value):

    try:
        value = float(value)

        return (
            math.isfinite(value)
            and value > 0
        )

    except Exception:
        return False


def get_price_decimals(symbol):

    if symbol == "GC=F":
        return 2

    if symbol in [
        "BTC-USD",
        "ETH-USD",
        "SOL-USD",
        "BNB-USD"
    ]:
        return 2

    if symbol == "USDJPY=X":
        return 3

    return 5


def format_price(value, symbol):

    """
    IMPORTANT:
    Do NOT use nested f-strings here.
    The previous version caused:
    SyntaxError: f-string: expecting '}'
    """

    try:
        decimals = get_price_decimals(symbol)
        number = float(value)

        return format(
            number,
            f".{decimals}f"
        )

    except Exception:
        return "N/A"


def is_weekend():

    return (
        datetime.datetime.utcnow().weekday()
        in [5, 6]
    )


def safe_float(series, index=-1):

    try:

        value = float(
            series.iloc[index]
        )

        if math.isfinite(value):
            return value

        return None

    except Exception:
        return None


# ============================================================
# V4 ADAPTIVE HELPERS
# ============================================================

def _prepared_to_frame(data):
    """Normalize V4 prepared-data dictionaries into an OHLCV DataFrame."""
    if data is None:
        return None

    if isinstance(data, pd.DataFrame):
        return data.copy()

    if not isinstance(data, dict):
        return None

    required = ["open", "high", "low", "close", "volume"]
    if any(key not in data for key in required):
        return None

    try:
        frame = pd.concat(
            [
                data["open"].rename("open"),
                data["high"].rename("high"),
                data["low"].rename("low"),
                data["close"].rename("close"),
                data["volume"].rename("volume"),
            ],
            axis=1,
        )
        frame = frame.dropna(subset=["open", "high", "low", "close"])
        frame["volume"] = frame["volume"].fillna(0)
        return frame
    except Exception as e:
        print(f"Prepared data normalization error: {e}")
        return None


def resample_h4(data):
    """Build true H4 candles from closed H1 candles.

    V4 stores prepared timeframes as dictionaries, while the H4/regime
    layer needs a DataFrame. Normalize here so both representations work.
    """
    x = _prepared_to_frame(data)
    if x is None or x.empty:
        return None
    try:
        if len(x) > 1:
            x = x.iloc[:-1].copy()  # closed candles only
        x.index = pd.to_datetime(x.index)
        return x.resample("4h").agg({
            "open": "first", "high": "max", "low": "min",
            "close": "last", "volume": "sum"
        }).dropna()
    except Exception as e:
        print(f"H4 resample error: {e}")
        return None


def market_regime(data):
    """Classify regime without forcing a trade direction."""
    df = _prepared_to_frame(data)
    if df is None or len(df) < 60:
        return {"name": "UNKNOWN", "trend": 0, "strength": 0.0, "volatility": "UNKNOWN"}
    c, h, l = df["close"], df["high"], df["low"]
    adx = ta.trend.ADXIndicator(h, l, c, 14).adx()
    atr = ta.volatility.average_true_range(h, l, c, 14)
    e50 = ta.trend.ema_indicator(c, 50)
    e200 = ta.trend.ema_indicator(c, 200)
    a = safe_float(adx, -2) or 0.0
    av = safe_float(atr, -2) or 0.0
    e5 = safe_float(e50, -2) or 0.0
    e2 = safe_float(e200, -2) or 0.0
    trend = 1 if e5 > e2 else -1 if e5 < e2 else 0
    name = "TREND" if a >= MIN_REGIME_ADX else "RANGE"
    if av > 0 and len(atr.dropna()) >= 40:
        med = float(atr.dropna().tail(40).median())
        vol = "HIGH" if av > med * 1.5 else "LOW" if av < med * 0.7 else "NORMAL"
    else:
        vol = "NORMAL"
    return {"name": name, "trend": trend, "strength": a, "volatility": vol}


def adaptive_risk(balance=None):
    """Risk budget only; never uses martingale or increases after losses."""
    b = float(balance if balance is not None else ACCOUNT_BALANCE)
    pct = MICRO_RISK_PCT if b <= MICRO_ACCOUNT_THRESHOLD else BASE_RISK_PCT
    pct = max(0.1, min(MAX_RISK_PCT, pct))
    return {"balance": b, "risk_pct": pct, "risk_cash": b * pct / 100.0, "mode": "MICRO" if b <= MICRO_ACCOUNT_THRESHOLD else "STANDARD"}


# ============================================================
# MARKET DATA
# ============================================================

def get_data(symbol, interval="5m"):

    try:

        print(
            f"Downloading {symbol} "
            f"{interval} data..."
        )

        period = {
            "1m": "7d",
            "5m": "7d",
            "15m": "60d",
            "1h": "730d"
        }.get(
            interval,
            "60d"
        )

        data = yf.download(
            tickers=symbol,
            period=period,
            interval=interval,
            progress=False,
            auto_adjust=False,
            threads=False
        )

        if data is None or data.empty:

            print(
                f"{symbol}: EMPTY DATA "
                f"interval={interval}"
            )

            return None

        if getattr(
            data.columns,
            "nlevels",
            1
        ) > 1:

            data.columns = [
                col[0]
                if isinstance(col, tuple)
                else col
                for col in data.columns
            ]

        required = [
            "Open",
            "Close",
            "High",
            "Low",
            "Volume"
        ]

        missing = [
            c
            for c in required
            if c not in data.columns
        ]

        if missing:

            print(
                f"{symbol}: "
                f"missing columns {missing}"
            )

            return None

        data = data.dropna(
            subset=[
                "Open",
                "Close",
                "High",
                "Low"
            ]
        )

        if len(data) < 60:

            print(
                f"{symbol}: "
                f"insufficient data "
                f"({len(data)} candles)"
            )

            return None

        return data

    except Exception as e:

        print(
            f"Data error {symbol} "
            f"{interval}: {e}"
        )

        return None


def prepare_data(symbol, interval="5m"):

    data = get_data(
        symbol,
        interval
    )

    if data is None:
        return None

    try:

        open_price = data["Open"]
        close = data["Close"]
        high = data["High"]
        low = data["Low"]
        volume = data["Volume"]

        if hasattr(
            open_price,
            "columns"
        ):
            open_price = (
                open_price.iloc[:, 0]
            )

        if hasattr(
            close,
            "columns"
        ):
            close = close.iloc[:, 0]

        if hasattr(
            high,
            "columns"
        ):
            high = high.iloc[:, 0]

        if hasattr(
            low,
            "columns"
        ):
            low = low.iloc[:, 0]

        if hasattr(
            volume,
            "columns"
        ):
            volume = volume.iloc[:, 0]

        open_price = (
            open_price.dropna()
        )

        close = (
            close.dropna()
        )

        high = (
            high.dropna()
        )

        low = (
            low.dropna()
        )

        volume = (
            volume.fillna(0)
        )

        if len(close) < 220:

            print(
                f"{symbol}: "
                f"insufficient prepared "
                f"data ({len(close)})"
            )

            return None

        return {
            "open": open_price,
            "close": close,
            "high": high,
            "low": low,
            "volume": volume
        }

    except Exception as e:

        print(
            f"Prepare data error "
            f"{symbol}: {e}"
        )

        return None


# ============================================================
# MARKET STRUCTURE
# ============================================================

def find_recent_swings(
    high,
    low,
    lookback=SWING_LOOKBACK
):

    highs = []
    lows = []

    start = max(
        lookback,
        len(high) - STRUCTURE_LOOKBACK
    )

    for i in range(
        start,
        len(high) - lookback
    ):

        current_high = float(
            high.iloc[i]
        )

        current_low = float(
            low.iloc[i]
        )

        left_high = float(
            high.iloc[
                i - lookback:i
            ].max()
        )

        right_high = float(
            high.iloc[
                i + 1:i + lookback + 1
            ].max()
        )

        left_low = float(
            low.iloc[
                i - lookback:i
            ].min()
        )

        right_low = float(
            low.iloc[
                i + 1:i + lookback + 1
            ].min()
        )

        if (
            current_high > left_high
            and current_high > right_high
        ):

            highs.append(
                (i, current_high)
            )

        if (
            current_low < left_low
            and current_low < right_low
        ):

            lows.append(
                (i, current_low)
            )

    return highs, lows


def analyze_structure(
    close,
    high,
    low
):

    try:

        last_i = len(close) - 2

        if last_i < 10:

            return {
                "bullish_bos": False,
                "bearish_bos": False,
                "bullish_choch": False,
                "bearish_choch": False
            }

        highs, lows = (
            find_recent_swings(
                high.iloc[
                    :last_i + 1
                ],
                low.iloc[
                    :last_i + 1
                ]
            )
        )

        recent_highs = highs[-3:]
        recent_lows = lows[-3:]

        swing_high = (
            recent_highs[-1][1]
            if recent_highs
            else None
        )

        swing_low = (
            recent_lows[-1][1]
            if recent_lows
            else None
        )

        last_close = float(
            close.iloc[last_i]
        )

        bullish_bos = (
            swing_high is not None
            and last_close > swing_high
        )

        bearish_bos = (
            swing_low is not None
            and last_close < swing_low
        )

        bullish_choch = (
            len(recent_highs) >= 2
            and last_close
            > recent_highs[-2][1]
        )

        bearish_choch = (
            len(recent_lows) >= 2
            and last_close
            < recent_lows[-2][1]
        )

        return {
            "bullish_bos": bullish_bos,
            "bearish_bos": bearish_bos,
            "bullish_choch": bullish_choch,
            "bearish_choch": bearish_choch
        }

    except Exception as e:

        print(
            f"Structure analysis error: {e}"
        )

        return {
            "bullish_bos": False,
            "bearish_bos": False,
            "bullish_choch": False,
            "bearish_choch": False
        }


# ============================================================
# LIQUIDITY SWEEP
# ============================================================

def detect_liquidity_sweep(
    close,
    high,
    low
):

    try:

        i = len(close) - 2

        start = max(
            0,
            i - LIQUIDITY_LOOKBACK
        )

        if i <= start:

            return {
                "bullish": False,
                "bearish": False
            }

        prior_high = float(
            high.iloc[start:i].max()
        )

        prior_low = float(
            low.iloc[start:i].min()
        )

        current_high = float(
            high.iloc[i]
        )

        current_low = float(
            low.iloc[i]
        )

        current_close = float(
            close.iloc[i]
        )

        bullish = (
            current_low < prior_low
            and current_close > prior_low
        )

        bearish = (
            current_high > prior_high
            and current_close < prior_high
        )

        return {
            "bullish": bullish,
            "bearish": bearish
        }

    except Exception as e:

        print(
            f"Liquidity sweep error: {e}"
        )

        return {
            "bullish": False,
            "bearish": False
        }


# ============================================================
# FAIR VALUE GAP
# ============================================================

def detect_fvg(
    close,
    high,
    low,
    atr_value
):

    try:

        i = len(close) - 2

        if (
            i < 2
            or atr_value <= 0
        ):

            return {
                "bullish": False,
                "bearish": False
            }

        bullish_gap = (
            float(low.iloc[i])
            - float(high.iloc[i - 2])
        )

        bearish_gap = (
            float(low.iloc[i - 2])
            - float(high.iloc[i])
        )

        minimum_gap = (
            atr_value * 0.05
        )

        return {
            "bullish": (
                bullish_gap > minimum_gap
            ),
            "bearish": (
                bearish_gap > minimum_gap
            )
        }

    except Exception as e:

        print(
            f"FVG detection error: {e}"
        )

        return {
            "bullish": False,
            "bearish": False
        }


# ============================================================
# DISPLACEMENT
# ============================================================

def detect_displacement(
    open_price,
    close,
    high,
    low,
    atr_value
):

    try:

        i = len(close) - 2

        if (
            i < 1
            or atr_value <= 0
        ):

            return {
                "bullish": False,
                "bearish": False
            }

        previous_close = float(
            close.iloc[i - 1]
        )

        current_close = float(
            close.iloc[i]
        )

        candle_range = float(
            high.iloc[i]
            - low.iloc[i]
        )

        current_open = float(open_price.iloc[i])
        body = abs(
            current_close
            - current_open
        )

        strong = (
            body >= atr_value * 0.60
            and candle_range
            >= atr_value * 0.80
        )

        return {
            "bullish": (
                current_close
                > previous_close
                and strong
            ),
            "bearish": (
                current_close
                < previous_close
                and strong
            )
        }

    except Exception as e:

        print(
            f"Displacement error: {e}"
        )

        return {
            "bullish": False,
            "bearish": False
        }


# ============================================================
# GAINZALGO V2
# ============================================================

def detect_gainzalgo_v2(
    open_price,
    close,
    high,
    low,
    rsi_value
):

    try:

        i = len(close) - 2

        if i < GAINZ_V2_DELTA:

            return {
                "buy": False,
                "sell": False,
                "bullish_engulfing": False,
                "bearish_engulfing": False,
                "stable_candle": False,
                "rsi_buy": False,
                "rsi_sell": False,
                "price_decrease": False,
                "price_increase": False
            }

        current_open = float(
            open_price.iloc[i]
        )

        current_close = float(
            close.iloc[i]
        )

        previous_open = float(
            open_price.iloc[i - 1]
        )

        previous_close = float(
            close.iloc[i - 1]
        )

        current_high = float(
            high.iloc[i]
        )

        current_low = float(
            low.iloc[i]
        )

        tr1 = (
            current_high
            - current_low
        )

        tr2 = abs(
            current_high
            - previous_close
        )

        tr3 = abs(
            current_low
            - previous_close
        )

        true_range = max(
            tr1,
            tr2,
            tr3
        )

        if true_range <= 0:

            return {
                "buy": False,
                "sell": False,
                "bullish_engulfing": False,
                "bearish_engulfing": False,
                "stable_candle": False,
                "rsi_buy": False,
                "rsi_sell": False,
                "price_decrease": False,
                "price_increase": False
            }

        stable_candle = (
            abs(
                current_close
                - current_open
            ) / true_range
            > GAINZ_V2_STABILITY
        )

        bullish_engulfing = (
            previous_close < previous_open
            and current_close > current_open
            and current_close > previous_open
        )

        bearish_engulfing = (
            previous_close > previous_open
            and current_close < current_open
            and current_close < previous_open
        )

        rsi_buy = (
            rsi_value < GAINZ_V2_RSI
        )

        rsi_sell = (
            rsi_value
            > 100 - GAINZ_V2_RSI
        )

        close_delta = float(
            close.iloc[
                i - GAINZ_V2_DELTA
            ]
        )

        price_decrease = (
            current_close
            < close_delta
        )

        price_increase = (
            current_close
            > close_delta
        )

        gainz_buy = (
            bullish_engulfing
            and stable_candle
            and rsi_buy
            and price_decrease
        )

        gainz_sell = (
            bearish_engulfing
            and stable_candle
            and rsi_sell
            and price_increase
        )

        return {
            "buy": gainz_buy,
            "sell": gainz_sell,
            "bullish_engulfing": bullish_engulfing,
            "bearish_engulfing": bearish_engulfing,
            "stable_candle": stable_candle,
            "rsi_buy": rsi_buy,
            "rsi_sell": rsi_sell,
            "price_decrease": price_decrease,
            "price_increase": price_increase
        }

    except Exception as e:

        print(
            f"GainzAlgo V2 error: {e}"
        )

        return {
            "buy": False,
            "sell": False,
            "bullish_engulfing": False,
            "bearish_engulfing": False,
            "stable_candle": False,
            "rsi_buy": False,
            "rsi_sell": False,
            "price_decrease": False,
            "price_increase": False
        }


# ============================================================
# GAINZALGO PRO
# ============================================================

def detect_gainzalgo_pro(
    open_price,
    close,
    high,
    low,
    rsi_value
):

    try:

        i = len(close) - 2

        if i < GAINZ_PRO_DELTA:

            return {
                "buy": False,
                "sell": False,
                "bullish_engulfing": False,
                "bearish_engulfing": False,
                "stable_candle": False,
                "rsi_buy": False,
                "rsi_sell": False,
                "price_decrease": False,
                "price_increase": False
            }

        current_open = float(
            open_price.iloc[i]
        )

        current_close = float(
            close.iloc[i]
        )

        previous_open = float(
            open_price.iloc[i - 1]
        )

        previous_close = float(
            close.iloc[i - 1]
        )

        current_high = float(
            high.iloc[i]
        )

        current_low = float(
            low.iloc[i]
        )

        tr1 = (
            current_high
            - current_low
        )

        tr2 = abs(
            current_high
            - previous_close
        )

        tr3 = abs(
            current_low
            - previous_close
        )

        true_range = max(
            tr1,
            tr2,
            tr3
        )

        if true_range <= 0:

            return {
                "buy": False,
                "sell": False,
                "bullish_engulfing": False,
                "bearish_engulfing": False,
                "stable_candle": False,
                "rsi_buy": False,
                "rsi_sell": False,
                "price_decrease": False,
                "price_increase": False
            }

        stable_candle = (
            abs(
                current_close
                - current_open
            ) / true_range
            > GAINZ_PRO_STABILITY
        )

        bullish_engulfing = (
            previous_close < previous_open
            and current_close > current_open
            and current_close > previous_open
        )

        bearish_engulfing = (
            previous_close > previous_open
            and current_close < current_open
            and current_close < previous_open
        )

        rsi_buy = (
            rsi_value < GAINZ_PRO_RSI
        )

        rsi_sell = (
            rsi_value
            > 100 - GAINZ_PRO_RSI
        )

        close_delta = float(
            close.iloc[
                i - GAINZ_PRO_DELTA
            ]
        )

        price_decrease = (
            current_close
            < close_delta
        )

        price_increase = (
            current_close
            > close_delta
        )

        gainz_buy = (
            bullish_engulfing
            and stable_candle
            and rsi_buy
            and price_decrease
        )

        gainz_sell = (
            bearish_engulfing
            and stable_candle
            and rsi_sell
            and price_increase
        )

        return {
            "buy": gainz_buy,
            "sell": gainz_sell,
            "bullish_engulfing": bullish_engulfing,
            "bearish_engulfing": bearish_engulfing,
            "stable_candle": stable_candle,
            "rsi_buy": rsi_buy,
            "rsi_sell": rsi_sell,
            "price_decrease": price_decrease,
            "price_increase": price_increase
        }

    except Exception as e:

        print(
            f"GainzAlgo Pro error: {e}"
        )

        return {
            "buy": False,
            "sell": False,
            "bullish_engulfing": False,
            "bearish_engulfing": False,
            "stable_candle": False,
            "rsi_buy": False,
            "rsi_sell": False,
            "price_decrease": False,
            "price_increase": False
        }


# ============================================================
# V3.1 MICROSTRUCTURE / HFT-STYLE LAYER
# ============================================================
# OHLCV-based microstructure. This is NOT true exchange order-book HFT.
# True HFT requires tick/order-book/bid-ask data from a suitable feed.

MICROSTRUCTURE_ENABLED = True
MICROSTRUCTURE_HARD_FILTER = False
MIN_MICRO_SCORE = 55
MICRO_BONUS = 5
MICRO_PENALTY = 5


def _safe_ratio(numerator, denominator, default=0.0):
    try:
        d = float(denominator)
        if abs(d) < 1e-12:
            return default
        return float(numerator) / d
    except Exception:
        return default


def analyze_microstructure(open_price, close, high, low, volume, atr_value):
    """Analyze the last completed candle and prior M5 candles only."""
    neutral = {
        "buy_score": 0, "sell_score": 0, "score": 50,
        "direction": "NEUTRAL", "impulse": 0.0, "velocity": 0.0,
        "range_ratio": 1.0, "volume_ratio": 0.0,
        "breakout_buy": False, "breakout_sell": False,
        "fake_breakout_buy": False, "fake_breakout_sell": False,
        "rejection_buy": False, "rejection_sell": False,
        "pullback_buy": False, "pullback_sell": False,
        "reason": "Microstructure unavailable",
    }
    try:
        i = len(close) - 2
        atr = float(atr_value)
        if i < 25 or atr <= 0:
            return neutral
        o, c = float(open_price.iloc[i]), float(close.iloc[i])
        h, l = float(high.iloc[i]), float(low.iloc[i])
        prev_c = float(close.iloc[i - 1])
        prev_o = float(open_price.iloc[i - 1])
        if h <= l:
            return neutral
        start = max(0, i - 20)
        prev_high20 = float(high.iloc[start:i].max())
        prev_low20 = float(low.iloc[start:i].min())
        ranges = (high - low).iloc[start:i].astype(float)
        avg_range = float(ranges.median()) if len(ranges) else 0.0
        vols = volume.iloc[start:i].astype(float)
        avg_volume = float(vols.mean()) if len(vols) else 0.0
        current_volume = float(volume.iloc[i])
        candle_range = h - l
        body = abs(c - o)
        body_ratio = _safe_ratio(body, candle_range)
        close_location = _safe_ratio(c - l, candle_range)
        upper_wick = h - max(o, c)
        lower_wick = min(o, c) - l
        impulse = _safe_ratio(c - o, atr)
        velocity = _safe_ratio(c - prev_c, atr)
        range_ratio = _safe_ratio(candle_range, avg_range, 1.0)
        volume_ratio = _safe_ratio(current_volume, avg_volume, 0.0)
        breakout_buy = c > prev_high20
        breakout_sell = c < prev_low20
        fake_breakout_buy = l < prev_low20 and c > prev_low20
        fake_breakout_sell = h > prev_high20 and c < prev_high20
        rejection_buy = lower_wick >= body * 1.2 and close_location >= 0.65
        rejection_sell = upper_wick >= body * 1.2 and close_location <= 0.35
        pullback_buy = (prev_c - prev_o) < 0 and (c - o) > 0 and c > prev_c
        pullback_sell = (prev_c - prev_o) > 0 and (c - o) < 0 and c < prev_c
        buy = sell = 0
        reasons = []
        if impulse >= 0.35 and velocity > 0:
            buy += 18; reasons.append("bullish impulse")
        elif impulse <= -0.35 and velocity < 0:
            sell += 18; reasons.append("bearish impulse")
        if velocity >= 0.20: buy += 12
        elif velocity <= -0.20: sell += 12
        if body_ratio >= 0.55 and close_location >= 0.70: buy += 12
        elif body_ratio >= 0.55 and close_location <= 0.30: sell += 12
        if range_ratio >= 1.25:
            if c > o: buy += 10
            elif c < o: sell += 10
        if volume_ratio >= 1.20:
            if c > o: buy += 12
            elif c < o: sell += 12
        elif volume_ratio >= 1.05:
            if c > o: buy += 5
            elif c < o: sell += 5
        if breakout_buy: buy += 15; reasons.append("20-bar upside breakout")
        if breakout_sell: sell += 15; reasons.append("20-bar downside breakout")
        if fake_breakout_buy: buy += 10; sell = max(0, sell - 8); reasons.append("bullish liquidity sweep")
        if fake_breakout_sell: sell += 10; buy = max(0, buy - 8); reasons.append("bearish liquidity sweep")
        if rejection_buy: buy += 8
        if rejection_sell: sell += 8
        if pullback_buy: buy += 8
        if pullback_sell: sell += 8
        buy, sell = max(0, min(100, buy)), max(0, min(100, sell))
        score = int(max(0, min(100, 50 + (buy - sell) * 0.5)))
        if buy > sell and buy >= MIN_MICRO_SCORE: direction = "BUY"
        elif sell > buy and sell >= MIN_MICRO_SCORE: direction = "SELL"
        else: direction = "NEUTRAL"
        return {
            "buy_score": buy, "sell_score": sell, "score": score,
            "direction": direction, "impulse": impulse, "velocity": velocity,
            "range_ratio": range_ratio, "volume_ratio": volume_ratio,
            "breakout_buy": breakout_buy, "breakout_sell": breakout_sell,
            "fake_breakout_buy": fake_breakout_buy, "fake_breakout_sell": fake_breakout_sell,
            "rejection_buy": rejection_buy, "rejection_sell": rejection_sell,
            "pullback_buy": pullback_buy, "pullback_sell": pullback_sell,
            "reason": ", ".join(reasons) if reasons else "No strong microstructure event",
        }
    except Exception as e:
        print(f"Microstructure error: {e}")
        return neutral


def microstructure_confirms(signal, micro):
    if signal == "🟢 BUY":
        return micro.get("direction") == "BUY" or micro.get("buy_score", 0) >= MIN_MICRO_SCORE
    if signal == "🔴 SELL":
        return micro.get("direction") == "SELL" or micro.get("sell_score", 0) >= MIN_MICRO_SCORE
    return False


# ============================================================
# TP / SL VALIDATION
# ============================================================

def validate_trade_levels(
    signal,
    price,
    stop_loss,
    tp1,
    tp2,
    tp3
):

    try:

        values = [
            price,
            stop_loss,
            tp1,
            tp2,
            tp3
        ]

        if not all(
            is_valid_number(x)
            for x in values
        ):

            return (
                False,
                "Invalid price values"
            )

        if signal == "🟢 BUY":

            valid = (
                stop_loss < price
                and tp1 > price
                and tp2 > tp1
                and tp3 > tp2
            )

        elif signal == "🔴 SELL":

            valid = (
                stop_loss > price
                and tp1 < price
                and tp2 < tp1
                and tp3 < tp2
            )

        else:

            return (
                False,
                "Invalid signal"
            )

        if not valid:

            return (
                False,
                "Invalid TP/SL structure"
            )

        risk = abs(
            price - stop_loss
        )

        reward = abs(
            tp3 - price
        )

        if risk <= 0:

            return (
                False,
                "Zero risk"
            )

        rr = reward / risk

        if rr < 1.20:

            return (
                False,
                f"Risk/Reward too low ({rr:.2f})"
            )

        return (
            True,
            f"Valid TP/SL R:R={rr:.2f}"
        )

    except Exception as e:

        return (
            False,
            f"TP/SL validation error: {e}"
        )


# ============================================================
# V3 QUALITY SCORE
# ============================================================

def calculate_quality_score(
    signal,
    ema_bullish,
    m15_bullish,
    h1_bullish,
    macd_bullish,
    rsi_value,
    adx_value,
    volume_confirmed,
    news_risk,
    entry_quality,
    structure_confirmed=False,
    liquidity_confirmed=False,
    fvg_confirmed=False,
    displacement_confirmed=False,
    dxy_confirmed=False,
    gainz_v2_confirmed=False,
    gainz_pro_confirmed=False
):

    score = 0

    buy = (
        signal == "🟢 BUY"
    )

    sell = (
        signal == "🔴 SELL"
    )

    if (
        (buy and ema_bullish)
        or
        (sell and not ema_bullish)
    ):
        score += 15

    if (
        (buy and macd_bullish)
        or
        (sell and not macd_bullish)
    ):
        score += 15

    if (
        (buy and m15_bullish)
        or
        (sell and not m15_bullish)
    ):
        score += 10

    if (
        (buy and h1_bullish)
        or
        (sell and not h1_bullish)
    ):
        score += 10

    if adx_value >= 30:

        score += 15

    elif adx_value >= 25:

        score += 10

    elif adx_value >= 20:

        score += 5

    if volume_confirmed:
        score += 10

    if buy:

        if 45 < rsi_value < 70:
            score += 10

        elif 40 < rsi_value < 75:
            score += 5

    elif sell:

        if 30 < rsi_value < 55:
            score += 10

        elif 25 < rsi_value < 60:
            score += 5

    if news_risk == "HIGH":

        score -= 20

    elif news_risk == "MEDIUM":

        score += 5

    else:

        score += 10

    if entry_quality == "A":

        score += 10

    elif entry_quality == "B":

        score += 5

    else:

        score -= 10

    if structure_confirmed:
        score += 5

    if liquidity_confirmed:
        score += 5

    if fvg_confirmed:
        score += 5

    if displacement_confirmed:
        score += 5

    if dxy_confirmed:
        score += 5

    if gainz_v2_confirmed:
        score += GAINZ_V2_BONUS

    if gainz_pro_confirmed:
        score += GAINZ_PRO_BONUS

    return max(
        0,
        min(
            100,
            int(score)
        )
    )


# ============================================================
# MASTER V3 HARD FILTER
# ============================================================

def master_quality_filter(
    signal,
    ai_score,
    quality_score,
    entry_quality,
    adx_value,
    volume_confirmed,
    trend_aligned,
    rsi_valid,
    news_risk,
    tp_sl_valid
):

    if signal not in [
        "🟢 BUY",
        "🔴 SELL"
    ]:

        return (
            False,
            "No clear signal"
        )

    if ai_score < MIN_AI_SCORE:

        return (
            False,
            f"AI Score below {MIN_AI_SCORE}"
        )

    if quality_score < MIN_QUALITY_SCORE:

        return (
            False,
            f"Quality below {MIN_QUALITY_SCORE}"
        )

    if entry_quality != "A":

        return (
            False,
            f"Entry Quality {entry_quality}"
        )

    if adx_value < MIN_ADX:

        return (
            False,
            f"ADX below {MIN_ADX}"
        )

    if not volume_confirmed:

        return (
            False,
            "Volume confirmation missing"
        )

    if not trend_aligned:

        return (
            False,
            "M5/M15/H1 trend conflict"
        )

    if not rsi_valid:

        return (
            False,
            "RSI not valid"
        )

    if news_risk == "HIGH":

        return (
            False,
            "HIGH news risk"
        )

    if not tp_sl_valid:

        return (
            False,
            "Invalid TP/SL"
        )

    return (
        True,
        "ALL MASTER V3 HARD FILTERS PASSED"
    )


# ============================================================
# MARKET ANALYSIS
# ============================================================

def analyze_market(
    symbol,
    name
):

    try:

        print(
            f"\n{'=' * 60}\n"
            f"Analyzing {name}\n"
            f"{'=' * 60}"
        )

        if is_weekend() and symbol not in {x[0] for x in CRYPTO_MARKETS}:

            print(
                f"{name}: "
                f"Weekend - skipped"
            )

            return None

        # ====================================================
        # NEWS
        # ====================================================

        try:

            news = check_news() or {
                "risk": "HIGH"
            }

            news_risk = str(
                news.get(
                    "risk",
                    "HIGH"
                )
            ).upper()

        except Exception as e:

            print(
                f"{name}: "
                f"News error: {e}"
            )

            news_risk = "HIGH"

        # ====================================================
        # DATA
        # ====================================================

        m5 = prepare_data(
            symbol,
            "5m"
        )

        m15 = prepare_data(
            symbol,
            "15m"
        )

        h1 = prepare_data(
            symbol,
            "1h"
        )

        h4 = resample_h4(h1) if H4_ENABLED else None
        m1 = prepare_data(symbol, "1m") if M1_ENABLED else None

        if (
            m5 is None
            or m15 is None
            or h1 is None
            or (H4_ENABLED and h4 is None)
            or (M1_ENABLED and m1 is None)
        ):

            print(
                f"{name}: "
                f"Missing timeframe data"
            )

            return None

        # ====================================================
        # V4 REGIME + MULTI-TIMEFRAME CONTEXT
        # ====================================================
        regime = market_regime(h1) if REGIME_ENABLED else {"name": "UNKNOWN", "trend": 0, "strength": 0.0, "volatility": "UNKNOWN"}
        h4_regime = market_regime(h4) if h4 is not None else {"trend": 0, "strength": 0.0, "name": "UNKNOWN", "volatility": "UNKNOWN"}
        m15_regime = market_regime(m15)
        m1_regime = market_regime(m1) if m1 is not None else {"trend": 0, "strength": 0.0, "name": "UNKNOWN", "volatility": "UNKNOWN"}
        risk_profile = adaptive_risk()
        print(f"{name}: V4 regime H4={h4_regime['name']}/{h4_regime['trend']} H1={regime['name']}/{regime['trend']} M15={m15_regime['trend']} M1={m1_regime['trend']} Risk={risk_profile['mode']} {risk_profile['risk_pct']:.2f}%")

        dxy = None

        if symbol == "GC=F":

            dxy = prepare_data(
                "DX-Y.NYB",
                "5m"
            )

        # ====================================================
        # M5 DATA
        # ====================================================

        open_price = m5["open"]
        close = m5["close"]
        high = m5["high"]
        low = m5["low"]
        volume = m5["volume"]

        # ====================================================
        # LIVE PRICE
        # ====================================================

        if symbol == "GC=F":

            price = (
                get_live_gold_price()
            )

        else:

            price = None

        if (
            price is None
            or not is_valid_number(price)
        ):

            price = safe_float(
                close,
                -2
            )

        if price is None:
            return None

        # ====================================================
        # SUPPORT / RESISTANCE
        # ====================================================

        sr = find_support_resistance(
            close
        )

        if not sr:

            print(
                f"{name}: "
                f"Support/Resistance "
                f"unavailable"
            )

            return None

        support = float(
            sr["support"]
        )

        resistance = float(
            sr["resistance"]
        )

        # ====================================================
        # INDICATORS
        # ====================================================

        ema50 = ta.trend.ema_indicator(
            close,
            50
        )

        ema200 = ta.trend.ema_indicator(
            close,
            200
        )

        rsi = ta.momentum.rsi(
            close,
            14
        )

        macd = ta.trend.MACD(
            close
        )

        atr = (
            ta.volatility.average_true_range(
                high,
                low,
                close,
                14
            )
        )

        adx = ta.trend.ADXIndicator(
            high,
            low,
            close,
            14
        )

        e50 = safe_float(
            ema50,
            -2
        )

        e200 = safe_float(
            ema200,
            -2
        )

        r = safe_float(
            rsi,
            -2
        )

        m = safe_float(
            macd.macd(),
            -2
        )

        ms = safe_float(
            macd.macd_signal(),
            -2
        )

        atr_value = safe_float(
            atr,
            -2
        )

        adx_value = safe_float(
            adx.adx(),
            -2
        )

        if any(
            x is None
            for x in [
                e50,
                e200,
                r,
                m,
                ms,
                atr_value,
                adx_value
            ]
        ):

            print(
                f"{name}: "
                f"Indicator data unavailable"
            )

            return None

        # ====================================================
        # GAINZALGO
        # ====================================================

        gainz_v2 = detect_gainzalgo_v2(
            open_price,
            close,
            high,
            low,
            r
        )

        gainz_v2_buy = (
            gainz_v2["buy"]
        )

        gainz_v2_sell = (
            gainz_v2["sell"]
        )

        gainz_pro = detect_gainzalgo_pro(
            open_price,
            close,
            high,
            low,
            r
        )

        gainz_pro_buy = (
            gainz_pro["buy"]
        )

        gainz_pro_sell = (
            gainz_pro["sell"]
        )

        print(
            f"{name}: "
            f"Gainz V2 BUY="
            f"{gainz_v2_buy} "
            f"SELL="
            f"{gainz_v2_sell}"
        )

        print(
            f"{name}: "
            f"Gainz Pro BUY="
            f"{gainz_pro_buy} "
            f"SELL="
            f"{gainz_pro_sell}"
        )

        # ====================================================
        # TREND
        # ====================================================

        ema_bullish = (
            e50 > e200
        )

        macd_bullish = (
            m > ms
        )

        # ====================================================
        # M15
        # ====================================================

        m15_ema50 = ta.trend.ema_indicator(
            m15["close"],
            50
        )

        m15_ema200 = ta.trend.ema_indicator(
            m15["close"],
            200
        )

        m15_e50 = safe_float(
            m15_ema50,
            -2
        )

        m15_e200 = safe_float(
            m15_ema200,
            -2
        )

        if (
            m15_e50 is None
            or m15_e200 is None
        ):
            return None

        m15_bullish = (
            m15_e50 > m15_e200
        )

        # ====================================================
        # H1
        # ====================================================

        h1_ema50 = ta.trend.ema_indicator(
            h1["close"],
            50
        )

        h1_ema200 = ta.trend.ema_indicator(
            h1["close"],
            200
        )

        h1_e50 = safe_float(
            h1_ema50,
            -2
        )

        h1_e200 = safe_float(
            h1_ema200,
            -2
        )

        if (
            h1_e50 is None
            or h1_e200 is None
        ):
            return None

        h1_bullish = (
            h1_e50 > h1_e200
        )

        # ====================================================
        # VOLUME
        # ====================================================

        v = volume.fillna(0)

        current_volume = (
            safe_float(v, -2)
            or 0.0
        )

        start_volume = max(
            0,
            len(v) - 52
        )

        end_volume = max(
            1,
            len(v) - 2
        )

        window = v.iloc[
            start_volume:end_volume
        ]

        avg_volume = (
            float(window.mean())
            if len(window)
            else 0.0
        )

        volume_confirmed = (
            avg_volume > 0
            and current_volume
            >= avg_volume * 1.05
        )

        # ====================================================
        # V3.1 MICROSTRUCTURE / HFT-STYLE ANALYSIS
        # ====================================================
        micro = analyze_microstructure(
            open_price, close, high, low, volume, atr_value
        )
        print(
            f"{name}: Microstructure BUY={micro['buy_score']} "
            f"SELL={micro['sell_score']} DIR={micro['direction']} "
            f"VOLx={micro['volume_ratio']:.2f} RANGEx={micro['range_ratio']:.2f}"
        )

        # ====================================================
        # SMART MONEY
        # ====================================================

        structure = analyze_structure(
            close,
            high,
            low
        )

        liquidity = detect_liquidity_sweep(
            close,
            high,
            low
        )

        fvg = detect_fvg(
            close,
            high,
            low,
            atr_value
        )

        displacement = detect_displacement(
            open_price,
            close,
            high,
            low,
            atr_value
        )

        # ====================================================
        # BUY / SELL SCORING
        # ====================================================

        buy_score = 0
        sell_score = 0

        if ema_bullish:
            buy_score += 20
        else:
            sell_score += 20

        if macd_bullish:
            buy_score += 20
        else:
            sell_score += 20

        if m15_bullish:
            buy_score += 20
        else:
            sell_score += 20

        if h1_bullish:
            buy_score += 20
        else:
            sell_score += 20

        # V4: higher timeframe context is directional guidance, not a hard gate.
        if h4_regime["trend"] > 0:
            buy_score += 8
        elif h4_regime["trend"] < 0:
            sell_score += 8

        # M1 is timing confirmation only.
        if m1_regime["trend"] > 0:
            buy_score += 5
        elif m1_regime["trend"] < 0:
            sell_score += 5

        if 45 < r < 70:
            buy_score += 10

        if 30 < r < 55:
            sell_score += 10

        if adx_value >= 25:
            buy_score += 10
            sell_score += 10

        if gainz_v2_buy:
            buy_score += GAINZ_V2_BONUS

        if gainz_v2_sell:
            sell_score += GAINZ_V2_BONUS

        if gainz_pro_buy:
            buy_score += GAINZ_PRO_BONUS

        if gainz_pro_sell:
            sell_score += GAINZ_PRO_BONUS

        if (
            structure["bullish_bos"]
            or structure["bullish_choch"]
        ):
            buy_score += 10

        if (
            structure["bearish_bos"]
            or structure["bearish_choch"]
        ):
            sell_score += 10

        if liquidity["bullish"]:
            buy_score += 10

        if liquidity["bearish"]:
            sell_score += 10

        if displacement["bullish"]:
            buy_score += 5

        if displacement["bearish"]:
            sell_score += 5

        if fvg["bullish"]:
            buy_score += 5

        if fvg["bearish"]:
            sell_score += 5

        # ====================================================
        # SIGNAL CANDIDATE
        # ====================================================

        if (
            buy_score >= 70
            and buy_score > sell_score
        ):

            signal = "🟢 BUY"

            preliminary = min(
                100,
                buy_score
            )

        elif (
            sell_score >= 70
            and sell_score > buy_score
        ):

            signal = "🔴 SELL"

            preliminary = min(
                100,
                sell_score
            )

        else:

            print(
                f"{name}: "
                f"No clear direction "
                f"BUY={buy_score} "
                f"SELL={sell_score}"
            )

            return None

        print(
            f"{name}: "
            f"{signal} candidate "
            f"BUY={buy_score} "
            f"SELL={sell_score}"
        )

        # ====================================================
        # GAINZ CONFIRMATION
        # ====================================================

        if signal == "🟢 BUY":

            gainz_v2_confirmed = (
                gainz_v2_buy
            )

            gainz_pro_confirmed = (
                gainz_pro_buy
            )

        else:

            gainz_v2_confirmed = (
                gainz_v2_sell
            )

            gainz_pro_confirmed = (
                gainz_pro_sell
            )

        # ====================================================
        # ENTRY
        # ====================================================

        entry = check_entry(
            signal,
            price,
            support,
            resistance,
            r,
            preliminary
        )

        if not entry:

            print(
                f"{name}: "
                f"Entry rejected"
            )

            return None

        entry_quality = entry.get(
            "quality",
            "C"
        )

        # ====================================================
        # RSI VALIDATION
        # ====================================================

        if signal == "🟢 BUY":

            rsi_valid = (
                45 < r < 70
            )

        else:

            rsi_valid = (
                30 < r < 55
            )

        # ====================================================
        # TREND ALIGNMENT
        # ====================================================

        if signal == "🟢 BUY":

            trend_aligned = (
                ema_bullish
                and macd_bullish
                and m15_bullish
                and h1_bullish
            )

        else:

            trend_aligned = (
                not ema_bullish
                and not macd_bullish
                and not m15_bullish
                and not h1_bullish
            )

        # ====================================================
        # SMART MONEY DIRECTION
        # ====================================================

        if signal == "🟢 BUY":

            structure_confirmed = (
                structure["bullish_bos"]
                or structure["bullish_choch"]
            )

            liquidity_confirmed = (
                liquidity["bullish"]
            )

            fvg_confirmed = (
                fvg["bullish"]
            )

            displacement_confirmed = (
                displacement["bullish"]
            )

        else:

            structure_confirmed = (
                structure["bearish_bos"]
                or structure["bearish_choch"]
            )

            liquidity_confirmed = (
                liquidity["bearish"]
            )

            fvg_confirmed = (
                fvg["bearish"]
            )

            displacement_confirmed = (
                displacement["bearish"]
            )

        # ====================================================
        # TP / SL MULTIPLIERS
        # ====================================================

        if symbol == "GC=F":

            sl_mult = 2.0
            tp_mult = 3.0

        elif symbol in [
            "BTC-USD",
            "ETH-USD",
            "SOL-USD",
            "BNB-USD"
        ]:

            sl_mult = 3.0
            tp_mult = 5.0

        else:

            sl_mult = 2.0
            tp_mult = 3.0

        # ====================================================
        # TP / SL
        # ====================================================

        if signal == "🟢 BUY":

            stop_loss = (
                price
                - atr_value * sl_mult
            )

            tp1 = (
                price
                + atr_value
            )

            tp2 = (
                price
                + atr_value * 2
            )

            tp3 = (
                price
                + atr_value * tp_mult
            )

        else:

            stop_loss = (
                price
                + atr_value * sl_mult
            )

            tp1 = (
                price
                - atr_value
            )

            tp2 = (
                price
                - atr_value * 2
            )

            tp3 = (
                price
                - atr_value * tp_mult
            )

        valid_levels, level_reason = (
            validate_trade_levels(
                signal,
                price,
                stop_loss,
                tp1,
                tp2,
                tp3
            )
        )

        if not valid_levels:

            print(
                f"{name}: "
                f"TP/SL rejected - "
                f"{level_reason}"
            )

            return None

        # ====================================================
        # DXY
        # ====================================================

        dxy_confirmed = False

        if (
            symbol == "GC=F"
            and dxy is not None
            and len(dxy["close"]) >= 22
        ):

            dxy_now = safe_float(
                dxy["close"],
                -2
            )

            dxy_old = safe_float(
                dxy["close"],
                -22
            )

            if (
                dxy_now is not None
                and dxy_old is not None
            ):

                if signal == "🟢 BUY":

                    dxy_confirmed = (
                        dxy_now < dxy_old
                    )

                else:

                    dxy_confirmed = (
                        dxy_now > dxy_old
                    )

        # ====================================================
        # SMART SCORE
        # ====================================================

        try:

            smart = calculate_score(
                name,
                signal,
                preliminary,
                price,
                support,
                resistance,
                news_risk
            )

            smart_score = int(
                max(
                    0,
                    min(
                        100,
                        float(
                            smart.get(
                                "score",
                                0
                            )
                        )
                    )
                )
            )

            smart_decision = smart.get(
                "decision",
                "Unknown"
            )

        except Exception as e:

            print(
                f"{name}: "
                f"Smart score error: {e}"
            )

            smart_score = 0

            smart_decision = (
                "Smart score unavailable"
            )

        # ====================================================
        # QUALITY SCORE
        # ====================================================

        quality_score = calculate_quality_score(
            signal,
            ema_bullish,
            m15_bullish,
            h1_bullish,
            macd_bullish,
            r,
            adx_value,
            volume_confirmed,
            news_risk,
            entry_quality,
            structure_confirmed,
            liquidity_confirmed,
            fvg_confirmed,
            displacement_confirmed,
            dxy_confirmed,
            gainz_v2_confirmed,
            gainz_pro_confirmed
        )

        # Soft microstructure contribution.
        micro_confirmed = microstructure_confirms(signal, micro)
        if micro_confirmed:
            quality_score = min(100, quality_score + MICRO_BONUS)
        elif micro.get("direction") not in ("NEUTRAL", None):
            quality_score = max(0, quality_score - MICRO_PENALTY)

        # ====================================================
        # FINAL AI SCORE
        # ====================================================

        final_ai_score = max(
            0,
            min(
                100,
                int(
                    min(
                        smart_score,
                        quality_score
                    )
                )
            )
        )

        # ====================================================
        # NO TRADE FILTER
        # ====================================================

        try:

            old = apply_no_trade_filter(
                signal=signal,
                ai_score=final_ai_score,
                news_risk=news_risk,
                entry_quality=entry_quality,
                quality_score=quality_score,
                adx_value=adx_value,
                volume_confirmed=volume_confirmed,
                trend_aligned=trend_aligned,
                rsi_valid=rsi_valid,
                tp_sl_valid=valid_levels
            )

            filtered_signal = old.get(
                "signal",
                "⚪ WAIT"
            )

            old_reason = old.get(
                "reason",
                ""
            )

        except Exception as e:

            print(
                f"{name}: "
                f"No-trade filter error: {e}"
            )

            filtered_signal = "⚪ WAIT"

            old_reason = (
                "No-trade filter error"
            )

        if filtered_signal not in [
            "🟢 BUY",
            "🔴 SELL"
        ]:

            print(
                f"{name}: "
                f"No-trade filter rejected: "
                f"{old_reason}"
            )

            return None

        # ====================================================
        # MASTER V3 HARD FILTER
        # ====================================================

        passed, reason = master_quality_filter(
            filtered_signal,
            final_ai_score,
            quality_score,
            entry_quality,
            adx_value,
            volume_confirmed,
            trend_aligned,
            rsi_valid,
            news_risk,
            valid_levels
        )

        if not passed:

            print(
                f"\n{name}: "
                f"V3 REJECTED"
            )

            print(
                f"AI Score: "
                f"{final_ai_score}/100"
            )

            print(
                f"Quality: "
                f"{quality_score}/100"
            )

            print(
                f"Smart Score: "
                f"{smart_score}/100"
            )

            print(
                f"ADX: "
                f"{adx_value:.2f}"
            )

            print(
                f"Entry: "
                f"{entry_quality}"
            )

            print(
                f"Gainz V2: "
                f"{gainz_v2_confirmed}"
            )

            print(
                f"Gainz Pro: "
                f"{gainz_pro_confirmed}"
            )

            print(
                f"Structure: "
                f"{structure_confirmed}"
            )

            print(
                f"Liquidity: "
                f"{liquidity_confirmed}"
            )

            print(
                f"FVG: "
                f"{fvg_confirmed}"
            )

            print(
                f"Displacement: "
                f"{displacement_confirmed}"
            )

            print(
                f"Reason: "
                f"{reason}"
            )

            return None

        # Optional strict microstructure gate. OFF by default.
        if MICROSTRUCTURE_ENABLED and MICROSTRUCTURE_HARD_FILTER:
            if not microstructure_confirms(filtered_signal, micro):
                print(
                    f"{name}: V3.1 MICRO REJECTED - "
                    f"score={micro['score']} direction={micro['direction']}"
                )
                return None

        # ====================================================
        # FINAL TP / SL VALIDATION
        # ====================================================

        final_valid, _ = (
            validate_trade_levels(
                filtered_signal,
                price,
                stop_loss,
                tp1,
                tp2,
                tp3
            )
        )

        if not final_valid:
            return None

        # ====================================================
        # DUPLICATE SIGNAL FILTER
        # ====================================================

        try:

            allowed = allow_new_signal(
                filtered_signal,
                price
            )

        except Exception as e:

            print(
                f"{name}: "
                f"Duplicate filter error: {e}"
            )

            allowed = False

        if not allowed:

            print(
                f"{name}: "
                f"Duplicate signal blocked"
            )

            return None

        # ====================================================
        # SAVE
        # ====================================================

        try:

            save_last_signal(
                filtered_signal,
                price
            )

            save_trade(
                filtered_signal,
                price,
                final_ai_score,
                stop_loss,
                tp3
            )

            save_signal(
                filtered_signal
            )

        except Exception as e:

            print(
                f"{name}: "
                f"Save error: {e}"
            )

        # ====================================================
        # MESSAGE
        # ====================================================

        direction = (
            "BUY"
            if filtered_signal == "🟢 BUY"
            else "SELL"
        )

        p = lambda x: format_price(
            x,
            symbol
        )

        structure_status = (
            "CONFIRMED"
            if structure_confirmed
            else "NOT CONFIRMED"
        )

        liquidity_status = (
            "CONFIRMED"
            if liquidity_confirmed
            else "NOT CONFIRMED"
        )

        fvg_status = (
            "CONFIRMED"
            if fvg_confirmed
            else "NOT CONFIRMED"
        )

        displacement_status = (
            "CONFIRMED"
            if displacement_confirmed
            else "NOT CONFIRMED"
        )

        dxy_status = (
            "CONFIRMED"
            if dxy_confirmed
            else "NOT CONFIRMED"
        )

        gainz_v2_status = (
            "CONFIRMED"
            if gainz_v2_confirmed
            else "NOT CONFIRMED"
        )

        gainz_pro_status = (
            "CONFIRMED"
            if gainz_pro_confirmed
            else "NOT CONFIRMED"
        )

        reasons = [
            "Master V3 hard filters passed",
            "AI Score 80+",
            "Quality Score 80+",
            "Entry Quality A",
            "ADX 25+",
            "Volume confirmed",
            "M5/M15/H1 aligned",
            "RSI valid",
            "News risk acceptable"
        ]

        if gainz_v2_confirmed:

            reasons.append(
                "GainzAlgo V2 confirmation +10"
            )

        if gainz_pro_confirmed:

            reasons.append(
                "GainzAlgo Pro confirmation +10"
            )

        if structure_confirmed:

            reasons.append(
                "BOS/CHoCH bonus +5"
            )

        if liquidity_confirmed:

            reasons.append(
                "Liquidity Sweep bonus +5"
            )

        if fvg_confirmed:

            reasons.append(
                "FVG bonus +5"
            )

        if displacement_confirmed:

            reasons.append(
                "Displacement bonus +5"
            )

        if dxy_confirmed:

            reasons.append(
                "DXY confirmation bonus +5"
            )

        reasons.append(
            f"Microstructure V3.1: {micro['direction']} "
            f"score={micro['score']} BUY={micro['buy_score']} SELL={micro['sell_score']}"
        )
        if micro_confirmed:
            reasons.append("Microstructure confirmation +5")

        reasons_text = "\n".join(
            "✅ " + x
            for x in reasons
        )

        volume_status = (
            "CONFIRMED"
            if volume_confirmed
            else "LOW"
        )

        v2_buy_status = (
            "YES"
            if gainz_v2_buy
            else "NO"
        )

        v2_sell_status = (
            "YES"
            if gainz_v2_sell
            else "NO"
        )

        pro_buy_status = (
            "YES"
            if gainz_pro_buy
            else "NO"
        )

        pro_sell_status = (
            "YES"
            if gainz_pro_sell
            else "NO"
        )

        return f"""📊 {name} {direction} NOW {p(price)}

⚠️ SL: {p(stop_loss)}
🎯 TP1: {p(tp1)}
🎯 TP2: {p(tp2)}
🎯 TP3: {p(tp3)}

AI Score: {final_ai_score}/100
Regime: {regime['name']} | H4: {h4_regime['trend']} | H1: {regime['trend']} | M15: {m15_regime['trend']} | M1: {m1_regime['trend']}
Risk Mode: {risk_profile['mode']} | Risk: {risk_profile['risk_pct']:.2f}%
QuantumGold Adaptive Scalping V4"""

    except Exception as e:

        print(
            f"{name}: "
            f"Unexpected analysis error: "
            f"{e}"
        )

        return None


# ============================================================
# MAIN
# ============================================================

async def main():

    print(
        "\n"
        "====================================================\n"
        "QuantumGold Adaptive Scalping V4\n"
        "===================================================="
    )

    print(
        f"Minimum AI Score: "
        f"{MIN_AI_SCORE}"
    )

    print(
        f"Minimum Quality: "
        f"{MIN_QUALITY_SCORE}"
    )

    print(
        f"Minimum ADX: "
        f"{MIN_ADX}"
    )

    print(
        f"Design Target Win Rate: "
        f"{TARGET_WIN_RATE}%"
    )

    print(
        "Markets: Gold + Forex"
    )

    print(
        "GainzAlgo V2: ENABLED"
    )

    print(
        "GainzAlgo Pro: ENABLED"
    )

    print(
        "Smart Money confirmations: "
        "SOFT / BONUS"
    )

    print(
        "Microstructure V3.1: "
        f"{'ENABLED' if MICROSTRUCTURE_ENABLED else 'DISABLED'} | "
        f"Hard Gate={'ON' if MICROSTRUCTURE_HARD_FILTER else 'OFF'}"
    )

    crypto_status = (
        "ENABLED"
        if CRYPTO_ENABLED
        else "DISABLED"
    )

    print(
        "Crypto signal delivery: "
        f"{crypto_status}"
    )

    if is_weekend() and not CRYPTO_ENABLED:

        print(
            "Weekend - Gold/Forex closed; Crypto disabled"
        )

        return

    if not TOKEN:

        print(
            "ERROR: "
            "TELEGRAM_TOKEN not configured"
        )

        return

    if not CHAT_ID:

        print(
            "ERROR: "
            "TELEGRAM_CHAT_ID not configured"
        )

        return

    bot = Bot(
        token=TOKEN
    )

    messages = []

    markets_to_scan = list(
        MARKETS
    )

    if CRYPTO_ENABLED:

        markets_to_scan.extend(
            CRYPTO_MARKETS
        )

    for symbol, name in markets_to_scan:

        try:

            result = analyze_market(
                symbol,
                name
            )

            if result:

                messages.append(
                    result
                )

        except Exception as e:

            print(
                f"{name}: "
                f"Unexpected analysis error: "
                f"{e}"
            )

    if messages:

        try:

            separator = (
                "\n\n"
                "━━━━━━━━━━━━━━━━━━━━"
                "\n\n"
            )

            await bot.send_message(
                chat_id=CHAT_ID,
                text=separator.join(
                    messages
                )
            )

            print(
                "High quality "
                "MASTER V3 signals sent"
            )

        except Exception as e:

            print(
                f"Telegram error: {e}"
            )

        try:

            report = get_report()

            crypto_report_status = (
                "ENABLED"
                if CRYPTO_ENABLED
                else "DISABLED"
            )

            report_text = f"""
📊 QuantumGold AI Daily Report

Total Signals:
{report["total"]}

🟢 BUY:
{report["buy"]}

🔴 SELL:
{report["sell"]}

━━━━━━━━━━━━━━━━━━━━

Mode:
MASTER FILTER V3

Minimum AI:
{MIN_AI_SCORE}

Minimum Quality:
{MIN_QUALITY_SCORE}

Minimum ADX:
{MIN_ADX}

Design Target:
{TARGET_WIN_RATE}%

━━━━━━━━━━━━━━━━━━━━

GainzAlgo V2:
ENABLED

GainzAlgo Pro:
ENABLED

V2 Bonus:
+{GAINZ_V2_BONUS}

Pro Bonus:
+{GAINZ_PRO_BONUS}

━━━━━━━━━━━━━━━━━━━━

Smart Money:
SOFT BONUS

BOS/CHoCH:
+5

Liquidity:
+5

FVG:
+5

Displacement:
+5

DXY:
+5 for Gold

Crypto:
{crypto_report_status}
"""

            await bot.send_message(
                chat_id=CHAT_ID,
                text=report_text
            )

        except Exception as e:

            print(
                f"Report error: {e}"
            )

    else:

        print(
            "No MASTER V3 "
            "quality BUY/SELL signals"
        )


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":

    asyncio.run(main())