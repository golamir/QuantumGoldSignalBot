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

# =========================================================
# QUANTUMGOLD STRICT SETTINGS
# =========================================================

MIN_AI_SCORE = 80
MIN_QUALITY_SCORE = 80

MIN_ADX = 25

TARGET_WIN_RATE = 85

# =========================================================
# MARKETS
# =========================================================

MARKETS = [
    ("GC=F", "XAU/USD"),

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

        # yfinance MultiIndex protection

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

        if price <= 0:
            return False, "Invalid entry price"

        # -------------------------------------------------
        # BUY
        # -------------------------------------------------

        if signal == "🟢 BUY":

            if not (
                stop_loss < price
                and tp1 > price
                and tp2 > tp1
                and tp3 > tp2
            ):

                return False, (
                    "Invalid BUY TP/SL structure"
                )

        # -------------------------------------------------
        # SELL
        # -------------------------------------------------

        elif signal == "🔴 SELL":

            if not (
                stop_loss > price
                and tp1 < price
                and tp2 < tp1
                and tp3 < tp2
            ):

                return False, (
                    "Invalid SELL TP/SL structure"
                )

        else:

            return False, "Invalid signal"

        return True, "Valid TP/SL"

    except Exception as e:

        return False, (
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

    is_buy = signal == "🟢 BUY"
    is_sell = signal == "🔴 SELL"

    # =====================================================
    # EMA
    # =====================================================

    ema_ok = (
        (is_buy and ema_bullish)
        or
        (is_sell and not ema_bullish)
    )

    if ema_ok:
        score += 15

    # =====================================================
    # MACD
    # =====================================================

    macd_ok = (
        (is_buy and macd_bullish)
        or
        (is_sell and not macd_bullish)
    )

    if macd_ok:
        score += 15

    # =====================================================
    # M15
    # =====================================================

    m15_ok = (
        (is_buy and m15_bullish)
        or
        (is_sell and not m15_bullish)
    )

    if m15_ok:
        score += 10

    # =====================================================
    # H1
    # =====================================================

    h1_ok = (
        (is_buy and h1_bullish)
        or
        (is_sell and not h1_bullish)
    )

    if h1_ok:
        score += 10

    # =====================================================
    # ADX
    # =====================================================

    if adx_value >= 25:
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
            score += 5

    elif is_sell:

        if 30 < rsi_value < 55:
            score += 5

    # =====================================================
    # NEWS
    # =====================================================

    if news_risk == "HIGH":

        score -= 20

    else:

        score += 10

    # =====================================================
    # ENTRY QUALITY
    # =====================================================

    if entry_quality == "A":

        score += 10

    elif entry_quality == "B":

        score += 5

    else:

        score -= 5

    # =====================================================
    # FINAL LIMIT
    # =====================================================

    score = max(
        0,
        min(100, int(score))
    )

    return score


# =========================================================
# MASTER QUALITY FILTER
# =========================================================

def master_quality_filter(
    signal,
    final_ai_score,
    quality_score,
    entry_quality,
    adx_value,
    volume_confirmed,
    news_risk,
    ema_bullish,
    macd_bullish,
    m15_bullish,
    h1_bullish,
    rsi_value
):

    # =====================================================
    # SIGNAL
    # =====================================================

    if signal not in [
        "🟢 BUY",
        "🔴 SELL"
    ]:

        return False, "Signal is not BUY/SELL"

    is_buy = signal == "🟢 BUY"
    is_sell = signal == "🔴 SELL"

    # =====================================================
    # AI SCORE
    # =====================================================

    if final_ai_score < MIN_AI_SCORE:

        return False, (
            f"AI Score below {MIN_AI_SCORE}"
        )

    # =====================================================
    # QUALITY SCORE
    # =====================================================

    if quality_score < MIN_QUALITY_SCORE:

        return False, (
            f"Quality below {MIN_QUALITY_SCORE}"
        )

    # =====================================================
    # ENTRY QUALITY
    # =====================================================

    if entry_quality != "A":

        return False, (
            "Entry Quality is not A"
        )

    # =====================================================
    # NEWS
    # =====================================================

    if news_risk == "HIGH":

        return False, (
            "High news risk"
        )

    # =====================================================
    # ADX
    # =====================================================

    if adx_value < MIN_ADX:

        return False, (
            f"ADX below {MIN_ADX}"
        )

    # =====================================================
    # VOLUME
    # =====================================================

    if not volume_confirmed:

        return False, (
            "Volume confirmation missing"
        )

    # =====================================================
    # TREND ALIGNMENT
    # =====================================================

    if is_buy:

        if not ema_bullish:
            return False, "BUY EMA not bullish"

        if not macd_bullish:
            return False, "BUY MACD not bullish"

        if not m15_bullish:
            return False, "BUY M15 not bullish"

        if not h1_bullish:
            return False, "BUY H1 not bullish"

    elif is_sell:

        if ema_bullish:
            return False, "SELL EMA not bearish"

        if macd_bullish:
            return False, "SELL MACD not bearish"

        if m15_bullish:
            return False, "SELL M15 not bearish"

        if h1_bullish:
            return False, "SELL H1 not bearish"

    # =====================================================
    # RSI
    # =====================================================

    if is_buy:

        if not (
            45 < rsi_value < 70
        ):

            return False, (
                "BUY RSI outside safe range"
            )

    if is_sell:

        if not (
            30 < rsi_value < 55
        ):

            return False, (
                "SELL RSI outside safe range"
            )

    # =====================================================
    # EVERYTHING PASSED
    # =====================================================

    return True, (
        "MASTER FILTER PASSED"
    )


# =========================================================
# MARKET ANALYSIS
# =========================================================

def analyze_market(symbol, name):

    try:

        # =================================================
        # WEEKEND FILTER
        # =================================================

        weekday = datetime.datetime.utcnow().weekday()

        if weekday in [5, 6]:

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
            news.get("risk", "HIGH")
        ).upper()

        # =================================================
        # MARKET DATA
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

        dxy = None

        if symbol == "GC=F":

            dxy = prepare_data(
                "DX-Y.NYB",
                "5m"
            )

        if market_m5 is None:

            print(
                f"{name}: M5 data unavailable"
            )

            return None

        # =================================================
        # M5 DATA
        # =================================================

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

            price = float(
                close.iloc[-1]
            )

        # =================================================
        # SUPPORT / RESISTANCE
        # =================================================

        sr = find_support_resistance(
            close
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

        ema_bullish = e50 > e200

        macd_bullish = m > ms

        # =================================================
        # M15 TREND
        # =================================================

        if market_m15 is None:

            print(
                f"{name}: M15 unavailable"
            )

            return None

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

        if market_h1 is None:

            print(
                f"{name}: H1 unavailable"
            )

            return None

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
        # VOLUME
        # =================================================

        avg_volume_raw = volume.mean()

        if hasattr(
            avg_volume_raw,
            "iloc"
        ):

            avg_volume = float(
                avg_volume_raw.iloc[0]
            )

        else:

            avg_volume = float(
                avg_volume_raw
            )

        last_volume = volume.iloc[-1]

        if hasattr(
            last_volume,
            "iloc"
        ):

            current_volume = float(
                last_volume.iloc[0]
            )

        else:

            current_volume = float(
                last_volume
            )

        volume_confirmed = (
            current_volume > avg_volume
        )

        # =================================================
        # RAW DIRECTIONAL SCORE
        # =================================================

        buy_score = 0
        sell_score = 0

        reasons = []

        # =================================================
        # NEWS
        # =================================================

        if news_risk == "HIGH":

            buy_score -= 20
            sell_score -= 20

            reasons.append(
                "⚠️ High news risk"
            )

        else:

            buy_score += 5
            sell_score += 5

            reasons.append(
                "✅ News environment acceptable"
            )

        # =================================================
        # VOLUME
        # =================================================

        if volume_confirmed:

            buy_score += 10
            sell_score += 10

            reasons.append(
                "✅ Volume confirmed"
            )

        else:

            buy_score -= 10
            sell_score -= 10

            reasons.append(
                "⚠️ Low volume"
            )

        # =================================================
        # ADX
        # =================================================

        if adx_value >= 25:

            buy_score += 15
            sell_score += 15

            reasons.append(
                "✅ Strong ADX"
            )

        elif adx_value >= 20:

            buy_score += 5
            sell_score += 5

            reasons.append(
                "⚠️ Medium ADX"
            )

        else:

            buy_score -= 10
            sell_score -= 10

            reasons.append(
                "❌ Weak ADX"
            )

        # =================================================
        # M15
        # =================================================

        if m15_bullish:

            buy_score += 15
            sell_score -= 15

            reasons.append(
                "✅ M15 bullish"
            )

        else:

            buy_score -= 15
            sell_score += 15

            reasons.append(
                "✅ M15 bearish"
            )

        # =================================================
        # H1
        # =================================================

        if h1_bullish:

            buy_score += 15
            sell_score -= 15

            reasons.append(
                "✅ H1 bullish"
            )

        else:

            buy_score -= 15
            sell_score += 15

            reasons.append(
                "✅ H1 bearish"
            )

        # =================================================
        # EMA
        # =================================================

        if ema_bullish:

            buy_score += 20
            sell_score -= 20

            reasons.append(
                "✅ EMA bullish"
            )

        else:

            buy_score -= 20
            sell_score += 20

            reasons.append(
                "✅ EMA bearish"
            )

        # =================================================
        # RSI
        # =================================================

        if 45 < r < 70:

            buy_score += 10

        elif r >= 70:

            buy_score -= 10

        if 30 < r < 55:

            sell_score += 10

        elif r <= 30:

            sell_score -= 10

        # =================================================
        # MACD
        # =================================================

        if macd_bullish:

            buy_score += 20
            sell_score -= 20

            reasons.append(
                "✅ MACD bullish"
            )

        else:

            buy_score -= 20
            sell_score += 20

            reasons.append(
                "✅ MACD bearish"
            )

        # =================================================
        # DXY FOR GOLD
        # =================================================

        if (
            symbol == "GC=F"
            and dxy is not None
        ):

            dxy_close = dxy["close"]

            if len(dxy_close) > 20:

                dxy_now = float(
                    dxy_close.iloc[-1]
                )

                dxy_old = float(
                    dxy_close.iloc[-20]
                )

                if dxy_now < dxy_old:

                    buy_score += 15

                    sell_score -= 15

                    reasons.append(
                        "✅ DXY supports Gold BUY"
                    )

                else:

                    buy_score -= 15

                    sell_score += 15

                    reasons.append(
                        "⚠️ DXY pressures Gold"
                    )

        # =================================================
        # SIGNAL DIRECTION
        # =================================================

        if (
            buy_score >= 50
            and buy_score > sell_score
        ):

            signal = "🟢 BUY"

            directional_score = buy_score

        elif (
            sell_score >= 50
            and sell_score > buy_score
        ):

            signal = "🔴 SELL"

            directional_score = sell_score

        else:

            print(
                f"{name}: No clear direction"
            )

            return None

        # =================================================
        # PRELIMINARY CONFIDENCE
        # =================================================

        preliminary_confidence = min(
            100,
            max(
                0,
                abs(directional_score)
            )
        )

        # =================================================
        # ENTRY FILTER
        # =================================================

        entry = check_entry(
            signal,
            price,
            sr["support"],
            sr["resistance"],
            r,
            preliminary_confidence
        )

        if not entry:

            print(
                f"{name}: Entry filter unavailable"
            )

            return None

        entry_quality = entry.get(
            "quality",
            "C"
        )

        # =================================================
        # ENTRY REASON
        # =================================================

        if entry_quality == "A":

            reasons.append(
                "✅ Entry Quality A"
            )

        elif entry_quality == "B":

            reasons.append(
                "⚠️ Entry Quality B"
            )

        else:

            reasons.append(
                "❌ Entry Quality C"
            )

        # =================================================
        # ONLY BUY / SELL
        # =================================================

        if signal not in [
            "🟢 BUY",
            "🔴 SELL"
        ]:

            return None

        # =================================================
        # SL / TP
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
        # BUY TP / SL
        # =================================================

        if signal == "🟢 BUY":

            stop_loss = (
                price
                -
                (
                    atr_value
                    *
                    sl_multiplier
                )
            )

            tp1 = (
                price
                +
                atr_value
            )

            tp2 = (
                price
                +
                (
                    atr_value * 2
                )
            )

            tp3 = (
                price
                +
                (
                    atr_value
                    *
                    tp_multiplier
                )
            )

        # =================================================
        # SELL TP / SL
        # =================================================

        else:

            stop_loss = (
                price
                +
                (
                    atr_value
                    *
                    sl_multiplier
                )
            )

            tp1 = (
                price
                -
                atr_value
            )

            tp2 = (
                price
                -
                (
                    atr_value * 2
                )
            )

            tp3 = (
                price
                -
                (
                    atr_value
                    *
                    tp_multiplier
                )
            )

        # =================================================
        # FIRST TP/SL VALIDATION
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
                f"{level_reason}"
            )

            return None

        # =================================================
        # SMART SCORE
        # =================================================

        try:

            smart = calculate_score(
                name,
                signal,
                preliminary_confidence,
                price,
                sr["support"],
                sr["resistance"],
                news_risk
            )

        except Exception as e:

            print(
                f"{name}: Smart score error: {e}"
            )

            return None

        try:

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

        except Exception:

            smart_score = 0

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

        confidence = final_ai_score

        # =================================================
        # MASTER QUALITY FILTER
        # =================================================

        master_passed, master_reason = (
            master_quality_filter(
                signal=signal,
                final_ai_score=final_ai_score,
                quality_score=quality_score,
                entry_quality=entry_quality,
                adx_value=adx_value,
                volume_confirmed=volume_confirmed,
                news_risk=news_risk,
                ema_bullish=ema_bullish,
                macd_bullish=macd_bullish,
                m15_bullish=m15_bullish,
                h1_bullish=h1_bullish,
                rsi_value=r
            )
        )

        if not master_passed:

            print(
                f"{name}: MASTER REJECTED - "
                f"{master_reason} | "
                f"AI={final_ai_score} "
                f"Quality={quality_score}"
            )

            return None

        # =================================================
        # NO TRADE FILTER
        # =================================================

        try:

            final_trade = (
                apply_no_trade_filter(
                    signal,
                    final_ai_score,
                    news_risk,
                    entry_quality
                )
            )

        except Exception as e:

            print(
                f"{name}: No trade filter error: {e}"
            )

            return None

        final_signal = final_trade.get(
            "signal"
        )

        final_reason = final_trade.get(
            "reason",
            "No trade filter passed"
        )

        # =================================================
        # FINAL SIGNAL MUST MATCH
        # =================================================

        if final_signal != signal:

            print(
                f"{name}: Signal changed "
                f"by final filter"
            )

            return None

        # =================================================
        # FINAL AI CHECK
        # =================================================

        if final_ai_score < MIN_AI_SCORE:

            print(
                f"{name}: "
                f"AI Score {final_ai_score} "
                f"< {MIN_AI_SCORE}"
            )

            return None

        # =================================================
        # FINAL QUALITY CHECK
        # =================================================

        if quality_score < MIN_QUALITY_SCORE:

            print(
                f"{name}: "
                f"Quality {quality_score} "
                f"< {MIN_QUALITY_SCORE}"
            )

            return None

        # =================================================
        # FINAL ENTRY CHECK
        # =================================================

        if entry_quality != "A":

            print(
                f"{name}: "
                f"Entry Quality is not A"
            )

            return None

        # =================================================
        # FINAL TP/SL CHECK
        # =================================================

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
                f"Final TP/SL failed - "
                f"{level_reason}"
            )

            return None

        # =================================================
        # DUPLICATE SIGNAL FILTER
        # =================================================

        try:

            if not allow_new_signal(
                final_signal,
                price
            ):

                print(
                    f"{name}: "
                    f"Duplicate signal blocked"
                )

                return None

        except Exception as e:

            print(
                f"{name}: "
                f"Signal memory error: {e}"
            )

            return None

        # =================================================
        # SAVE SIGNAL
        # =================================================

        try:

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

        except Exception as e:

            print(
                f"{name}: Save error: {e}"
            )

            return None

        # =================================================
        # REASONS
        # =================================================

        reasons.append(
            "✅ MASTER QUALITY FILTER PASSED"
        )

        reasons_text = "\n".join(
            reasons
        )

        # =================================================
        # DIRECTION
        # =================================================

        direction = (
            "BUY"
            if final_signal == "🟢 BUY"
            else "SELL"
        )

        # =================================================
        # MESSAGE
        # =================================================

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

━━━━━━━━━━━━━━━━━━━━

Entry Quality:
{entry_quality}

AI Score:
{final_ai_score}/100

Smart Score:
{smart_score}/100

Quality Score:
{quality_score}/100

Target Win Rate:
{TARGET_WIN_RATE}%

━━━━━━━━━━━━━━━━━━━━

Decision:
{smart.get("decision", "Strong setup")}

Final Filter:
{final_reason}

Master Filter:
{master_reason}

ATR:
{atr_value:.5f}

RSI:
{r:.2f}

MACD:
{m:.5f}

ADX:
{adx_value:.2f}

Volume:
{"CONFIRMED" if volume_confirmed else "LOW"}

News Risk:
{news_risk}

News:
{news.get("message", "No news message")}

━━━━━━━━━━━━━━━━━━━━

Reasons:
{reasons_text}

Timeframe:
M5
"""

        print(
            f"{name}: "
            f"MASTER PASSED | "
            f"AI={final_ai_score} | "
            f"Quality={quality_score} | "
            f"Entry={entry_quality}"
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

    # =====================================================
    # WEEKEND GLOBAL FILTER
    # =====================================================

    weekday = datetime.datetime.utcnow().weekday()

    if weekday in [5, 6]:

        print(
            "Weekend - no signals"
        )

        return

    # =====================================================
    # TELEGRAM
    # =====================================================

    if not TOKEN or not CHAT_ID:

        print(
            "ERROR: "
            "TELEGRAM_TOKEN or "
            "TELEGRAM_CHAT_ID missing"
        )

        return

    bot = Bot(
        token=TOKEN
    )

    messages = []

    # =====================================================
    # ANALYZE MARKETS
    # =====================================================

    for symbol, name in MARKETS:

        print(
            f"Analyzing {name}..."
        )

        result = analyze_market(
            symbol,
            name
        )

        if result:

            messages.append(
                result
            )

    # =====================================================
    # SEND SIGNALS
    # =====================================================

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

Minimum AI Score:
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
            "High quality signals sent"
        )

    else:

        print(
            "No 80+ quality BUY/SELL signals"
        )


# =========================================================
# START
# =========================================================

if __name__ == "__main__":

    asyncio.run(main())
