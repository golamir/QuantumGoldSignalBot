import os
import asyncio
import datetime
import math
import inspect

import yfinance as yf
import ta
from telegram import Bot

from news_filter import check_news
from daily_report import save_signal
from signal_memory import allow_new_signal
from trade_memory import save_trade, save_last_signal
from live_price import get_live_gold_price
from support_resistance import find_support_resistance
from entry_filter import check_entry
from smart_score import calculate_score
from no_trade_filter import apply_no_trade_filter


# ============================================================
# OPTIONAL HFT / MICROSTRUCTURE ENGINE
# ============================================================

HFT_ENGINE_AVAILABLE = False
hft_engine = None

try:
    import hft_engine
    HFT_ENGINE_AVAILABLE = True
    print("HFT Engine: MODULE LOADED")
except Exception as e:
    print(f"HFT Engine: unavailable -> {e}")


# ============================================================
# QuantumGold AI Signal Bot
# MASTER FILTER V3.2 + MICROSTRUCTURE / HFT
#
# Gold + Forex + Crypto
#
# M5  = Entry
# M15 = Confirmation
# H1  = Main Trend
#
# HARD FILTERS:
#   AI >= 80
#   Quality >= 80
#   ADX
#   Trend alignment
#   RSI valid
#   TP/SL valid
#   Entry Quality A
#
# GOLD / FOREX:
#   ADX >= 25
#   Volume = HARD
#   HIGH NEWS = HARD REJECT
#
# CRYPTO:
#   ADX >= 20
#   Volume = SOFT
#   HIGH NEWS = SOFT
#   Triangle = SOFT
#
# SMART MONEY:
#   BOS / CHOCH
#   Liquidity Sweep
#   FVG
#   Displacement
#   All are SOFT confirmations
#
# HFT / MICROSTRUCTURE:
#   SOFT confirmation
#   Never replaces MASTER hard filters
# ============================================================


TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")


# ============================================================
# MASTER HARD FILTERS
# ============================================================

MIN_AI_SCORE = 80
MIN_QUALITY_SCORE = 80

# Gold / Forex
MIN_ADX = 25

# Crypto
MIN_CRYPTO_ADX = 20

TARGET_WIN_RATE = 85


# ============================================================
# HFT / MICROSTRUCTURE SETTINGS
# ============================================================

HFT_ENABLED = True

# HFT is currently a SOFT confirmation.
# It does NOT become a hard rejection.
HFT_HARD_GATE = False

# HFT confirmation bonus
HFT_BONUS = 10

# Minimum HFT score considered useful
HFT_MIN_SCORE = 60


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

# Crypto triangle
TRIANGLE_LOOKBACK = 24
TRIANGLE_MIN_WIDTH_ATR = 1.5
TRIANGLE_MAX_CONVERGENCE_RATIO = 0.85


# ============================================================
# WEEKEND HELPERS
# ============================================================

def is_weekend():

    return (
        datetime.datetime.utcnow().weekday()
        in [5, 6]
    )


def is_crypto_symbol(symbol):

    return symbol in [
        "BTC-USD",
        "ETH-USD",
        "SOL-USD",
        "BNB-USD"
    ]


# ============================================================
# MARKET TYPE
# ============================================================

def is_crypto_market(symbol):

    return is_crypto_symbol(symbol)


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

    try:

        decimals = get_price_decimals(symbol)

        number = float(value)

        return format(
            number,
            f".{decimals}f"
        )

    except Exception:

        return "N/A"


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


# ============================================================
# LIVE MARKET PRICE
# ============================================================

def get_live_market_price(symbol):

    try:

        print(
            f"{symbol}: "
            f"Fetching LIVE 1m price..."
        )

        ticker = yf.Ticker(symbol)

        data = ticker.history(
            period="1d",
            interval="1m",
            auto_adjust=False
        )

        if (
            data is not None
            and not data.empty
        ):

            if "Close" in data.columns:

                data = data.dropna(
                    subset=["Close"]
                )

                if not data.empty:

                    live_price = float(
                        data["Close"].iloc[-1]
                    )

                    if is_valid_number(
                        live_price
                    ):

                        print(
                            f"{symbol}: "
                            f"LIVE 1m PRICE = "
                            f"{live_price}"
                        )

                        return live_price

        print(
            f"{symbol}: "
            f"LIVE 1m price unavailable"
        )

    except Exception as e:

        print(
            f"{symbol}: "
            f"LIVE price error: {e}"
        )

    return None


# ============================================================
# FINAL LIVE PRICE
# ============================================================

def get_final_live_price(symbol):

    live_price = get_live_market_price(
        symbol
    )

    if (
        live_price is not None
        and is_valid_number(live_price)
    ):

        return float(live_price)

    if symbol == "GC=F":

        try:

            gold_price = get_live_gold_price()

            if is_valid_number(
                gold_price
            ):

                gold_price = float(
                    gold_price
                )

                print(
                    f"{symbol}: "
                    f"Dedicated LIVE GOLD "
                    f"price = {gold_price}"
                )

                return gold_price

        except Exception as e:

            print(
                f"{symbol}: "
                f"Dedicated gold live "
                f"price error: {e}"
            )

    print(
        f"{symbol}: "
        f"NO LIVE PRICE AVAILABLE"
    )

    return None


# ============================================================
# PREPARE DATA
# ============================================================

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

        if hasattr(open_price, "columns"):
            open_price = open_price.iloc[:, 0]

        if hasattr(close, "columns"):
            close = close.iloc[:, 0]

        if hasattr(high, "columns"):
            high = high.iloc[:, 0]

        if hasattr(low, "columns"):
            low = low.iloc[:, 0]

        if hasattr(volume, "columns"):
            volume = volume.iloc[:, 0]

        open_price = open_price.dropna()
        close = close.dropna()
        high = high.dropna()
        low = low.dropna()
        volume = volume.fillna(0)

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

        highs, lows = find_recent_swings(
            high.iloc[:last_i + 1],
            low.iloc[:last_i + 1]
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
            and last_close > recent_highs[-2][1]
        )

        bearish_choch = (
            len(recent_lows) >= 2
            and last_close < recent_lows[-2][1]
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

        minimum_gap = atr_value * 0.05

        return {
            "bullish": bullish_gap > minimum_gap,
            "bearish": bearish_gap > minimum_gap
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

        body = abs(
            current_close
            - previous_close
        )

        strong = (
            body >= atr_value * 0.60
            and candle_range >= atr_value * 0.80
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

        return {
            "bullish": False,
            "bearish": False
        }


# ============================================================
# CRYPTO SYMMETRICAL TRIANGLE
# ============================================================

def detect_symmetric_triangle(
    close,
    high,
    low,
    atr_value,
    lookback=TRIANGLE_LOOKBACK
):

    result = {
        "detected": False,
        "bullish_breakout": False,
        "bearish_breakout": False,
        "bullish_retest": False,
        "bearish_retest": False,
        "upper_boundary": None,
        "lower_boundary": None
    }

    try:

        if (
            atr_value is None
            or atr_value <= 0
            or len(close) < lookback + 10
        ):

            return result

        last_closed = len(close) - 2

        structure_end = last_closed - 1

        structure_start = max(
            0,
            structure_end - lookback + 1
        )

        if (
            structure_end
            - structure_start
            + 1
            < 15
        ):

            return result

        structure_highs = [
            float(
                high.iloc[i]
            )
            for i in range(
                structure_start,
                structure_end + 1
            )
        ]

        structure_lows = [
            float(
                low.iloc[i]
            )
            for i in range(
                structure_start,
                structure_end + 1
            )
        ]

        if len(structure_highs) < 15:
            return result

        n = len(structure_highs)

        mid = n // 2

        first_high = max(
            structure_highs[:mid]
        )

        second_high = max(
            structure_highs[mid:]
        )

        first_low = min(
            structure_lows[:mid]
        )

        second_low = min(
            structure_lows[mid:]
        )

        upper_falling = (
            second_high < first_high
        )

        lower_rising = (
            second_low > first_low
        )

        if not (
            upper_falling
            and lower_rising
        ):

            return result

        first_width = (
            first_high
            - first_low
        )

        second_width = (
            second_high
            - second_low
        )

        if first_width <= 0:
            return result

        convergence_ratio = (
            second_width
            / first_width
        )

        if (
            convergence_ratio
            > TRIANGLE_MAX_CONVERGENCE_RATIO
        ):

            return result

        if (
            first_width
            < atr_value * TRIANGLE_MIN_WIDTH_ATR
        ):

            return result

        upper_boundary = second_high
        lower_boundary = second_low

        result["detected"] = True

        result["upper_boundary"] = (
            upper_boundary
        )

        result["lower_boundary"] = (
            lower_boundary
        )

        breakout_close = float(
            close.iloc[last_closed]
        )

        breakout_buffer = (
            atr_value * 0.05
        )

        bullish_breakout = (
            breakout_close
            > upper_boundary
            + breakout_buffer
        )

        bearish_breakout = (
            breakout_close
            < lower_boundary
            - breakout_buffer
        )

        result[
            "bullish_breakout"
        ] = bullish_breakout

        result[
            "bearish_breakout"
        ] = bearish_breakout

        retest_start = max(
            structure_start,
            last_closed - 7
        )

        if bullish_breakout:

            for i in range(
                retest_start,
                last_closed
            ):

                candle_low = float(
                    low.iloc[i]
                )

                candle_close = float(
                    close.iloc[i]
                )

                near_boundary = (
                    abs(
                        candle_low
                        - upper_boundary
                    )
                    <= atr_value * 0.30
                )

                held = (
                    candle_close
                    >= upper_boundary
                    - atr_value * 0.10
                )

                if (
                    near_boundary
                    and held
                ):

                    result[
                        "bullish_retest"
                    ] = True

        if bearish_breakout:

            for i in range(
                retest_start,
                last_closed
            ):

                candle_high = float(
                    high.iloc[i]
                )

                candle_close = float(
                    close.iloc[i]
                )

                near_boundary = (
                    abs(
                        candle_high
                        - lower_boundary
                    )
                    <= atr_value * 0.30
                )

                held = (
                    candle_close
                    <= lower_boundary
                    + atr_value * 0.10
                )

                if (
                    near_boundary
                    and held
                ):

                    result[
                        "bearish_retest"
                    ] = True

        return result

    except Exception as e:

        print(
            f"Triangle detection error: {e}"
        )

        return result


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

        tr1 = current_high - current_low
        tr2 = abs(
            current_high - previous_close
        )
        tr3 = abs(
            current_low - previous_close
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
            rsi_value > 100 - GAINZ_V2_RSI
        )

        close_delta = float(
            close.iloc[
                i - GAINZ_V2_DELTA
            ]
        )

        price_decrease = (
            current_close < close_delta
        )

        price_increase = (
            current_close > close_delta
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

        tr1 = current_high - current_low
        tr2 = abs(
            current_high - previous_close
        )
        tr3 = abs(
            current_low - previous_close
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
            rsi_value > 100 - GAINZ_PRO_RSI
        )

        close_delta = float(
            close.iloc[
                i - GAINZ_PRO_DELTA
            ]
        )

        price_decrease = (
            current_close < close_delta
        )

        price_increase = (
            current_close > close_delta
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
# HFT / MICROSTRUCTURE ADAPTER
# ============================================================

def run_hft_engine(
    symbol,
    name,
    m5,
    m15,
    h1,
    signal,
    price,
    atr_value,
    volume_confirmed,
    adx_value
):

    result = {
        "available": False,
        "confirmed": False,
        "score": 0,
        "direction": "NEUTRAL",
        "reason": "HFT unavailable"
    }

    if not HFT_ENABLED:

        result["reason"] = "HFT disabled"

        return result

    if not HFT_ENGINE_AVAILABLE:

        result["reason"] = "hft_engine.py not loaded"

        return result

    try:

        functions = [
            "analyze_hft",
            "get_hft_signal",
            "analyze",
            "get_signal",
            "run_hft",
            "run"
        ]

        target = None

        for function_name in functions:

            candidate = getattr(
                hft_engine,
                function_name,
                None
            )

            if callable(candidate):

                target = candidate
                break

        if target is None:

            result["reason"] = (
                "No supported HFT function found"
            )

            print(
                f"{name}: "
                f"HFT module loaded but "
                f"no supported function found"
            )

            return result

        context = {
            "symbol": symbol,
            "name": name,
            "m5": m5,
            "m15": m15,
            "h1": h1,
            "signal": signal,
            "price": price,
            "atr": atr_value,
            "atr_value": atr_value,
            "volume_confirmed": volume_confirmed,
            "adx": adx_value,
            "adx_value": adx_value
        }

        # ----------------------------------------------------
        # Try intelligent argument matching
        # ----------------------------------------------------

        try:

            signature = inspect.signature(target)

            parameters = signature.parameters

            kwargs = {}

            for parameter_name in parameters:

                if parameter_name in context:

                    kwargs[
                        parameter_name
                    ] = context[
                        parameter_name
                    ]

            if kwargs:

                raw_result = target(
                    **kwargs
                )

            else:

                raw_result = target(
                    context
                )

        except Exception:

            try:

                raw_result = target(
                    context
                )

            except Exception:

                raw_result = target()

        # ----------------------------------------------------
        # Normalize result
        # ----------------------------------------------------

        result["available"] = True

        if isinstance(
            raw_result,
            dict
        ):

            raw_score = (
                raw_result.get(
                    "score",
                    raw_result.get(
                        "hft_score",
                        0
                    )
                )
            )

            try:

                raw_score = float(
                    raw_score
                )

            except Exception:

                raw_score = 0

            result["score"] = int(
                max(
                    0,
                    min(
                        100,
                        raw_score
                    )
                )
            )

            direction = str(
                raw_result.get(
                    "direction",
                    raw_result.get(
                        "signal",
                        "NEUTRAL"
                    )
                )
            ).upper()

            if "BUY" in direction:

                result["direction"] = "BUY"

            elif "SELL" in direction:

                result["direction"] = "SELL"

            else:

                result["direction"] = "NEUTRAL"

            confirmed = raw_result.get(
                "confirmed",
                raw_result.get(
                    "confirmation",
                    None
                )
            )

            if confirmed is None:

                result["confirmed"] = (
                    result["score"]
                    >= HFT_MIN_SCORE
                    and (
                        (
                            signal == "🟢 BUY"
                            and result["direction"] == "BUY"
                        )
                        or
                        (
                            signal == "🔴 SELL"
                            and result["direction"] == "SELL"
                        )
                    )
                )

            else:

                result["confirmed"] = bool(
                    confirmed
                )

            result["reason"] = str(
                raw_result.get(
                    "reason",
                    "HFT analysis completed"
                )
            )

        elif isinstance(
            raw_result,
            (int, float)
        ):

            result["score"] = int(
                max(
                    0,
                    min(
                        100,
                        float(raw_result)
                    )
                )
            )

            result["confirmed"] = (
                result["score"]
                >= HFT_MIN_SCORE
            )

            result["reason"] = (
                "Numeric HFT score"
            )

        elif isinstance(
            raw_result,
            str
        ):

            direction = raw_result.upper()

            if "BUY" in direction:

                result["direction"] = "BUY"

            elif "SELL" in direction:

                result["direction"] = "SELL"

            result["confirmed"] = (
                (
                    signal == "🟢 BUY"
                    and result["direction"] == "BUY"
                )
                or
                (
                    signal == "🔴 SELL"
                    and result["direction"] == "SELL"
                )
            )

            result["score"] = (
                HFT_MIN_SCORE
                if result["confirmed"]
                else 0
            )

            result["reason"] = (
                "Text HFT result"
            )

        else:

            result["reason"] = (
                "Unknown HFT result type"
            )

        # ----------------------------------------------------
        # Direction safety
        # ----------------------------------------------------

        if signal == "🟢 BUY":

            if result["direction"] == "SELL":

                result["confirmed"] = False

        elif signal == "🔴 SELL":

            if result["direction"] == "BUY":

                result["confirmed"] = False

        print(
            f"{name}: "
            f"HFT available="
            f"{result['available']} "
            f"score="
            f"{result['score']} "
            f"direction="
            f"{result['direction']} "
            f"confirmed="
            f"{result['confirmed']}"
        )

        return result

    except Exception as e:

        print(
            f"{name}: "
            f"HFT execution error: {e}"
        )

        result["reason"] = (
            f"HFT error: {e}"
        )

        return result


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

            return False, "Invalid price values"

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

            return False, "Invalid signal"

        if not valid:

            return False, "Invalid TP/SL structure"

        risk = abs(
            price - stop_loss
        )

        reward = abs(
            tp3 - price
        )

        if risk <= 0:

            return False, "Zero risk"

        rr = reward / risk

        if rr < 1.20:

            return False, (
                f"Risk/Reward too low ({rr:.2f})"
            )

        return True, (
            f"Valid TP/SL R:R={rr:.2f}"
        )

    except Exception as e:

        return False, (
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
    gainz_pro_confirmed=False,
    triangle_breakout=False,
    triangle_volume=False,
    triangle_retest=False,
    triangle_m15_confirmation=False,
    triangle_h1_alignment=False,
    hft_confirmed=False
):

    score = 0

    buy = signal == "🟢 BUY"
    sell = signal == "🔴 SELL"

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

    # ========================================================
    # SMART MONEY
    # ========================================================

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

    # ========================================================
    # GAINZALGO
    # ========================================================

    if gainz_v2_confirmed:
        score += GAINZ_V2_BONUS

    if gainz_pro_confirmed:
        score += GAINZ_PRO_BONUS

    # ========================================================
    # CRYPTO TRIANGLE
    # ========================================================

    if triangle_breakout:
        score += 5

    if triangle_volume:
        score += 5

    if triangle_retest:
        score += 5

    if triangle_m15_confirmation:
        score += 5

    if triangle_h1_alignment:
        score += 5

    # ========================================================
    # HFT / MICROSTRUCTURE
    # ========================================================

    if hft_confirmed:
        score += HFT_BONUS

    return max(
        0,
        min(
            100,
            int(score)
        )
    )


# ============================================================
# MASTER V3.2 HARD FILTER
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
    crypto=False
):

    if signal not in [
        "🟢 BUY",
        "🔴 SELL"
    ]:

        return False, "No clear signal"

    if ai_score < MIN_AI_SCORE:

        return False, (
            f"AI Score below {MIN_AI_SCORE}"
        )

    if quality_score < MIN_QUALITY_SCORE:

        return False, (
            f"Quality below {MIN_QUALITY_SCORE}"
        )

    if entry_quality != "A":

        return False, (
            f"Entry Quality {entry_quality}"
        )

    required_adx = (
        MIN_CRYPTO_ADX
        if crypto
        else MIN_ADX
    )

    if adx_value < required_adx:

        return False, (
            f"ADX below {required_adx}"
        )

    # Gold / Forex volume = HARD
    # Crypto volume = SOFT

    if not crypto:

        if not volume_confirmed:

            return False, (
                "Volume confirmation missing"
            )

    if not trend_aligned:

        return False, (
            "M5/M15/H1 trend conflict"
        )

    if not rsi_valid:

        return False, (
            "RSI not valid"
        )

    if news_risk == "HIGH":

        if not crypto:

            return False, (
                "HIGH news risk"
            )

    if not tp_sl_valid:

        return False, (
            "Invalid TP/SL"
        )

    return True, (
        "ALL MASTER V3.2 HARD FILTERS PASSED"
    )


# ============================================================
# MARKET ANALYSIS
# ============================================================

def analyze_market(symbol, name):

    try:

        print(
            f"\n{'=' * 60}\n"
            f"Analyzing {name}\n"
            f"{'=' * 60}"
        )

        crypto = is_crypto_market(symbol)

        # ====================================================
        # WEEKEND
        # ====================================================

        if (
            is_weekend()
            and not crypto
        ):

            print(
                f"{name}: "
                f"Weekend - Gold/Forex skipped"
            )

            return None

        # ====================================================
        # NEWS
        # ====================================================

        try:

            news = check_news() or {
                "risk": "HIGH"
            }

            raw_news_risk = str(
                news.get(
                    "risk",
                    "HIGH"
                )
            ).upper()

        except Exception as e:

            print(
                f"{name}: News error: {e}"
            )

            raw_news_risk = "HIGH"

        if crypto:

            if raw_news_risk == "HIGH":

                print(
                    f"{name}: "
                    f"Global news risk HIGH "
                    f"-> Crypto treated as MEDIUM"
                )

                news_risk = "MEDIUM"

            else:

                news_risk = raw_news_risk

        else:

            news_risk = raw_news_risk

        print(
            f"{name}: "
            f"Effective News Risk = "
            f"{news_risk}"
        )

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

        if (
            m5 is None
            or m15 is None
            or h1 is None
        ):

            print(
                f"{name}: Missing timeframe data"
            )

            return None

        # ====================================================
        # DXY
        # ====================================================

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
        # INITIAL LIVE PRICE
        # ====================================================

        price = get_final_live_price(
            symbol
        )

        if (
            price is None
            or not is_valid_number(price)
        ):

            print(
                f"{name}: "
                f"NO INITIAL LIVE PRICE "
                f"-> SIGNAL REJECTED"
            )

            return None

        print(
            f"{name}: "
            f"Initial LIVE price = {price}"
        )

        # ====================================================
        # SUPPORT / RESISTANCE
        # ====================================================

        sr = find_support_resistance(
            close
        )

        if not sr:

            print(
                f"{name}: "
                f"Support/Resistance unavailable"
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

        atr = ta.volatility.average_true_range(
            high,
            low,
            close,
            14
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

        gainz_pro = detect_gainzalgo_pro(
            open_price,
            close,
            high,
            low,
            r
        )

        gainz_v2_buy = gainz_v2["buy"]
        gainz_v2_sell = gainz_v2["sell"]

        gainz_pro_buy = gainz_pro["buy"]
        gainz_pro_sell = gainz_pro["sell"]

        print(
            f"{name}: "
            f"Gainz V2 BUY={gainz_v2_buy} "
            f"SELL={gainz_v2_sell}"
        )

        print(
            f"{name}: "
            f"Gainz Pro BUY={gainz_pro_buy} "
            f"SELL={gainz_pro_sell}"
        )

        # ====================================================
        # TREND
        # ====================================================

        ema_bullish = e50 > e200
        macd_bullish = m > ms

        # ====================================================
        # M15 TREND
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
        # H1 TREND
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
            float(window.mean())
            if len(window)
            else 0.0
        )

        volume_confirmed = (
            avg_volume > 0
            and current_volume
            >= avg_volume * 1.05
        )

        print(
            f"{name}: "
            f"Volume confirmation="
            f"{volume_confirmed} "
            f"({'SOFT' if crypto else 'HARD'})"
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
            close,
            high,
            low,
            atr_value
        )

        # ====================================================
        # CRYPTO TRIANGLE
        # ====================================================

        triangle = {
            "detected": False,
            "bullish_breakout": False,
            "bearish_breakout": False,
            "bullish_retest": False,
            "bearish_retest": False,
            "upper_boundary": None,
            "lower_boundary": None
        }

        triangle_m15 = {
            "detected": False,
            "bullish_breakout": False,
            "bearish_breakout": False,
            "bullish_retest": False,
            "bearish_retest": False,
            "upper_boundary": None,
            "lower_boundary": None
        }

        if crypto:

            triangle = detect_symmetric_triangle(
                close,
                high,
                low,
                atr_value
            )

            m15_atr = ta.volatility.average_true_range(
                m15["high"],
                m15["low"],
                m15["close"],
                14
            )

            m15_atr_value = safe_float(
                m15_atr,
                -2
            )

            if (
                m15_atr_value is not None
                and m15_atr_value > 0
            ):

                triangle_m15 = (
                    detect_symmetric_triangle(
                        m15["close"],
                        m15["high"],
                        m15["low"],
                        m15_atr_value
                    )
                )

            print(
                f"{name}: "
                f"Triangle detected="
                f"{triangle['detected']}"
            )

            print(
                f"{name}: "
                f"Triangle BUY breakout="
                f"{triangle['bullish_breakout']} "
                f"SELL breakdown="
                f"{triangle['bearish_breakout']}"
            )

            print(
                f"{name}: "
                f"Triangle BUY retest="
                f"{triangle['bullish_retest']} "
                f"SELL retest="
                f"{triangle['bearish_retest']}"
            )

            print(
                f"{name}: "
                f"M15 Triangle BUY="
                f"{triangle_m15['bullish_breakout']} "
                f"SELL="
                f"{triangle_m15['bearish_breakout']}"
            )

        # ====================================================
        # BUY / SELL SCORE
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

        if 45 < r < 70:
            buy_score += 10

        if 30 < r < 55:
            sell_score += 10

        # Crypto and Forex use their own ADX hard thresholds later.
        if crypto:

            if adx_value >= MIN_CRYPTO_ADX:
                buy_score += 10
                sell_score += 10

        else:

            if adx_value >= MIN_ADX:
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
        # CRYPTO TRIANGLE SCORE
        # SOFT ONLY
        # ====================================================

        if crypto:

            if triangle["bullish_breakout"]:
                buy_score += 5

            if (
                triangle["bullish_breakout"]
                and volume_confirmed
            ):
                buy_score += 5

            if triangle["bullish_retest"]:
                buy_score += 5

            if (
                triangle_m15["bullish_breakout"]
                or triangle_m15["bullish_retest"]
            ):
                buy_score += 5

            if (
                triangle["bullish_breakout"]
                and h1_bullish
            ):
                buy_score += 5

            if triangle["bearish_breakout"]:
                sell_score += 5

            if (
                triangle["bearish_breakout"]
                and volume_confirmed
            ):
                sell_score += 5

            if triangle["bearish_retest"]:
                sell_score += 5

            if (
                triangle_m15["bearish_breakout"]
                or triangle_m15["bearish_retest"]
            ):
                sell_score += 5

            if (
                triangle["bearish_breakout"]
                and not h1_bullish
            ):
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
        # TRIANGLE CONFIRMATION VARIABLES
        # ====================================================

        if crypto:

            if signal == "🟢 BUY":

                triangle_breakout = (
                    triangle["bullish_breakout"]
                )

                triangle_volume = (
                    triangle_breakout
                    and volume_confirmed
                )

                triangle_retest = (
                    triangle["bullish_retest"]
                )

                triangle_m15_confirmation = (
                    triangle_m15[
                        "bullish_breakout"
                    ]
                    or
                    triangle_m15[
                        "bullish_retest"
                    ]
                )

                triangle_h1_alignment = (
                    h1_bullish
                )

            else:

                triangle_breakout = (
                    triangle["bearish_breakout"]
                )

                triangle_volume = (
                    triangle_breakout
                    and volume_confirmed
                )

                triangle_retest = (
                    triangle["bearish_retest"]
                )

                triangle_m15_confirmation = (
                    triangle_m15[
                        "bearish_breakout"
                    ]
                    or
                    triangle_m15[
                        "bearish_retest"
                    ]
                )

                triangle_h1_alignment = (
                    not h1_bullish
                )

        else:

            triangle_breakout = False
            triangle_volume = False
            triangle_retest = False
            triangle_m15_confirmation = False
            triangle_h1_alignment = False

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
            preliminary,
            triangle_breakout=triangle_breakout,
            breakout_volume=triangle_volume,
            successful_retest=triangle_retest,
            m15_confirmation=triangle_m15_confirmation,
            h1_trend_alignment=triangle_h1_alignment
        )

        if not entry:

            print(
                f"{name}: Entry rejected"
            )

            return None

        entry_quality = entry.get(
            "quality",
            "C"
        )

        # ====================================================
        # RSI
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
        # HFT / MICROSTRUCTURE
        #
        # Run after the directional candidate exists.
        # HFT does NOT override the trend.
        # ====================================================

        hft = run_hft_engine(
            symbol=symbol,
            name=name,
            m5=m5,
            m15=m15,
            h1=h1,
            signal=signal,
            price=price,
            atr_value=atr_value,
            volume_confirmed=volume_confirmed,
            adx_value=adx_value
        )

        hft_confirmed = (
            hft["confirmed"]
        )

        hft_score = (
            hft["score"]
        )

        print(
            f"{name}: "
            f"HFT Score={hft_score}/100 "
            f"Confirmed={hft_confirmed} "
            f"Direction={hft['direction']}"
        )

        # ====================================================
        # OPTIONAL HFT HARD GATE
        #
        # Default OFF.
        # ====================================================

        if HFT_HARD_GATE:

            if (
                HFT_ENABLED
                and hft["available"]
                and not hft_confirmed
            ):

                print(
                    f"{name}: "
                    f"HFT HARD GATE rejected signal"
                )

                return None

        # ====================================================
        # TP / SL
        # ====================================================

        if symbol == "GC=F":

            sl_mult = 2.0
            tp_mult = 3.0

        elif crypto:

            sl_mult = 3.0
            tp_mult = 5.0

        else:

            sl_mult = 2.0
            tp_mult = 3.0

        # ====================================================
        # INITIAL TP / SL
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
            smart_decision = "Unavailable"

        # ====================================================
        # QUALITY
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
            gainz_pro_confirmed,
            triangle_breakout,
            triangle_volume,
            triangle_retest,
            triangle_m15_confirmation,
            triangle_h1_alignment,
            hft_confirmed
        )

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

        print(
            f"{name}: "
            f"Preliminary={preliminary} "
            f"Smart={smart_score} "
            f"Quality={quality_score} "
            f"HFT={hft_score} "
            f"Final AI={final_ai_score}"
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

        # ====================================================
        # NO TRADE RESULT
        # ====================================================

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
        # MASTER V3.2 HARD FILTER
        # ====================================================

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
                crypto=crypto
            )
        )

        if not passed:

            print(
                f"\n{name}: V3.2 REJECTED"
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
                f"Smart Decision: "
                f"{smart_decision}"
            )

            print(
                f"HFT Score: "
                f"{hft_score}/100"
            )

            print(
                f"HFT Confirmed: "
                f"{hft_confirmed}"
            )

            print(
                f"HFT Direction: "
                f"{hft['direction']}"
            )

            print(
                f"ADX: "
                f"{adx_value:.2f}"
            )

            if crypto:

                print(
                    f"Required Crypto ADX: "
                    f"{MIN_CRYPTO_ADX}"
                )

            else:

                print(
                    f"Required ADX: "
                    f"{MIN_ADX}"
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
                f"Volume Policy: "
                f"{'SOFT' if crypto else 'HARD'}"
            )

            print(
                f"News Risk: "
                f"{news_risk}"
            )

            print(
                f"Gainz V2: "
                f"{gainz_v2_confirmed}"
            )

            print(
                f"Gainz Pro: "
                f"{gainz_pro_confirmed}"
            )

            if crypto:

                print(
                    f"Triangle Breakout: "
                    f"{triangle_breakout}"
                )

                print(
                    f"Triangle Volume: "
                    f"{triangle_volume}"
                )

                print(
                    f"Triangle Retest: "
                    f"{triangle_retest}"
                )

                print(
                    f"Triangle M15: "
                    f"{triangle_m15_confirmation}"
                )

                print(
                    f"Triangle H1: "
                    f"{triangle_h1_alignment}"
                )

            print(
                f"Reason: "
                f"{reason}"
            )

            return None

        # ====================================================
        # FINAL LIVE PRICE REFRESH
        # ====================================================

        old_price = price

        final_live_price = get_final_live_price(
            symbol
        )

        if (
            final_live_price is None
            or not is_valid_number(
                final_live_price
            )
        ):

            print(
                f"{name}: "
                f"FINAL LIVE PRICE unavailable "
                f"-> SIGNAL NOT SENT"
            )

            return None

        price = float(
            final_live_price
        )

        print(
            f"{name}: "
            f"FINAL PRICE REFRESH "
            f"{old_price} -> {price}"
        )

        # ====================================================
        # REBUILD TP / SL FROM FINAL LIVE PRICE
        # ====================================================

        if filtered_signal == "🟢 BUY":

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

        # ====================================================
        # FINAL TP / SL VALIDATION
        # ====================================================

        final_live_valid, final_live_reason = (
            validate_trade_levels(
                filtered_signal,
                price,
                stop_loss,
                tp1,
                tp2,
                tp3
            )
        )

        if not final_live_valid:

            print(
                f"{name}: "
                f"FINAL LIVE TP/SL REJECTED - "
                f"{final_live_reason}"
            )

            return None

        print(
            f"{name}: "
            f"FINAL LIVE TRADE PRICE = "
            f"{price}"
        )

        print(
            f"{name}: "
            f"FINAL SL = "
            f"{stop_loss}"
        )

        print(
            f"{name}: "
            f"FINAL TP1 = "
            f"{tp1}"
        )

        print(
            f"{name}: "
            f"FINAL TP2 = "
            f"{tp2}"
        )

        print(
            f"{name}: "
            f"FINAL TP3 = "
            f"{tp3}"
        )

        # ====================================================
        # DUPLICATE FILTER
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
        # TELEGRAM
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

        if direction == "BUY":

            direction_display = "🔵 BUY"

        else:

            direction_display = "🔴 SELL"

        return (
            f"📊 <b>{name}</b> "
            f"{direction_display} NOW {p(price)}\n\n"
            f"⚠️ Stop Loss (SL): {p(stop_loss)}\n"
            f"🎯 TP1: {p(tp1)}\n"
            f"🎯 TP2: {p(tp2)}\n"
            f"🎯 TP3: {p(tp3)}"
        )

    except Exception as e:

        print(
            f"{name}: "
            f"Fatal analysis error: {e}"
        )

        return None


# ============================================================
# MAIN
# ============================================================

async def main():

    print(
        "\n"
        "====================================================\n"
        "QuantumGold AI MASTER FILTER V3.2\n"
        "+ MICROSTRUCTURE / HFT\n"
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
        "Markets: Gold + Forex + Crypto"
    )

    print(
        "Crypto: BTC / ETH / SOL / BNB"
    )

    print(
        "Triangle Breakout: "
        "ENABLED FOR ALL CRYPTO"
    )

    print(
        "Triangle Mode: "
        "SOFT CONFIRMATION"
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
        f"HFT Engine: "
        f"{'ENABLED' if HFT_ENABLED else 'DISABLED'}"
    )

    print(
        f"HFT Module: "
        f"{'LOADED' if HFT_ENGINE_AVAILABLE else 'NOT LOADED'}"
    )

    print(
        f"HFT Hard Gate: "
        f"{'ON' if HFT_HARD_GATE else 'OFF'}"
    )

    print(
        f"HFT Bonus: "
        f"+{HFT_BONUS}"
    )

    print(
        "Crypto signal delivery: "
        "ENABLED"
    )

    print(
        "LIVE PRICE MODE: "
        "ENABLED"
    )

    print(
        "Final LIVE PRICE refresh: "
        "ENABLED"
    )

    print(
        "Old candle price fallback: "
        "DISABLED"
    )

    print(
        "Daily Report: "
        "DISABLED"
    )

    print(
        "News Policy:"
    )

    print(
        "Gold + Forex: "
        "HIGH NEWS = HARD REJECT"
    )

    print(
        "Crypto: "
        "HIGH NEWS = SOFT RISK"
    )

    # ========================================================
    # WEEKEND STATUS
    # ========================================================

    if is_weekend():

        print(
            "Weekend:"
        )

        print(
            "Gold + Forex: DISABLED"
        )

        print(
            "Crypto: ENABLED 24/7"
        )

    else:

        print(
            "Weekday:"
        )

        print(
            "Gold + Forex: ENABLED"
        )

        print(
            "Crypto: ENABLED 24/7"
        )

    # ========================================================
    # TELEGRAM
    # ========================================================

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

    # ========================================================
    # MARKETS TO SCAN
    # ========================================================

    markets_to_scan = list(
        MARKETS
    )

    if CRYPTO_ENABLED:

        markets_to_scan.extend(
            CRYPTO_MARKETS
        )

    # ========================================================
    # SCAN
    # ========================================================

    for symbol, name in markets_to_scan:

        try:

            result = analyze_market(
                symbol,
                name
            )

            if result:

                try:

                    await bot.send_message(
                        chat_id=CHAT_ID,
                        text=result,
                        parse_mode="HTML"
                    )

                    print(
                        f"{name}: "
                        f"Signal sent"
                    )

                except Exception as e:

                    print(
                        f"{name}: "
                        f"Telegram error: {e}"
                    )

        except Exception as e:

            print(
                f"{name}: "
                f"Unexpected analysis error: "
                f"{e}"
            )


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":

    asyncio.run(main())
