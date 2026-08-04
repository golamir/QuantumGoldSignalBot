import os
import asyncio
import yfinance as yf
import ta

from telegram import Bot


TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")


def analyze_gold():
    try:
        print("Downloading gold data...")

        data = yf.download(
            "GC=F",
            period="10d",
            interval="15m",
            progress=False
        )

        print("Rows:", len(data))

        if data.empty:
            return "❌ No gold data received"

        close = data["Close"]

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

        price = float(close.iloc[-1])
        e50 = float(ema50.iloc[-1])
        e200 = float(ema200.iloc[-1])
        r = float(rsi.iloc[-1])

        if e50 > e200 and r > 50:
            signal = "🟢 BUY"
        elif e50 < e200 and r < 50:
            signal = "🔴 SELL"
        else:
            signal = "⚪ WAIT"

        return f"""
🥇 QuantumGold AI Signal

XAU/USD

Signal: {signal}

Price: {price:.2f}

EMA50: {e50:.2f}
EMA200: {e200:.2f}

RSI: {r:.2f}

Timeframe: M15
"""

    except Exception as e:
        print("Analysis error:", e)
        return f"❌ Error:\n{e}"


async def main():

    print("Starting QuantumGoldSignalBot")

    print("TOKEN exists:", bool(TOKEN))
    print("CHAT_ID exists:", bool(CHAT_ID))

    if not TOKEN or not CHAT_ID:
        print("Missing Telegram settings")
        return

    bot = Bot(token=TOKEN)

    message = analyze_gold()

    await bot.send_message(
        chat_id=CHAT_ID,
        text=message
    )

    print("Signal sent successfully")


if __name__ == "__main__":
    asyncio.run(main())
