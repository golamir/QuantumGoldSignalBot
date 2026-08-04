import os
import asyncio
import yfinance as yf
import ta

from telegram import Bot

from news_filter import check_news
from trade_memory import save_trade, get_trade_count
from live_price import get_live_gold_price
from support_resistance import find_support_resistance
from entry_filter import check_entry
from smart_score import calculate_score
from no_trade_filter import apply_no_trade_filter


TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")


def get_data(symbol):

    data = yf.download(
        symbol,
        period="7d",
        interval="5m",
        progress=False
    )

    if data.empty:
        return None

    return data


def analyze_gold():

    try:

        news = check_news()

        gold = get_data("GC=F")
        dxy_data = get_data("DX-Y.NYB")

        live_price = get_live_gold_price()

        if gold is None:
            return "❌ Gold data unavailable"


        close = gold["Close"]
        high = gold["High"]
        low = gold["Low"]


        if hasattr(close, "columns"):
            close = close.iloc[:, 0]
            high = high.iloc[:, 0]
            low = low.iloc[:, 0]


        sr = find_support_resistance(close)


        ema50 = ta.trend.ema_indicator(close, window=50)

        ema200 = ta.trend.ema_indicator(close, window=200)

        rsi = ta.momentum.rsi(close, window=14)

        macd = ta.trend.MACD(close)

        atr = ta.volatility.average_true_range(
            high,
            low,
            close,
            14
        )


        price = live_price if live_price else float(close.iloc[-1])


        e50 = float(ema50.iloc[-1])
        e200 = float(ema200.iloc[-1])

        r = float(rsi.iloc[-1])

        m = float(macd.macd().iloc[-1])
        ms = float(macd.macd_signal().iloc[-1])

        atr_value = float(atr.iloc[-1])


        score = 0
        reasons = []

        if e50 > e200:
            score += 25
            reasons.append("✅ EMA bullish")
        else:
            score -= 25
            reasons.append("❌ EMA bearish")


        if r > 50:
            score += 15
            reasons.append("✅ RSI positive")
        else:
            score -= 15
            reasons.append("⚠️ RSI weak")


        if m > ms:
            score += 25
            reasons.append("✅ MACD positive")
        else:
            score -= 25
            reasons.append("❌ MACD negative")


        if dxy_data is not None:

            dxy = dxy_data["Close"]

            if hasattr(dxy, "columns"):
                dxy = dxy.iloc[:, 0]

            if float(dxy.iloc[-1]) < float(dxy.iloc[-20]):
                score += 15
                reasons.append("✅ DXY supports gold")
            else:
                score -= 15
                reasons.append("❌ DXY pressure")


        if news["risk"] == "HIGH":
            score -= 20
            reasons.append("⚠️ News risk")


        if score >= 50:
            signal = "🟢 BUY"
            stop_loss = price - atr_value * 2
            take_profit = price + atr_value * 2

        elif score <= -50:
            signal = "🔴 SELL"
            stop_loss = price + atr_value * 2
            take_profit = price - atr_value * 2

        else:
            signal = "⚪ WAIT"
            stop_loss = 0
            take_profit = 0


        confidence = abs(score)


        entry = check_entry(
            signal,
            price,
            sr["support"],
            sr["resistance"],
            r,
            confidence
        )

        entry_reasons = "\n".join(entry["reasons"])


        smart = calculate_score(
            signal,
            confidence,
            price,
            sr["support"],
            sr["resistance"],
            news["risk"]
        )

        smart_reasons = "\n".join(smart["reasons"])


        final_trade = apply_no_trade_filter(
            signal,
            smart["score"],
            news["risk"],
            entry["quality"]
        )

        final_signal = final_trade["signal"]
        final_reason = final_trade["reason"]


        save_trade(
            final_signal,
            price,
            confidence,
            stop_loss,
            take_profit
        )


        reasons_text = "\n".join(reasons)


        return f"""
🥇 QuantumGold AI Signal

XAU/USD

Signal:
{final_signal}

Confidence:
{confidence}%

Live Price:
{price:.2f}

Stop Loss:
{stop_loss:.2f}

Take Profit:
{take_profit:.2f}

Stored Signals:
{get_trade_count()}

Support:
{sr["support"]:.2f}

Resistance:
{sr["resistance"]:.2f}

Entry Quality:
{entry["quality"]}

Entry Analysis:
{entry_reasons}

AI Score:
{smart["score"]}/100

Decision:
{smart["decision"]}

Final Filter:
{final_reason}

Smart Analysis:
{smart_reasons}

ATR:
{atr_value:.2f}

RSI:
{r:.2f}

MACD:
{m:.4f}

News:
{news["message"]}

Reasons:
{reasons_text}

Timeframe:
M5
"""


    except Exception as e:
        return f"❌ Error:\n{e}"


async def main():

    print("Starting QuantumGold AI")

    bot = Bot(token=TOKEN)

    message = analyze_gold()

    await bot.send_message(
        chat_id=CHAT_ID,
        text=message
    )

    print("Signal sent successfully")


if __name__ == "__main__":
    asyncio.run(main())
