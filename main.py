import os
import asyncio
import yfinance as yf
import pandas as pd
import ta

from telegram import Bot


TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")


def analyze_gold():
    data = yf.download(
        "GC=F",
        period="5d",
        interval="15m",
        progress=False
    )

    if data.empty:
        return "❌ دریافت اطلاعات طلا ناموفق بود"

    close = data["Close"]

    data["EMA50"] = ta.trend.ema_indicator(close, window=50)
    data["EMA200"] = ta.trend.ema_indicator(close, window=200)
    data["RSI"] = ta.momentum.rsi(close, window=14)

    macd = ta.trend.MACD(close)
    data["MACD"] = macd.macd()
    data["MACD_SIGNAL"] = macd.macd_signal()

    last = data.iloc[-1]

    score = 0
    reasons = []

    if last["EMA50"] > last["EMA200"]:
        score += 1
        reasons.append("✅ Trend bullish")
    else:
        score -= 1
        reasons.append("❌ Trend bearish")

    if last["MACD"] > last["MACD_SIGNAL"]:
        score += 1
        reasons.append("✅ MACD positive")
    else:
        score -= 1
        reasons.append("❌ MACD negative")

    if 50 < last["RSI"] < 70:
        score += 1
        reasons.append("✅ RSI مناسب")

    elif 30 < last["RSI"] < 50:
        score -= 1
        reasons.append("⚠️ RSI ضعیف")

    if score >= 2:
        signal = "🟢 BUY"
    elif score <= -2:
        signal = "🔴 SELL"
    else:
        signal = "⚪ NO SIGNAL"

    return f"""
🥇 QuantumGold AI Signal

XAU/USD

Signal: {signal}

RSI: {last['RSI']:.2f}

Score: {score}/3

Reasons:
{"\n".join(reasons)}
"""


async def main():

    bot = Bot(token=TOKEN)

    message = analyze_gold()

    await bot.send_message(
        chat_id=CHAT_ID,
        text=message
    )

    print("Signal sent")


if __name__ == "__main__":
    asyncio.run(main())
