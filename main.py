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
            return "❌ داده طلا دریافت نشد"

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

        last_price = float(close.iloc[-1])
        last_ema50 = float(ema50.iloc[-1])
        last_ema200 = float(ema200.iloc[-1])
        last_rsi = float(rsi.iloc[-1])

        score = 0
        reasons = []

        if last_ema50 > last_ema200:
            score += 1
            reasons.append("✅ روند صعودی")
        else:
            score -= 1
            reasons.append("❌ روند نزولی")

        if last_rsi > 50:
            score += 1
            reasons.append("✅ قدرت خریداران")
        else:
            score -= 1
            reasons.append("⚠️ قدرت فروشندگان")

        if score >= 2:
            signal = "🟢 BUY"
        elif score <= -2:
            signal = "🔴 SELL"
        else:
            signal = "⚪ WAIT"

        return f"""
🥇 QuantumGold AI Signal

Symbol: XAU/USD

Signal: {signal}

Price: {last_price:.2f}

EMA50: {last_ema50:.2f}
EMA200: {last_ema200:.2f}

RSI: {last_rsi:.2f}

Score: {score}/2

Analysis:
{"\n".join(reasons)}
"""

    except Exception as e:
        return f"❌ Analysis Error:\n{str(e)}"


async def main():
    if not TOKEN or not CHAT_ID:
        print("Missing Telegram settings")
        return

    bot = Bot(token=TOKEN)

    message = analyze_gold()

    await bot.send_message(
        chat_id=CHAT_ID,
        text=message
    )

    print("Signal sent")


if __name__ == "__main__":
    asyncio.run(main())
