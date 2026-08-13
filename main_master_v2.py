import os
import asyncio
import datetime
import math

import yfinance as yf
import ta
from telegram import Bot

from news_filter import check_news
from daily_report import save_signal, get_report
from signal_memory import allow_new_signal
from trade_memory import save_trade, get_trade_count, save_last_signal
from live_price import get_live_gold_price
from support_resistance import find_support_resistance
from entry_filter import check_entry
from smart_score import calculate_score
from no_trade_filter import apply_no_trade_filter

TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
MIN_AI_SCORE = 80
MIN_QUALITY_SCORE = 80
MIN_ADX = 25
TARGET_WIN_RATE = 85  # design target, not a guaranteed/measured win rate
CRYPTO_ENABLED = False
SWING_LOOKBACK = 3
STRUCTURE_LOOKBACK = 40
LIQUIDITY_LOOKBACK = 30

MARKETS = [
    ("GC=F", "XAU/USD"),
    ("EURUSD=X", "EUR/USD"),
    ("GBPUSD=X", "GBP/USD"),
    ("USDJPY=X", "USD/JPY"),
    ("USDCHF=X", "USD/CHF"),
    ("AUDUSD=X", "AUD/USD"),
    ("USDCAD=X", "USD/CAD"),
    ("NZDUSD=X", "NZD/USD"),
]


def is_valid_number(value):
    try:
        value = float(value)
        return math.isfinite(value) and value > 0
    except Exception:
        return False


def get_price_decimals(symbol):
    if symbol == "GC=F": return 2
    if symbol in ["BTC-USD", "ETH-USD", "SOL-USD", "BNB-USD"]: return 2
    if symbol == "USDJPY=X": return 3
    return 5


def format_price(value, symbol):
    return f"{float(value):.{get_price_decimals(symbol)}f}"


def is_weekend():
    return datetime.datetime.utcnow().weekday() in [5, 6]


def safe_float(series, index=-1):
    try:
        value = float(series.iloc[index])
        return value if math.isfinite(value) else None
    except Exception:
        return None


def get_data(symbol, interval="5m"):
    try:
        print(f"Downloading {symbol} {interval} data...")
        period = {"5m": "7d", "15m": "60d", "1h": "730d"}.get(interval, "60d")
        data = yf.download(tickers=symbol, period=period, interval=interval,
                           progress=False, auto_adjust=False, threads=False)
        if data is None or data.empty:
            print(f"{symbol}: EMPTY DATA interval={interval}")
            return None
        if getattr(data.columns, "nlevels", 1) > 1:
            data.columns = [col[0] if isinstance(col, tuple) else col for col in data.columns]
        required = ["Close", "High", "Low", "Volume"]
        missing = [c for c in required if c not in data.columns]
        if missing:
            print(f"{symbol}: missing columns {missing}")
            return None
        data = data.dropna(subset=["Close", "High", "Low"])
        if len(data) < 60:
            print(f"{symbol}: insufficient data ({len(data)} candles)")
            return None
        return data
    except Exception as e:
        print(f"Data error {symbol} {interval}: {e}")
        return None


def prepare_data(symbol, interval="5m"):
    data = get_data(symbol, interval)
    if data is None:
        return None
    try:
        close, high, low, volume = data["Close"], data["High"], data["Low"], data["Volume"]
        if hasattr(close, "columns"): close = close.iloc[:, 0]
        if hasattr(high, "columns"): high = high.iloc[:, 0]
        if hasattr(low, "columns"): low = low.iloc[:, 0]
        if hasattr(volume, "columns"): volume = volume.iloc[:, 0]
        close, high, low, volume = close.dropna(), high.dropna(), low.dropna(), volume.fillna(0)
        if len(close) < 220:
            print(f"{symbol}: insufficient prepared data ({len(close)})")
            return None
        return {"close": close, "high": high, "low": low, "volume": volume}
    except Exception as e:
        print(f"Prepare data error {symbol}: {e}")
        return None


def find_recent_swings(high, low, lookback=SWING_LOOKBACK):
    highs, lows = [], []
    start = max(lookback, len(high) - STRUCTURE_LOOKBACK)
    for i in range(start, len(high) - lookback):
        if float(high.iloc[i]) > float(high.iloc[i-lookback:i].max()) and float(high.iloc[i]) > float(high.iloc[i+1:i+lookback+1].max()):
            highs.append((i, float(high.iloc[i])))
        if float(low.iloc[i]) < float(low.iloc[i-lookback:i].min()) and float(low.iloc[i]) < float(low.iloc[i+1:i+lookback+1].min()):
            lows.append((i, float(low.iloc[i])))
    return highs, lows


def analyze_structure(close, high, low):
    try:
        last_i = len(close) - 2
        if last_i < 10:
            return {"bullish_bos": False, "bearish_bos": False, "bullish_choch": False, "bearish_choch": False}
        highs, lows = find_recent_swings(high.iloc[:last_i+1], low.iloc[:last_i+1])
        rh, rl = highs[-3:], lows[-3:]
        swing_high = rh[-1][1] if rh else None
        swing_low = rl[-1][1] if rl else None
        last_close = float(close.iloc[last_i])
        bullish_bos = swing_high is not None and last_close > swing_high
        bearish_bos = swing_low is not None and last_close < swing_low
        bullish_choch = len(rh) >= 2 and last_close > rh[-2][1]
        bearish_choch = len(rl) >= 2 and last_close < rl[-2][1]
        return {"bullish_bos": bullish_bos, "bearish_bos": bearish_bos,
                "bullish_choch": bullish_choch, "bearish_choch": bearish_choch}
    except Exception as e:
        print(f"Structure analysis error: {e}")
        return {"bullish_bos": False, "bearish_bos": False, "bullish_choch": False, "bearish_choch": False}


def detect_liquidity_sweep(close, high, low):
    try:
        i = len(close) - 2
        start = max(0, i - LIQUIDITY_LOOKBACK)
        if i <= start: return {"bullish": False, "bearish": False}
        prior_high, prior_low = float(high.iloc[start:i].max()), float(low.iloc[start:i].min())
        ch, cl, cc = float(high.iloc[i]), float(low.iloc[i]), float(close.iloc[i])
        return {"bullish": cl < prior_low and cc > prior_low,
                "bearish": ch > prior_high and cc < prior_high}
    except Exception as e:
        print(f"Liquidity sweep error: {e}")
        return {"bullish": False, "bearish": False}


def detect_fvg(close, high, low, atr_value):
    try:
        i = len(close) - 2
        if i < 2 or atr_value <= 0: return {"bullish": False, "bearish": False}
        bullish_gap = float(low.iloc[i]) - float(high.iloc[i-2])
        bearish_gap = float(low.iloc[i-2]) - float(high.iloc[i])
        minimum_gap = atr_value * 0.05
        return {"bullish": bullish_gap > minimum_gap, "bearish": bearish_gap > minimum_gap}
    except Exception as e:
        print(f"FVG detection error: {e}")
        return {"bullish": False, "bearish": False}


def detect_displacement(close, high, low, atr_value):
    try:
        i = len(close) - 2
        if i < 1 or atr_value <= 0: return {"bullish": False, "bearish": False}
        previous_close, current_close = float(close.iloc[i-1]), float(close.iloc[i])
        candle_range, body = float(high.iloc[i] - low.iloc[i]), abs(current_close - previous_close)
        strong = body >= atr_value * 0.60 and candle_range >= atr_value * 0.80
        return {"bullish": current_close > previous_close and strong,
                "bearish": current_close < previous_close and strong}
    except Exception as e:
        print(f"Displacement error: {e}")
        return {"bullish": False, "bearish": False}


def validate_trade_levels(signal, price, stop_loss, tp1, tp2, tp3):
    try:
        if not all(is_valid_number(x) for x in [price, stop_loss, tp1, tp2, tp3]):
            return False, "Invalid price values"
        if signal == "🟢 BUY":
            valid = stop_loss < price and tp1 > price and tp2 > tp1 and tp3 > tp2
        elif signal == "🔴 SELL":
            valid = stop_loss > price and tp1 < price and tp2 < tp1 and tp3 < tp2
        else:
            return False, "Invalid signal"
        if not valid: return False, "Invalid TP/SL structure"
        risk, reward = abs(price-stop_loss), abs(tp3-price)
        if risk <= 0: return False, "Zero risk"
        rr = reward / risk
        if rr < 1.20: return False, f"Risk/Reward too low ({rr:.2f})"
        return True, f"Valid TP/SL R:R={rr:.2f}"
    except Exception as e:
        return False, f"TP/SL validation error: {e}"


def calculate_quality_score(signal, ema_bullish, m15_bullish, h1_bullish, macd_bullish,
                            rsi_value, adx_value, volume_confirmed, news_risk, entry_quality,
                            structure_confirmed=False, liquidity_confirmed=False,
                            fvg_confirmed=False, displacement_confirmed=False):
    score = 0
    buy, sell = signal == "🟢 BUY", signal == "🔴 SELL"
    if (buy and ema_bullish) or (sell and not ema_bullish): score += 15
    if (buy and macd_bullish) or (sell and not macd_bullish): score += 15
    if (buy and m15_bullish) or (sell and not m15_bullish): score += 10
    if (buy and h1_bullish) or (sell and not h1_bullish): score += 10
    score += 15 if adx_value >= 30 else 10 if adx_value >= 25 else 5 if adx_value >= 20 else 0
    if volume_confirmed: score += 10
    if buy: score += 10 if 45 < rsi_value < 70 else 5 if 40 < rsi_value < 75 else 0
    if sell: score += 10 if 30 < rsi_value < 55 else 5 if 25 < rsi_value < 60 else 0
    score += -20 if news_risk == "HIGH" else 5 if news_risk == "MEDIUM" else 10
    score += 10 if entry_quality == "A" else 5 if entry_quality == "B" else -10
    if structure_confirmed: score += 5
    if liquidity_confirmed: score += 5
    if fvg_confirmed: score += 5
    if displacement_confirmed: score += 5
    return max(0, min(100, int(score)))


def master_quality_filter(signal, ai_score, quality_score, entry_quality, adx_value,
                          volume_confirmed, trend_aligned, rsi_valid, news_risk,
                          tp_sl_valid, structure_confirmed, liquidity_confirmed,
                          fvg_confirmed, displacement_confirmed):
    if signal not in ["🟢 BUY", "🔴 SELL"]: return False, "No clear signal"
    if ai_score < MIN_AI_SCORE: return False, f"AI Score below {MIN_AI_SCORE}"
    if quality_score < MIN_QUALITY_SCORE: return False, f"Quality below {MIN_QUALITY_SCORE}"
    if entry_quality != "A": return False, f"Entry Quality {entry_quality}"
    if adx_value < MIN_ADX: return False, f"ADX below {MIN_ADX}"
    if not volume_confirmed: return False, "Volume confirmation missing"
    if not trend_aligned: return False, "M5/M15/H1 trend conflict"
    if not rsi_valid: return False, "RSI not valid"
    if news_risk == "HIGH": return False, "HIGH news risk"
    if not tp_sl_valid: return False, "Invalid TP/SL"
    if not structure_confirmed: return False, "Market structure not confirmed"
    if not liquidity_confirmed: return False, "Liquidity confirmation missing"
    if not displacement_confirmed: return False, "Displacement confirmation missing"
    return True, "ALL MASTER V2 FILTERS PASSED"


def analyze_market(symbol, name):
    try:
        print(f"Analyzing {name}...")
        if is_weekend(): return None
        news = check_news() or {"risk": "HIGH"}
        news_risk = str(news.get("risk", "HIGH")).upper()
        m5, m15, h1 = prepare_data(symbol, "5m"), prepare_data(symbol, "15m"), prepare_data(symbol, "1h")
        if m5 is None or m15 is None or h1 is None: return None
        dxy = prepare_data("DX-Y.NYB", "5m") if symbol == "GC=F" else None
        close, high, low, volume = m5["close"], m5["high"], m5["low"], m5["volume"]
        price = get_live_gold_price() if symbol == "GC=F" else None
        if price is None or not is_valid_number(price): price = safe_float(close, -2)
        if price is None: return None
        sr = find_support_resistance(close)
        if not sr: return None
        support, resistance = float(sr["support"]), float(sr["resistance"])

        ema50, ema200 = ta.trend.ema_indicator(close, 50), ta.trend.ema_indicator(close, 200)
        rsi = ta.momentum.rsi(close, 14)
        macd = ta.trend.MACD(close)
        atr = ta.volatility.average_true_range(high, low, close, 14)
        adx = ta.trend.ADXIndicator(high, low, close, 14)
        e50, e200, r, m, ms, atr_value, adx_value = [safe_float(x, -2) for x in [ema50, ema200, rsi, macd.macd(), macd.macd_signal(), atr, adx.adx()]]
        if any(x is None for x in [e50,e200,r,m,ms,atr_value,adx_value]): return None
        ema_bullish, macd_bullish = e50 > e200, m > ms

        c15, c1 = m15["close"], h1["close"]
        m15_bullish = safe_float(ta.trend.ema_indicator(c15,50),-2) > safe_float(ta.trend.ema_indicator(c15,200),-2)
        h1_bullish = safe_float(ta.trend.ema_indicator(c1,50),-2) > safe_float(ta.trend.ema_indicator(c1,200),-2)

        v = volume.fillna(0)
        current_volume = safe_float(v, -2) or 0.0
        window = v.iloc[max(0,len(v)-52):max(1,len(v)-2)]
        avg_volume = float(window.mean()) if len(window) else 0.0
        volume_confirmed = avg_volume > 0 and current_volume >= avg_volume * 1.05

        structure = analyze_structure(close, high, low)
        liquidity = detect_liquidity_sweep(close, high, low)
        fvg = detect_fvg(close, high, low, atr_value)
        displacement = detect_displacement(close, high, low, atr_value)

        buy_score = sell_score = 0
        if ema_bullish: buy_score += 20
        else: sell_score += 20
        if macd_bullish: buy_score += 20
        else: sell_score += 20
        if m15_bullish: buy_score += 20
        else: sell_score += 20
        if h1_bullish: buy_score += 20
        else: sell_score += 20
        if 45 < r < 70: buy_score += 10
        if 30 < r < 55: sell_score += 10
        if adx_value >= 25: buy_score += 10; sell_score += 10
        if structure["bullish_bos"] or structure["bullish_choch"]: buy_score += 10
        if structure["bearish_bos"] or structure["bearish_choch"]: sell_score += 10
        if liquidity["bullish"]: buy_score += 10
        if liquidity["bearish"]: sell_score += 10
        if displacement["bullish"]: buy_score += 5
        if displacement["bearish"]: sell_score += 5

        if buy_score >= 70 and buy_score > sell_score:
            signal, preliminary = "🟢 BUY", min(100,buy_score)
        elif sell_score >= 70 and sell_score > buy_score:
            signal, preliminary = "🔴 SELL", min(100,sell_score)
        else: return None

        entry = check_entry(signal, price, support, resistance, r, preliminary)
        if not entry: return None
        entry_quality = entry.get("quality", "C")
        rsi_valid = (45 < r < 70) if signal == "🟢 BUY" else (30 < r < 55)
        trend_aligned = (ema_bullish and macd_bullish and m15_bullish and h1_bullish) if signal == "🟢 BUY" else (not ema_bullish and not macd_bullish and not m15_bullish and not h1_bullish)

        if signal == "🟢 BUY":
            structure_confirmed, liquidity_confirmed = structure["bullish_bos"] or structure["bullish_choch"], liquidity["bullish"]
            fvg_confirmed, displacement_confirmed = fvg["bullish"], displacement["bullish"]
        else:
            structure_confirmed, liquidity_confirmed = structure["bearish_bos"] or structure["bearish_choch"], liquidity["bearish"]
            fvg_confirmed, displacement_confirmed = fvg["bearish"], displacement["bearish"]

        sl_mult, tp_mult = ((2.0,3.0) if symbol == "GC=F" else (3.0,5.0) if symbol in ["BTC-USD","ETH-USD","SOL-USD","BNB-USD"] else (2.0,3.0))
        if signal == "🟢 BUY":
            stop_loss, tp1, tp2, tp3 = price-atr_value*sl_mult, price+atr_value, price+atr_value*2, price+atr_value*tp_mult
        else:
            stop_loss, tp1, tp2, tp3 = price+atr_value*sl_mult, price-atr_value, price-atr_value*2, price-atr_value*tp_mult
        valid_levels, level_reason = validate_trade_levels(signal,price,stop_loss,tp1,tp2,tp3)
        if not valid_levels: return None

        dxy_confirmed = None
        if symbol == "GC=F" and dxy is not None and len(dxy["close"]) >= 22:
            dn, do = safe_float(dxy["close"],-2), safe_float(dxy["close"],-22)
            if dn is not None and do is not None:
                dxy_confirmed = dn < do if signal == "🟢 BUY" else dn > do

        try:
            smart = calculate_score(name,signal,preliminary,price,support,resistance,news_risk)
            smart_score = int(max(0,min(100,float(smart.get("score",0)))))
            smart_decision = smart.get("decision","Unknown")
        except Exception as e:
            print(f"{name}: Smart score error: {e}"); smart_score, smart_decision = 0, "Smart score unavailable"

        quality_score = calculate_quality_score(signal,ema_bullish,m15_bullish,h1_bullish,macd_bullish,r,adx_value,volume_confirmed,news_risk,entry_quality,structure_confirmed,liquidity_confirmed,fvg_confirmed,displacement_confirmed)
        final_ai_score = max(0,min(100,int(min(smart_score,quality_score))))

        try:
            old = apply_no_trade_filter(signal,final_ai_score,news_risk,entry_quality)
            filtered_signal, old_reason = old.get("signal","⚪ WAIT"), old.get("reason","")
        except Exception as e:
            print(f"{name}: No-trade filter error: {e}"); filtered_signal, old_reason = "⚪ WAIT", "No-trade filter error"
        if filtered_signal not in ["🟢 BUY","🔴 SELL"]: return None

        passed, reason = master_quality_filter(filtered_signal,final_ai_score,quality_score,entry_quality,adx_value,volume_confirmed,trend_aligned,rsi_valid,news_risk,valid_levels,structure_confirmed,liquidity_confirmed,fvg_confirmed,displacement_confirmed)
        if not passed: return None
        final_valid, _ = validate_trade_levels(filtered_signal,price,stop_loss,tp1,tp2,tp3)
        if not final_valid: return None
        try: allowed = allow_new_signal(filtered_signal,price)
        except Exception as e: print(f"{name}: Duplicate filter error: {e}"); allowed = False
        if not allowed: return None

        try:
            save_last_signal(filtered_signal,price); save_trade(filtered_signal,price,final_ai_score,stop_loss,tp3); save_signal(filtered_signal)
        except Exception as e: print(f"{name}: Save error: {e}")

        direction = "BUY" if filtered_signal == "🟢 BUY" else "SELL"
        p = lambda x: format_price(x,symbol)
        structure_text = "BOS/CHoCH confirmed"
        reasons = ["Master V2 passed","AI Score 80+","Quality Score 80+","Entry Quality A","ADX 25+","Volume confirmed","M5/M15/H1 aligned","RSI valid",structure_text,"Liquidity sweep confirmed","Displacement confirmed"]
        if fvg_confirmed: reasons.append("FVG confirmed")
        if dxy_confirmed is True: reasons.append("DXY confirmation passed")
        reasons_text = "\n".join(f"✅ {x}" for x in reasons)

        return f"""📊 {name} {direction} NOW {p(price)}

⚠️ Stop Loss (SL): {p(stop_loss)}

🎯 TP1: {p(tp1)}
🎯 TP2: {p(tp2)}
🎯 TP3: {p(tp3)}

━━━━━━━━━━━━━━━━━━━━

🥇 QuantumGold AI Signal
MASTER FILTER V2

{name}

Signal:
{filtered_signal}

Confidence:
{final_ai_score}%

Live Price:
{p(price)}

Stop Loss:
{p(stop_loss)}

Take Profit:
{p(tp3)}

━━━━━━━━━━━━━━━━━━━━

Entry Quality: {entry_quality}
AI Score: {final_ai_score}/100
Smart Score: {smart_score}/100
Quality Score: {quality_score}/100
Decision: {smart_decision}

Master Filter:
{reason}

ADX: {adx_value:.2f}
RSI: {r:.2f}
MACD: {m:.6f}
ATR: {atr_value:.6f}
Volume: {"CONFIRMED" if volume_confirmed else "LOW"}
Structure: {"CONFIRMED" if structure_confirmed else "NO"}
Liquidity: {"CONFIRMED" if liquidity_confirmed else "NO"}
FVG: {"CONFIRMED" if fvg_confirmed else "NO"}
Displacement: {"CONFIRMED" if displacement_confirmed else "NO"}
News Risk: {news_risk}
Target Win Rate: {TARGET_WIN_RATE}% (design target, not guaranteed)

Support: {p(support)}
Resistance: {p(resistance)}

━━━━━━━━━━━━━━━━━━━━

Reasons:
{reasons_text}

Timeframe:
M5 Entry
M15 Confirmation
H1 Major Trend
"""
    except Exception as e:
        print(f"Error analyzing {name}: {e}")
        return None


async def main():
    print("Starting QuantumGold AI MASTER FILTER V2")
    print(f"Minimum AI Score: {MIN_AI_SCORE}")
    print(f"Minimum Quality: {MIN_QUALITY_SCORE}")
    print(f"Minimum ADX: {MIN_ADX}")
    print(f"Design Target Win Rate: {TARGET_WIN_RATE}%")
    print("Markets: Gold + Forex")
    print("Crypto signal delivery: DISABLED")
    if is_weekend(): print("Weekend - no signals for any market"); return
    if not TOKEN: print("ERROR: TELEGRAM_TOKEN not configured"); return
    if not CHAT_ID: print("ERROR: TELEGRAM_CHAT_ID not configured"); return
    bot, messages = Bot(token=TOKEN), []
    for symbol, name in MARKETS:
        result = analyze_market(symbol,name)
        if result: messages.append(result)
    if messages:
        try:
            await bot.send_message(chat_id=CHAT_ID,text="\n\n━━━━━━━━━━━━━━━━━━━━\n\n".join(messages))
            print("High quality MASTER V2 signals sent")
        except Exception as e: print(f"Telegram error: {e}")
        try:
            report = get_report()
            await bot.send_message(chat_id=CHAT_ID,text=f"""📊 QuantumGold AI Daily Report

Total Signals:
{report["total"]}

🟢 BUY:
{report["buy"]}

🔴 SELL:
{report["sell"]}

━━━━━━━━━━━━━━━━━━━━

Mode: MASTER FILTER V2
Minimum AI: {MIN_AI_SCORE}
Minimum Quality: {MIN_QUALITY_SCORE}
Minimum ADX: {MIN_ADX}
Design Target: {TARGET_WIN_RATE}%
Crypto: DISABLED""")
        except Exception as e: print(f"Report error: {e}")
    else: print("No MASTER V2 quality BUY/SELL signals")


if __name__ == "__main__":
    asyncio.run(main())
