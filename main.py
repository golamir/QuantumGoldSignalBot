import os
import asyncio
import datetime
import math

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
# MASTER FILTER V3.1 + MICROSTRUCTURE
#
# M5 Entry
# M15 Confirmation
# H1 Major Trend
#
# GainzAlgo V2 Essential
# GainzAlgo Pro
#
# Smart Money:
# BOS / CHoCH
# Liquidity Sweep
# FVG
# Displacement
#
# Microstructure V3.1:
# OHLCV-based HFT-style layer
#
# IMPORTANT:
# This is NOT true exchange HFT.
# True HFT requires tick/order-book/bid-ask data.
# ============================================================


# ============================================================
# TELEGRAM
# ============================================================

TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")


# ============================================================
# MASTER HARD FILTERS
# ============================================================

MIN_AI_SCORE = 80
MIN_QUALITY_SCORE = 80

# Gold + Forex
MIN_ADX = 25

# Crypto
MIN_CRYPTO_ADX = 20

# Design target only - NOT guaranteed
TARGET_WIN_RATE = 85


# ============================================================
# GAINZALGO V2 SETTINGS
# ============================================================

GAINZ_V2_STABILITY = 0.50
GAINZ_V2_RSI = 70
GAINZ_V2_DELTA = 4

GAINZ_V2_BONUS = 10


# ============================================================
# GAINZALGO PRO SETTINGS
# ============================================================

GAINZ_PRO_STABILITY = 0.50
GAINZ_PRO_RSI = 50
GAINZ_PRO_DELTA = 5

GAINZ_PRO_BONUS = 10


# ============================================================
# MARKETS
# ============================================================

# Keep False for the current production configuration.
CRYPTO_ENABLED = False


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
# MICROSTRUCTURE V3.1
# ============================================================

MICROSTRUCTURE_ENABLED = True

# False = soft confirmation / bonus
# True  = Microstructure becomes an additional hard gate
MICROSTRUCTURE_HARD_FILTER = False

MIN_MICRO_SCORE = 55

MICRO_BONUS = 5
MICRO_PENALTY = 5


# ============================================================
# BASIC HELPERS
# ============================================================

def is_crypto_symbol(symbol):
    return symbol in {
        "BTC-USD",
        "ETH-USD",
        "SOL-USD",
        "BNB-USD",
    }


def is_forex_or_gold(symbol):
    return symbol in {
        "GC=F",
        "EURUSD=X",
        "GBPUSD=X",
        "USDJPY=X",
        "USDCHF=X",
        "AUDUSD=X",
        "USDCAD=X",
        "NZDUSD=X",
    }


def get_required_adx(symbol):
    if is_crypto_symbol(symbol):
        return MIN_CRYPTO_ADX

    return MIN_ADX


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

    if symbol in {
        "BTC-USD",
        "ETH-USD",
        "SOL-USD",
        "BNB-USD",
    }:
        return 2

    if symbol == "USDJPY=X":
        return 3

    return 5


def format_price(value, symbol):

    """
    Safe price formatting.
    Avoids nested f-string problems.
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

        # ----------------------------------------------------
        # Fix MultiIndex returned by yfinance
        # ----------------------------------------------------

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
            "Volume",
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
                "Low",
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

        # ----------------------------------------------------
        # Convert possible DataFrame columns to Series
        # ----------------------------------------------------

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

        # ----------------------------------------------------
        # Numeric conversion
        # ----------------------------------------------------

        open_price = (
            open_price
            .astype(float)
            .replace(
                [math.inf, -math.inf],
                math.nan
            )
            .dropna()
        )

        close = (
            close
            .astype(float)
            .replace(
                [math.inf, -math.inf],
                math.nan
            )
            .dropna()
        )

        high = (
            high
            .astype(float)
            .replace(
                [math.inf, -math.inf],
                math.nan
            )
            .dropna()
        )

        low = (
            low
            .astype(float)
            .replace(
                [math.inf, -math.inf],
                math.nan
            )
            .dropna()
        )

        volume = (
            volume
            .astype(float)
            .replace(
                [math.inf, -math.inf],
                math.nan
            )
            .fillna(0)
        )

        # ----------------------------------------------------
        # Make all OHLC series use common index
        # ----------------------------------------------------

        common_index = (
            open_price.index
            .intersection(close.index)
            .intersection(high.index)
            .intersection(low.index)
            .intersection(volume.index)
        )

        if len(common_index) < 60:

            print(
                f"{symbol}: "
                f"insufficient common data "
                f"({len(common_index)})"
            )

            return None

        open_price = (
            open_price
            .loc[common_index]
            .sort_index()
        )

        close = (
            close
            .loc[common_index]
            .sort_index()
        )

        high = (
            high
            .loc[common_index]
            .sort_index()
        )

        low = (
            low
            .loc[common_index]
            .sort_index()
        )

        volume = (
            volume
            .loc[common_index]
            .sort_index()
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

    end = (
        len(high) - lookback
    )

    for i in range(
        start,
        end
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

        # Use last completed candle only.
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

        if not recent_highs and not recent_lows:

            return neutral

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
            f"Structure analysis error: {e}"
        )

        return neutral


# ============================================================
# LIQUIDITY SWEEP
# ============================================================

def detect_liquidity_sweep(
    close,
    high,
    low
):

    neutral = {
        "bullish": False,
        "bearish": False,
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
            "bearish": bearish,
        }

    except Exception as e:

        print(
            f"Liquidity sweep error: {e}"
        )

        return neutral


# ============================================================
# FAIR VALUE GAP
# ============================================================

def detect_fvg(
    close,
    high,
    low,
    atr_value
):

    neutral = {
        "bullish": False,
        "bearish": False,
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
            ),
        }

    except Exception as e:

        print(
            f"FVG detection error: {e}"
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
        "bearish": False,
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

        candle_range = float(
            high.iloc[i]
            - low.iloc[i]
        )

        current_open = float(
            open_price.iloc[i]
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
                current_close
                > previous_close
                and strong
            ),
            "bearish": (
                current_close
                < previous_close
                and strong
            ),
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
        "price_increase": False,
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

            return neutral

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
            "price_increase": price_increase,
        }

    except Exception as e:

        print(
            f"GainzAlgo V2 error: {e}"
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
        "price_increase": False,
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

            return neutral

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
            "price_increase": price_increase,
        }

    except Exception as e:

        print(
            f"GainzAlgo Pro error: {e}"
        )

        return neutral


# ============================================================
# MICROSTRUCTURE / HFT-STYLE
# ============================================================

def _safe_ratio(
    numerator,
    denominator,
    default=0.0
):

    try:

        d = float(
            denominator
        )

        if abs(d) < 1e-12:

            return default

        return (
            float(numerator) / d
        )

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
        "reason": "Microstructure unavailable",
    }

    try:

        # Last completed candle
        i = len(close) - 2

        atr = float(
            atr_value
        )

        if (
            i < 25
            or atr <= 0
        ):

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
        ).iloc[
            start:i
        ].astype(float)

        avg_range = (
            float(
                ranges.median()
            )
            if len(ranges)
            else 0.0
        )

        vols = (
            volume.iloc[start:i]
            .astype(float)
        )

        avg_volume = (
            float(
                vols.mean()
            )
            if len(vols)
            else 0.0
        )

        current_volume = float(
            volume.iloc[i]
        )

        candle_range = (
            h - l
        )

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
            (prev_c - prev_o) < 0
            and (c - o) > 0
            and c > prev_c
        )

        pullback_sell = (
            (prev_c - prev_o) > 0
            and (c - o) < 0
            and c < prev_c
        )

        buy = 0
        sell = 0

        reasons = []

        # ----------------------------------------------------
        # Impulse
        # ----------------------------------------------------

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

        # ----------------------------------------------------
        # Velocity
        # ----------------------------------------------------

        if velocity >= 0.20:

            buy += 12

        elif velocity <= -0.20:

            sell += 12

        # ----------------------------------------------------
        # Candle body
        # ----------------------------------------------------

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

        # ----------------------------------------------------
        # Range expansion
        # ----------------------------------------------------

        if range_ratio >= 1.25:

            if c > o:

                buy += 10

            elif c < o:

                sell += 10

        # ----------------------------------------------------
        # Volume
        # ----------------------------------------------------

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

        # ----------------------------------------------------
        # Breakout
        # ----------------------------------------------------

        if breakout_buy:

            buy += 15

            reasons.append(
                "20-bar upside breakout"
            )

        if breakout_sell:

            sell += 15

            reasons.append(
                "20-bar downside breakout"
            )

        # ----------------------------------------------------
        # Fake breakout / liquidity sweep
        # ----------------------------------------------------

        if fake_breakout_buy:

            buy += 10

            sell = max(
                0,
                sell - 8
            )

            reasons.append(
                "bullish liquidity sweep"
            )

        if fake_breakout_sell:

            sell += 10

            buy = max(
                0,
                buy - 8
            )

            reasons.append(
                "bearish liquidity sweep"
            )

        # ----------------------------------------------------
        # Rejection
        # ----------------------------------------------------

        if rejection_buy:

            buy += 8

        if rejection_sell:

            sell += 8

        # ----------------------------------------------------
        # Pullback
        # ----------------------------------------------------

        if pullback_buy:

            buy += 8

        if pullback_sell:

            sell += 8

        buy = max(
            0,
            min(
                100,
                buy
            )
        )

        sell = max(
            0,
            min(
                100,
                sell
            )
        )

        score = int(
            max(
                0,
                min(
                    100,
                    50
                    + (buy - sell) * 0.5
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
            "fake_breakout_buy": fake_breakout_buy,
            "fake_breakout_sell": fake_breakout_sell,
            "rejection_buy": rejection_buy,
            "rejection_sell": rejection_sell,
            "pullback_buy": pullback_buy,
            "pullback_sell": pullback_sell,
            "reason": (
                ", ".join(reasons)
                if reasons
                else "No strong microstructure event"
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
            micro.get(
                "buy_score",
                0
            )
            >= MIN_MICRO_SCORE
        )

    if signal == "🔴 SELL":

        return (
            micro.get("direction")
            == "SELL"
            or
            micro.get(
                "sell_score",
                0
            )
            >= MIN_MICRO_SCORE
        )

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
            tp3,
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

        rr = (
            reward / risk
        )

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
# QUALITY SCORE
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

    # --------------------------------------------------------
    # M5 EMA
    # --------------------------------------------------------

    if (
        (buy and ema_bullish)
        or
        (sell and not ema_bullish)
    ):

        score += 15

    # --------------------------------------------------------
    # MACD
    # --------------------------------------------------------

    if (
        (buy and macd_bullish)
        or
        (sell and not macd_bullish)
    ):

        score += 15

    # --------------------------------------------------------
    # M15
    # --------------------------------------------------------

    if (
        (buy and m15_bullish)
        or
        (sell and not m15_bullish)
    ):

        score += 10

    # --------------------------------------------------------
    # H1
    # --------------------------------------------------------

    if (
        (buy and h1_bullish)
        or
        (sell and not h1_bullish)
    ):

        score += 10

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
    # Volume
    # --------------------------------------------------------

    if volume_confirmed:

        score += 10

    # --------------------------------------------------------
    # RSI
    # --------------------------------------------------------

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

    # --------------------------------------------------------
    # News
    # --------------------------------------------------------

    if news_risk == "HIGH":

        score -= 20

    elif news_risk == "MEDIUM":

        score += 5

    else:

        score += 10

    # --------------------------------------------------------
    # Entry Quality
    # --------------------------------------------------------

    if entry_quality == "A":

        score += 10

    elif entry_quality == "B":

        score += 5

    else:

        score -= 10

    # --------------------------------------------------------
    # Smart Money
    # --------------------------------------------------------

    if structure_confirmed:

        score += 5

    if liquidity_confirmed:

        score += 5

    if fvg_confirmed:

        score += 5

    if displacement_confirmed:

        score += 5

    # --------------------------------------------------------
    # DXY
    # --------------------------------------------------------

    if dxy_confirmed:

        score += 5

    # --------------------------------------------------------
    # GainzAlgo
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
# MASTER HARD FILTER
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
    tp_sl_valid,
    required_adx=MIN_ADX
):

    # --------------------------------------------------------
    # Signal
    # --------------------------------------------------------

    if signal not in [
        "🟢 BUY",
        "🔴 SELL",
    ]:

        return (
            False,
            "No clear signal"
        )

    # --------------------------------------------------------
    # AI
    # --------------------------------------------------------

    if ai_score < MIN_AI_SCORE:

        return (
            False,
            f"AI Score below {MIN_AI_SCORE}"
        )

    # --------------------------------------------------------
    # Quality
    # --------------------------------------------------------

    if quality_score < MIN_QUALITY_SCORE:

        return (
            False,
            f"Quality below {MIN_QUALITY_SCORE}"
        )

    # --------------------------------------------------------
    # Entry
    # --------------------------------------------------------

    if entry_quality != "A":

        return (
            False,
            f"Entry Quality {entry_quality}"
        )

    # --------------------------------------------------------
    # ADX
    # --------------------------------------------------------

    if adx_value < required_adx:

        return (
            False,
            f"ADX below {required_adx}"
        )

    # --------------------------------------------------------
    # Volume
    # --------------------------------------------------------

    if not volume_confirmed:

        return (
            False,
            "Volume confirmation missing"
        )

    # --------------------------------------------------------
    # Trend
    # --------------------------------------------------------

    if not trend_aligned:

        return (
            False,
            "M5/M15/H1 trend conflict"
        )

    # --------------------------------------------------------
    # RSI
    # --------------------------------------------------------

    if not rsi_valid:

        return (
            False,
            "RSI not valid"
        )

    # --------------------------------------------------------
    # News
    # --------------------------------------------------------

    if news_risk == "HIGH":

        return (
            False,
            "HIGH news risk"
        )

    # --------------------------------------------------------
    # TP / SL
    # --------------------------------------------------------

    if not tp_sl_valid:

        return (
            False,
            "Invalid TP/SL"
        )

    return (
        True,
        "ALL MASTER V3.1 HARD FILTERS PASSED"
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
            "\n"
            + "=" * 60
        )

        print(
            f"Analyzing {name}"
        )

        print(
            "=" * 60
        )

        # ----------------------------------------------------
        # Weekend
        # ----------------------------------------------------

        if (
            is_weekend()
            and not is_crypto_symbol(symbol)
        ):

            print(
                f"{name}: "
                "Weekend - skipped"
            )

            return None

        # ----------------------------------------------------
        # NEWS
        # ----------------------------------------------------

        try:

            news = (
                check_news()
                or {
                    "risk": "HIGH"
                }
            )

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

            # Fail-safe:
            # If news cannot be checked,
            # do not allow a risky trade.
            news_risk = "HIGH"

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

            print(
                f"{name}: "
                "Missing timeframe data"
            )

            return None

        # ----------------------------------------------------
        # DXY FOR GOLD
        # ----------------------------------------------------

        dxy = None

        if symbol == "GC=F":

            dxy = prepare_data(
                "DX-Y.NYB",
                "5m"
            )

        # ----------------------------------------------------
        # M5 DATA
        # ----------------------------------------------------

        open_price = m5["open"]
        close = m5["close"]
        high = m5["high"]
        low = m5["low"]
        volume = m5["volume"]

        # ----------------------------------------------------
        # LIVE PRICE
        # ----------------------------------------------------

        if symbol == "GC=F":

            price = (
                get_live_gold_price()
            )

        else:

            price = None

        # ----------------------------------------------------
        # Fallback to latest completed candle
        # ----------------------------------------------------

        if (
            price is None
            or not is_valid_number(price)
        ):

            price = safe_float(
                close,
                -2
            )

        if (
            price is None
            or not is_valid_number(price)
        ):

            print(
                f"{name}: "
                "Live price unavailable"
            )

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
                f"{name}: "
                f"S/R error: {e}"
            )

            return None

        if not sr:

            print(
                f"{name}: "
                "Support/Resistance unavailable"
            )

            return None

        try:

            support = float(
                sr["support"]
            )

            resistance = float(
                sr["resistance"]
            )

        except Exception:

            print(
                f"{name}: "
                "Invalid Support/Resistance"
            )

            return None

        if (
            not is_valid_number(support)
            or
            not is_valid_number(resistance)
        ):

            return None

        # ----------------------------------------------------
        # INDICATORS
        # ----------------------------------------------------

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
                adx_value,
            ]
        ):

            print(
                f"{name}: "
                "Indicator data unavailable"
            )

            return None

        # ----------------------------------------------------
        # Required ADX
        # ----------------------------------------------------

        required_adx = (
            get_required_adx(symbol)
        )

        # ----------------------------------------------------
        # GAINZ V2
        # ----------------------------------------------------

        gainz_v2 = (
            detect_gainzalgo_v2(
                open_price,
                close,
                high,
                low,
                r
            )
        )

        gainz_v2_buy = (
            gainz_v2["buy"]
        )

        gainz_v2_sell = (
            gainz_v2["sell"]
        )

        # ----------------------------------------------------
        # GAINZ PRO
        # ----------------------------------------------------

        gainz_pro = (
            detect_gainzalgo_pro(
                open_price,
                close,
                high,
                low,
                r
            )
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

            print(
                f"{name}: "
                "M15 EMA unavailable"
            )

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

            print(
                f"{name}: "
                "H1 EMA unavailable"
            )

            return None

        h1_bullish = (
            h1_e50 > h1_e200
        )

        # ----------------------------------------------------
        # VOLUME
        # ----------------------------------------------------

        v = (
            volume
            .fillna(0)
            .astype(float)
        )

        current_volume = (
            safe_float(
                v,
                -2
            )
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
            float(
                window.mean()
            )
            if len(window)
            else 0.0
        )

        volume_confirmed = (
            avg_volume > 0
            and current_volume
            >= avg_volume * 1.05
        )

        # ----------------------------------------------------
        # MICROSTRUCTURE
        # ----------------------------------------------------

        if MICROSTRUCTURE_ENABLED:

            micro = (
                analyze_microstructure(
                    open_price,
                    close,
                    high,
                    low,
                    volume,
                    atr_value
                )
            )

        else:

            micro = {
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
                "reason": "Disabled",
            }

        print(
            f"{name}: "
            f"Microstructure "
            f"BUY={micro['buy_score']} "
            f"SELL={micro['sell_score']} "
            f"DIR={micro['direction']} "
            f"VOLx={micro['volume_ratio']:.2f} "
            f"RANGEx={micro['range_ratio']:.2f}"
        )

        # ----------------------------------------------------
        # SMART MONEY
        # ----------------------------------------------------

        structure = (
            analyze_structure(
                close,
                high,
                low
            )
        )

        liquidity = (
            detect_liquidity_sweep(
                close,
                high,
                low
            )
        )

        fvg = (
            detect_fvg(
                close,
                high,
                low,
                atr_value
            )
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
        # BUY / SELL SCORING
        # ----------------------------------------------------

        buy_score = 0
        sell_score = 0

        # M5 EMA
        if ema_bullish:

            buy_score += 20

        else:

            sell_score += 20

        # MACD
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

        # RSI
        if 45 < r < 70:

            buy_score += 10

        if 30 < r < 55:

            sell_score += 10

        # ADX
        if adx_value >= required_adx:

            buy_score += 10
            sell_score += 10

        # Gainz V2
        if gainz_v2_buy:

            buy_score += GAINZ_V2_BONUS

        if gainz_v2_sell:

            sell_score += GAINZ_V2_BONUS

        # Gainz Pro
        if gainz_pro_buy:

            buy_score += GAINZ_PRO_BONUS

        if gainz_pro_sell:

            sell_score += GAINZ_PRO_BONUS

        # BOS / CHoCH
        if (
            structure["bullish_bos"]
            or
            structure["bullish_choch"]
        ):

            buy_score += 10

        if (
            structure["bearish_bos"]
            or
            structure["bearish_choch"]
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
        # Microstructure contributes to candidate direction
        # ----------------------------------------------------

        if MICROSTRUCTURE_ENABLED:

            if (
                micro["buy_score"]
                >= MIN_MICRO_SCORE
                and
                micro["buy_score"]
                > micro["sell_score"]
            ):

                buy_score += MICRO_BONUS

            elif (
                micro["sell_score"]
                >= MIN_MICRO_SCORE
                and
                micro["sell_score"]
                > micro["buy_score"]
            ):

                sell_score += MICRO_BONUS

        # ----------------------------------------------------
        # SIGNAL CANDIDATE
        # ----------------------------------------------------

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

        else:

            gainz_v2_confirmed = (
                gainz_v2_sell
            )

            gainz_pro_confirmed = (
                gainz_pro_sell
            )

        # ----------------------------------------------------
        # ENTRY FILTER
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
                f"{name}: "
                f"Entry filter error: {e}"
            )

            return None

        if not entry:

            print(
                f"{name}: "
                "Entry rejected"
            )

            return None

        entry_quality = entry.get(
            "quality",
            "C"
        )

        # ----------------------------------------------------
        # RSI VALIDATION
        # ----------------------------------------------------

        if signal == "🟢 BUY":

            rsi_valid = (
                45 < r < 70
            )

        else:

            rsi_valid = (
                30 < r < 55
            )

        # ----------------------------------------------------
        # TREND ALIGNMENT
        # ----------------------------------------------------

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

        # ----------------------------------------------------
        # SMART MONEY DIRECTION
        # ----------------------------------------------------

        if signal == "🟢 BUY":

            structure_confirmed = (
                structure["bullish_bos"]
                or
                structure["bullish_choch"]
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
                or
                structure["bearish_choch"]
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
        # DXY CONFIRMATION
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
        # TP / SL MULTIPLIERS
        # ----------------------------------------------------

        if symbol == "GC=F":

            sl_mult = 2.0
            tp_mult = 3.0

        elif is_crypto_symbol(symbol):

            sl_mult = 3.0
            tp_mult = 5.0

        else:

            sl_mult = 2.0
            tp_mult = 3.0

        # ----------------------------------------------------
        # TP / SL
        # ----------------------------------------------------

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

        # ----------------------------------------------------
        # TP / SL VALIDATION
        # ----------------------------------------------------

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

        # ----------------------------------------------------
        # QUALITY SCORE
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
                gainz_pro_confirmed
            )
        )

        # ----------------------------------------------------
        # MICROSTRUCTURE SOFT CONFIRMATION
        # ----------------------------------------------------

        micro_confirmed = (
            microstructure_confirms(
                signal,
                micro
            )
        )

        if (
            MICROSTRUCTURE_ENABLED
            and micro_confirmed
        ):

            quality_score = min(
                100,
                quality_score
                + MICRO_BONUS
            )

        elif (
            MICROSTRUCTURE_ENABLED
            and
            micro.get(
                "direction"
            )
            not in (
                "NEUTRAL",
                None
            )
        ):

            # Opposite micro direction
            quality_score = max(
                0,
                quality_score
                - MICRO_PENALTY
            )

        # ----------------------------------------------------
        # FINAL AI SCORE
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

            filtered_signal = (
                "⚪ WAIT"
            )

            old_reason = (
                "No-trade filter error"
            )

        # ----------------------------------------------------
        # WAIT NEVER SENT
        # ----------------------------------------------------

        if filtered_signal not in [
            "🟢 BUY",
            "🔴 SELL",
        ]:

            print(
                f"{name}: "
                f"No-trade filter rejected: "
                f"{old_reason}"
            )

            return None

        # ----------------------------------------------------
        # MICROSTRUCTURE HARD GATE
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
                    f"{name}: "
                    f"V3.1 MICRO REJECTED "
                    f"score={micro['score']} "
                    f"direction={micro['direction']}"
                )

                return None

        # ----------------------------------------------------
        # MASTER HARD FILTER
        # ----------------------------------------------------

        passed, reason = (
            master_quality_filter(
                filtered_signal,
                final_ai_score,
                quality_score,
                entry_quality,
                adx_value,
                volume_confirmed,
                trend_aligned,
                rsi_valid,
                news_risk,
                valid_levels,
                required_adx
            )
        )

        if not passed:

            print(
                f"\n{name}: "
                "V3.1 REJECTED"
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
                f"Required ADX: "
                f"{required_adx}"
            )

            print(
                f"Entry: "
                f"{entry_quality}"
            )

            print(
                f"Volume: "
                f"{volume_confirmed}"
            )

            print(
                f"Trend aligned: "
                f"{trend_aligned}"
            )

            print(
                f"RSI valid: "
                f"{rsi_valid}"
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
                f"DXY: "
                f"{dxy_confirmed}"
            )

            print(
                f"Micro: "
                f"{micro_confirmed}"
            )

            print(
                f"Reason: "
                f"{reason}"
            )

            return None

        # ----------------------------------------------------
        # FINAL TP / SL VALIDATION
        # ----------------------------------------------------

        final_valid, final_level_reason = (
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

            print(
                f"{name}: "
                "Final TP/SL validation failed"
            )

            return None

        # ----------------------------------------------------
        # DUPLICATE SIGNAL FILTER
        # ----------------------------------------------------

        try:

            allowed = (
                allow_new_signal(
                    filtered_signal,
                    price
                )
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
                "Duplicate signal blocked"
            )

            return None

        # ----------------------------------------------------
        # SAVE TRADE / SIGNAL
        # ----------------------------------------------------

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

        # ----------------------------------------------------
        # MESSAGE
        # ----------------------------------------------------

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

        micro_status = (
            "CONFIRMED"
            if micro_confirmed
            else "NOT CONFIRMED"
        )

        # ----------------------------------------------------
        # REASONS
        # ----------------------------------------------------

        reasons = [
            "Master V3.1 hard filters passed",
            "AI Score 80+",
            "Quality Score 80+",
            "Entry Quality A",
            f"ADX {required_adx}+",
            "Volume confirmed",
            "M5/M15/H1 aligned",
            "RSI valid",
            "News risk acceptable",
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
                "BOS/CHoCH confirmation +5"
            )

        if liquidity_confirmed:

            reasons.append(
                "Liquidity Sweep confirmation +5"
            )

        if fvg_confirmed:

            reasons.append(
                "FVG confirmation +5"
            )

        if displacement_confirmed:

            reasons.append(
                "Displacement confirmation +5"
            )

        if dxy_confirmed:

            reasons.append(
                "DXY confirmation +5"
            )

        if micro_confirmed:

            reasons.append(
                "Microstructure confirmation +5"
            )

        reasons.append(
            f"Microstructure: "
            f"{micro['direction']} "
            f"score={micro['score']} "
            f"BUY={micro['buy_score']} "
            f"SELL={micro['sell_score']}"
        )

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

        # ----------------------------------------------------
        # FINAL TELEGRAM MESSAGE
        # ----------------------------------------------------

        return f"""
📊 {name} {direction} NOW {p(price)}

⚠️ Stop Loss (SL): {p(stop_loss)}

🎯 TP1: {p(tp1)}
🎯 TP2: {p(tp2)}
🎯 TP3: {p(tp3)}

━━━━━━━━━━━━━━━━━━━━

🥇 QuantumGold AI Signal
MASTER FILTER V3.1

{name}

Signal: {filtered_signal}

Confidence: {final_ai_score}%

Live Price: {p(price)}

Stop Loss: {p(stop_loss)}

Take Profit: {p(tp3)}

━━━━━━━━━━━━━━━━━━━━

Entry Quality:
{entry_quality}

AI Score:
{final_ai_score}/100

Smart Score:
{smart_score}/100

Quality Score:
{quality_score}/100

Decision:
{smart_decision}

Master Filter:
{reason}

━━━━━━━━━━━━━━━━━━━━

ADX:
{adx_value:.2f}

Required ADX:
{required_adx}

RSI:
{r:.2f}

MACD:
{m:.6f}

ATR:
{atr_value:.6f}

Volume:
{volume_status}

━━━━━━━━━━━━━━━━━━━━

GAINZALGO CONFIRMATION

GainzAlgo V2 Essential:
{gainz_v2_status}

GainzAlgo Pro:
{gainz_pro_status}

V2 BUY:
{v2_buy_status}

V2 SELL:
{v2_sell_status}

Pro BUY:
{pro_buy_status}

Pro SELL:
{pro_sell_status}

━━━━━━━━━━━━━━━━━━━━

SMART MONEY CONFLUENCE

BOS / CHoCH:
{structure_status}

Liquidity Sweep:
{liquidity_status}

FVG:
{fvg_status}

Displacement:
{displacement_status}

DXY:
{dxy_status}

━━━━━━━━━━━━━━━━━━━━

MICROSTRUCTURE V3.1

Status:
{"ENABLED" if MICROSTRUCTURE_ENABLED else "DISABLED"}

Hard Gate:
{"ON" if MICROSTRUCTURE_HARD_FILTER else "OFF"}

Direction:
{micro["direction"]}

Micro Score:
{micro["score"]}/100

BUY Score:
{micro["buy_score"]}

SELL Score:
{micro["sell_score"]}

Volume Ratio:
{micro["volume_ratio"]:.2f}x

Range Ratio:
{micro["range_ratio"]:.2f}x

Impulse:
{micro["impulse"]:.2f}

Velocity:
{micro["velocity"]:.2f}

Confirmation:
{micro_status}

━━━━━━━━━━━━━━━━━━━━

NEWS

News Risk:
{news_risk}

━━━━━━━━━━━━━━━━━━━━

RISK MANAGEMENT

Risk / Reward:
{final_level_reason}

Target Win Rate:
{TARGET_WIN_RATE}%
(design target, not guaranteed)

Support:
{p(support)}

Resistance:
{p(resistance)}

━━━━━━━━━━━━━━━━━━━━

REASONS

{reasons_text}

━━━━━━━━━━━━━━━━━━━━

TIMEFRAME

M5 Entry
M15 Confirmation
H1 Major Trend

━━━━━━━━━━━━━━━━━━━━

QuantumGold
MASTER FILTER V3.1
MICROSTRUCTURE
"""


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
        "===================================================="
    )

    print(
        "QuantumGold AI MASTER FILTER V3.1"
    )

    print(
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
        f"Minimum ADX Gold/Forex: "
        f"{MIN_ADX}"
    )

    print(
        f"Minimum ADX Crypto: "
        f"{MIN_CRYPTO_ADX}"
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
        "Smart Money: SOFT / BONUS"
    )

    print(
        "Microstructure V3.1: "
        f"{'ENABLED' if MICROSTRUCTURE_ENABLED else 'DISABLED'}"
    )

    print(
        "Microstructure Hard Gate: "
        f"{'ON' if MICROSTRUCTURE_HARD_FILTER else 'OFF'}"
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

    # --------------------------------------------------------
    # WEEKEND
    # --------------------------------------------------------

    if (
        is_weekend()
        and not CRYPTO_ENABLED
    ):

        print(
            "Weekend - "
            "Gold/Forex closed; "
            "Crypto disabled"
        )

        return

    # --------------------------------------------------------
    # TELEGRAM TOKEN
    # --------------------------------------------------------

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

    # --------------------------------------------------------
    # BOT
    # --------------------------------------------------------

    bot = Bot(
        token=TOKEN
    )

    messages = []

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

    print(
        "\nMarkets to scan:"
    )

    for symbol, name in markets_to_scan:

        print(
            f" - {name} ({symbol})"
        )

    print(
        "\nStarting market scan..."
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

            print(
                f"{name}: "
                f"Unexpected analysis error: "
                f"{e}"
            )

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
                "\nHigh quality "
                "MASTER V3.1 signals sent"
            )

        except Exception as e:

            print(
                f"Telegram error: {e}"
            )

        # ----------------------------------------------------
        # DAILY REPORT
        # ----------------------------------------------------

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
MASTER FILTER V3.1

Minimum AI:
{MIN_AI_SCORE}

Minimum Quality:
{MIN_QUALITY_SCORE}

ADX Gold/Forex:
{MIN_ADX}

ADX Crypto:
{MIN_CRYPTO_ADX}

Design Target:
{TARGET_WIN_RATE}%

━━━━━━━━━━━━━━━━━━━━

GainzAlgo V2:
ENABLED

V2 Bonus:
+{GAINZ_V2_BONUS}

GainzAlgo Pro:
ENABLED

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

━━━━━━━━━━━━━━━━━━━━

Microstructure V3.1:
{"ENABLED" if MICROSTRUCTURE_ENABLED else "DISABLED"}

Micro Hard Gate:
{"ON" if MICROSTRUCTURE_HARD_FILTER else "OFF"}

Micro Bonus:
+{MICRO_BONUS}

Micro Penalty:
-{MICRO_PENALTY}

━━━━━━━━━━━━━━━━━━━━

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
            "\nNo MASTER V3.1 "
            "quality BUY/SELL signals"
        )


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":

    asyncio.run(
        main()
    )
