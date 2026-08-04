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
            period="30d",
            interval="15m",
            progress=False
        )

        if data.empty:
            return "❌ No gold data received"

        close = data["Close"]
        high = data["High"]
        low = data["Low"]
        open_price = data["Open"]

        if hasattr(close, "columns"):
            close = close.iloc[:, 0]
            high = high.iloc[:, 0]
            low = low.iloc[:, 0]
            open_price = open_price.iloc[:, 0]


        ema50 = ta.trend.ema_indicator(close, 50)
        ema200 = ta.trend.ema_indicator(close, 200)

        rsi = ta.momentum.rsi(close, 14)

        macd = ta.trend.MACD(close)

        atr = ta.volatility.average_true_range(
            high,
            low,
            close,
            14
        )


        price = float(close.iloc[-1])
        e50 = float(ema50.iloc[-1])
        e200 = float(ema200.iloc[-1])
        r = float(rsi.iloc[-1])
        macd_line = float(macd.macd().iloc[-1])
        macd_sig = float(macd.macd_signal().iloc[-1])
        atr_value = float(atr.iloc[-1])


        score = 0
        factors = []


        # Trend 25%
        if e50 > e200:
            score += 25
            factors.append("✅ EMA Trend +25")
        else:
            score -= 25
            factors.append("❌ EMA Trend -25")


        # MACD 25%
        if macd_line > macd_sig:
            score += 25
            factors.append("✅ MACD +25")
        else:
            score -= 25
            factors.append("❌ MACD -25")


        # RSI 15%
        if 50 < r < 70:
            score += 15
            factors.append("✅ RSI +15")
        elif 30 < r < 50:
            score -= 15
            factors.append("❌ RSI -15")


        # ATR 15
        if atr_value > 0:
            score += 15
            factors.append("✅ Volatility OK +15")


        # Candle 20
        o = float(open_price.iloc[-1])
        c = float(close.iloc[-1])

        if c > o:
            score += 20
            factors.append("✅ Bullish Candle +20")
        else:
            score -= 20
            factors.append("❌ Bearish Candle -20")


        confidence = max(0, min(abs(score), 100))


        if score >= 60:
            signal = "🟢 STRONG BUY"
        elif score <= -60:
            signal = "🔴 STRONG SELL"
        else:
            signal = "⚪ WAIT"


        return f"""
🥇 QuantumGold AI Signal

XAU/USD

Signal:
{signal}

AI Confidence:
{confidence}%

Price:
{price:.2f}

EMA50:
{e50:.2f}

EMA200:
{e200:.2f}

RSI:
{r:.2f}

ATR:
{atr_value:.2f}


Factors:
{"\n".join(factors)}

Timeframe:
M15
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

    print("AI Scoring Signal sent")


if __name__ == "__main__":
    asyncio.run(main())
