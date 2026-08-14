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
# MASTER FILTER V3
#
# GainzAlgo V2 Essential + GainzAlgo Pro integrated
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

# GainzAlgo V2 Essential
GAINZ_V2_STABILITY = 0.50
GAINZ_V2_RSI = 70
GAINZ_V2_DELTA = 4

# GainzAlgo Pro
GAINZ_PRO_STABILITY = 0.50
GAINZ_PRO_RSI = 50
GAINZ_PRO_DELTA = 5

# Soft confirmation bonuses
GAINZ_V2_BONUS = 10
GAINZ_PRO_BONUS = 10


# ============================================================
# MARKETS
# ============================================================

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

# Future crypto support
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
        return math.isfinite(value) and value > 0
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
    return f"{float(value):.{get_price_decimals(symbol)}f}"


def is_weekend():
    """
    UTC Saturday/Sunday.
    """
    return datetime.datetime.utcnow().weekday() in [5, 6]


def safe_float(series, index=-1):

    try:

        value = float(series.iloc[index])

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
            f"Downloading {symbol} {interval} data..."
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

        # ----------------------------------------------------
        # Flatten MultiIndex columns
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

        # ----------------------------------------------------
        # Required columns
        # ----------------------------------------------------

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
                f"{symbol}: insufficient data "
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
            open_price = open_price.iloc[:, 0]

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

        open_price = open_price.dropna()
        close = close.dropna()
        high = high.dropna()
        low = low.dropna()
        volume = volume.fillna(0)

        if len(close) < 220:

            print(
                f"{symbol}: insufficient prepared "
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

        if i < 2 or atr_value <= 0:

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
    close,
    high,
    low,
    atr_value
):

    try:

        i = len(close) - 2

        if i < 1 or atr_value <= 0:

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
# GAINZALGO V2 ESSENTIAL
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

        previous_close_for_tr = (
            previous_close
        )

        tr1 = (
            current_high
            - current_low
        )

        tr2 = abs(
            current_high
            - previous_close_for_tr
        )

        tr3 = abs(
            current_low
            - previous_close_for_tr
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

        # ----------------------------------------------------
        # Pine ta.tr equivalent
        # ----------------------------------------------------

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

        # ----------------------------------------------------
        # Candle Stability
        # ----------------------------------------------------

        stable_candle = (
            abs(
                current_close
                - current_open
            ) / true_range
            > GAINZ_PRO_STABILITY
        )

        # ----------------------------------------------------
        # Bullish Engulfing
        # ----------------------------------------------------

        bullish_engulfing = (
            previous_close < previous_open
            and current_close > current_open
            and current_close > previous_open
        )

        # ----------------------------------------------------
        # Bearish Engulfing
        # ----------------------------------------------------

        bearish_engulfing = (
            previous_close > previous_open
            and current_close < current_open
            and current_close < previous_open
        )

        # ----------------------------------------------------
        # RSI
        #
        # Pro default:
        # BUY RSI < 50
        # SELL RSI > 50
        # ----------------------------------------------------

        rsi_buy = (
            rsi_value < GAINZ_PRO_RSI
        )

        rsi_sell = (
            rsi_value
            > 100 - GAINZ_PRO_RSI
        )

        # ----------------------------------------------------
        # Candle Delta
        # ----------------------------------------------------

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

        # ----------------------------------------------------
        # Final Pro BUY
        # ----------------------------------------------------

        gainz_buy = (
            bullish_engulfing
            and stable_candle
            and rsi_buy
            and price_decrease
        )

        # ----------------------------------------------------
        # Final Pro SELL
        # ----------------------------------------------------

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

    buy = signal == "🟢 BUY"
    sell = signal == "🔴 SELL"

    # --------------------------------------------------------
    # CORE TREND
    # --------------------------------------------------------

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
    # NEWS
    # --------------------------------------------------------

    if news_risk == "HIGH":

        score -= 20

    elif news_risk == "MEDIUM":

        score += 5

    else:

        score += 10

    # --------------------------------------------------------
    # ENTRY QUALITY
    # --------------------------------------------------------

    if entry_quality == "A":

        score += 10

    elif entry_quality == "B":

        score += 5

    else:

        score -= 10

    # ========================================================
    # SMART MONEY BONUS
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
    # GAINZALGO V2
    # ========================================================

    if gainz_v2_confirmed:

        score += GAINZ_V2_BONUS

    # ========================================================
    # GAINZALGO PRO
    # ========================================================

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

    # --------------------------------------------------------
    # AI
    # --------------------------------------------------------

    if ai_score < MIN_AI_SCORE:

        return (
            False,
            f"AI Score below {MIN_AI_SCORE}"
        )

    # --------------------------------------------------------
    # QUALITY
    # --------------------------------------------------------

    if quality_score < MIN_QUALITY_SCORE:

        return (
            False,
            f"Quality below {MIN_QUALITY_SCORE}"
        )

    # --------------------------------------------------------
    # ENTRY
    # --------------------------------------------------------

    if entry_quality != "A":

        return (
            False,
            f"Entry Quality {entry_quality}"
        )

    # --------------------------------------------------------
    # ADX
    # --------------------------------------------------------

    if adx_value < MIN_ADX:

        return (
            False,
            f"ADX below {MIN_ADX}"
        )

    # --------------------------------------------------------
    # VOLUME
    # --------------------------------------------------------

    if not volume_confirmed:

        return (
            False,
            "Volume confirmation missing"
        )

    # --------------------------------------------------------
    # M5 / M15 / H1
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
    # NEWS
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

        # ----------------------------------------------------
        # WEEKEND
        # ----------------------------------------------------

        if is_weekend():

            print(
                f"{name}: Weekend - skipped"
            )

            return None

        # ----------------------------------------------------
        # NEWS
        # ----------------------------------------------------

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
                f"{name}: News error: {e}"
            )

            news_risk = "HIGH"

        # ----------------------------------------------------
        # MULTI TIMEFRAME DATA
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
                f"Missing timeframe data"
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

            price = get_live_gold_price()

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

        # ----------------------------------------------------
        # SUPPORT / RESISTANCE
        # ----------------------------------------------------

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
        # GAINZALGO V2
        # ====================================================

        gainz_v2 = detect_gainzalgo_v2(
            open_price,
            close,
            high,
            low,
            r
        )

        gainz_v2_buy = gainz_v2["buy"]
        gainz_v2_sell = gainz_v2["sell"]

        # ====================================================
        # GAINZALGO PRO
        # ====================================================

        gainz_pro = detect_gainzalgo_pro(
            open_price,
            close,
            high,
            low,
            r
        )

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
        # M5 TREND
        # ====================================================

        ema_bullish = (
            e50 > e200
        )

        macd_bullish = (
            m > ms
        )

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
        # SMART MONEY STRUCTURE
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
        # PRELIMINARY BUY / SELL SCORE
        # ====================================================

        buy_score = 0
        sell_score = 0

        # ----------------------------------------------------
        # EMA
        # ----------------------------------------------------

        if ema_bullish:

            buy_score += 20

        else:

            sell_score += 20

        # ----------------------------------------------------
        # MACD
        # ----------------------------------------------------

        if macd_bullish:

            buy_score += 20

        else:

            sell_score += 20

        # ----------------------------------------------------
        # M15
        # ----------------------------------------------------

        if m15_bullish:

            buy_score += 20

        else:

            sell_score += 20

        # ----------------------------------------------------
        # H1
        # ----------------------------------------------------

        if h1_bullish:

            buy_score += 20

        else:

            sell_score += 20

        # ----------------------------------------------------
        # RSI
        # ----------------------------------------------------

        if 45 < r < 70:

            buy_score += 10

        if 30 < r < 55:

            sell_score += 10

        # ----------------------------------------------------
        # ADX
        # ----------------------------------------------------

        if adx_value >= 25:

            buy_score += 10
            sell_score += 10

        # ====================================================
        # GAINZALGO V2 BONUS
        # ====================================================

        if gainz_v2_buy:

            buy_score += GAINZ_V2_BONUS

        if gainz_v2_sell:

            sell_score += GAINZ_V2_BONUS

        # ====================================================
        # GAINZALGO PRO BONUS
        # ====================================================

        if gainz_pro_buy:

            buy_score += GAINZ_PRO_BONUS

        if gainz_pro_sell:

            sell_score += GAINZ_PRO_BONUS

        # ====================================================
        # STRUCTURE BONUS
        # ====================================================

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

        # ====================================================
        # LIQUIDITY BONUS
        # ====================================================

        if liquidity["bullish"]:

            buy_score += 10

        if liquidity["bearish"]:

            sell_score += 10

        # ====================================================
        # DISPLACEMENT BONUS
        # ====================================================

        if displacement["bullish"]:

            buy_score += 5

        if displacement["bearish"]:

            sell_score += 5

        # ====================================================
        # FVG BONUS
        # ====================================================

        if fvg["bullish"]:

            buy_score += 5

        if fvg["bearish"]:

            sell_score += 5

        # ====================================================
        # SELECT DIRECTION
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

        # ====================================================
        # GAINZ FINAL DIRECTION STATUS
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
        # ENTRY FILTER
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
        # RSI HARD VALIDATION
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
        # FULL M5 / M15 / H1 ALIGNMENT
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
        # SMART MONEY CONFIRMATIONS
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
        # TP / SL
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

        # ====================================================
        # TP / SL VALIDATION
        # ====================================================

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
        # DXY CONFIRMATION FOR GOLD
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
        # QUALITY SCORE V3
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

        # ====================================================
        # FINAL AI SCORE
        #
        # Conservative:
        # weakest Smart/Quality determines final score.
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
                signal,
                final_ai_score,
                news_risk,
                entry_quality
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
                f"\n{name}: V3 REJECTED"
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

        # ====================================================
        # FINAL TP / SL CHECK
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
        # DUPLICATE SIGNAL PROTECTION
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
        # SAVE TRADE
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

        # ----------------------------------------------------
        # SMART MONEY STATUS
        # ----------------------------------------------------

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

        # ----------------------------------------------------
        # REASONS
        # ----------------------------------------------------

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

        reasons_text = "\n".join(
            f"✅ {x}"
            for x in reasons
        )

        # ====================================================
        # FINAL MESSAGE
        # ====================================================

        return f"""
📊 {name} {direction} NOW {p(price)}

⚠️ Stop Loss (SL): {p(stop_loss)}

🎯 TP1: {p(tp1)}
🎯 TP2: {p(tp2)}
🎯 TP3: {p(tp3)}

━━━━━━━━━━━━━━━━━━━━

🥇 QuantumGold AI Signal
MASTER FILTER V3

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

RSI:
{r:.2f}

MACD:
{m:.6f}

ATR:
{atr_value:.6f}

Volume:
{"CONFIRMED" if volume_confirmed else "LOW"}

━━━━━━━━━━━━━━━━━━━━

GAINZALGO CONFIRMATION

GainzAlgo V2 Essential:
{gainz_v2_status}

GainzAlgo Pro:
{gainz_pro_status}

V2 BUY:
{"YES" if gainz_v2_buy else "NO"}

V2 SELL:
{"YES" if gainz_v2_sell else "NO"}

Pro BUY:
{"YES" if gainz_pro_buy else "NO"}

Pro SELL:
{"YES" if gainz_pro_sell else "NO"}

━━━━━━━━━━━━━━━━━━━━

Smart Money Confluence

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

News Risk:
{news_risk}

Risk / Reward:
{level_reason}

Target Win Rate:
{TARGET_WIN_RATE}%
(design target, not guaranteed)

Support:
{p(support)}

Resistance:
{p(resistance)}

━━━━━━━━━━━━━━━━━━━━

Reasons:

{reasons_text}

━━━━━━━━━━━━━━━━━━━━

Timeframe:
M5 Entry
M15 Confirmation
H1 Major Trend

QuantumGold MASTER FILTER V3
"""


# ============================================================
# MAIN
# ============================================================

async def main():

    print(
        "\n"
        "====================================================\n"
        "QuantumGold AI MASTER FILTER V3\n"
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
        "Crypto signal delivery: "
        f"{'ENABLED' if CRYPTO_ENABLED else 'DISABLED'}"
    )

    # --------------------------------------------------------
    # WEEKEND
    # --------------------------------------------------------

    if is_weekend():

        print(
            "Weekend - "
            "no signals for any market"
        )

        return

    # --------------------------------------------------------
    # TELEGRAM CONFIG
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

    bot = Bot(
        token=TOKEN
    )

    messages = []

    # --------------------------------------------------------
    # MARKET LIST
    # --------------------------------------------------------

    markets_to_scan = list(
        MARKETS
    )

    if CRYPTO_ENABLED:

        markets_to_scan.extend(
            CRYPTO_MARKETS
        )

    # --------------------------------------------------------
    # ANALYZE MARKETS
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

            await bot.send_message(
                chat_id=CHAT_ID,
                text=(
                    "\n\n"
                    "━━━━━━━━━━━━━━━━━━━━"
                    "\n\n"
                ).join(messages)
            )

            print(
                "High quality "
                "MASTER V3 signals sent"
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

            await bot.send_message(
                chat_id=CHAT_ID,
                text=f"""
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
{"ENABLED" if CRYPTO_ENABLED else "DISABLED"}
"""
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
