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
            period="20d",
            interval="15m",
            progress=False
        )

        if data.empty:
            return "❌ No gold data received"

        close = data["Close"]

        if hasattr(close, "columns"):
            close = close.iloc[:, 0]

        high = data["High"]
        low = data["Low"]

        if hasattr(high, "columns"):
            high = high.iloc[:, 0]

        if hasattr(low, "columns"):
            low = low.iloc[:, 0]


        # Indicators
        ema50 = ta.trend.ema_indicator(close, window=50)
        ema200 = ta.trend.ema_indicator(close, window=200)

        rsi = ta.momentum.rsi(close, window=14)

        macd = ta.trend.MACD(close)

        atr = ta.volatility.average_true_range(
            high,
            low,
            close,
            window=14
        )


        price = float(close.iloc[-1])
        e50 = float(ema50.iloc[-1])
        e200 = float(ema200.iloc[-1])
        r = float(rsi.iloc[-1])
        m = float(macd.macd().iloc[-1])
        ms = float(macd.macd_signal().iloc[-1])
        a = float(atr.iloc[-1])


        # Support / Resistance
        support = float(low.tail(50).min())
        resistance = float(high.tail(50).max())


        score = 0
        reasons = []


        if e50 > e200:
            score += 1
            reasons.append("✅ EMA bullish")
        else:
            score -= 1
            reasons.append("❌ EMA bearish")


        if r > 50:
            score += 1
            reasons.append("✅ RSI buyers")
        else:
            score -= 1
            reasons.append("⚠️ RSI weak")


        if m > ms:
            score += 1
            reasons.append("✅ MACD positive")
        else:
            score -= 1
            reasons.append("❌ MACD negative")


        if price > support and price < resistance:
            score += 1
            reasons.append("✅ Good market zone")


        if score >= 3:
            signal = "🟢 BUY"
        elif score <= -3:
            signal = "🔴 SELL"
        else:
            signal = "⚪ WAIT"


        confidence = abs(score) / 4 * 100


        return f"""
🥇 QuantumGold AI Signal

XAU/USD

Signal: {signal}

Confidence: {confidence:.0f}%

Price: {price:.2f}

Support: {support:.2f}
Resistance: {resistance:.2f}

EMA50: {e50:.2f}
EMA200: {e200:.2f}

RSI: {r:.2f}

MACD:
{m:.4f}

ATR:
{a:.2f}

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

    print("Advanced Signal sent")


if __name__ == "__main__":
    asyncio.run(main())
