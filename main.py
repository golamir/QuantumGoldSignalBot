import os
import asyncio
import yfinance as yf
import ta

from telegram import Bot


TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")


def analyze_gold():
    try:
        data = yf.download(
            "GC=F",
            period="10d",
            interval="15m",
            progress=False
        )

        if data.empty:
            return "❌ No gold data received"

        close = data["Close"]

        if hasattr(close, "columns"):
            close = close.iloc[:, 0]

        ema50 = ta.trend.ema_indicator(close, window=50)
        ema200 = ta.trend.ema_indicator(close, window=200)

        rsi = ta.momentum.rsi(close, window=14)

        macd = ta.trend.MACD(close)

        macd_line = macd.macd()
        macd_signal = macd.macd_signal()

        price = float(close.iloc[-1])
        e50 = float(ema50.iloc[-1])
        e200 = float(ema200.iloc[-1])
        r = float(rsi.iloc[-1])
        m = float(macd_line.iloc[-1])
        ms = float(macd_signal.iloc[-1])

        score = 0
        reasons = []

        # Trend
        if e50 > e200:
            score += 1
            reasons.append("✅ EMA trend bullish")
        else:
            score -= 1
            reasons.append("❌ EMA trend bearish")

        # RSI
        if 50 < r < 70:
            score += 1
            reasons.append("✅ RSI supports buyers")
        elif 30 < r < 50:
            score -= 1
            reasons.append("⚠️ RSI supports sellers")

        # MACD
        if m > ms:
            score += 1
            reasons.append("✅ MACD positive")
        else:
            score -= 1
            reasons.append("❌ MACD negative")

        if score >= 2:
            signal = "🟢 BUY"
        elif score <= -2:
            signal = "🔴 SELL"
        else:
            signal = "⚪ WAIT"

        confidence = abs(score) / 3 * 100

        return f"""
🥇 QuantumGold AI Signal

XAU/USD

Signal: {signal}

Confidence: {confidence:.0f}%

Price: {price:.2f}

EMA50: {e50:.2f}
EMA200: {e200:.2f}

RSI: {r:.2f}

MACD:
{m:.4f}

Reasons:
{"\n".join(reasons)}

Timeframe: M15
"""

    except Exception as e:
        return f"❌ Error:\n{e}"


async def main():

    bot = Bot(token=TOKEN)

    message = analyze_gold()

    await bot.send_message(
        chat_id=CHAT_ID,
        text=message
    )

    print("AI Signal sent")


if __name__ == "__main__":
    asyncio.run(main())
