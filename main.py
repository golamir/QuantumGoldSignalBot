import os
import asyncio
import datetime

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


TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

MIN_AI_SCORE = 70

MARKETS = [
    ("EURUSD=X", "EUR/USD"),
    ("GBPUSD=X", "GBP/USD"),
    ("USDJPY=X", "USD/JPY"),
    ("USDCHF=X", "USD/CHF"),
    ("AUDUSD=X", "AUD/USD"),
    ("USDCAD=X", "USD/CAD"),
    ("NZDUSD=X", "NZD/USD")
]


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
            auto_adjust=False
        )

        if data is None or data.empty:
            return None

        return data

    except Exception as e:
        print(f"Data error {symbol}: {e}")
        return None


def prepare_data(symbol, interval="5m"):
    data = get_data(symbol, interval)

    if data is None:
        return None

    try:
        close = data["Close"]
        high = data["High"]
        low = data["Low"]
        volume = data["Volume"]

        # yfinance sometimes returns MultiIndex columns
        if hasattr(close, "columns"):
            close = close.iloc[:, 0]

        if hasattr(high, "columns"):
            high = high.iloc[:, 0]

        if hasattr(low, "columns"):
            low = low.iloc[:, 0]

        if hasattr(volume, "columns"):
            volume = volume.iloc[:, 0]

        return {
            "close": close,
            "high": high,
            "low": low,
            "volume": volume
        }

    except Exception as e:
        print(f"Prepare data error {symbol}: {e}")
        return None


# =========================================================
# PRICE / TP / SL VALIDATION
# =========================================================

def validate_trade_levels(signal, price, stop_loss, tp1, tp2, tp3):
    """
    BUY:
        SL < Entry
        TP1 > Entry
        TP2 > TP1
        TP3 > TP2

    SELL:
        SL > Entry
        TP1 < Entry
        TP2 < TP1
        TP3 < TP2
    """

    try:
        price = float(price)
        stop_loss = float(stop_loss)
        tp1 = float(tp1)
        tp2 = float(tp2)
        tp3 = float(tp3)

        if price <= 0:
            return False, "Invalid entry price"

        if signal == "🟢 BUY":

            if not (
                stop_loss < price
                and tp1 > price
                and tp2 > tp1
                and tp3 > tp2
            ):
                return False, "Invalid BUY TP/SL structure"

        elif signal == "🔴 SELL":

            if not (
                stop_loss > price
                and tp1 < price
                and tp2 < tp1
                and tp3 < tp2
            ):
                return False, "Invalid SELL TP/SL structure"

        else:
            return False, "Invalid signal"

        return True, "Valid TP/SL"

    except Exception as e:
        return False, f"TP/SL validation error: {e}"


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
    """
    مستقل از smart_score:
    امتیاز کیفیت واقعی معامله را محاسبه می‌کند.

    سپس در analyze_market:
        final_ai_score = min(smart_score, quality_score)

    بنابراین smart_score دیگر نمی‌تواند
    هشدارهای مهم را نادیده بگیرد و 100 بدهد.
    """

    score = 0

    is_buy = signal == "🟢 BUY"
    is_sell = signal == "🔴 SELL"

    # -----------------------------------------------------
    # EMA
    # -----------------------------------------------------

    if (is_buy and ema_bullish) or (is_sell and not ema_bullish):
        score += 15

    # -----------------------------------------------------
    # MACD
    # -----------------------------------------------------

    if (is_buy and macd_bullish) or (is_sell and not macd_bullish):
        score += 15

    # -----------------------------------------------------
    # M15
    # -----------------------------------------------------

    if (is_buy and m15_bullish) or (is_sell and not m15_bullish):
        score += 10

    # -----------------------------------------------------
    # H1
    # -----------------------------------------------------

    if (is_buy and h1_bullish) or (is_sell and not h1_bullish):
        score += 10

    # -----------------------------------------------------
    # ADX
    # -----------------------------------------------------

    if adx_value >= 25:
        score += 10

    elif adx_value >= 20:
        score += 5

    # -----------------------------------------------------
    # Volume
    # -----------------------------------------------------

    if volume_confirmed:
        score += 10

    # -----------------------------------------------------
    # RSI
    # -----------------------------------------------------

    if is_buy:

        if 50 <= rsi_value <= 70:
            score += 5

        elif rsi_value < 30:
            score -= 5

    elif is_sell:

        if 30 <= rsi_value <= 50:
            score += 5

        elif rsi_value > 70:
            score -= 5

    # -----------------------------------------------------
    # NEWS
    # -----------------------------------------------------

    if news_risk == "HIGH":
        score -= 15

    else:
        score += 10

    # -----------------------------------------------------
    # ENTRY QUALITY
    # -----------------------------------------------------

    if entry_quality == "A":
        score += 10

    elif entry_quality == "B":
        score += 5

    else:
        score -= 5

    # -----------------------------------------------------
    # Clamp 0-100
    # -----------------------------------------------------

    score = max(0, min(100, score))

    return score


# =========================================================
# MARKET ANALYSIS
# =========================================================

def analyze_market(symbol, name):

    try:

        # =================================================
        # WEEKEND FILTER
        # =================================================

        weekday = datetime.datetime.now().weekday()

        if weekday in [5, 6]:
            print(f"{name}: Market closed - weekend")
            return None

        # =================================================
        # NEWS
        # =================================================

        news = check_news()

        if not news:
            news = {
                "risk": "HIGH",
                "message": "⚠️ News data unavailable"
            }

        # =================================================
        # MARKET DATA
        # =================================================

        market_m5 = prepare_data(symbol, "5m")
        market_m15 = prepare_data(symbol, "15m")
        market_h1 = prepare_data(symbol, "1h")

        dxy = prepare_data("DX-Y.NYB")

        if market_m5 is None:
            return None

        close = market_m5["close"]
        high = market_m5["high"]
        low = market_m5["low"]
        volume = market_m5["volume"]

        # =================================================
        # PRICE
        # =================================================

        if symbol == "GC=F":
            live_price = get_live_gold_price()
        else:
            live_price = None

        if live_price:
            price = float(live_price)
        else:
            price = float(close.iloc[-1])

        # =================================================
        # SUPPORT / RESISTANCE
        # =================================================

        sr = find_support_resistance(close)

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

        macd = ta.trend.MACD(close)

        atr = ta.volatility.average_true_range(
            high,
            low,
            close,
            window=14
        )

        adx_indicator = ta.trend.ADXIndicator(
            high,
            low,
            close,
            window=14
        )

        # =================================================
        # CURRENT VALUES
        # =================================================

        e50 = float(ema50.iloc[-1])
        e200 = float(ema200.iloc[-1])

        r = float(rsi.iloc[-1])

        m = float(macd.macd().iloc[-1])
        ms = float(macd.macd_signal().iloc[-1])

        atr_value = float(atr.iloc[-1])

        adx_value = float(
            adx_indicator.adx().iloc[-1]
        )

        ema_bullish = e50 > e200
        macd_bullish = m > ms

        # =================================================
        # M15 TREND
        # =================================================

        m15_bullish = False

        if market_m15 is not None:

            ema50_m15 = ta.trend.ema_indicator(
                market_m15["close"],
                window=50
            )

            ema200_m15 = ta.trend.ema_indicator(
                market_m15["close"],
                window=200
            )

            m15_bullish = (
                float(ema50_m15.iloc[-1])
                >
                float(ema200_m15.iloc[-1])
            )

        # =================================================
        # H1 TREND
        # =================================================

        h1_bullish = False

        if market_h1 is not None:

            ema50_h1 = ta.trend.ema_indicator(
                market_h1["close"],
                window=50
            )

            ema200_h1 = ta.trend.ema_indicator(
                market_h1["close"],
                window=200
            )

            h1_bullish = (
                float(ema50_h1.iloc[-1])
                >
                float(ema200_h1.iloc[-1])
            )

        # =================================================
        # SL / TP MULTIPLIERS
        # =================================================

        if symbol == "GC=F":

            sl_multiplier = 2
            tp_multiplier = 3

        elif symbol == "BTC-USD":

            sl_multiplier = 3
            tp_multiplier = 5

        elif symbol == "ETH-USD":

            sl_multiplier = 3
            tp_multiplier = 5

        else:

            sl_multiplier = 2
            tp_multiplier = 3

        # =================================================
        # VOLUME
        # =================================================

        avg_volume_raw = volume.mean()

        if hasattr(avg_volume_raw, "iloc"):
            avg_volume = float(avg_volume_raw.iloc[0])
        else:
            avg_volume = float(avg_volume_raw)

        last_volume = volume.iloc[-1]

        if hasattr(last_volume, "iloc"):
            current_volume = float(last_volume.iloc[0])
        else:
            current_volume = float(last_volume)

        volume_confirmed = current_volume > avg_volume

        # =================================================
        # RAW DIRECTIONAL SCORE
        # =================================================

        score = 0
        reasons = []

        # -------------------------------------------------
        # NEWS
        # -------------------------------------------------

        if news["risk"] == "HIGH":

            score -= 20
            reasons.append("⚠️ High news risk")

        else:

            score += 5
            reasons.append("✅ News environment safe")

        # -------------------------------------------------
        # VOLUME
        # -------------------------------------------------

        if volume_confirmed:

            score += 10
            reasons.append("✅ Volume confirms movement")

        else:

            score -= 5
            reasons.append("⚠️ Low volume")

        # -------------------------------------------------
        # ADX
        # -------------------------------------------------

        if adx_value >= 25:

            score += 15
            reasons.append("✅ Strong trend ADX")

        else:

            score -= 5
            reasons.append("⚠️ Weak trend ADX")

        # -------------------------------------------------
        # M15
        # -------------------------------------------------

        if m15_bullish:

            score += 10
            reasons.append("✅ M15 trend bullish")

        else:

            score -= 10
            reasons.append("❌ M15 trend bearish")

        # -------------------------------------------------
        # H1
        # -------------------------------------------------

        if h1_bullish:

            score += 10
            reasons.append("✅ H1 trend bullish")

        else:

            score -= 10
            reasons.append("❌ H1 trend bearish")

        # -------------------------------------------------
        # EMA
        # -------------------------------------------------

        if ema_bullish:

            score += 25
            reasons.append("✅ EMA bullish")

        else:

            score -= 25
            reasons.append("❌ EMA bearish")

        # -------------------------------------------------
        # RSI
        # -------------------------------------------------

        if r > 50:

            score += 15
            reasons.append("✅ RSI positive")

        else:

            score -= 15
            reasons.append("⚠️ RSI weak")

        # -------------------------------------------------
        # MACD
        # -------------------------------------------------

        if macd_bullish:

            score += 25
            reasons.append("✅ MACD positive")

        else:

            score -= 25
            reasons.append("❌ MACD negative")

        # -------------------------------------------------
        # DXY - GOLD ONLY
        # -------------------------------------------------

        if symbol == "GC=F" and dxy is not None:

            dxy_close = dxy["close"]

            if (
                len(dxy_close) > 20
                and float(dxy_close.iloc[-1])
                <
                float(dxy_close.iloc[-20])
            ):

                score += 15
                reasons.append("✅ DXY supports gold")

            else:

                score -= 15
                reasons.append("❌ DXY pressure")

        # =================================================
        # SIGNAL DIRECTION
        # =================================================

        if score >= 50:

            signal = "🟢 BUY"

        elif score <= -50:

            signal = "🔴 SELL"

        else:

            signal = "⚪ WAIT"

        # =================================================
        # INITIAL CONFIDENCE
        # =================================================

        preliminary_confidence = min(
            100,
            abs(score)
        )

        # =================================================
        # ENTRY QUALITY
        # =================================================

        entry = check_entry(
            signal,
            price,
            sr["support"],
            sr["resistance"],
            r,
            preliminary_confidence
        )

        entry_quality = entry["quality"]

        if entry_quality == "A":

            reasons.append("✅ High quality entry")

        elif entry_quality == "B":

            reasons.append("✅ Good quality entry")

        else:

            reasons.append("⚠️ Weak entry quality")

        # =================================================
        # WAIT FILTER
        # =================================================

        if signal not in ["🟢 BUY", "🔴 SELL"]:
            return None

        # =================================================
        # CREATE TP / SL
        # =================================================

        if signal == "🟢 BUY":

            stop_loss = price - (
                atr_value * sl_multiplier
            )

            tp1 = price + atr_value
            tp2 = price + (
                atr_value * 2
            )

            tp3 = price + (
                atr_value * tp_multiplier
            )

        else:

            stop_loss = price + (
                atr_value * sl_multiplier
            )

            tp1 = price - atr_value
            tp2 = price - (
                atr_value * 2
            )

            tp3 = price - (
                atr_value * tp_multiplier
            )

        # =================================================
        # TP / SL VALIDATION
        # =================================================

        valid_levels, level_reason = validate_trade_levels(
            signal,
            price,
            stop_loss,
            tp1,
            tp2,
            tp3
        )

        if not valid_levels:

            print(
                f"{name}: Signal rejected - "
                f"{level_reason}"
            )

            return None

        # =================================================
        # EXISTING SMART SCORE
        # =================================================

        smart = calculate_score(
            name,
            signal,
            preliminary_confidence,
            price,
            sr["support"],
            sr["resistance"],
            news["risk"]
        )

        try:
            smart_score = int(
                max(
                    0,
                    min(
                        100,
                        float(smart["score"])
                    )
                )
            )

        except Exception:

            smart_score = 0

        # =================================================
        # NEW REAL QUALITY SCORE
        # =================================================

        quality_score = calculate_quality_score(
            signal=signal,
            ema_bullish=ema_bullish,
            m15_bullish=m15_bullish,
            h1_bullish=h1_bullish,
            macd_bullish=macd_bullish,
            rsi_value=r,
            adx_value=adx_value,
            volume_confirmed=volume_confirmed,
            news_risk=news["risk"],
            entry_quality=entry_quality
        )

        # =================================================
        # FINAL AI SCORE
        # =================================================
        #
        # مهم:
        # اگر smart_score = 100 باشد ولی کیفیت واقعی
        # فقط 50 باشد، نتیجه 50 خواهد بود.
        #
        # بنابراین دیگر شرایط ضعیف نمی‌تواند 100/100 شود.
        # =================================================

        final_ai_score = min(
            smart_score,
            quality_score
        )

        final_ai_score = max(
            0,
            min(100, int(final_ai_score))
        )

        # =================================================
        # FINAL CONFIDENCE
        # =================================================

        confidence = final_ai_score

        # =================================================
        # FINAL FILTER
        # =================================================

        final_trade = apply_no_trade_filter(
            signal,
            final_ai_score,
            news["risk"],
            entry_quality
        )

        final_signal = final_trade["signal"]
        final_reason = final_trade["reason"]

        # =================================================
        # FINAL SIGNAL CHECK
        # =================================================

        if final_signal not in [
            "🟢 BUY",
            "🔴 SELL"
        ]:

            return None

        if final_ai_score < MIN_AI_SCORE:

            print(
                f"{name}: rejected - "
                f"AI Score {final_ai_score}"
            )

            return None

        # =================================================
        # HIGH NEWS SAFETY
        # =================================================

        if news["risk"] == "HIGH" and final_ai_score < 75:

            print(
                f"{name}: rejected - "
                f"high news risk"
            )

            return None

        # =================================================
        # FINAL TP/SL VALIDATION AGAIN
        # =================================================

        valid_levels, level_reason = validate_trade_levels(
            final_signal,
            price,
            stop_loss,
            tp1,
            tp2,
            tp3
        )

        if not valid_levels:

            print(
                f"{name}: final validation failed - "
                f"{level_reason}"
            )

            return None

        # =================================================
        # DUPLICATE SIGNAL FILTER
        # =================================================

        if not allow_new_signal(
            final_signal,
            price
        ):

            print(
                f"{name}: duplicate signal blocked"
            )

            return None

        # =================================================
        # SAVE SIGNAL
        # =================================================

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

        save_signal(final_signal)

        # =================================================
        # REASONS
        # =================================================

        reasons_text = "\n".join(reasons)

        # =================================================
        # MESSAGE
        # =================================================

        direction = (
            "BUY"
            if final_signal == "🟢 BUY"
            else "SELL"
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
{confidence}%

Live Price:
{price:.5f}

Stop Loss:
{stop_loss:.5f}

Take Profit:
{tp3:.5f}

Stored Signals:
{get_trade_count()}

Support:
{sr["support"]:.5f}

Resistance:
{sr["resistance"]:.5f}

Entry Quality:
{entry_quality}

AI Score:
{final_ai_score}/100

Smart Score:
{smart_score}/100

Quality Score:
{quality_score}/100

Decision:
{smart["decision"]}

Final Filter:
{final_reason}

ATR:
{atr_value:.5f}

RSI:
{r:.2f}

MACD:
{m:.5f}

ADX:
{adx_value:.2f}

News:
{news["message"]}

Reasons:
{reasons_text}

Timeframe:
M5
"""

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

    print("Starting QuantumGold AI")

    # Weekend global filter
    weekday = datetime.datetime.now().weekday()

    if weekday in [5, 6]:

        print(
            "Weekend - no signals"
        )

        return

    bot = Bot(token=TOKEN)

    messages = []

    for symbol, name in MARKETS:

        result = analyze_market(
            symbol,
            name
        )

        if result:
            messages.append(result)

    if messages:

        message = (
            "\n\n"
            "━━━━━━━━━━━━━━━━━━━━"
            "\n\n"
        ).join(messages)

        await bot.send_message(
            chat_id=CHAT_ID,
            text=message
        )

        report = get_report()

        report_message = f"""
📊 QuantumGold AI Daily Report

Total Signals:
{report["total"]}

🟢 BUY:
{report["buy"]}

🔴 SELL:
{report["sell"]}
"""

        await bot.send_message(
            chat_id=CHAT_ID,
            text=report_message
        )

        print(
            "High quality signals sent"
        )

    else:

        print(
            "No high quality BUY/SELL signals"
        )


if __name__ == "__main__":
    asyncio.run(main())
