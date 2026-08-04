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

    return data


def analyze_gold():

    try:
        news = check_news()

        gold = get_data("GC=F")
        dxy_data = get_data("DX-Y.NYB")

        if gold is None:
            return "❌ Gold data unavailable"


        close = gold["Close"]
        high = gold["High"]
        low = gold["Low"]

        if hasattr(close, "columns"):
            close = close.iloc[:, 0]
            high = high.iloc[:, 0]
            low = low.iloc[:, 0]


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
                dxy = dxy.iloc[:,0]

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

            stop_loss = price - (atr_value * 2)
            take1 = price + (atr_value * 2)
            take2 = price + (atr_value * 3)

        elif score <= -50:
            signal = "🔴 SELL"

            stop_loss = price + (atr_value * 2)
            take1 = price - (atr_value * 2)
            take2 = price - (atr_value * 3)

        else:
            signal = "⚪ WAIT"

            stop_loss = 0
            take1 = 0
            take2 = 0


        confidence = abs(score)


        return f"""
🥇 QuantumGold AI Signal

XAU/USD

Signal:
{signal}

Confidence:
{confidence}%

Entry:
{price:.2f}

Stop Loss:
{stop_loss:.2f}

Take Profit 1:
{take1:.2f}

Take Profit 2:
{take2:.2f}


ATR:
{atr_value:.2f}

EMA50:
{e50:.2f}

EMA200:
{e200:.2f}

RSI:
{r:.2f}

MACD:
{m:.4f}


News:
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

    print("ATR Risk Signal sent")


if __name__ == "__main__":
    asyncio.run(main())
