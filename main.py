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
from trade_memory import (
    save_trade,
    get_trade_count,
    save_last_signal
)
from live_price import get_live_gold_price
from support_resistance import find_support_resistance
from entry_filter import check_entry
from smart_score import calculate_score
from no_trade_filter import apply_no_trade_filter


# =========================================================
# CONFIGURATION
# =========================================================

TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# STRICT QUALITY MODE
MIN_AI_SCORE = 80
MIN_QUALITY_SCORE = 80
MIN_ADX = 25

# Target only - NOT a guaranteed win rate
TARGET_WIN_RATE = 85


# =========================================================
# MARKETS
# =========================================================
# Gold + Forex + Crypto
# =========================================================

MARKETS = [

    # GOLD
    ("GC=F", "XAU/USD"),

    # FOREX
    ("EURUSD=X", "EUR/USD"),
    ("GBPUSD=X", "GBP/USD"),
    ("USDJPY=X", "USD/JPY"),
    ("USDCHF=X", "USD/CHF"),
    ("AUDUSD=X", "AUD/USD"),
    ("USDCAD=X", "USD/CAD"),
    ("NZDUSD=X", "NZD/USD"),

    # CRYPTO
    ("BTC-USD", "BTC/USD"),
    ("ETH-USD", "ETH/USD"),
    ("SOL-USD", "SOL/USD"),
    ("BNB-USD", "BNB/USD"),
]


# =========================================================
# HELPER
# =========================================================

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

    decimals = get_price_decimals(symbol)

    return f"{float(value):.{decimals}f}"


# =========================================================
# WEEKEND FILTER
# =========================================================

def is_weekend():

    now = datetime.datetime.utcnow()

    return now.weekday() in [5, 6]


# =========================================================
# DATA
# =========================================================
def get_data(symbol, interval="5m"):
    try:
        print(f"Downloading {symbol} {interval} data...")

        if interval == "5m":
            period = "7d"

        elif interval == "15m":
            period = "60d"

        elif interval == "1h":
            period = "730d"

        else:
            period = "60d"

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

        # Flatten MultiIndex
        if getattr(data.columns, "nlevels", 1) > 1:
            data.columns = [
                col[0] if isinstance(col, tuple) else col
                for col in data.columns
            ]

        required_columns = [
            "Close",
            "High",
            "Low",
            "Volume"
        ]

        missing = [
            col
            for col in required_columns
            if col not in data.columns
        ]

        if missing:
            print(
                f"{symbol}: missing columns "
                f"{missing}"
            )
            return None

        data = data.dropna(
            subset=[
                "Close",
                "High",
                "Low"
            ]
        )

        print(
            f"{symbol} {interval}: "
            f"{len(data)} candles received"
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

        close = data["Close"]
        high = data["High"]
        low = data["Low"]
        volume = data["Volume"]

        # yfinance MultiIndex protection
        if hasattr(close, "columns"):

            close = close.iloc[:, 0]

        if hasattr(high, "columns"):

            high = high.iloc[:, 0]

        if hasattr(low, "columns"):

            low = low.iloc[:, 0]

        if hasattr(volume, "columns"):

            volume = volume.iloc[:, 0]

        close = close.dropna()
        high = high.dropna()
        low = low.dropna()
        volume = volume.fillna(0)

        if len(close) < 220:

            print(
                f"{symbol}: insufficient data"
            )

            return None

        return {

            "close": close,
            "high": high,
            "low": low,
            "volume": volume

        }

    except Exception as e:

        print(
            f"Prepare data error {symbol}: {e}"
        )

        return None


# =========================================================
# TP / SL VALIDATION
# =========================================================

def validate_trade_levels(
    signal,
    price,
    stop_loss,
    tp1,
    tp2,
    tp3
):

    try:

        price = float(price)
        stop_loss = float(stop_loss)
        tp1 = float(tp1)
        tp2 = float(tp2)
        tp3 = float(tp3)

        if not all(
            is_valid_number(x)
            for x in [
                price,
                stop_loss,
                tp1,
                tp2,
                tp3
            ]
        ):

            return (
                False,
                "Invalid price values"
            )

        # =================================================
        # BUY
        # =================================================

        if signal == "🟢 BUY":

            valid = (
                stop_loss < price
                and tp1 > price
                and tp2 > tp1
                and tp3 > tp2
            )

            if not valid:

                return (
                    False,
                    "Invalid BUY TP/SL structure"
                )

        # =================================================
        # SELL
        # =================================================

        elif signal == "🔴 SELL":

            valid = (
                stop_loss > price
                and tp1 < price
                and tp2 < tp1
                and tp3 < tp2
            )

            if not valid:

                return (
                    False,
                    "Invalid SELL TP/SL structure"
                )

        else:

            return (
                False,
                "Invalid signal"
            )

        return (
            True,
            "Valid TP/SL"
        )

    except Exception as e:

        return (
            False,
            f"TP/SL validation error: {e}"
        )


# =========================================================
# QUALITY SCORE
# =========================================================

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
    entry_quality
):

    score = 0

    is_buy = (
        signal == "🟢 BUY"
    )

    is_sell = (
        signal == "🔴 SELL"
    )

    # =====================================================
    # EMA
    # =====================================================

    if (
        is_buy
        and ema_bullish
    ) or (
        is_sell
        and not ema_bullish
    ):

        score += 15

    # =====================================================
    # MACD
    # =====================================================

    if (
        is_buy
        and macd_bullish
    ) or (
        is_sell
        and not macd_bullish
    ):

        score += 15

    # =====================================================
    # M15
    # =====================================================

    if (
        is_buy
        and m15_bullish
    ) or (
        is_sell
        and not m15_bullish
    ):

        score += 10

    # =====================================================
    # H1
    # =====================================================

    if (
        is_buy
        and h1_bullish
    ) or (
        is_sell
        and not h1_bullish
    ):

        score += 10

    # =====================================================
    # ADX
    # =====================================================

    if adx_value >= 30:

        score += 15

    elif adx_value >= 25:

        score += 10

    elif adx_value >= 20:

        score += 5

    # =====================================================
    # VOLUME
    # =====================================================

    if volume_confirmed:

        score += 10

    # =====================================================
    # RSI
    # =====================================================

    if is_buy:

        if 45 < rsi_value < 70:

            score += 10

        elif 40 < rsi_value < 75:

            score += 5

    elif is_sell:

        if 30 < rsi_value < 55:

            score += 10

        elif 25 < rsi_value < 60:

            score += 5

    # =====================================================
    # NEWS
    # =====================================================

    if news_risk == "HIGH":

        score -= 20

    elif news_risk == "MEDIUM":

        score += 5

    else:

        score += 10

    # =====================================================
    # ENTRY
    # =====================================================

    if entry_quality == "A":

        score += 10

    elif entry_quality == "B":

        score += 5

    else:

        score -= 10

    # =====================================================
    # LIMIT
    # =====================================================

    score = max(
        0,
        min(
            100,
            int(score)
        )
    )

    return score


# =========================================================
# MASTER QUALITY FILTER
# =========================================================

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

    # =====================================================
    # SIGNAL
    # =====================================================

    if signal not in [
        "🟢 BUY",
        "🔴 SELL"
    ]:

        return (
            False,
            "No clear signal"
        )

    # =====================================================
    # AI SCORE
    # =====================================================

    if ai_score < MIN_AI_SCORE:

        return (
            False,
            f"AI Score below {MIN_AI_SCORE}"
        )

    # =====================================================
    # QUALITY
    # =====================================================

    if quality_score < MIN_QUALITY_SCORE:

        return (
            False,
            f"Quality below {MIN_QUALITY_SCORE}"
        )

    # =====================================================
    # ENTRY
    # =====================================================

    if entry_quality != "A":

        return (
            False,
            f"Entry Quality {entry_quality}"
        )

    # =====================================================
    # ADX
    # =====================================================

    if adx_value < MIN_ADX:

        return (
            False,
            f"ADX below {MIN_ADX}"
        )

    # =====================================================
    # VOLUME
    # =====================================================

    if not volume_confirmed:

        return (
            False,
            "Volume confirmation missing"
        )

    # =====================================================
    # TREND
    # =====================================================

    if not trend_aligned:

        return (
            False,
            "M5/M15/H1 trend conflict"
        )

    # =====================================================
    # RSI
    # =====================================================

    if not rsi_valid:

        return (
            False,
            "RSI not valid"
        )

    # =====================================================
    # NEWS
    # =====================================================

    if news_risk == "HIGH":

        return (
            False,
            "HIGH news risk"
        )

    # =====================================================
    # TP / SL
    # =====================================================

    if not tp_sl_valid:

        return (
            False,
            "Invalid TP/SL"
        )

    # =====================================================
    # ALL PASSED
    # =====================================================

    return (
        True,
        "ALL MASTER FILTERS PASSED"
    )


# =========================================================
# MARKET ANALYSIS
# =========================================================

def analyze_market(
    symbol,
    name
):

    try:

        print(
            f"Analyzing {name}..."
        )

        # =================================================
        # WEEKEND
        # =================================================

        if is_weekend():

            print(
                f"{name}: Weekend - no signal"
            )

            return None

        # =================================================
        # NEWS
        # =================================================

        news = check_news()

        if not news:

            news = {
                "risk": "HIGH",
                "message":
                "⚠️ News data unavailable"
            }

        news_risk = str(
            news.get(
                "risk",
                "HIGH"
            )
        ).upper()

        # =================================================
        # DATA
        # =================================================

        market_m5 = prepare_data(
            symbol,
            "5m"
        )

        market_m15 = prepare_data(
            symbol,
            "15m"
        )

        market_h1 = prepare_data(
            symbol,
            "1h"
        )

        if market_m5 is None:

            print(
                f"{name}: M5 data unavailable"
            )

            return None

        if market_m15 is None:

            print(
                f"{name}: M15 data unavailable"
            )

            return None

        if market_h1 is None:

            print(
                f"{name}: H1 data unavailable"
            )

            return None

        # =================================================
        # DXY
        # =================================================

        dxy = None

        if symbol == "GC=F":

            dxy = prepare_data(
                "DX-Y.NYB",
                "5m"
            )

        # =================================================
        # M5
        # =================================================

        close = market_m5["close"]
        high = market_m5["high"]
        low = market_m5["low"]
        volume = market_m5["volume"]

        # =================================================
        # PRICE
        # =================================================

        if symbol == "GC=F":

            live_price = (
                get_live_gold_price()
            )

        else:

            live_price = None

        if (
            live_price is not None
            and is_valid_number(
                live_price
            )
        ):

            price = float(
                live_price
            )

        else:

            price = float(
                close.iloc[-1]
            )

        if not is_valid_number(price):

            print(
                f"{name}: invalid price"
            )

            return None

        # =================================================
        # SUPPORT / RESISTANCE
        # =================================================

        sr = find_support_resistance(
            close
        )

        if not sr:

            print(
                f"{name}: S/R unavailable"
            )

            return None

        support = float(
            sr["support"]
        )

        resistance = float(
            sr["resistance"]
        )

        # =================================================
        # M5 INDICATORS
        # =================================================

        ema50 = ta.trend.ema_indicator(
            close,
            window=50
        )

        ema200 = ta.trend.ema_indicator(
            close,
            window=200
        )

        rsi = ta.momentum.rsi(
            close,
            window=14
        )

        macd = ta.trend.MACD(
            close
        )

        atr = (
            ta.volatility.average_true_range(
                high,
                low,
                close,
                window=14
            )
        )

        adx_indicator = (
            ta.trend.ADXIndicator(
                high,
                low,
                close,
                window=14
            )
        )

        # =================================================
        # VALUES
        # =================================================

        e50 = float(
            ema50.iloc[-1]
        )

        e200 = float(
            ema200.iloc[-1]
        )

        r = float(
            rsi.iloc[-1]
        )

        m = float(
            macd.macd().iloc[-1]
        )

        ms = float(
            macd.macd_signal().iloc[-1]
        )

        atr_value = float(
            atr.iloc[-1]
        )

        adx_value = float(
            adx_indicator.adx().iloc[-1]
        )

        if not all(
            math.isfinite(x)
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
                f"{name}: indicator data invalid"
            )

            return None

        # =================================================
        # M5 TREND
        # =================================================

        ema_bullish = (
            e50 > e200
        )

        macd_bullish = (
            m > ms
        )

        # =================================================
        # M15 TREND
        # =================================================

        close_m15 = (
            market_m15["close"]
        )

        ema50_m15 = (
            ta.trend.ema_indicator(
                close_m15,
                window=50
            )
        )

        ema200_m15 = (
            ta.trend.ema_indicator(
                close_m15,
                window=200
            )
        )

        m15_bullish = (
            float(
                ema50_m15.iloc[-1]
            )
            >
            float(
                ema200_m15.iloc[-1]
            )
        )

        # =================================================
        # H1 TREND
        # =================================================

        close_h1 = (
            market_h1["close"]
        )

        ema50_h1 = (
            ta.trend.ema_indicator(
                close_h1,
                window=50
            )
        )

        ema200_h1 = (
            ta.trend.ema_indicator(
                close_h1,
                window=200
            )
        )

        h1_bullish = (
            float(
                ema50_h1.iloc[-1]
            )
            >
            float(
                ema200_h1.iloc[-1]
            )
        )

        # =================================================
        # VOLUME
        # =================================================

        volume_clean = (
            volume.fillna(0)
        )

        avg_volume = float(
            volume_clean.tail(50).mean()
        )

        current_volume = float(
            volume_clean.iloc[-1]
        )

        volume_confirmed = (
            current_volume
            >
            avg_volume
        )

        # =================================================
        # DIRECTION SCORE
        # =================================================

        buy_score = 0
        sell_score = 0

        reasons = []

        # -------------------------------------------------
        # EMA
        # -------------------------------------------------

        if ema_bullish:

            buy_score += 20

            reasons.append(
                "✅ M5 EMA bullish"
            )

        else:

            sell_score += 20

            reasons.append(
                "✅ M5 EMA bearish"
            )

        # -------------------------------------------------
        # MACD
        # -------------------------------------------------

        if macd_bullish:

            buy_score += 20

            reasons.append(
                "✅ M5 MACD bullish"
            )

        else:

            sell_score += 20

            reasons.append(
                "✅ M5 MACD bearish"
            )

        # -------------------------------------------------
        # M15
        # -------------------------------------------------

        if m15_bullish:

            buy_score += 20

            reasons.append(
                "✅ M15 bullish"
            )

        else:

            sell_score += 20

            reasons.append(
                "✅ M15 bearish"
            )

        # -------------------------------------------------
        # H1
        # -------------------------------------------------

        if h1_bullish:

            buy_score += 20

            reasons.append(
                "✅ H1 bullish"
            )

        else:

            sell_score += 20

            reasons.append(
                "✅ H1 bearish"
            )

        # -------------------------------------------------
        # RSI
        # -------------------------------------------------

        if 45 < r < 70:

            buy_score += 10

        if 30 < r < 55:

            sell_score += 10

        # -------------------------------------------------
        # ADX
        # -------------------------------------------------

        if adx_value >= 25:

            buy_score += 10
            sell_score += 10

            reasons.append(
                "✅ ADX confirms trend"
            )

        else:

            reasons.append(
                "⚠️ ADX below 25"
            )

        # =================================================
        # SIGNAL
        # =================================================

        if buy_score >= 70 and buy_score > sell_score:

            signal = "🟢 BUY"

            preliminary_confidence = (
                buy_score
            )

        elif sell_score >= 70 and sell_score > buy_score:

            signal = "🔴 SELL"

            preliminary_confidence = (
                sell_score
            )

        else:

            print(
                f"{name}: No clear direction"
            )

            return None

        # =================================================
        # ENTRY QUALITY
        # =================================================

        entry = check_entry(
            signal,
            price,
            support,
            resistance,
            r,
            preliminary_confidence
        )

        if not entry:

            print(
                f"{name}: Entry filter failed"
            )

            return None

        entry_quality = entry.get(
            "quality",
            "C"
        )

        # =================================================
        # RSI VALIDATION
        # =================================================

        if signal == "🟢 BUY":

            rsi_valid = (
                45 < r < 70
            )

        else:

            rsi_valid = (
                30 < r < 55
            )

        # =================================================
        # TREND ALIGNMENT
        # =================================================

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

        # =================================================
        # SL / TP SETTINGS
        # =================================================

        if symbol == "GC=F":

            sl_multiplier = 2.0
            tp_multiplier = 3.0

        elif symbol == "BTC-USD":

            sl_multiplier = 3.0
            tp_multiplier = 5.0

        elif symbol in [
            "ETH-USD",
            "SOL-USD",
            "BNB-USD"
        ]:

            sl_multiplier = 3.0
            tp_multiplier = 5.0

        else:

            sl_multiplier = 2.0
            tp_multiplier = 3.0

        # =================================================
        # TP / SL
        # =================================================

        if signal == "🟢 BUY":

            stop_loss = (
                price
                -
                atr_value * sl_multiplier
            )

            tp1 = (
                price
                +
                atr_value
            )

            tp2 = (
                price
                +
                atr_value * 2
            )

            tp3 = (
                price
                +
                atr_value * tp_multiplier
            )

        else:

            stop_loss = (
                price
                +
                atr_value * sl_multiplier
            )

            tp1 = (
                price
                -
                atr_value
            )

            tp2 = (
                price
                -
                atr_value * 2
            )

            tp3 = (
                price
                -
                atr_value * tp_multiplier
            )

        # =================================================
        # TP / SL VALIDATION
        # =================================================

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

        # =================================================
        # GOLD / DXY
        # =================================================

        if (
            symbol == "GC=F"
            and dxy is not None
        ):

            dxy_close = (
                dxy["close"]
            )

            if len(dxy_close) >= 20:

                dxy_now = float(
                    dxy_close.iloc[-1]
                )

                dxy_old = float(
                    dxy_close.iloc[-20]
                )

                if (
                    signal == "🟢 BUY"
                    and dxy_now < dxy_old
                ):

                    reasons.append(
                        "✅ DXY supports Gold BUY"
                    )

                elif (
                    signal == "🔴 SELL"
                    and dxy_now > dxy_old
                ):

                    reasons.append(
                        "✅ DXY supports Gold SELL"
                    )

                else:

                    reasons.append(
                        "⚠️ DXY not confirming Gold"
                    )

        # =================================================
        # SMART SCORE
        # =================================================

        try:

            smart = calculate_score(
                name,
                signal,
                preliminary_confidence,
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
                f"{name}: Smart score error: {e}"
            )

            smart_score = 0

            smart_decision = (
                "Smart score unavailable"
            )

        # =================================================
        # QUALITY SCORE
        # =================================================

        quality_score = (
            calculate_quality_score(
                signal=signal,
                ema_bullish=ema_bullish,
                m15_bullish=m15_bullish,
                h1_bullish=h1_bullish,
                macd_bullish=macd_bullish,
                rsi_value=r,
                adx_value=adx_value,
                volume_confirmed=volume_confirmed,
                news_risk=news_risk,
                entry_quality=entry_quality
            )
        )

        # =================================================
        # FINAL AI SCORE
        # =================================================

        final_ai_score = min(
            smart_score,
            quality_score
        )

        final_ai_score = max(
            0,
            min(
                100,
                int(final_ai_score)
            )
        )

        confidence = (
            final_ai_score
        )

        # =================================================
        # OLD NO-TRADE FILTER
        # =================================================

        try:

            old_filter = (
                apply_no_trade_filter(
                    signal,
                    final_ai_score,
                    news_risk,
                    entry_quality
                )
            )

            filtered_signal = (
                old_filter.get(
                    "signal",
                    "⚪ WAIT"
                )
            )

            old_reason = (
                old_filter.get(
                    "reason",
                    ""
                )
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

        if filtered_signal not in [
            "🟢 BUY",
            "🔴 SELL"
        ]:

            print(
                f"{name}: "
                f"MASTER REJECTED - "
                f"{old_reason} | "
                f"AI={final_ai_score} "
                f"Quality={quality_score}"
            )

            return None

        # =================================================
        # MASTER QUALITY FILTER
        # =================================================

        master_passed, master_reason = (
            master_quality_filter(
                signal=filtered_signal,
                ai_score=final_ai_score,
                quality_score=quality_score,
                entry_quality=entry_quality,
                adx_value=adx_value,
                volume_confirmed=volume_confirmed,
                trend_aligned=trend_aligned,
                rsi_valid=rsi_valid,
                news_risk=news_risk,
                tp_sl_valid=valid_levels
            )
        )

        if not master_passed:

            print(
                f"{name}: "
                f"MASTER REJECTED - "
                f"{master_reason} | "
                f"AI={final_ai_score} "
                f"Quality={quality_score}"
            )

            return None

        # =================================================
        # FINAL TP / SL VALIDATION
        # =================================================

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
                f"MASTER REJECTED - "
                f"{final_level_reason}"
            )

            return None

        # =================================================
        # DUPLICATE SIGNAL FILTER
        # =================================================

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
                f"Duplicate signal blocked"
            )

            return None

        # =================================================
        # SAVE SIGNAL
        # =================================================

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

        # =================================================
        # REASONS
        # =================================================

        reasons.append(
            "✅ Master Quality Filter passed"
        )

        reasons.append(
            "✅ AI Score 80+"
        )

        reasons.append(
            "✅ Quality Score 80+"
        )

        reasons.append(
            "✅ Entry Quality A"
        )

        reasons.append(
            "✅ ADX 25+"
        )

        reasons.append(
            "✅ Volume confirmed"
        )

        reasons.append(
            "✅ M5/M15/H1 aligned"
        )

        reasons.append(
            "✅ RSI valid"
        )

        reasons_text = "\n".join(
            reasons
        )

        # =================================================
        # MESSAGE
        # =================================================

        direction = (
            "BUY"
            if filtered_signal == "🟢 BUY"
            else "SELL"
        )

        p = lambda x: format_price(
            x,
            symbol
        )

        message = f"""
📊 {name} {direction} NOW {p(price)}

⚠️ Stop Loss (SL): {p(stop_loss)}

🎯 TP1: {p(tp1)}
🎯 TP2: {p(tp2)}
🎯 TP3: {p(tp3)}

━━━━━━━━━━━━━━━━━━━━

🥇 QuantumGold AI Signal

{name}

Signal:
{filtered_signal}

Confidence:
{confidence}%

Live Price:
{p(price)}

Stop Loss:
{p(stop_loss)}

Take Profit:
{p(tp3)}

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
{master_reason}

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

News Risk:
{news_risk}

Target Win Rate:
{TARGET_WIN_RATE}%

Stored Signals:
{get_trade_count()}

Support:
{p(support)}

Resistance:
{p(resistance)}

━━━━━━━━━━━━━━━━━━━━

Reasons:

{reasons_text}

Timeframe:
M5 Entry
M15 Confirmation
H1 Major Trend
"""

        print(
            f"{name}: "
            f"MASTER PASSED | "
            f"{direction} | "
            f"AI={final_ai_score} | "
            f"Quality={quality_score}"
        )

        return message

    except Exception as e:

        print(
            f"Error analyzing {name}: {e}"
        )

        return None


# =========================================================
# MAIN
# =========================================================

async def main():

    print(
        "Starting QuantumGold AI "
        "STRICT 80+ MODE"
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
        f"Target Win Rate: "
        f"{TARGET_WIN_RATE}%"
    )

    print(
        "Markets: Gold + Forex + Crypto"
    )

    # =================================================
    # WEEKEND
    # =================================================

    if is_weekend():

        print(
            "Weekend - "
            "no signals for any market"
        )

        return

    # =================================================
    # TELEGRAM
    # =================================================

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

    # =================================================
    # ANALYZE ALL MARKETS
    # =================================================

    for symbol, name in MARKETS:

        result = analyze_market(
            symbol,
            name
        )

        if result:

            messages.append(
                result
            )

    # =================================================
    # SEND SIGNALS
    # =================================================

    if messages:

        message = (
            "\n\n"
            "━━━━━━━━━━━━━━━━━━━━"
            "\n\n"
        ).join(
            messages
        )

        try:

            await bot.send_message(
                chat_id=CHAT_ID,
                text=message
            )

            print(
                "High quality signals sent"
            )

        except Exception as e:

            print(
                f"Telegram error: {e}"
            )

        # =================================================
        # DAILY REPORT
        # =================================================

        try:

            report = get_report()

            report_message = f"""
📊 QuantumGold AI Daily Report

Total Signals:
{report["total"]}

🟢 BUY:
{report["buy"]}

🔴 SELL:
{report["sell"]}

━━━━━━━━━━━━━━━━━━━━

Mode:
STRICT 80+

Minimum AI:
{MIN_AI_SCORE}

Minimum Quality:
{MIN_QUALITY_SCORE}

Minimum ADX:
{MIN_ADX}

Target Win Rate:
{TARGET_WIN_RATE}%
"""

            await bot.send_message(
                chat_id=CHAT_ID,
                text=report_message
            )

        except Exception as e:

            print(
                f"Report error: {e}"
            )

    else:

        print(
            "No 80+ quality "
            "BUY/SELL signals"
        )


# =========================================================
# RUN
# =========================================================

if __name__ == "__main__":

    asyncio.run(
        main()
    )
