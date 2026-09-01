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
# ADAPTIVE SCALPING V4.1
# MICROSTRUCTURE + SMC + GAINZALGO
#
# IMPORTANT:
# AI >= 80
# QUALITY >= 80
# ADX >= 25
#
# V4.1 FIXES:
# - Reduced over-filtering
# - Weighted M5/M15/H1 trend alignment
# - Smarter RSI validation
# - Forex volume proxy
# - Safer News failure handling
# - Safer Smart Score failure handling
# - Safer duplicate-memory failure handling
# - Detailed rejection diagnostics
# - Scan statistics
# ============================================================


# ============================================================
# TELEGRAM
# ============================================================

TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")


# ============================================================
# MASTER HARD TARGETS
# ============================================================

MIN_AI_SCORE = 80
MIN_QUALITY_SCORE = 80
MIN_ADX = 25

TARGET_WIN_RATE = 85


# ============================================================
# SMARTER ENTRY SETTINGS
# ============================================================

# Core trend alignment:
# Old V4 required 4/4.
# V4.1 uses weighted alignment.
#
# H1 = most important
# M15 = important
# M5 EMA/MACD = entry direction
#
MIN_TREND_ALIGNMENT = 70

# RSI:
# Old:
# BUY 45-70
# SELL 30-55
#
# V4.1:
# Wider valid zone with ideal-zone bonus.
BUY_RSI_MIN = 40
BUY_RSI_MAX = 72

SELL_RSI_MIN = 28
SELL_RSI_MAX = 60

BUY_RSI_IDEAL_MIN = 45
BUY_RSI_IDEAL_MAX = 68

SELL_RSI_IDEAL_MIN = 32
SELL_RSI_IDEAL_MAX = 55


# ============================================================
# GAINZALGO
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

H4_ENABLED = True
M1_ENABLED = True
REGIME_ENABLED = True

ACCOUNT_BALANCE = float(
    os.getenv("ACCOUNT_BALANCE", "1000")
)

BASE_RISK_PCT = float(
    os.getenv("BASE_RISK_PCT", "1.0")
)

MICRO_ACCOUNT_THRESHOLD = float(
    os.getenv("MICRO_ACCOUNT_THRESHOLD", "10")
)

MICRO_RISK_PCT = float(
    os.getenv("MICRO_RISK_PCT", "1.0")
)

MAX_RISK_PCT = float(
    os.getenv("MAX_RISK_PCT", "1.0")
)

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


CRYPTO_SYMBOLS = {
    x[0] for x in CRYPTO_MARKETS
}


FOREX_SYMBOLS = {
    x[0]
    for x in MARKETS
    if x[0] != "GC=F"
}


# ============================================================
# STRUCTURE
# ============================================================

SWING_LOOKBACK = 3
STRUCTURE_LOOKBACK = 40
LIQUIDITY_LOOKBACK = 30


# ============================================================
# MICROSTRUCTURE
# ============================================================

MICROSTRUCTURE_ENABLED = True

# IMPORTANT:
# Microstructure remains SOFT.
MICROSTRUCTURE_HARD_FILTER = False

MIN_MICRO_SCORE = 55

MICRO_BONUS = 5
MICRO_PENALTY = 5


# ============================================================
# DIAGNOSTIC COUNTERS
# ============================================================

SCAN_STATS = {
    "markets": 0,
    "data_failed": 0,
    "indicator_failed": 0,
    "no_candidate": 0,
    "entry_rejected": 0,
    "rsi_rejected": 0,
    "trend_rejected": 0,
    "tp_sl_rejected": 0,
    "smart_rejected": 0,
    "quality_rejected": 0,
    "adx_rejected": 0,
    "volume_rejected": 0,
    "news_rejected": 0,
    "no_trade_rejected": 0,
    "duplicate_rejected": 0,
    "signals": 0,
    "errors": 0,
}


def reset_scan_stats():

    for key in SCAN_STATS:
        SCAN_STATS[key] = 0


def print_scan_summary():

    print("\n")
    print("=" * 70)
    print("QUANTUMGOLD V4.1 SCAN SUMMARY")
    print("=" * 70)

    for key, value in SCAN_STATS.items():

        print(
            f"{key:25s}: {value}"
        )

    print("=" * 70)


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


def get_price_decimals(symbol):

    if symbol == "GC=F":
        return 2

    if symbol in CRYPTO_SYMBOLS:
        return 2

    if symbol == "USDJPY=X":
        return 3

    return 5


def format_price(value, symbol):

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


def signal_direction(signal):

    if signal == "🟢 BUY":
        return "BUY"

    if signal == "🔴 SELL":
        return "SELL"

    return "NONE"


# ============================================================
# OHLCV NORMALIZATION
# ============================================================

def _to_ohlcv_dataframe(data):

    if data is None:
        return None

    try:

        if isinstance(data, dict):

            mapping = {
                "open": data.get("open"),
                "high": data.get("high"),
                "low": data.get("low"),
                "close": data.get("close"),
                "volume": data.get("volume"),
            }

            if any(
                value is None
                for value in mapping.values()
            ):

                return None

            df = pd.concat(
                mapping,
                axis=1
            )

        elif isinstance(data, pd.DataFrame):

            df = data.copy()

            if isinstance(
                df.columns,
                pd.MultiIndex
            ):

                df.columns = [
                    str(c[0]).lower()
                    for c in df.columns
                ]

            else:

                df.columns = [
                    str(c).lower()
                    for c in df.columns
                ]

            required = [
                "open",
                "high",
                "low",
                "close",
                "volume"
            ]

            if not all(
                c in df.columns
                for c in required
            ):

                return None

            df = df[required]

        else:

            return None

        if isinstance(
            df.columns,
            pd.MultiIndex
        ):

            df.columns = [
                str(c[0]).lower()
                for c in df.columns
            ]

        df.columns = [
            str(c).lower()
            for c in df.columns
        ]

        for col in [
            "open",
            "high",
            "low",
            "close",
            "volume"
        ]:

            if col in df.columns:

                df[col] = pd.to_numeric(
                    df[col],
                    errors="coerce"
                )

        df = df.dropna(
            subset=[
                "open",
                "high",
                "low",
                "close"
            ]
        ).copy()

        df["volume"] = (
            df["volume"]
            .fillna(0)
        )

        if not isinstance(
            df.index,
            pd.DatetimeIndex
        ):

            df.index = pd.to_datetime(
                df.index,
                errors="coerce"
            )

        df = df[
            ~df.index.isna()
        ]

        df = df.sort_index()

        if df.empty:
            return None

        return df

    except Exception as e:

        print(
            f"OHLCV normalization error: {e}"
        )

        return None


# ============================================================
# H4
# ============================================================

def resample_h4(data):

    try:

        df = _to_ohlcv_dataframe(data)

        if df is None or len(df) < 10:
            return None

        # Remove currently forming H1 candle.
        df = df.iloc[:-1].copy()

        if df.empty:
            return None

        h4 = (
            df.resample("4h")
            .agg({
                "open": "first",
                "high": "max",
                "low": "min",
                "close": "last",
                "volume": "sum",
            })
            .dropna(
                subset=[
                    "open",
                    "high",
                    "low",
                    "close"
                ]
            )
        )

        if len(h4) < 60:
            return None

        return h4

    except Exception as e:

        print(
            f"H4 resample error: {e}"
        )

        return None


# ============================================================
# MARKET REGIME
# ============================================================

def market_regime(data):

    unknown = {
        "name": "UNKNOWN",
        "trend": 0,
        "strength": 0.0,
        "volatility": "UNKNOWN",
    }

    try:

        df = _to_ohlcv_dataframe(data)

        if df is None or len(df) < 60:
            return unknown

        c = df["close"]
        h = df["high"]
        l = df["low"]

        adx = ta.trend.ADXIndicator(
            h,
            l,
            c,
            14
        ).adx()

        atr = (
            ta.volatility
            .average_true_range(
                h,
                l,
                c,
                14
            )
        )

        e50 = ta.trend.ema_indicator(
            c,
            50
        )

        e200 = ta.trend.ema_indicator(
            c,
            200
        )

        a = safe_float(
            adx,
            -2
        ) or 0.0

        av = safe_float(
            atr,
            -2
        ) or 0.0

        e5 = safe_float(
            e50,
            -2
        ) or 0.0

        e2 = safe_float(
            e200,
            -2
        ) or 0.0

        trend = (
            1
            if e5 > e2
            else -1
            if e5 < e2
            else 0
        )

        name = (
            "TREND"
            if a >= MIN_REGIME_ADX
            else "RANGE"
        )

        valid_atr = atr.dropna()

        if (
            av > 0
            and len(valid_atr) >= 40
        ):

            med = float(
                valid_atr
                .tail(40)
                .median()
            )

            volatility = (
                "HIGH"
                if av > med * 1.5
                else "LOW"
                if av < med * 0.7
                else "NORMAL"
            )

        else:

            volatility = "NORMAL"

        return {
            "name": name,
            "trend": trend,
            "strength": a,
            "volatility": volatility,
        }

    except Exception as e:

        print(
            f"Market regime error: {e}"
        )

        return unknown


# ============================================================
# ADAPTIVE RISK
# ============================================================

def adaptive_risk(balance=None):

    try:

        b = float(
            balance
            if balance is not None
            else ACCOUNT_BALANCE
        )

    except Exception:

        b = ACCOUNT_BALANCE

    pct = (
        MICRO_RISK_PCT
        if b <= MICRO_ACCOUNT_THRESHOLD
        else BASE_RISK_PCT
    )

    pct = max(
        0.1,
        min(
            MAX_RISK_PCT,
            pct
        )
    )

    return {
        "balance": b,
        "risk_pct": pct,
        "risk_cash": (
            b * pct / 100.0
        ),
        "mode": (
            "MICRO"
            if b <= MICRO_ACCOUNT_THRESHOLD
            else "STANDARD"
        ),
    }


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
            "5m": "7d",
            "15m": "60d",
            "1h": "730d",
            "1m": "7d",
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

        if (
            data is None
            or data.empty
        ):

            print(
                f"{symbol}: EMPTY DATA "
                f"{interval}"
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
            "High",
            "Low",
            "Close",
            "Volume"
        ]

        missing = [
            c
            for c in required
            if c not in data.columns
        ]

        if missing:

            print(
                f"{symbol}: missing "
                f"columns {missing}"
            )

            return None

        data = data.dropna(
            subset=[
                "Open",
                "High",
                "Low",
                "Close"
            ]
        )

        if len(data) < 60:

            print(
                f"{symbol}: insufficient "
                f"{interval} candles="
                f"{len(data)}"
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

            close = (
                close.iloc[:, 0]
            )

        if hasattr(
            high,
            "columns"
        ):

            high = (
                high.iloc[:, 0]
            )

        if hasattr(
            low,
            "columns"
        ):

            low = (
                low.iloc[:, 0]
            )

        if hasattr(
            volume,
            "columns"
        ):

            volume = (
                volume.iloc[:, 0]
            )

        open_price = (
            pd.to_numeric(
                open_price,
                errors="coerce"
            )
            .dropna()
        )

        close = (
            pd.to_numeric(
                close,
                errors="coerce"
            )
            .dropna()
        )

        high = (
            pd.to_numeric(
                high,
                errors="coerce"
            )
            .dropna()
        )

        low = (
            pd.to_numeric(
                low,
                errors="coerce"
            )
            .dropna()
        )

        volume = (
            pd.to_numeric(
                volume,
                errors="coerce"
            )
            .fillna(0)
        )

        if len(close) < 220:

            print(
                f"{symbol}: insufficient "
                f"prepared {interval} "
                f"data={len(close)}"
            )

            return None

        return {
            "open": open_price,
            "close": close,
            "high": high,
            "low": low,
            "volume": volume,
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

        try:

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
                    i + 1:
                    i + lookback + 1
                ].max()
            )

            left_low = float(
                low.iloc[
                    i - lookback:i
                ].min()
            )

            right_low = float(
                low.iloc[
                    i + 1:
                    i + lookback + 1
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

        except Exception:
            continue

    return highs, lows


def analyze_structure(
    close,
    high,
    low
):

    neutral = {
        "bullish_bos": False,
        "bearish_bos": False,
        "bullish_choch": False,
        "bearish_choch": False,
    }

    try:

        last_i = len(close) - 2

        if last_i < 10:
            return neutral

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
            "bearish_choch": bearish_choch,
        }

    except Exception as e:

        print(
            f"Structure error: {e}"
        )

        return neutral


# ============================================================
# LIQUIDITY
# ============================================================

def detect_liquidity_sweep(
    close,
    high,
    low
):

    neutral = {
        "bullish": False,
        "bearish": False
    }

    try:

        i = len(close) - 2

        start = max(
            0,
            i - LIQUIDITY_LOOKBACK
        )

        if i <= start:
            return neutral

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

        return {
            "bullish": (
                current_low < prior_low
                and current_close > prior_low
            ),
            "bearish": (
                current_high > prior_high
                and current_close < prior_high
            )
        }

    except Exception as e:

        print(
            f"Liquidity error: {e}"
        )

        return neutral


# ============================================================
# FVG
# ============================================================

def detect_fvg(
    close,
    high,
    low,
    atr_value
):

    neutral = {
        "bullish": False,
        "bearish": False
    }

    try:

        i = len(close) - 2

        if (
            i < 2
            or atr_value <= 0
        ):

            return neutral

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
            f"FVG error: {e}"
        )

        return neutral


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

    neutral = {
        "bullish": False,
        "bearish": False
    }

    try:

        i = len(close) - 2

        if (
            i < 1
            or atr_value <= 0
        ):

            return neutral

        previous_close = float(
            close.iloc[i - 1]
        )

        current_close = float(
            close.iloc[i]
        )

        current_open = float(
            open_price.iloc[i]
        )

        candle_range = float(
            high.iloc[i]
            - low.iloc[i]
        )

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
                current_close > previous_close
                and strong
            ),
            "bearish": (
                current_close < previous_close
                and strong
            )
        }

    except Exception as e:

        print(
            f"Displacement error: {e}"
        )

        return neutral


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

    neutral = {
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

    try:

        i = len(close) - 2

        if i < GAINZ_V2_DELTA:
            return neutral

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

        true_range = max(
            current_high - current_low,
            abs(
                current_high
                - previous_close
            ),
            abs(
                current_low
                - previous_close
            )
        )

        if true_range <= 0:
            return neutral

        stable_candle = (
            abs(
                current_close
                - current_open
            )
            / true_range
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

        return {
            "buy": (
                bullish_engulfing
                and stable_candle
                and rsi_buy
                and price_decrease
            ),
            "sell": (
                bearish_engulfing
                and stable_candle
                and rsi_sell
                and price_increase
            ),
            "bullish_engulfing":
                bullish_engulfing,
            "bearish_engulfing":
                bearish_engulfing,
            "stable_candle":
                stable_candle,
            "rsi_buy":
                rsi_buy,
            "rsi_sell":
                rsi_sell,
            "price_decrease":
                price_decrease,
            "price_increase":
                price_increase
        }

    except Exception as e:

        print(
            f"Gainz V2 error: {e}"
        )

        return neutral


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

    neutral = {
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

    try:

        i = len(close) - 2

        if i < GAINZ_PRO_DELTA:
            return neutral

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

        true_range = max(
            current_high - current_low,
            abs(
                current_high
                - previous_close
            ),
            abs(
                current_low
                - previous_close
            )
        )

        if true_range <= 0:
            return neutral

        stable_candle = (
            abs(
                current_close
                - current_open
            )
            / true_range
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

        return {
            "buy": (
                bullish_engulfing
                and stable_candle
                and rsi_buy
                and price_decrease
            ),
            "sell": (
                bearish_engulfing
                and stable_candle
                and rsi_sell
                and price_increase
            ),
            "bullish_engulfing":
                bullish_engulfing,
            "bearish_engulfing":
                bearish_engulfing,
            "stable_candle":
                stable_candle,
            "rsi_buy":
                rsi_buy,
            "rsi_sell":
                rsi_sell,
            "price_decrease":
                price_decrease,
            "price_increase":
                price_increase
        }

    except Exception as e:

        print(
            f"Gainz Pro error: {e}"
        )

        return neutral


# ============================================================
# MICROSTRUCTURE
# ============================================================

def _safe_ratio(
    numerator,
    denominator,
    default=0.0
):

    try:

        d = float(denominator)

        if abs(d) < 1e-12:
            return default

        return float(numerator) / d

    except Exception:

        return default


def analyze_microstructure(
    open_price,
    close,
    high,
    low,
    volume,
    atr_value
):

    neutral = {
        "buy_score": 0,
        "sell_score": 0,
        "score": 50,
        "direction": "NEUTRAL",
        "impulse": 0.0,
        "velocity": 0.0,
        "range_ratio": 1.0,
        "volume_ratio": 0.0,
        "breakout_buy": False,
        "breakout_sell": False,
        "fake_breakout_buy": False,
        "fake_breakout_sell": False,
        "rejection_buy": False,
        "rejection_sell": False,
        "pullback_buy": False,
        "pullback_sell": False,
        "reason": "Unavailable",
    }

    try:

        i = len(close) - 2
        atr = float(atr_value)

        if i < 25 or atr <= 0:
            return neutral

        o = float(
            open_price.iloc[i]
        )

        c = float(
            close.iloc[i]
        )

        h = float(
            high.iloc[i]
        )

        l = float(
            low.iloc[i]
        )

        prev_c = float(
            close.iloc[i - 1]
        )

        prev_o = float(
            open_price.iloc[i - 1]
        )

        if h <= l:
            return neutral

        start = max(
            0,
            i - 20
        )

        prev_high20 = float(
            high.iloc[start:i].max()
        )

        prev_low20 = float(
            low.iloc[start:i].min()
        )

        ranges = (
            high - low
        ).iloc[start:i].astype(float)

        avg_range = (
            float(ranges.median())
            if len(ranges)
            else 0.0
        )

        vols = (
            volume
            .iloc[start:i]
            .astype(float)
        )

        avg_volume = (
            float(vols.mean())
            if len(vols)
            else 0.0
        )

        current_volume = float(
            volume.iloc[i]
        )

        candle_range = h - l

        body = abs(
            c - o
        )

        body_ratio = _safe_ratio(
            body,
            candle_range
        )

        close_location = _safe_ratio(
            c - l,
            candle_range
        )

        upper_wick = (
            h - max(o, c)
        )

        lower_wick = (
            min(o, c) - l
        )

        impulse = _safe_ratio(
            c - o,
            atr
        )

        velocity = _safe_ratio(
            c - prev_c,
            atr
        )

        range_ratio = _safe_ratio(
            candle_range,
            avg_range,
            1.0
        )

        volume_ratio = _safe_ratio(
            current_volume,
            avg_volume,
            0.0
        )

        breakout_buy = (
            c > prev_high20
        )

        breakout_sell = (
            c < prev_low20
        )

        fake_breakout_buy = (
            l < prev_low20
            and c > prev_low20
        )

        fake_breakout_sell = (
            h > prev_high20
            and c < prev_high20
        )

        rejection_buy = (
            lower_wick >= body * 1.2
            and close_location >= 0.65
        )

        rejection_sell = (
            upper_wick >= body * 1.2
            and close_location <= 0.35
        )

        pullback_buy = (
            prev_c < prev_o
            and c > o
            and c > prev_c
        )

        pullback_sell = (
            prev_c > prev_o
            and c < o
            and c < prev_c
        )

        buy = 0
        sell = 0

        reasons = []

        if (
            impulse >= 0.35
            and velocity > 0
        ):

            buy += 18
            reasons.append(
                "bullish impulse"
            )

        elif (
            impulse <= -0.35
            and velocity < 0
        ):

            sell += 18
            reasons.append(
                "bearish impulse"
            )

        if velocity >= 0.20:
            buy += 12

        elif velocity <= -0.20:
            sell += 12

        if (
            body_ratio >= 0.55
            and close_location >= 0.70
        ):

            buy += 12

        elif (
            body_ratio >= 0.55
            and close_location <= 0.30
        ):

            sell += 12

        if range_ratio >= 1.25:

            if c > o:
                buy += 10

            elif c < o:
                sell += 10

        if volume_ratio >= 1.20:

            if c > o:
                buy += 12

            elif c < o:
                sell += 12

        elif volume_ratio >= 1.05:

            if c > o:
                buy += 5

            elif c < o:
                sell += 5

        if breakout_buy:

            buy += 15

            reasons.append(
                "upside breakout"
            )

        if breakout_sell:

            sell += 15

            reasons.append(
                "downside breakout"
            )

        if fake_breakout_buy:

            buy += 10
            sell = max(
                0,
                sell - 8
            )

            reasons.append(
                "bullish sweep"
            )

        if fake_breakout_sell:

            sell += 10
            buy = max(
                0,
                buy - 8
            )

            reasons.append(
                "bearish sweep"
            )

        if rejection_buy:
            buy += 8

        if rejection_sell:
            sell += 8

        if pullback_buy:
            buy += 8

        if pullback_sell:
            sell += 8

        buy = max(
            0,
            min(100, buy)
        )

        sell = max(
            0,
            min(100, sell)
        )

        score = int(
            max(
                0,
                min(
                    100,
                    50 + (buy - sell) * 0.5
                )
            )
        )

        if (
            buy > sell
            and buy >= MIN_MICRO_SCORE
        ):

            direction = "BUY"

        elif (
            sell > buy
            and sell >= MIN_MICRO_SCORE
        ):

            direction = "SELL"

        else:

            direction = "NEUTRAL"

        return {
            "buy_score": buy,
            "sell_score": sell,
            "score": score,
            "direction": direction,
            "impulse": impulse,
            "velocity": velocity,
            "range_ratio": range_ratio,
            "volume_ratio": volume_ratio,
            "breakout_buy": breakout_buy,
            "breakout_sell": breakout_sell,
            "fake_breakout_buy":
                fake_breakout_buy,
            "fake_breakout_sell":
                fake_breakout_sell,
            "rejection_buy":
                rejection_buy,
            "rejection_sell":
                rejection_sell,
            "pullback_buy":
                pullback_buy,
            "pullback_sell":
                pullback_sell,
            "reason": (
                ", ".join(reasons)
                if reasons
                else "No strong event"
            ),
        }

    except Exception as e:

        print(
            f"Microstructure error: {e}"
        )

        return neutral


def microstructure_confirms(
    signal,
    micro
):

    if signal == "🟢 BUY":

        return (
            micro.get("direction")
            == "BUY"
            or
            micro.get("buy_score", 0)
            >= MIN_MICRO_SCORE
        )

    if signal == "🔴 SELL":

        return (
            micro.get("direction")
            == "SELL"
            or
            micro.get("sell_score", 0)
            >= MIN_MICRO_SCORE
        )

    return False


# ============================================================
# V4.1 WEIGHTED TREND ALIGNMENT
# ============================================================

def calculate_trend_alignment(
    signal,
    ema_bullish,
    macd_bullish,
    m15_bullish,
    h1_bullish
):

    if signal == "🟢 BUY":

        values = [
            (ema_bullish, 20),
            (macd_bullish, 20),
            (m15_bullish, 25),
            (h1_bullish, 35),
        ]

    elif signal == "🔴 SELL":

        values = [
            (not ema_bullish, 20),
            (not macd_bullish, 20),
            (not m15_bullish, 25),
            (not h1_bullish, 35),
        ]

    else:

        return 0

    score = sum(
        weight
        for condition, weight
        in values
        if condition
    )

    return int(score)


def trend_alignment_ok(
    signal,
    alignment_score
):

    return (
        alignment_score
        >= MIN_TREND_ALIGNMENT
    )


# ============================================================
# RSI
# ============================================================

def calculate_rsi_valid(
    signal,
    rsi_value
):

    if signal == "🟢 BUY":

        return (
            BUY_RSI_MIN
            < rsi_value
            < BUY_RSI_MAX
        )

    if signal == "🔴 SELL":

        return (
            SELL_RSI_MIN
            < rsi_value
            < SELL_RSI_MAX
        )

    return False


def calculate_rsi_score(
    signal,
    rsi_value
):

    if signal == "🟢 BUY":

        if (
            BUY_RSI_IDEAL_MIN
            < rsi_value
            < BUY_RSI_IDEAL_MAX
        ):

            return 10

        if (
            BUY_RSI_MIN
            < rsi_value
            < BUY_RSI_MAX
        ):

            return 5

    elif signal == "🔴 SELL":

        if (
            SELL_RSI_IDEAL_MIN
            < rsi_value
            < SELL_RSI_IDEAL_MAX
        ):

            return 10

        if (
            SELL_RSI_MIN
            < rsi_value
            < SELL_RSI_MAX
        ):

            return 5

    return 0


# ============================================================
# VOLUME
# ============================================================

def calculate_volume_confirmation(
    symbol,
    volume
):

    try:

        v = volume.fillna(0)

        current_volume = (
            safe_float(v, -2)
            or 0.0
        )

        start = max(
            0,
            len(v) - 52
        )

        end = max(
            1,
            len(v) - 2
        )

        window = v.iloc[
            start:end
        ]

        # ----------------------------------------------------
        # FOREX FIX
        #
        # Yahoo Finance Forex volume is frequently zero or
        # unreliable. Do NOT reject all Forex because of it.
        # ----------------------------------------------------

        if symbol in FOREX_SYMBOLS:

            if len(window) == 0:

                return (
                    True,
                    "FOREX_VOLUME_PROXY"
                )

            nonzero = (
                window[window > 0]
            )

            if len(nonzero) < 10:

                return (
                    True,
                    "FOREX_VOLUME_PROXY_NO_REAL_VOLUME"
                )

            avg_volume = float(
                nonzero.mean()
            )

            if avg_volume <= 0:

                return (
                    True,
                    "FOREX_VOLUME_PROXY"
                )

            confirmed = (
                current_volume >=
                avg_volume * 1.05
            )

            return (
                confirmed,
                "FOREX_TICK_VOLUME"
                if confirmed
                else "FOREX_LOW_VOLUME"
            )

        # ----------------------------------------------------
        # GOLD / CRYPTO
        # ----------------------------------------------------

        avg_volume = (
            float(window.mean())
            if len(window)
            else 0.0
        )

        if avg_volume <= 0:

            return (
                False,
                "NO_VOLUME_DATA"
            )

        confirmed = (
            current_volume
            >= avg_volume * 1.05
        )

        return (
            confirmed,
            "VOLUME_CONFIRMED"
            if confirmed
            else "VOLUME_LOW"
        )

    except Exception as e:

        print(
            f"Volume calculation error: {e}"
        )

        # Forex remains proxy-safe.
        if symbol in FOREX_SYMBOLS:

            return (
                True,
                "FOREX_VOLUME_PROXY_ERROR"
            )

        return (
            False,
            "VOLUME_ERROR"
        )


# ============================================================
# TP / SL
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
                "Invalid numeric values"
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
                f"R:R={rr:.2f} < 1.20"
            )

        return (
            True,
            f"R:R={rr:.2f}"
        )

    except Exception as e:

        return (
            False,
            f"TP/SL error: {e}"
        )


# ============================================================
# QUALITY SCORE V4.1
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
    gainz_pro_confirmed=False,
    trend_alignment_score=0
):

    score = 0

    buy = (
        signal == "🟢 BUY"
    )

    sell = (
        signal == "🔴 SELL"
    )

    # --------------------------------------------------------
    # TREND ALIGNMENT
    # --------------------------------------------------------

    # Instead of requiring every component to agree,
    # award quality according to weighted alignment.
    score += int(
        trend_alignment_score * 0.40
    )

    # Maximum contribution here = 40.

    # --------------------------------------------------------
    # ADX
    # --------------------------------------------------------

    if adx_value >= 30:

        score += 15

    elif adx_value >= 25:

        score += 10

    elif adx_value >= 20:

        score += 5

    # --------------------------------------------------------
    # VOLUME
    # --------------------------------------------------------

    if volume_confirmed:

        score += 10

    # --------------------------------------------------------
    # RSI
    # --------------------------------------------------------

    score += calculate_rsi_score(
        signal,
        rsi_value
    )

    # --------------------------------------------------------
    # NEWS
    # --------------------------------------------------------

    if news_risk == "HIGH":

        score -= 20

    elif news_risk == "MEDIUM":

        score += 5

    else:

        score += 10

    # --------------------------------------------------------
    # ENTRY
    # --------------------------------------------------------

    if entry_quality == "A":

        score += 10

    elif entry_quality == "B":

        score += 5

    else:

        score -= 10

    # --------------------------------------------------------
    # SMART MONEY
    # --------------------------------------------------------

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

    # --------------------------------------------------------
    # GAINZALGO
    # --------------------------------------------------------

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
# MASTER FILTER V4.1
# ============================================================

def master_quality_filter(
    signal,
    ai_score,
    quality_score,
    entry_quality,
    adx_value,
    volume_confirmed,
    trend_alignment_score,
    rsi_valid,
    news_risk,
    tp_sl_valid,
    symbol
):

    if signal not in [
        "🟢 BUY",
        "🔴 SELL"
    ]:

        return (
            False,
            "No BUY/SELL signal"
        )

    if ai_score < MIN_AI_SCORE:

        return (
            False,
            f"AI {ai_score} < {MIN_AI_SCORE}"
        )

    if quality_score < MIN_QUALITY_SCORE:

        return (
            False,
            f"Quality {quality_score} < {MIN_QUALITY_SCORE}"
        )

    if entry_quality != "A":

        return (
            False,
            f"Entry Quality={entry_quality}"
        )

    if adx_value < MIN_ADX:

        return (
            False,
            f"ADX {adx_value:.2f} < {MIN_ADX}"
        )

    # --------------------------------------------------------
    # VOLUME
    #
    # Forex can use proxy because Yahoo Forex volume is often
    # unavailable.
    # --------------------------------------------------------

    if (
        not volume_confirmed
        and symbol not in FOREX_SYMBOLS
    ):

        return (
            False,
            "Volume confirmation missing"
        )

    # --------------------------------------------------------
    # TREND
    # --------------------------------------------------------

    if (
        trend_alignment_score
        < MIN_TREND_ALIGNMENT
    ):

        return (
            False,
            "Weighted trend alignment below minimum"
        )

    # --------------------------------------------------------
    # RSI
    # --------------------------------------------------------

    if not rsi_valid:

        return (
            False,
            "RSI outside valid zone"
        )

    # --------------------------------------------------------
    # NEWS
    # --------------------------------------------------------

    if news_risk == "HIGH":

        return (
            False,
            "HIGH news risk"
        )

    # --------------------------------------------------------
    # TP/SL
    # --------------------------------------------------------

    if not tp_sl_valid:

        return (
            False,
            "Invalid TP/SL"
        )

    return (
        True,
        "ALL V4.1 MASTER FILTERS PASSED"
    )


# ============================================================
# MARKET ANALYSIS
# ============================================================

def analyze_market(
    symbol,
    name
):

    SCAN_STATS["markets"] += 1

    try:

        print("\n")
        print("=" * 70)
        print(
            f"ANALYZING {name}"
        )
        print("=" * 70)

        # ----------------------------------------------------
        # WEEKEND
        # ----------------------------------------------------

        if (
            is_weekend()
            and symbol not in CRYPTO_SYMBOLS
        ):

            print(
                f"{name}: Weekend - skipped"
            )

            return None

        # ----------------------------------------------------
        # NEWS
        # ----------------------------------------------------

        try:

            news = (
                check_news()
                or {}
            )

            news_risk = str(
                news.get(
                    "risk",
                    "MEDIUM"
                )
            ).upper()

            if news_risk not in [
                "LOW",
                "MEDIUM",
                "HIGH"
            ]:

                news_risk = "MEDIUM"

        except Exception as e:

            # IMPORTANT:
            # Do not turn an API failure into HIGH
            # and thereby block every market.
            print(
                f"{name}: News API error: "
                f"{e}"
            )

            news_risk = "MEDIUM"

        print(
            f"{name}: News Risk={news_risk}"
        )

        # ----------------------------------------------------
        # DATA
        # ----------------------------------------------------

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

        if (
            m5 is None
            or m15 is None
            or h1 is None
        ):

            SCAN_STATS["data_failed"] += 1

            print(
                f"{name}: Missing core "
                f"M5/M15/H1 data"
            )

            return None

        h4 = (
            resample_h4(h1)
            if H4_ENABLED
            else None
        )

        m1 = (
            prepare_data(
                symbol,
                "1m"
            )
            if M1_ENABLED
            else None
        )

        if h4 is None:

            print(
                f"{name}: H4 unavailable - "
                f"context disabled"
            )

        if m1 is None:

            print(
                f"{name}: M1 unavailable - "
                f"context disabled"
            )

        # ----------------------------------------------------
        # REGIME
        # ----------------------------------------------------

        regime = (
            market_regime(h1)
            if REGIME_ENABLED
            else {
                "name": "UNKNOWN",
                "trend": 0,
                "strength": 0,
                "volatility": "UNKNOWN"
            }
        )

        h4_regime = (
            market_regime(h4)
            if h4 is not None
            else {
                "name": "UNKNOWN",
                "trend": 0,
                "strength": 0,
                "volatility": "UNKNOWN"
            }
        )

        m15_regime = market_regime(
            m15
        )

        m1_regime = (
            market_regime(m1)
            if m1 is not None
            else {
                "name": "UNKNOWN",
                "trend": 0,
                "strength": 0,
                "volatility": "UNKNOWN"
            }
        )

        risk_profile = adaptive_risk()

        print(
            f"{name}: "
            f"H4={h4_regime['trend']} "
            f"H1={regime['trend']} "
            f"M15={m15_regime['trend']} "
            f"M1={m1_regime['trend']} "
            f"Risk={risk_profile['mode']}"
        )

        # ----------------------------------------------------
        # DXY
        # ----------------------------------------------------

        dxy = None

        if symbol == "GC=F":

            dxy = prepare_data(
                "DX-Y.NYB",
                "5m"
            )

        # ----------------------------------------------------
        # M5
        # ----------------------------------------------------

        open_price = m5["open"]
        close = m5["close"]
        high = m5["high"]
        low = m5["low"]
        volume = m5["volume"]

        # ----------------------------------------------------
        # LIVE PRICE
        # ----------------------------------------------------

        price = None

        if symbol == "GC=F":

            try:

                price = (
                    get_live_gold_price()
                )

            except Exception as e:

                print(
                    f"{name}: Live gold "
                    f"price error: {e}"
                )

        if (
            price is None
            or not is_valid_number(price)
        ):

            price = safe_float(
                close,
                -2
            )

        if price is None:

            SCAN_STATS["data_failed"] += 1

            return None

        # ----------------------------------------------------
        # SUPPORT / RESISTANCE
        # ----------------------------------------------------

        try:

            sr = find_support_resistance(
                close
            )

        except Exception as e:

            print(
                f"{name}: S/R error: {e}"
            )

            sr = None

        if not sr:

            print(
                f"{name}: S/R unavailable"
            )

            # Do not automatically kill the market.
            # Build conservative local S/R.
            try:

                support = float(
                    low.tail(30).min()
                )

                resistance = float(
                    high.tail(30).max()
                )

            except Exception:

                return None

        else:

            try:

                support = float(
                    sr["support"]
                )

                resistance = float(
                    sr["resistance"]
                )

            except Exception:

                support = float(
                    low.tail(30).min()
                )

                resistance = float(
                    high.tail(30).max()
                )

        # ----------------------------------------------------
        # INDICATORS
        # ----------------------------------------------------

        try:

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
                ta.volatility
                .average_true_range(
                    high,
                    low,
                    close,
                    14
                )
            )

            adx = (
                ta.trend
                .ADXIndicator(
                    high,
                    low,
                    close,
                    14
                )
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

        except Exception as e:

            SCAN_STATS[
                "indicator_failed"
            ] += 1

            print(
                f"{name}: Indicator error: "
                f"{e}"
            )

            return None

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

            SCAN_STATS[
                "indicator_failed"
            ] += 1

            print(
                f"{name}: Invalid indicators"
            )

            return None

        print(
            f"{name}: "
            f"RSI={r:.2f} "
            f"ADX={adx_value:.2f} "
            f"ATR={atr_value:.5f}"
        )

        # ----------------------------------------------------
        # GAINZ
        # ----------------------------------------------------

        gainz_v2 = detect_gainzalgo_v2(
            open_price,
            close,
            high,
            low,
            r
        )

        gainz_pro = detect_gainzalgo_pro(
            open_price,
            close,
            high,
            low,
            r
        )

        gainz_v2_buy = bool(
            gainz_v2["buy"]
        )

        gainz_v2_sell = bool(
            gainz_v2["sell"]
        )

        gainz_pro_buy = bool(
            gainz_pro["buy"]
        )

        gainz_pro_sell = bool(
            gainz_pro["sell"]
        )

        # ----------------------------------------------------
        # M5 TREND
        # ----------------------------------------------------

        ema_bullish = (
            e50 > e200
        )

        macd_bullish = (
            m > ms
        )

        # ----------------------------------------------------
        # M15 TREND
        # ----------------------------------------------------

        m15_ema50 = (
            ta.trend.ema_indicator(
                m15["close"],
                50
            )
        )

        m15_ema200 = (
            ta.trend.ema_indicator(
                m15["close"],
                200
            )
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

        # ----------------------------------------------------
        # H1 TREND
        # ----------------------------------------------------

        h1_ema50 = (
            ta.trend.ema_indicator(
                h1["close"],
                50
            )
        )

        h1_ema200 = (
            ta.trend.ema_indicator(
                h1["close"],
                200
            )
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

        # ----------------------------------------------------
        # VOLUME
        # ----------------------------------------------------

        (
            volume_confirmed,
            volume_reason
        ) = calculate_volume_confirmation(
            symbol,
            volume
        )

        print(
            f"{name}: "
            f"Volume={volume_confirmed} "
            f"({volume_reason})"
        )

        # ----------------------------------------------------
        # MICROSTRUCTURE
        # ----------------------------------------------------

        micro = analyze_microstructure(
            open_price,
            close,
            high,
            low,
            volume,
            atr_value
        )

        print(
            f"{name}: "
            f"Micro BUY={micro['buy_score']} "
            f"SELL={micro['sell_score']} "
            f"DIR={micro['direction']} "
            f"VOLx={micro['volume_ratio']:.2f}"
        )

        # ----------------------------------------------------
        # SMC
        # ----------------------------------------------------

        structure = analyze_structure(
            close,
            high,
            low
        )

        liquidity = (
            detect_liquidity_sweep(
                close,
                high,
                low
            )
        )

        fvg = detect_fvg(
            close,
            high,
            low,
            atr_value
        )

        displacement = (
            detect_displacement(
                open_price,
                close,
                high,
                low,
                atr_value
            )
        )

        # ----------------------------------------------------
        # DIRECTION SCORING
        # ----------------------------------------------------

        buy_score = 0
        sell_score = 0

        # M5 EMA
        if ema_bullish:
            buy_score += 20
        else:
            sell_score += 20

        # M5 MACD
        if macd_bullish:
            buy_score += 20
        else:
            sell_score += 20

        # M15
        if m15_bullish:
            buy_score += 20
        else:
            sell_score += 20

        # H1
        if h1_bullish:
            buy_score += 20
        else:
            sell_score += 20

        # H4
        if h4_regime["trend"] > 0:
            buy_score += 8

        elif h4_regime["trend"] < 0:
            sell_score += 8

        # M1
        if m1_regime["trend"] > 0:
            buy_score += 5

        elif m1_regime["trend"] < 0:
            sell_score += 5

        # RSI
        if (
            BUY_RSI_MIN
            < r
            < BUY_RSI_MAX
        ):

            buy_score += 10

        if (
            SELL_RSI_MIN
            < r
            < SELL_RSI_MAX
        ):

            sell_score += 10

        # ADX direction neutral bonus
        if adx_value >= MIN_ADX:

            buy_score += 10
            sell_score += 10

        # Gainz
        if gainz_v2_buy:
            buy_score += GAINZ_V2_BONUS

        if gainz_v2_sell:
            sell_score += GAINZ_V2_BONUS

        if gainz_pro_buy:
            buy_score += GAINZ_PRO_BONUS

        if gainz_pro_sell:
            sell_score += GAINZ_PRO_BONUS

        # Structure
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

        # Liquidity
        if liquidity["bullish"]:
            buy_score += 10

        if liquidity["bearish"]:
            sell_score += 10

        # Displacement
        if displacement["bullish"]:
            buy_score += 5

        if displacement["bearish"]:
            sell_score += 5

        # FVG
        if fvg["bullish"]:
            buy_score += 5

        if fvg["bearish"]:
            sell_score += 5

        # ----------------------------------------------------
        # CANDIDATE
        # ----------------------------------------------------

        if (
            buy_score >= 65
            and buy_score > sell_score
        ):

            signal = "🟢 BUY"

            preliminary = min(
                100,
                buy_score
            )

        elif (
            sell_score >= 65
            and sell_score > buy_score
        ):

            signal = "🔴 SELL"

            preliminary = min(
                100,
                sell_score
            )

        else:

            SCAN_STATS[
                "no_candidate"
            ] += 1

            print(
                f"{name}: NO CANDIDATE "
                f"BUY={buy_score} "
                f"SELL={sell_score}"
            )

            return None

        print(
            f"{name}: CANDIDATE "
            f"{signal} "
            f"BUY={buy_score} "
            f"SELL={sell_score}"
        )

        # ----------------------------------------------------
        # GAINZ CONFIRMATION
        # ----------------------------------------------------

        if signal == "🟢 BUY":

            gainz_v2_confirmed = (
                gainz_v2_buy
            )

            gainz_pro_confirmed = (
                gainz_pro_buy
            )

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

            gainz_v2_confirmed = (
                gainz_v2_sell
            )

            gainz_pro_confirmed = (
                gainz_pro_sell
            )

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

        # ----------------------------------------------------
        # ENTRY
        # ----------------------------------------------------

        try:

            entry = check_entry(
                signal,
                price,
                support,
                resistance,
                r,
                preliminary
            )

        except Exception as e:

            print(
                f"{name}: Entry error: {e}"
            )

            entry = None

        if not entry:

            SCAN_STATS[
                "entry_rejected"
            ] += 1

            print(
                f"{name}: ENTRY REJECTED"
            )

            return None

        entry_quality = str(
            entry.get(
                "quality",
                "C"
            )
        ).upper()

        # ----------------------------------------------------
        # RSI
        # ----------------------------------------------------

        rsi_valid = calculate_rsi_valid(
            signal,
            r
        )

        if not rsi_valid:

            SCAN_STATS[
                "rsi_rejected"
            ] += 1

            print(
                f"{name}: RSI REJECTED "
                f"signal={signal} "
                f"RSI={r:.2f}"
            )

            return None

        # ----------------------------------------------------
        # WEIGHTED TREND ALIGNMENT
        # ----------------------------------------------------

        trend_alignment_score = (
            calculate_trend_alignment(
                signal,
                ema_bullish,
                macd_bullish,
                m15_bullish,
                h1_bullish
            )
        )

        trend_aligned = (
            trend_alignment_ok(
                signal,
                trend_alignment_score
            )
        )

        print(
            f"{name}: Trend Alignment="
            f"{trend_alignment_score}/100"
        )

        if not trend_aligned:

            SCAN_STATS[
                "trend_rejected"
            ] += 1

            print(
                f"{name}: TREND REJECTED"
            )

            return None

        # ----------------------------------------------------
        # TP/SL
        # ----------------------------------------------------

        if symbol in CRYPTO_SYMBOLS:

            sl_mult = 3.0
            tp_mult = 5.0

        else:

            sl_mult = 2.0
            tp_mult = 3.0

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

        (
            valid_levels,
            level_reason
        ) = validate_trade_levels(
            signal,
            price,
            stop_loss,
            tp1,
            tp2,
            tp3
        )

        if not valid_levels:

            SCAN_STATS[
                "tp_sl_rejected"
            ] += 1

            print(
                f"{name}: TP/SL REJECTED "
                f"{level_reason}"
            )

            return None

        # ----------------------------------------------------
        # DXY
        # ----------------------------------------------------

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

        # ----------------------------------------------------
        # SMART SCORE
        # ----------------------------------------------------

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

            if not isinstance(
                smart,
                dict
            ):

                smart = {}

            smart_score = int(
                max(
                    0,
                    min(
                        100,
                        float(
                            smart.get(
                                "score",
                                preliminary
                            )
                        )
                    )
                )
            )

            smart_decision = smart.get(
                "decision",
                "AVAILABLE"
            )

        except Exception as e:

            # IMPORTANT:
            # Previous version set this to ZERO.
            # That could block every signal.
            #
            # V4.1 uses preliminary score as a fallback
            # while clearly logging the error.
            print(
                f"{name}: Smart score error: "
                f"{e}"
            )

            smart_score = int(
                max(
                    0,
                    min(
                        100,
                        preliminary
                    )
                )
            )

            smart_decision = (
                "FALLBACK_PRELIMINARY"
            )

        print(
            f"{name}: Smart Score="
            f"{smart_score} "
            f"Decision={smart_decision}"
        )

        # ----------------------------------------------------
        # QUALITY
        # ----------------------------------------------------

        quality_score = (
            calculate_quality_score(
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
                gainz_pro_confirmed,
                trend_alignment_score
            )
        )

        # ----------------------------------------------------
        # MICRO BONUS
        # ----------------------------------------------------

        micro_confirmed = (
            microstructure_confirms(
                signal,
                micro
            )
        )

        if micro_confirmed:

            quality_score = min(
                100,
                quality_score
                + MICRO_BONUS
            )

        elif (
            micro.get("direction")
            not in [
                "NEUTRAL",
                None
            ]
        ):

            # Only small penalty.
            quality_score = max(
                0,
                quality_score
                - MICRO_PENALTY
            )

        # ----------------------------------------------------
        # FINAL AI
        # ----------------------------------------------------

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

        print(
            f"{name}: "
            f"AI={final_ai_score}/100 "
            f"Quality={quality_score}/100 "
            f"Smart={smart_score}/100"
        )

        # ----------------------------------------------------
        # QUICK DIAGNOSTIC
        # ----------------------------------------------------

        print(
            f"{name}: "
            f"Entry={entry_quality} "
            f"ADX={adx_value:.2f} "
            f"RSI={r:.2f} "
            f"Trend={trend_alignment_score}/100 "
            f"Volume={volume_confirmed} "
            f"News={news_risk}"
        )

        # ----------------------------------------------------
        # AI / QUALITY DIAGNOSTIC
        # ----------------------------------------------------

        if smart_score < MIN_AI_SCORE:

            SCAN_STATS[
                "smart_rejected"
            ] += 1

            print(
                f"{name}: SMART SCORE REJECTED "
                f"{smart_score} < "
                f"{MIN_AI_SCORE}"
            )

            return None

        if quality_score < MIN_QUALITY_SCORE:

            SCAN_STATS[
                "quality_rejected"
            ] += 1

            print(
                f"{name}: QUALITY REJECTED "
                f"{quality_score} < "
                f"{MIN_QUALITY_SCORE}"
            )

            return None

        if adx_value < MIN_ADX:

            SCAN_STATS[
                "adx_rejected"
            ] += 1

            print(
                f"{name}: ADX REJECTED "
                f"{adx_value:.2f}"
            )

            return None

        if (
            not volume_confirmed
            and symbol not in FOREX_SYMBOLS
        ):

            SCAN_STATS[
                "volume_rejected"
            ] += 1

            print(
                f"{name}: VOLUME REJECTED"
            )

            return None

        if news_risk == "HIGH":

            SCAN_STATS[
                "news_rejected"
            ] += 1

            print(
                f"{name}: NEWS REJECTED"
            )

            return None

        # ----------------------------------------------------
        # NO TRADE FILTER
        # ----------------------------------------------------

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

            if not isinstance(
                old,
                dict
            ):

                old = {}

            filtered_signal = old.get(
                "signal",
                signal
            )

            old_reason = old.get(
                "reason",
                ""
            )

        except Exception as e:

            # Do not let a broken optional filter
            # silently destroy the whole system.
            print(
                f"{name}: No-trade filter "
                f"error: {e}"
            )

            filtered_signal = signal

            old_reason = (
                "FILTER_ERROR_FALLBACK"
            )

        if filtered_signal not in [
            "🟢 BUY",
            "🔴 SELL"
        ]:

            SCAN_STATS[
                "no_trade_rejected"
            ] += 1

            print(
                f"{name}: "
                f"NO-TRADE REJECTED: "
                f"{old_reason}"
            )

            return None

        # ----------------------------------------------------
        # FINAL MASTER FILTER
        # ----------------------------------------------------

        (
            passed,
            reason
        ) = master_quality_filter(
            filtered_signal,
            final_ai_score,
            quality_score,
            entry_quality,
            adx_value,
            volume_confirmed,
            trend_alignment_score,
            rsi_valid,
            news_risk,
            valid_levels,
            symbol
        )

        if not passed:

            print(
                f"{name}: MASTER REJECTED"
            )

            print(
                f"Reason={reason}"
            )

            if "AI" in reason:

                SCAN_STATS[
                    "smart_rejected"
                ] += 1

            elif "Quality" in reason:

                SCAN_STATS[
                    "quality_rejected"
                ] += 1

            elif "ADX" in reason:

                SCAN_STATS[
                    "adx_rejected"
                ] += 1

            elif "Volume" in reason:

                SCAN_STATS[
                    "volume_rejected"
                ] += 1

            elif "news" in reason.lower():

                SCAN_STATS[
                    "news_rejected"
                ] += 1

            return None

        # ----------------------------------------------------
        # OPTIONAL MICRO HARD GATE
        # ----------------------------------------------------

        if (
            MICROSTRUCTURE_ENABLED
            and MICROSTRUCTURE_HARD_FILTER
        ):

            if not microstructure_confirms(
                filtered_signal,
                micro
            ):

                print(
                    f"{name}: MICRO HARD REJECTED"
                )

                return None

        # ----------------------------------------------------
        # FINAL TP/SL
        # ----------------------------------------------------

        final_valid, final_reason = (
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

            SCAN_STATS[
                "tp_sl_rejected"
            ] += 1

            print(
                f"{name}: Final TP/SL "
                f"rejected: "
                f"{final_reason}"
            )

            return None

        # ----------------------------------------------------
        # DUPLICATE FILTER
        # ----------------------------------------------------

        try:

            allowed = allow_new_signal(
                filtered_signal,
                price
            )

        except Exception as e:

            # IMPORTANT:
            # Previous version:
            # allowed = False
            #
            # That meant ANY memory error killed
            # an otherwise valid signal.
            #
            # V4.1 uses safe fallback:
            # all Master filters have already passed.
            print(
                f"{name}: Duplicate memory "
                f"error: {e}"
            )

            allowed = True

        if not allowed:

            SCAN_STATS[
                "duplicate_rejected"
            ] += 1

            print(
                f"{name}: DUPLICATE BLOCKED"
            )

            return None

        # ----------------------------------------------------
        # SAVE
        # ----------------------------------------------------

        try:

            save_last_signal(
                filtered_signal,
                price
            )

        except Exception as e:

            print(
                f"{name}: save_last_signal "
                f"error: {e}"
            )

        try:

            save_trade(
                filtered_signal,
                price,
                final_ai_score,
                stop_loss,
                tp3
            )

        except Exception as e:

            print(
                f"{name}: save_trade "
                f"error: {e}"
            )

        try:

            save_signal(
                filtered_signal
            )

        except Exception as e:

            print(
                f"{name}: save_signal "
                f"error: {e}"
            )

        # ----------------------------------------------------
        # SUCCESS
        # ----------------------------------------------------

        SCAN_STATS[
            "signals"
        ] += 1

        direction = (
            "BUY"
            if filtered_signal == "🟢 BUY"
            else "SELL"
        )

        p = lambda x: format_price(
            x,
            symbol
        )

        print(
            f"\n"
            f"*** {name} FINAL SIGNAL ***"
        )

        print(
            f"Direction: {direction}"
        )

        print(
            f"Price: {p(price)}"
        )

        print(
            f"AI: {final_ai_score}/100"
        )

        print(
            f"Quality: {quality_score}/100"
        )

        print(
            f"ADX: {adx_value:.2f}"
        )

        print(
            f"Trend Alignment: "
            f"{trend_alignment_score}/100"
        )

        print(
            f"RSI: {r:.2f}"
        )

        print(
            f"SL: {p(stop_loss)}"
        )

        print(
            f"TP1: {p(tp1)}"
        )

        print(
            f"TP2: {p(tp2)}"
        )

        print(
            f"TP3: {p(tp3)}"
        )

        print(
            f"Micro: "
            f"{micro['direction']} "
            f"{micro['score']}"
        )

        print(
            "*** SIGNAL PASSED ***"
        )

        # ----------------------------------------------------
        # TELEGRAM MESSAGE
        # ----------------------------------------------------

        return f"""📊 {name} {direction} NOW {p(price)}

⚠️ SL: {p(stop_loss)}
🎯 TP1: {p(tp1)}
🎯 TP2: {p(tp2)}
🎯 TP3: {p(tp3)}

AI Score: {final_ai_score}/100
Quality: {quality_score}/100
ADX: {adx_value:.2f}
RSI: {r:.2f}

Trend Alignment: {trend_alignment_score}/100
Microstructure: {micro['direction']} {micro['score']}/100

Regime: {regime['name']}
Risk Mode: {risk_profile['mode']} | Risk: {risk_profile['risk_pct']:.2f}%

QuantumGold Adaptive Scalping V4.1"""

    except Exception as e:

        SCAN_STATS[
            "errors"
        ] += 1

        print(
            f"{name}: UNEXPECTED ERROR: "
            f"{e}"
        )

        return None


# ============================================================
# MAIN
# ============================================================

async def main():

    reset_scan_stats()

    print("\n")
    print("=" * 70)
    print(
        "QuantumGold Adaptive Scalping V4.1"
    )
    print("=" * 70)

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
        f"Minimum Trend Alignment: "
        f"{MIN_TREND_ALIGNMENT}/100"
    )

    print(
        f"BUY RSI: "
        f"{BUY_RSI_MIN}-{BUY_RSI_MAX}"
    )

    print(
        f"SELL RSI: "
        f"{SELL_RSI_MIN}-{SELL_RSI_MAX}"
    )

    print(
        f"Design Target: "
        f"{TARGET_WIN_RATE}%"
    )

    print(
        "Markets: Gold + Forex"
    )

    print(
        f"Crypto: "
        f"{'ENABLED' if CRYPTO_ENABLED else 'DISABLED'}"
    )

    print(
        "GainzAlgo V2: ENABLED"
    )

    print(
        "GainzAlgo Pro: ENABLED"
    )

    print(
        "Smart Money: SOFT BONUS"
    )

    print(
        "Microstructure: "
        f"{'ENABLED' if MICROSTRUCTURE_ENABLED else 'DISABLED'}"
    )

    print(
        "Micro Hard Gate: "
        f"{'ON' if MICROSTRUCTURE_HARD_FILTER else 'OFF'}"
    )

    print("=" * 70)

    # --------------------------------------------------------
    # WEEKEND
    # --------------------------------------------------------

    if (
        is_weekend()
        and not CRYPTO_ENABLED
    ):

        print(
            "Weekend: Gold/Forex closed "
            "and Crypto disabled."
        )

        return

    # --------------------------------------------------------
    # TELEGRAM CONFIG
    # --------------------------------------------------------

    if not TOKEN:

        print(
            "ERROR: TELEGRAM_TOKEN "
            "not configured"
        )

        return

    if not CHAT_ID:

        print(
            "ERROR: TELEGRAM_CHAT_ID "
            "not configured"
        )

        return

    try:

        bot = Bot(
            token=TOKEN
        )

    except Exception as e:

        print(
            f"Telegram Bot initialization "
            f"error: {e}"
        )

        return

    # --------------------------------------------------------
    # MARKETS
    # --------------------------------------------------------

    markets_to_scan = list(
        MARKETS
    )

    if CRYPTO_ENABLED:

        markets_to_scan.extend(
            CRYPTO_MARKETS
        )

    messages = []

    print(
        f"\nTotal markets to scan: "
        f"{len(markets_to_scan)}"
    )

    # --------------------------------------------------------
    # SCAN
    # --------------------------------------------------------

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

            SCAN_STATS[
                "errors"
            ] += 1

            print(
                f"{name}: Scan error: "
                f"{e}"
            )

    # --------------------------------------------------------
    # SUMMARY
    # --------------------------------------------------------

    print_scan_summary()

    # --------------------------------------------------------
    # SEND SIGNALS
    # --------------------------------------------------------

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
                f"SUCCESS: "
                f"{len(messages)} "
                f"signal(s) sent to Telegram."
            )

        except Exception as e:

            print(
                f"Telegram send error: "
                f"{e}"
            )

        # ----------------------------------------------------
        # DAILY REPORT
        # ----------------------------------------------------

        try:

            report = get_report()

            crypto_status = (
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
MASTER FILTER V4.1

Minimum AI:
{MIN_AI_SCORE}

Minimum Quality:
{MIN_QUALITY_SCORE}

Minimum ADX:
{MIN_ADX}

Trend Alignment:
{MIN_TREND_ALIGNMENT}/100

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
+5 Gold

Microstructure:
ENABLED

Crypto:
{crypto_status}
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
            "\nNO FINAL BUY/SELL SIGNALS."
        )

        print(
            "IMPORTANT: "
            "Use the V4.1 SCAN SUMMARY above "
            "to see exactly which filter "
            "blocked the markets."
        )


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":

    asyncio.run(main())
