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

from signal_tracker import record_signal


# =========================================================
# SETTINGS
# =========================================================

TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

MIN_AI_SCORE = 80
MIN_QUALITY_SCORE = 80
MIN_ADX = 25

TARGET_WIN_RATE = 85


# =========================================================
# MARKETS
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
# WEEKEND FILTER
# =========================================================

def is_weekend():

    weekday = datetime.datetime.now().weekday()

    return weekday in [5, 6]


# =========================================================
# SAFE NUMBER
# =========================================================

def safe_float(value, default=0.0):

    try:

        value = float(value)

        if math.isnan(value):
            return default

        if math.isinf(value):
            return default

        return value

    except Exception:

        return default


# =========================================================
# DATA
# =========================================================

def get_data(symbol, interval="5m"):

    try:

        data = yf.download(
            symbol,
            period="7d",
            interval=interval,
            progress=False,
            auto_adjust=False,
            threads=False
        )

        if data is None or data.empty:

            print(
                f"{symbol}: No market data"
            )

            return None

        return data

    except Exception as e:

        print(
            f"Data error {symbol}: {e}"
        )

        return None


# =========================================================
# PREPARE DATA
# =========================================================

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
        volume = volume.dropna()

        if len(close) < 220:

            print(
                f"{symbol}: Not enough candles"
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
            f"Prepare data error "
            f"{symbol}: {e}"
        )

        return None


# =========================================================
# VOLUME CHECK
# =========================================================

def check_volume(volume):

    try:

        if volume is None:
            return False

        if len(volume) < 20:
            return False

        avg_volume = safe_float(
            volume.tail(20).mean()
        )

        current_volume = safe_float(
            volume.iloc[-1]
        )

        if avg_volume <= 0:
            return False

        return current_volume >= (
            avg_volume * 1.05
        )

    except Exception:

        return False


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

        if price <= 0:

            return (
                False,
                "Invalid entry price"
            )

        if signal == "🟢 BUY":

            if not (
                stop_loss < price
                and tp1 > price
                and tp2 > tp1
                and tp3 > tp2
            ):

                return (
                    False,
                    "Invalid BUY TP/SL structure"
                )

        elif signal == "🔴 SELL":

            if not (
                stop_loss > price
                and tp1 < price
                and tp2 < tp1
                and tp3 < tp2
            ):

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
            f"TP/SL error: {e}"
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

    # -----------------------------------------------------
    # EMA
    # -----------------------------------------------------

    if (
        (is_buy and ema_bullish)
        or
        (is_sell and not ema_bullish)
    ):

        score += 15

    # -----------------------------------------------------
    # MACD
    # -----------------------------------------------------

    if (
        (is_buy and macd_bullish)
        or
        (is_sell and not macd_bullish)
    ):

        score += 15

    # -----------------------------------------------------
    # M15
    # -----------------------------------------------------

    if (
        (is_buy and m15_bullish)
        or
        (is_sell and not m15_bullish)
    ):

        score += 15

    # -----------------------------------------------------
    # H1
    # -----------------------------------------------------

    if (
        (is_buy and h1_bullish)
        or
        (is_sell and not h1_bullish)
    ):

        score += 15

    # -----------------------------------------------------
    # ADX
    # -----------------------------------------------------

    if adx_value >= 30:

        score += 15

    elif adx_value >= 25:

        score += 10

    # Below 25 = no points

    # -----------------------------------------------------
    # VOLUME
    # -----------------------------------------------------

    if volume_confirmed:

        score += 10

    # -----------------------------------------------------
    # RSI
    # -----------------------------------------------------

    if is_buy:

        if 45 <= rsi_value <= 68:

            score += 5

        elif rsi_value > 75:

            score -= 10

    elif is_sell:

        if 32 <= rsi_value <= 55:

            score += 5

        elif rsi_value < 25:

            score -= 10

    # -----------------------------------------------------
    # NEWS
    # -----------------------------------------------------

    if news_risk == "HIGH":

        score -= 20

    else:

        score += 5

    # -----------------------------------------------------
    # ENTRY
    # -----------------------------------------------------

    if entry_quality == "A":

        score += 10

    elif entry_quality == "B":

        score += 5

    else:

        score -= 10

    # -----------------------------------------------------
    # LIMIT
    # -----------------------------------------------------

    score = max(
        0,
        min(
            100,
            score
        )
    )

    return int(score)


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
    news_risk,
    trend_aligned,
    ema_aligned,
    macd_aligned,
    rsi_valid
):

    if signal not in [
        "🟢 BUY",
        "🔴 SELL"
    ]:

        return (
            False,
            "No clear direction"
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
            "Entry Quality is not A"
        )

    if adx_value < MIN_ADX:

        return (
            False,
            f"ADX below {MIN_ADX}"
        )

    if not volume_confirmed:

        return (
            False,
            "Volume not confirmed"
        )

    if news_risk == "HIGH":

        return (
            False,
            "High News Risk"
        )

    if not trend_aligned:

        return (
            False,
            "M5/M15/H1 trend conflict"
        )

    if not ema_aligned:

        return (
            False,
            "EMA direction conflict"
        )

    if not macd_aligned:

        return (
            False,
            "MACD direction conflict"
        )

    if not rsi_valid:

        return (
            False,
            "RSI not suitable"
        )

    return (
        True,
        "MASTER APPROVED"
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

        # -------------------------------------------------
        # WEEKEND
        # -------------------------------------------------

        if is_weekend():

            print(
                f"{name}: Weekend - blocked"
            )

            return None

        # -------------------------------------------------
        # NEWS
        # -------------------------------------------------

        news = check_news()

        if not news:

            news = {

                "risk": "HIGH",

                "message":
                    "News data unavailable"

            }

        news_risk = news.get(
            "risk",
            "HIGH"
        )

        # -------------------------------------------------
        # DATA
        # -------------------------------------------------

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

            return None

        if market_m15 is None:

            return None

        if market_h1 is None:

            return None

        close = market_m5["close"]
        high = market_m5["high"]
        low = market_m5["low"]
        volume = market_m5["volume"]

        # -------------------------------------------------
        # PRICE
        # -------------------------------------------------

        if symbol == "GC=F":

            live_price = (
                get_live_gold_price()
            )

            if live_price:

                price = safe_float(
                    live_price
                )

            else:

                price = safe_float(
                    close.iloc[-1]
                )

        else:

            price = safe_float(
                close.iloc[-1]
            )

        if price <= 0:

            return None

        # -------------------------------------------------
        # SUPPORT / RESISTANCE
        # -------------------------------------------------

        sr = find_support_resistance(
            close
        )

        support = safe_float(
            sr.get("support")
        )

        resistance = safe_float(
            sr.get("resistance")
        )

        # -------------------------------------------------
        # M5 EMA
        # -------------------------------------------------

        ema50 = ta.trend.ema_indicator(
            close,
            window=50
        )

        ema200 = ta.trend.ema_indicator(
            close,
            window=200
        )

        # -------------------------------------------------
        # RSI
        # -------------------------------------------------

        rsi = ta.momentum.rsi(
            close,
            window=14
        )

        # -------------------------------------------------
        # MACD
        # -------------------------------------------------

        macd = ta.trend.MACD(
            close
        )

        # -------------------------------------------------
        # ATR
        # -------------------------------------------------

        atr = ta.volatility.average_true_range(
            high,
            low,
            close,
            window=14
        )

        # -------------------------------------------------
        # ADX
        # -------------------------------------------------

        adx_indicator = ta.trend.ADXIndicator(
            high,
            low,
            close,
            window=14
        )

        # -------------------------------------------------
        # CURRENT VALUES
        # -------------------------------------------------

        e50 = safe_float(
            ema50.iloc[-1]
        )

        e200 = safe_float(
            ema200.iloc[-1]
        )

        r = safe_float(
            rsi.iloc[-1]
        )

        macd_line = safe_float(
            macd.macd().iloc[-1]
        )

        macd_signal = safe_float(
            macd.macd_signal().iloc[-1]
        )

        atr_value = safe_float(
            atr.iloc[-1]
        )

        adx_value = safe_float(
            adx_indicator.adx().iloc[-1]
        )

        # -------------------------------------------------
        # DIRECTION
        # -------------------------------------------------

        ema_bullish = (
            e50 > e200
        )

        macd_bullish = (
            macd_line > macd_signal
        )

        # -------------------------------------------------
        # M15
        # -------------------------------------------------

        close_m15 = (
            market_m15["close"]
        )

        ema50_m15 = ta.trend.ema_indicator(
            close_m15,
            window=50
        )

        ema200_m15 = ta.trend.ema_indicator(
            close_m15,
            window=200
        )

        m15_bullish = (
            safe_float(
                ema50_m15.iloc[-1]
            )
            >
            safe_float(
                ema200_m15.iloc[-1]
            )
        )

        # -------------------------------------------------
        # H1
        # -------------------------------------------------

        close_h1 = (
            market_h1["close"]
        )

        ema50_h1 = ta.trend.ema_indicator(
            close_h1,
            window=50
        )

        ema200_h1 = ta.trend.ema_indicator(
            close_h1,
            window=200
        )

        h1_bullish = (
            safe_float(
                ema50_h1.iloc[-1]
            )
            >
            safe_float(
                ema200_h1.iloc[-1]
            )
        )

        # -------------------------------------------------
        # VOLUME
        # -------------------------------------------------

        volume_confirmed = check_volume(
            volume
        )

        # -------------------------------------------------
        # RAW SCORE
        # -------------------------------------------------

        score = 0

        reasons = []

        # -------------------------------------------------
        # EMA
        # -------------------------------------------------

        if ema_bullish:

            score += 25

            reasons.append(
                "✅ EMA bullish"
            )

        else:

            score -= 25

            reasons.append(
                "❌ EMA bearish"
            )

        # -------------------------------------------------
        # MACD
        # -------------------------------------------------

        if macd_bullish:

            score += 25

            reasons.append(
                "✅ MACD bullish"
            )

        else:

            score -= 25

            reasons.append(
                "❌ MACD bearish"
            )

        # -------------------------------------------------
        # M15
        # -------------------------------------------------

        if m15_bullish:

            score += 10

            reasons.append(
                "✅ M15 bullish"
            )

        else:

            score -= 10

            reasons.append(
                "❌ M15 bearish"
            )

        # -------------------------------------------------
        # H1
        # -------------------------------------------------

        if h1_bullish:

            score += 10

            reasons.append(
                "✅ H1 bullish"
            )

        else:

            score -= 10

            reasons.append(
                "❌ H1 bearish"
            )

        # -------------------------------------------------
        # ADX
        # -------------------------------------------------

        if adx_value >= 30:

            score += 15

            reasons.append(
                "✅ Strong ADX"
            )

        elif adx_value >= 25:

            score += 10

            reasons.append(
                "✅ ADX confirmed"
            )

        else:

            score -= 10

            reasons.append(
                "⚠️ ADX below 25"
            )

        # -------------------------------------------------
        # VOLUME
        # -------------------------------------------------

        if volume_confirmed:

            score += 10

            reasons.append(
                "✅ Volume confirmed"
            )

        else:

            score -= 10

            reasons.append(
                "⚠️ Volume not confirmed"
            )

        # -------------------------------------------------
        # RSI
        # -------------------------------------------------

        if r > 50:

            score += 10

            reasons.append(
                "✅ RSI bullish"
            )

        else:

            score -= 10

            reasons.append(
                "⚠️ RSI bearish"
            )

        # -------------------------------------------------
        # NEWS
        # -------------------------------------------------

        if news_risk == "HIGH":

            score -= 20

            reasons.append(
                "⚠️ High news risk"
            )

        else:

            score += 5

            reasons.append(
                "✅ News acceptable"
            )

        # -------------------------------------------------
        # SIGNAL
        # -------------------------------------------------

        if score >= 50:

            signal = "🟢 BUY"

        elif score <= -50:

            signal = "🔴 SELL"

        else:

            print(
                f"{name}: No clear direction"
            )

            return None

        # -------------------------------------------------
        # PRELIMINARY CONFIDENCE
        # -------------------------------------------------

        preliminary_confidence = min(
            100,
            abs(score)
        )

        # -------------------------------------------------
        # ENTRY FILTER
        # -------------------------------------------------

        entry = check_entry(
            signal,
            price,
            support,
            resistance,
            r,
            preliminary_confidence
        )

        entry_quality = entry.get(
            "quality",
            "C"
        )

        if entry_quality == "A":

            reasons.append(
                "✅ Entry A"
            )

        elif entry_quality == "B":

            reasons.append(
                "⚠️ Entry B"
            )

        else:

            reasons.append(
                "❌ Entry C"
            )

        # -------------------------------------------------
        # TREND ALIGNMENT
        # -------------------------------------------------

        if signal == "🟢 BUY":

            trend_aligned = (
                ema_bullish
                and m15_bullish
                and h1_bullish
            )

            ema_aligned = (
                ema_bullish
            )

            macd_aligned = (
                macd_bullish
            )

            rsi_valid = (
                45 <= r <= 68
            )

        else:

            trend_aligned = (
                not ema_bullish
                and not m15_bullish
                and not h1_bullish
            )

            ema_aligned = (
                not ema_bullish
            )

            macd_aligned = (
                not macd_bullish
            )

            rsi_valid = (
                32 <= r <= 55
            )

        # -------------------------------------------------
        # TP / SL
        # -------------------------------------------------

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

        if atr_value <= 0:

            print(
                f"{name}: Invalid ATR"
            )

            return None

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

        # -------------------------------------------------
        # TP/SL VALIDATION
        # -------------------------------------------------

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

        # -------------------------------------------------
        # SMART SCORE
        # -------------------------------------------------

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
                    safe_float(
                        smart.get(
                            "score",
                            0
                        )
                    )
                )
            )
        )

        # -------------------------------------------------
        # QUALITY SCORE
        # -------------------------------------------------

        quality_score = calculate_quality_score(
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

        # -------------------------------------------------
        # FINAL AI SCORE
        # -------------------------------------------------

        final_ai_score = min(
            smart_score,
            quality_score
        )

        final_ai_score = int(
            max(
                0,
                min(
                    100,
                    final_ai_score
                )
            )
        )

        # -------------------------------------------------
        # OLD NO TRADE FILTER
        # -------------------------------------------------

        # =================================================
# MASTER QUALITY FILTER
# =================================================

is_buy = signal == "🟢 BUY"

if is_buy:

    trend_aligned = (
        ema_bullish
        and macd_bullish
        and m15_bullish
        and h1_bullish
    )

    rsi_valid = (
        45 < r < 70
    )

else:

    trend_aligned = (
        not ema_bullish
        and not macd_bullish
        and not m15_bullish
        and not h1_bullish
    )

    rsi_valid = (
        30 < r < 55
    )


final_trade = apply_no_trade_filter(

    signal=signal,

    ai_score=final_ai_score,

    news_risk=news["risk"],

    entry_quality=entry_quality,

    quality_score=quality_score,

    adx_value=adx_value,

    volume_confirmed=volume_confirmed,

    trend_aligned=trend_aligned,

    rsi_valid=rsi_valid,

    tp_sl_valid=valid_levels
)


final_signal = final_trade["signal"]

final_reason = final_trade["reason"]
            "Rejected"
        )

        # -------------------------------------------------
        # MASTER FILTER
        # -------------------------------------------------

        approved, master_reason = (
            master_quality_filter(
                signal=final_signal,
                ai_score=final_ai_score,
                quality_score=quality_score,
                entry_quality=entry_quality,
                adx_value=adx_value,
                volume_confirmed=volume_confirmed,
                news_risk=news_risk,
                trend_aligned=trend_aligned,
                ema_aligned=ema_aligned,
                macd_aligned=macd_aligned,
                rsi_valid=rsi_valid
            )
        )

        if not approved:

            print(
                f"{name}: "
                f"MASTER REJECTED - "
                f"{master_reason} | "
                f"AI={final_ai_score} "
                f"Quality={quality_score}"
            )

            return None

        # -------------------------------------------------
        # FINAL TP/SL CHECK
        # -------------------------------------------------

        valid_levels, level_reason = (
            validate_trade_levels(
                final_signal,
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
                f"FINAL TP/SL REJECTED - "
                f"{level_reason}"
            )

            return None

        # -------------------------------------------------
        # DUPLICATE FILTER
        # -------------------------------------------------

        if not allow_new_signal(
            final_signal,
            price
        ):

            print(
                f"{name}: "
                f"Duplicate blocked"
            )

            return None

        # -------------------------------------------------
        # SAVE SIGNAL
        # -------------------------------------------------

        save_last_signal(
            final_signal,
            price
        )

        save_trade(
            final_signal,
            price,
            final_ai_score,
            stop_loss,
            tp3
        )

        save_signal(
            final_signal
        )

        # -------------------------------------------------
        # TRACK SIGNAL
        # -------------------------------------------------

        record_signal(
            symbol=symbol,
            name=name,
            signal=final_signal,
            entry=price,
            stop_loss=stop_loss,
            tp1=tp1,
            tp2=tp2,
            tp3=tp3,
            ai_score=final_ai_score,
            quality_score=quality_score,
            entry_quality=entry_quality,
            adx=adx_value,
            rsi=r,
            volume_confirmed=volume_confirmed
        )

        # -------------------------------------------------
        # MESSAGE
        # -------------------------------------------------

        direction = (
            "BUY"
            if final_signal == "🟢 BUY"
            else "SELL"
        )

        reasons_text = "\n".join(
            reasons
        )

        message = f"""
📊 {name} {direction} NOW {price:.5f}

⚠️ Stop Loss (SL): {stop_loss:.5f}

🎯 TP1: {tp1:.5f}
🎯 TP2: {tp2:.5f}
🎯 TP3: {tp3:.5f}

━━━━━━━━━━━━━━━━━━━━

🥇 QuantumGold AI Signal

{name}

Signal:
{final_signal}

Confidence:
{final_ai_score}%

Live Price:
{price:.5f}

Stop Loss:
{stop_loss:.5f}

Take Profit:
{tp3:.5f}

Entry Quality:
{entry_quality}

AI Score:
{final_ai_score}/100

Smart Score:
{smart_score}/100

Quality Score:
{quality_score}/100

Decision:
{smart.get("decision", "Strong setup")}

Master Filter:
✅ APPROVED

Stored Signals:
{get_trade_count()}

Support:
{support:.5f}

Resistance:
{resistance:.5f}

ATR:
{atr_value:.5f}

RSI:
{r:.2f}

MACD:
{macd_line:.5f}

ADX:
{adx_value:.2f}

News:
{news.get("message", "N/A")}

Reasons:
{reasons_text}

Timeframe:
M5

Target Win Rate:
{TARGET_WIN_RATE}%
"""

        print(
            f"{name}: "
            f"MASTER APPROVED | "
            f"AI={final_ai_score} "
            f"Quality={quality_score} "
            f"ADX={adx_value:.2f}"
        )

        return message

    except Exception as e:

        print(
            f"Error analyzing "
            f"{name}: {e}"
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

    # -----------------------------------------------------
    # GLOBAL WEEKEND FILTER
    # -----------------------------------------------------

    if is_weekend():

        print(
            "Weekend - "
            "NO SIGNALS FOR ALL MARKETS"
        )

        return

    if not TOKEN:

        print(
            "ERROR: "
            "TELEGRAM_TOKEN missing"
        )

        return

    if not CHAT_ID:

        print(
            "ERROR: "
            "TELEGRAM_CHAT_ID missing"
        )

        return

    bot = Bot(
        token=TOKEN
    )

    messages = []

    # -----------------------------------------------------
    # ANALYZE ALL MARKETS
    # -----------------------------------------------------

    for symbol, name in MARKETS:

        result = analyze_market(
            symbol,
            name
        )

        if result:

            messages.append(
                result
            )

    # -----------------------------------------------------
    # SEND
    # -----------------------------------------------------

    if messages:

        message = (
            "\n\n"
            "━━━━━━━━━━━━━━━━━━━━"
            "\n\n"
        ).join(
            messages
        )

        await bot.send_message(
            chat_id=CHAT_ID,
            text=message
        )

        # -------------------------------------------------
        # DAILY REPORT
        # -------------------------------------------------

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

        print(
            "High quality "
            "signals sent"
        )

    else:

        print(
            "No 80+ quality "
            "BUY/SELL signals"
        )


# =========================================================
# START
# =========================================================

if __name__ == "__main__":

    asyncio.run(
        main()
    )
