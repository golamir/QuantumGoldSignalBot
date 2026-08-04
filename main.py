import os
import asyncio
import csv
from datetime import datetime

import yfinance as yf
import ta

from telegram import Bot


TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

FILE = "signals.csv"


def save_signal(data):
    file_exists = os.path.isfile(FILE)

    with open(FILE, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)

        if not file_exists:
            writer.writerow([
                "time",
                "price",
                "signal",
                "confidence",
                "rsi",
                "ema50",
                "ema200",
                "macd"
            ])

        writer.writerow(data)


def analyze_gold():

    data = yf.download(
        "GC=F",
        period="30d",
        interval="15m",
        progress=False
    )

    if data.empty:
        return "❌ No data"


    close = data["Close"]

    if hasattr(close, "columns"):
        close = close.iloc[:,0]


    ema50 = ta.trend.ema_indicator(close,50)
    ema200 = ta.trend.ema_indicator(close,200)
    rsi = ta.momentum.rsi(close,14)

    macd = ta.trend.MACD(close)


    price = float(close.iloc[-1])
    e50 = float(ema50.iloc[-1])
    e200 = float(ema200.iloc[-1])
    r = float(rsi.iloc[-1])

    m = float(macd.macd().iloc[-1])
    ms = float(macd.macd_signal().iloc[-1])


    score = 0


    if e50 > e200:
        score += 25

    else:
        score -= 25


    if m > ms:
        score += 25

    else:
        score -= 25


    if r > 50:
        score += 25

    else:
        score -= 25


    if price > e50:
        score += 25


    confidence = max(0, abs(score))


    if score >= 50:
        signal = "🟢 BUY"

    elif score <= -50:
        signal = "🔴 SELL"

    else:
        signal = "⚪ WAIT"


    save_signal([
        datetime.now(),
        price,
        signal,
        confidence,
        r,
        e50,
        e200,
        m
    ])


    return f"""
🥇 QuantumGold AI Signal

XAU/USD

Signal: {signal}

Confidence: {confidence}%

Price: {price:.2f}

RSI: {r:.2f}

EMA50: {e50:.2f}

EMA200: {e200:.2f}

MACD: {m:.4f}

🧠 Signal saved
"""


async def main():

    bot = Bot(token=TOKEN)

    message = analyze_gold()

    await bot.send_message(
        chat_id=CHAT_ID,
        text=message
    )

    print("Saved and sent")


if __name__ == "__main__":
    asyncio.run(main())
