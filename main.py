import os
import asyncio
import yfinance as yf
import ta

from telegram import Bot


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
        # Gold
        gold = get_data("GC=F")

        # Dollar Index
        dxy = get_data("DX-Y.NYB")


        if gold is None:
            return "❌ Gold data unavailable"

        price = float(gold.iloc[-1])


        ema50 = ta.trend.ema_indicator(
            gold, 50
        )

        ema200 = ta.trend.ema_indicator(
            gold, 200
        )

        rsi = ta.momentum.rsi(
            gold, 14
        )


        e50 = float(ema50.iloc[-1])
        e200 = float(ema200.iloc[-1])
        r = float(rsi.iloc[-1])


        score = 0
        reasons = []


        # Gold trend
        if e50 > e200:
            score += 25
            reasons.append("✅ Gold trend bullish")
        else:
            score -= 25
            reasons.append("❌ Gold trend bearish")


        # RSI
        if r > 50:
            score += 15
            reasons.append("✅ RSI positive")
        else:
            score -= 15
            reasons.append("⚠️ RSI weak")


        # DXY filter
        dxy_status = "Unknown"

        if dxy is not None:

            dxy_now = float(dxy.iloc[-1])
            dxy_old = float(dxy.iloc[-20])

            if dxy_now < dxy_old:
                score += 20
                dxy_status = "🔻 DXY falling (Gold support)"
            else:
                score -= 20
                dxy_status = "🔺 DXY rising (Gold pressure)"


        if score >= 40:
            signal = "🟢 BUY"

        elif score <= -40:
            signal = "🔴 SELL"

        else:
            signal = "⚪ WAIT"


        confidence = abs(score)


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

DXY:
{dxy_status}


Analysis:
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

    print("DXY AI Signal sent")


if __name__ == "__main__":
    asyncio.run(main())
