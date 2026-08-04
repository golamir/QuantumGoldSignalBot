import os
import asyncio
import yfinance as yf
import ta

from telegram import Bot
from news_filter import check_news


TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")


def get_data(symbol):
    data = yf.download(
        symbol,
        period="30d",
        interval="15m",
        progress=False
    )

    if data.empty:
        return None

    close = data["Close"]

    if hasattr(close, "columns"):
        close = close.iloc[:, 0]

    return close


def analyze_gold():

    try:
        news = check_news()

        gold = get_data("GC=F")
        dxy = get_data("DX-Y.NYB")

        if gold is None:
            return "❌ Gold data unavailable"


        ema50 = ta.trend.ema_indicator(gold, 50)
        ema200 = ta.trend.ema_indicator(gold, 200)
        rsi = ta.momentum.rsi(gold, 14)

        macd = ta.trend.MACD(gold)


        price = float(gold.iloc[-1])
        e50 = float(ema50.iloc[-1])
        e200 = float(ema200.iloc[-1])
        r = float(rsi.iloc[-1])

        m = float(macd.macd().iloc[-1])
        ms = float(macd.macd_signal().iloc[-1])


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


        if dxy is not None:
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

        elif score <= -50:
            signal = "🔴 SELL"

        else:
            signal = "⚪ WAIT"


        confidence = abs(score)


        return f"""
🥇 QuantumGold AI Signal

XAU/USD

Signal:
{signal}

Confidence:
{confidence}%

Price:
{price:.2f}

EMA50:
{e50:.2f}

EMA200:
{e200:.2f}

RSI:
{r:.2f}

MACD:
{m:.4f}

News Filter:
{news["message"]}


Reasons:
{"\n".join(reasons)}

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

    print("Advanced AI Signal sent")


if __name__ == "__main__":
    asyncio.run(main())
