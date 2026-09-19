import os
import asyncio
import datetime
import math
from zoneinfo import ZoneInfo

import pandas as pd
import yfinance as yf
import ta
from telegram import Bot

from news_filter import check_news
from daily_report import save_signal, get_report
from signal_memory import allow_new_signal
from trade_memory import save_trade, save_last_signal
from live_price import get_live_gold_price
from support_resistance import find_support_resistance
from entry_filter import check_entry
from smart_score import calculate_score
from no_trade_filter import apply_no_trade_filter


# ============================================================
# QuantumGold AI Signal Bot
# ADAPTIVE SCALPING V4.1 + MICROSTRUCTURE
#
# GainzAlgo V2 Essential + GainzAlgo Pro integrated
# Smart Money confirmations = SOFT / BONUS
# ============================================================


TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")


# ============================================================
# HARD FILTERS
# ============================================================

MIN_AI_SCORE = 75
MIN_QUALITY_SCORE = 70
MIN_ADX = 18

# Dedicated XAU/USD short-term scalping profile for balances below $100.
# These are engineering thresholds, not a guaranteed win-rate claim.
SCALP_SUB100_ENABLED = True
SCALP_MIN_CANDIDATE_SCORE = 65
SCALP_MIN_AI_SCORE = 75
SCALP_MIN_QUALITY_SCORE = 70
SCALP_MIN_ADX = 18
SCALP_STRONG_ADX = 22
SCALP_MIN_M1_SCORE = 60
SCALP_MIN_M5_SCORE = 60
SCALP_MIN_MICRO_SCORE = 55
SCALP_MIN_MONEY_SCORE = 70
SCALP_MAX_ATR_RATIO = 2.2
SCALP_MIN_ATR_RATIO = 0.45
SCALP_SL_ATR = 1.25
SCALP_TP1_ATR = 0.75
SCALP_TP2_ATR = 1.20
SCALP_TP3_ATR = 1.80
SCALP_MAX_RISK_PCT = 1.0

# ============================================================
# SP2L SPIKE + 50% PULLBACK (from supplied xauusd(1).py)
# ============================================================
# Source strategy: detect a recent candle whose body is > 2x ATR
# and larger than the preceding candle, then wait for a 50% body
# pullback before treating it as a directional confirmation.
# Integrated as a SOFT confirmation for QuantumGold; it does not
# independently force a trade or create broker orders.
SP2L_ENABLED = True
SP2L_LOOKBACK = 10
SP2L_SPIKE_ATR_MULT = 2.0
SP2L_BONUS = 8

# Design target only - NOT guaranteed
TARGET_WIN_RATE = 85


# ============================================================
# GAINZALGO SETTINGS
# ============================================================

GAINZ_V2_STABILITY = 0.50
GAINZ_V2_RSI = 70
GAINZ_V2_DELTA = 4

GAINZ_PRO_STABILITY = 0.50
GAINZ_PRO_RSI = 50
GAINZ_PRO_DELTA = 5

GAINZ_V2_BONUS = 10
GAINZ_PRO_BONUS = 10


# ============================================================
# MARKETS
# ============================================================

CRYPTO_ENABLED = False

# V4 architecture
H4_ENABLED = True
M1_ENABLED = True
REGIME_ENABLED = True
ACCOUNT_BALANCE = float(os.getenv("ACCOUNT_BALANCE", "50"))
BASE_RISK_PCT = float(os.getenv("BASE_RISK_PCT", "1.0"))
MICRO_ACCOUNT_THRESHOLD = float(os.getenv("MICRO_ACCOUNT_THRESHOLD", "100"))
MICRO_RISK_PCT = float(os.getenv("MICRO_RISK_PCT", "1.0"))
MAX_RISK_PCT = float(os.getenv("MAX_RISK_PCT", "1.0"))
MIN_REGIME_ADX = 18

MARKETS = [
    ("GC=F", "XAU/USD"),
]


CRYPTO_MARKETS = [
    ("BTC-USD", "BTC/USD"),
    ("ETH-USD", "ETH/USD"),
    ("SOL-USD", "SOL/USD"),
    ("BNB-USD", "BNB/USD"),
]


# ============================================================
# STRUCTURE SETTINGS
# ============================================================

SWING_LOOKBACK = 3
STRUCTURE_LOOKBACK = 40
LIQUIDITY_LOOKBACK = 30


# ============================================================
# 10-CANDLE OPENING RANGE STRATEGY
# ============================================================
# XAU/USD M5 rule from the supplied video:
# 01:30 Iran time = Opening Candle anchor (not counted).
# Candle 1 = 01:35 ... Candle 10 = 02:20.
# Range High = highest HIGH of candles 1..10.
# Range Low  = lowest LOW of candles 1..10.
# IMPORTANT: The supplied video/caption does NOT define an entry rule.
# Therefore the 10-candle levels are CONTEXT/CONFIRMATION only.
# We do not hard-code BUY/SELL from the video position box or its 70/30 bias.
# Existing QuantumGold AI/Quality/SMC engines remain responsible for entries.
OPENING_RANGE_ENABLED = True
OPENING_RANGE_HARD_FILTER = False
OPENING_RANGE_START_HOUR = 1
OPENING_RANGE_START_MINUTE = 30
OPENING_RANGE_CANDLES = 10
OPENING_RANGE_TIMEZONE = "Asia/Tehran"


# ============================================================
# BASIC HELPERS
# ============================================================

def is_valid_number(value):

    try:
        value = float(value)

        return (
            math.isfinite(value)
            and value > 0
        )

    except Exception:
        return False


def get_price_decimals(symbol):

    if symbol == "GC=F":
        return 2

    if symbol in [
        "BTC-USD",
        "ETH-USD",
        "SOL-USD",
        "BNB-USD"
    ]:
        return 2

    if symbol == "USDJPY=X":
        return 3

    return 5


def format_price(value, symbol):

    """
    IMPORTANT:
    Do NOT use nested f-strings here.
    The previous version caused:
    SyntaxError: f-string: expecting '}'
    """

    try:
        decimals = get_price_decimals(symbol)
        number = float(value)

        return format(
            number,
            f".{decimals}f"
        )

    except Exception:
        return "N/A"


def is_weekend():

    return (
        datetime.datetime.utcnow().weekday()
        in [5, 6]
    )


def safe_float(series, index=-1):

    try:

        value = float(
            series.iloc[index]
        )

        if math.isfinite(value):
            return value

        return None

    except Exception:
        return None


# ============================================================
# V4 ADAPTIVE HELPERS
# ============================================================

def _to_ohlcv_dataframe(data):
    """Normalize V4 timeframe data from either dict or DataFrame to OHLCV DataFrame."""
    if data is None:
        return None

    try:
        if isinstance(data, dict):
            mapping = {
                "open": data.get("open"),
                "high": data.get("high"),
                "low": data.get("low"),
                "close": data.get("close"),
                "volume": data.get("volume"),
            }
            if any(v is None for v in mapping.values()):
                return None
            df = pd.concat(mapping, axis=1)
        elif isinstance(data, pd.DataFrame):
            df = data.copy()
            rename = {str(c).lower(): str(c).lower() for c in df.columns}
            df = df.rename(columns=rename)
            required = ["open", "high", "low", "close", "volume"]
            if not all(c in df.columns for c in required):
                return None
            df = df[required]
        else:
            return None

        # Flatten accidental MultiIndex columns and guarantee numeric OHLCV.
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = [str(c[0]).lower() for c in df.columns]
        df.columns = [str(c).lower() for c in df.columns]
        for col in ["open", "high", "low", "close", "volume"]:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")
        df = df.dropna(subset=["open", "high", "low", "close"]).copy()
        df["volume"] = df["volume"].fillna(0)
        if not isinstance(df.index, pd.DatetimeIndex):
            df.index = pd.to_datetime(df.index, errors="coerce")
        df = df[~df.index.isna()].sort_index()
        return df if not df.empty else None
    except Exception as e:
        print(f"OHLCV normalization error: {e}")
        return None


def resample_h4(data):
    """Build true H4 candles from closed H1 candles. Accepts dict or DataFrame."""
    try:
        df = _to_ohlcv_dataframe(data)
        if df is None or len(df) < 4:
            return None

        # Closed candles only. The last row from prepare_data is the latest
        # available candle, which may still be forming.
        df = df.iloc[:-1].copy()
        if df.empty:
            return None

        h4 = df.resample("4h").agg({
            "open": "first",
            "high": "max",
            "low": "min",
            "close": "last",
            "volume": "sum",
        }).dropna(subset=["open", "high", "low", "close"])

        return h4 if len(h4) >= 60 else None
    except Exception as e:
        print(f"H4 resample error: {e}")
        return None


def market_regime(data):
    """Classify regime without forcing a trade direction; accepts dict/DataFrame."""
    unknown = {
        "name": "UNKNOWN",
        "trend": 0,
        "strength": 0.0,
        "volatility": "UNKNOWN",
    }

    try:
        df = _to_ohlcv_dataframe(data)
        if df is None or len(df) < 60:
            return unknown

        c = df["close"]
        h = df["high"]
        l = df["low"]

        adx = ta.trend.ADXIndicator(h, l, c, 14).adx()
        atr = ta.volatility.average_true_range(h, l, c, 14)
        e50 = ta.trend.ema_indicator(c, 50)
        e200 = ta.trend.ema_indicator(c, 200)

        a = safe_float(adx, -2) or 0.0
        av = safe_float(atr, -2) or 0.0
        e5 = safe_float(e50, -2) or 0.0
        e2 = safe_float(e200, -2) or 0.0

        trend = 1 if e5 > e2 else -1 if e5 < e2 else 0
        name = "TREND" if a >= MIN_REGIME_ADX else "RANGE"

        valid_atr = atr.dropna()
        if av > 0 and len(valid_atr) >= 40:
            med = float(valid_atr.tail(40).median())
            vol = (
                "HIGH" if av > med * 1.5
                else "LOW" if av < med * 0.7
                else "NORMAL"
            )
        else:
            vol = "NORMAL"

        return {
            "name": name,
            "trend": trend,
            "strength": a,
            "volatility": vol,
        }
    except Exception as e:
        print(f"Market regime error: {e}")
        return unknown


def adaptive_risk(balance=None):
    """Risk budget only; never uses martingale or increases after losses."""
    b = float(balance if balance is not None else ACCOUNT_BALANCE)
    pct = MICRO_RISK_PCT if b <= MICRO_ACCOUNT_THRESHOLD else BASE_RISK_PCT
    pct = max(0.1, min(MAX_RISK_PCT, pct))
    return {"balance": b, "risk_pct": pct, "risk_cash": b * pct / 100.0, "mode": "MICRO" if b <= MICRO_ACCOUNT_THRESHOLD else "STANDARD"}


# ============================================================
# ADVANCED SCALP / SMART MODULES
# ============================================================
# Added from the requested 16-module professional scalping design.
# These modules are intentionally SOFT by default so they enrich the
# existing QuantumGold filters without creating another signal bottleneck.

ADVANCED_MODULES_ENABLED = True
ADVANCED_SCORE_WEIGHT = float(os.getenv("ADVANCED_SCORE_WEIGHT", "0.30"))
ADVANCED_BONUS = int(os.getenv("ADVANCED_BONUS", "8"))

# Smart risk controls. This version is a Telegram SIGNAL bot, so these
# values are calculated and reported; they do not place broker orders.
BREAK_EVEN_R = float(os.getenv("BREAK_EVEN_R", "1.0"))
TRAILING_ATR_MULT = float(os.getenv("TRAILING_ATR_MULT", "1.0"))
DAILY_LOSS_LIMIT_PCT = float(os.getenv("DAILY_LOSS_LIMIT_PCT", "2.0"))
DAILY_TARGET_PCT = float(os.getenv("DAILY_TARGET_PCT", "5.0"))
SIGNAL_COOLDOWN_MINUTES = int(os.getenv("SIGNAL_COOLDOWN_MINUTES", "5"))
ONE_ACTIVE_SIGNAL = True

# Kill zones are UTC-based and configurable. They are a soft timing module.
KILL_ZONE_WINDOWS_UTC = (
    (7, 10, "LONDON"),
    (12, 16, "NEW_YORK"),
)

_LAST_SIGNAL_TIME = None
_ACTIVE_SIGNAL = None


def _safe_bool(value):
    return bool(value) if value is not None else False


def detect_order_block(open_price, close, high, low, atr_value, direction):
    """Find the nearest recent opposite candle used as a simple Order Block."""
    neutral = {"valid": False, "direction": 0, "high": None, "low": None, "index": None, "distance": None}
    try:
        i = len(close) - 2
        if i < 5 or atr_value <= 0:
            return neutral

        # Search recent candles: last opposite candle before a strong move.
        start = max(1, i - 20)
        for j in range(i - 1, start - 1, -1):
            o = float(open_price.iloc[j])
            c = float(close.iloc[j])
            h = float(high.iloc[j])
            l = float(low.iloc[j])
            body = abs(c - o)

            if direction == 1:
                # Bullish OB: last bearish candle before bullish displacement.
                if c < o and body >= atr_value * 0.15:
                    move = float(close.iloc[i]) - c
                    if move >= atr_value * 0.50:
                        return {
                            "valid": True, "direction": 1,
                            "high": h, "low": l, "index": j,
                            "distance": abs(float(close.iloc[i]) - ((h + l) / 2.0)),
                        }
            else:
                # Bearish OB: last bullish candle before bearish displacement.
                if c > o and body >= atr_value * 0.15:
                    move = c - float(close.iloc[i])
                    if move >= atr_value * 0.50:
                        return {
                            "valid": True, "direction": -1,
                            "high": h, "low": l, "index": j,
                            "distance": abs(float(close.iloc[i]) - ((h + l) / 2.0)),
                        }
        return neutral
    except Exception:
        return neutral


def detect_breaker_block(open_price, close, high, low, atr_value, direction):
    """Detect a simple breaker: an opposite OB that has been invalidated."""
    neutral = {"valid": False, "direction": 0, "high": None, "low": None}
    try:
        ob = detect_order_block(open_price, close, high, low, atr_value, direction)
        if not ob["valid"]:
            return neutral
        last = float(close.iloc[-2])
        if direction == 1 and last > ob["high"]:
            return {"valid": True, "direction": 1, "high": ob["high"], "low": ob["low"]}
        if direction == -1 and last < ob["low"]:
            return {"valid": True, "direction": -1, "high": ob["high"], "low": ob["low"]}
        return neutral
    except Exception:
        return neutral


def detect_supply_demand(close, high, low, atr_value, direction):
    """Recent impulse-origin zone used as a supply/demand confirmation."""
    neutral = {"buy": False, "sell": False, "zone_high": None, "zone_low": None}
    try:
        i = len(close) - 2
        if i < 12 or atr_value <= 0:
            return neutral
        start = max(0, i - 12)
        recent_high = float(high.iloc[start:i].max())
        recent_low = float(low.iloc[start:i].min())
        price = float(close.iloc[i])
        near = atr_value * 1.0
        buy = direction == 1 and abs(price - recent_low) <= near
        sell = direction == -1 and abs(price - recent_high) <= near
        return {"buy": buy, "sell": sell, "zone_high": recent_high, "zone_low": recent_low}
    except Exception:
        return neutral


def detect_candlestick_patterns(open_price, close, high, low):
    """Engulfing, pin-bar and inside-bar patterns on the last completed candle."""
    neutral = {"bullish": False, "bearish": False, "patterns": []}
    try:
        i = len(close) - 2
        if i < 2:
            return neutral
        o, c, h, l = map(float, (
            open_price.iloc[i], close.iloc[i], high.iloc[i], low.iloc[i]
        ))
        po, pc = float(open_price.iloc[i-1]), float(close.iloc[i-1])
        rng = max(h - l, 1e-12)
        body = abs(c - o)
        upper = h - max(o, c)
        lower = min(o, c) - l
        bullish = bearish = False
        patterns = []

        if pc < po and c > o and c >= po and o <= pc:
            bullish = True; patterns.append("Bullish Engulfing")
        if pc > po and c < o and c <= po and o >= pc:
            bearish = True; patterns.append("Bearish Engulfing")

        if lower >= max(body, rng * 0.08) * 2 and (c - l) / rng >= 0.65:
            bullish = True; patterns.append("Bullish Pin Bar")
        if upper >= max(body, rng * 0.08) * 2 and (h - c) / rng >= 0.65:
            bearish = True; patterns.append("Bearish Pin Bar")

        ph, pl = float(high.iloc[i-1]), float(low.iloc[i-1])
        if h <= ph and l >= pl:
            if c >= o:
                bullish = True
                patterns.append("Inside Bar Bullish Bias")
            else:
                bearish = True
                patterns.append("Inside Bar Bearish Bias")

        return {"bullish": bullish, "bearish": bearish, "patterns": patterns}
    except Exception:
        return neutral


def detect_ote(close, high, low, direction):
    """61.8%-79% Fibonacci retracement context (OTE zone)."""
    neutral = {"buy": False, "sell": False, "ratio": None}
    try:
        i = len(close) - 2
        if i < 10:
            return neutral
        hh = float(high.iloc[max(0, i-20):i].max())
        ll = float(low.iloc[max(0, i-20):i].min())
        span = hh - ll
        if span <= 0:
            return neutral
        price = float(close.iloc[i])
        if direction == 1:
            retrace = (hh - price) / span
            return {"buy": 0.618 <= retrace <= 0.79, "sell": False, "ratio": retrace}
        retrace = (price - ll) / span
        return {"buy": False, "sell": 0.21 <= retrace <= 0.382, "ratio": retrace}
    except Exception:
        return neutral


def detect_kill_zone():
    now = datetime.datetime.utcnow()
    hour = now.hour + now.minute / 60.0
    for start, end, name in KILL_ZONE_WINDOWS_UTC:
        if start <= hour < end:
            return {"active": True, "name": name}
    return {"active": False, "name": "OFF"}


def detect_volatility_module(high, low, close, atr_value):
    try:
        i = len(close) - 2
        if i < 30 or atr_value <= 0:
            return {"score": 50, "state": "UNKNOWN"}
        atr_series = ta.volatility.average_true_range(high, low, close, 14).dropna()
        if len(atr_series) < 20:
            return {"score": 50, "state": "UNKNOWN"}
        med = float(atr_series.tail(30).median())
        ratio = atr_value / med if med > 0 else 1.0
        if 0.7 <= ratio <= 1.8:
            return {"score": 100, "state": "NORMAL"}
        if ratio < 0.7:
            return {"score": 55, "state": "LOW"}
        return {"score": 65, "state": "HIGH"}
    except Exception:
        return {"score": 50, "state": "UNKNOWN"}


def advanced_module_analysis(open_price, close, high, low, atr_value,
                             signal, structure, liquidity, fvg, displacement,
                             money_structure, micro, gainz_v2, gainz_pro,
                             regime, m15_regime, h1_regime, news_risk):
    """Combine 16 soft modules with explicit weights."""
    direction = 1 if signal == "🟢 BUY" else -1

    ob = detect_order_block(open_price, close, high, low, atr_value, direction)
    breaker = detect_breaker_block(open_price, close, high, low, atr_value, direction)
    sd = detect_supply_demand(close, high, low, atr_value, direction)
    candles = detect_candlestick_patterns(open_price, close, high, low)
    ote = detect_ote(close, high, low, direction)
    kz = detect_kill_zone()
    vol = detect_volatility_module(high, low, close, atr_value)

    modules = {
        "Order Block": (100 if ob["valid"] else 0),
        "FVG": (100 if ((direction == 1 and fvg.get("bullish")) or (direction == -1 and fvg.get("bearish"))) else 0),
        "Liquidity": (100 if ((direction == 1 and liquidity.get("bullish")) or (direction == -1 and liquidity.get("bearish"))) else 0),
        "Breaker Block": (100 if breaker["valid"] else 0),
        "Market Structure": (100 if ((direction == 1 and (structure.get("bullish_bos") or structure.get("bullish_choch"))) or (direction == -1 and (structure.get("bearish_bos") or structure.get("bearish_choch")))) else 0),
        "Supply/Demand": (100 if (sd["buy"] if direction == 1 else sd["sell"]) else 0),
        "Candlestick": (100 if (candles["bullish"] if direction == 1 else candles["bearish"]) else 0),
        "OTE": (100 if (ote["buy"] if direction == 1 else ote["sell"]) else 0),
        "Kill Zone": 100 if kz["active"] else 45,
        "Money Structure": int(money_structure.get("score", 0)),
        "Microstructure": int(micro.get("score", 0)),
        "Gainz V2": 100 if (gainz_v2.get("buy") if direction == 1 else gainz_v2.get("sell")) else 0,
        "Gainz Pro": 100 if (gainz_pro.get("buy") if direction == 1 else gainz_pro.get("sell")) else 0,
        "MTF H1/M15": 100 if ((direction == 1 and h1_regime.get("trend", 0) > 0 and m15_regime.get("trend", 0) > 0) or (direction == -1 and h1_regime.get("trend", 0) < 0 and m15_regime.get("trend", 0) < 0)) else 0,
        "Volatility": int(vol["score"]),
        "News Filter": 100 if news_risk == "LOW" else 70 if news_risk == "MEDIUM" else 0,
    }
    weights = {
        "Order Block": 8, "FVG": 6, "Liquidity": 7, "Breaker Block": 5,
        "Market Structure": 8, "Supply/Demand": 5, "Candlestick": 6,
        "OTE": 5, "Kill Zone": 4, "Money Structure": 8, "Microstructure": 8,
        "Gainz V2": 6, "Gainz Pro": 5, "MTF H1/M15": 9, "Volatility": 5,
        "News Filter": 5,
    }
    total_weight = sum(weights.values())
    score = sum(modules[k] * weights[k] for k in modules) / total_weight

    aligned = [k for k, v in modules.items() if v >= 70]
    return {
        "score": int(round(max(0, min(100, score)))),
        "modules": modules,
        "weights": weights,
        "aligned": aligned,
        "order_block": ob,
        "breaker_block": breaker,
        "supply_demand": sd,
        "candlestick": candles,
        "ote": ote,
        "kill_zone": kz,
        "volatility": vol,
    }


def calculate_smart_stop_loss(price, atr_value, direction, order_block):
    """Use the nearest valid Order Block boundary, with ATR fallback."""
    if direction == 1:
        atr_sl = price - atr_value * 2.0
        if order_block.get("valid") and order_block.get("low") is not None:
            candidate = float(order_block["low"]) - atr_value * 0.10
            if candidate < price:
                return candidate, "ORDER BLOCK"
        return atr_sl, "ATR"
    atr_sl = price + atr_value * 2.0
    if order_block.get("valid") and order_block.get("high") is not None:
        candidate = float(order_block["high"]) + atr_value * 0.10
        if candidate > price:
            return candidate, "ORDER BLOCK"
    return atr_sl, "ATR"


def risk_management_snapshot(price, stop_loss, atr_value, direction, risk_profile):
    """Calculate BE, trailing trigger, and safety limits for the signal."""
    risk_distance = abs(price - stop_loss)
    if direction == 1:
        be = price + risk_distance * BREAK_EVEN_R
        trail = price + max(atr_value * TRAILING_ATR_MULT, risk_distance * 0.50)
    else:
        be = price - risk_distance * BREAK_EVEN_R
        trail = price - max(atr_value * TRAILING_ATR_MULT, risk_distance * 0.50)
    return {
        "risk_distance": risk_distance,
        "risk_cash": risk_profile["risk_cash"],
        "break_even_trigger": be,
        "trailing_trigger": trail,
        "daily_loss_limit": risk_profile["balance"] * DAILY_LOSS_LIMIT_PCT / 100.0,
        "daily_target": risk_profile["balance"] * DAILY_TARGET_PCT / 100.0,
        "cooldown_minutes": SIGNAL_COOLDOWN_MINUTES,
        "one_active_signal": ONE_ACTIVE_SIGNAL,
    }


def signal_slot_available():
    """Signal-only equivalent of one simultaneous position + cooldown."""
    global _LAST_SIGNAL_TIME, _ACTIVE_SIGNAL
    if not ONE_ACTIVE_SIGNAL:
        return True
    now = datetime.datetime.utcnow()
    if _LAST_SIGNAL_TIME is None:
        return True
    elapsed = (now - _LAST_SIGNAL_TIME).total_seconds() / 60.0
    if elapsed < SIGNAL_COOLDOWN_MINUTES:
        return False
    return True


def mark_signal_slot(signal):
    global _LAST_SIGNAL_TIME, _ACTIVE_SIGNAL
    _LAST_SIGNAL_TIME = datetime.datetime.utcnow()
    _ACTIVE_SIGNAL = signal



# ============================================================
# MONEY STRUCTURE LEVEL - TRANSLATED FROM TRADINGVIEW PINE
# ============================================================
# Based on "Money Structure Levels [Mehdi Pirhayati]".
# The bot-side implementation uses the indicator's Scalping defaults:
# SuperTrend ATR=10, multiplier=3; signal ATR=10, TB multiplier=10,
# signal filter=0.5; cloud 10/40 MA blend; EMA 12/26 ribbon; and
# WaveTrend trap/bottom-top context. This is a Python translation,
# not a byte-for-byte TradingView execution, so broker/feed candles can
# produce small differences from TradingView.

MONEY_STRUCTURE_ENABLED = True
MONEY_STRUCTURE_HARD_FILTER = False
MONEY_STRUCTURE_BONUS = 10
MONEY_STRUCTURE_MIN_SCORE = 60


def _money_supertrend_direction(high, low, close, atr_period=10, multiplier=3.0):
    try:
        src = (high + low) / 2.0
        atr = ta.volatility.average_true_range(high, low, close, atr_period)
        if len(close) < atr_period + 5:
            return 0

        up = src - multiplier * atr
        dn = src + multiplier * atr
        trend = 1
        prev_up = None
        prev_dn = None

        for i in range(len(close)):
            u = float(up.iloc[i]) if pd.notna(up.iloc[i]) else None
            d = float(dn.iloc[i]) if pd.notna(dn.iloc[i]) else None
            c_prev = float(close.iloc[i - 1]) if i > 0 and pd.notna(close.iloc[i - 1]) else None
            c_now = float(close.iloc[i]) if pd.notna(close.iloc[i]) else None
            if u is None or d is None or c_now is None:
                continue
            if prev_up is not None and c_prev is not None and c_prev > prev_up:
                u = max(u, prev_up)
            if prev_dn is not None and c_prev is not None and c_prev < prev_dn:
                d = min(d, prev_dn)
            if prev_dn is not None and c_now > prev_dn:
                trend = 1
            elif prev_up is not None and c_now < prev_up:
                trend = -1
            prev_up, prev_dn = u, d
        return trend
    except Exception:
        return 0


def analyze_money_structure(open_price, high, low, close, volume=None):
    """Translate the useful, signal-producing parts of the supplied Pine script."""
    neutral = {
        "buy": False,
        "sell": False,
        "direction": 0,
        "score": 0,
        "supertrend": 0,
        "signal_direction": 0,
        "ribbon": "SIDEWAYS",
        "cloud": "SIDEWAYS",
        "trap": "NONE",
        "reason": "Money Structure unavailable",
    }
    try:
        if len(close) < 80:
            return neutral

        c = close.astype(float)
        h = high.astype(float)
        l = low.astype(float)
        o = open_price.astype(float)

        # ① Independent SuperTrend: ATR 10 / multiplier 3.
        st_dir = _money_supertrend_direction(h, l, c, 10, 3.0)

        # Main signal engine in the supplied Pine script, using its
        # "Scalping" preset: length=10, mult=10, SFilter=0.5.
        atr10 = ta.volatility.average_true_range(h, l, c, 10)
        src = (h + l) / 2.0
        atr_signal = 10.0 * atr10
        long_stop = src - atr_signal * 0.5
        short_stop = src + atr_signal * 0.5

        direction = 1
        prev_long = None
        prev_short = None
        dirs = []
        for i in range(len(c)):
            lo = float(long_stop.iloc[i]) if pd.notna(long_stop.iloc[i]) else None
            sh = float(short_stop.iloc[i]) if pd.notna(short_stop.iloc[i]) else None
            if lo is None or sh is None or pd.isna(c.iloc[i]):
                dirs.append(direction)
                continue
            cp = float(c.iloc[i - 1]) if i > 0 and pd.notna(c.iloc[i - 1]) else None
            cn = float(c.iloc[i])
            if prev_long is not None and cp is not None and cp > prev_long:
                lo = max(lo, prev_long)
            if prev_short is not None and cp is not None and cp < prev_short:
                sh = min(sh, prev_short)
            if prev_short is not None and cn > prev_short:
                direction = 1
            elif prev_long is not None and cn < prev_long:
                direction = -1
            dirs.append(direction)
            prev_long, prev_short = lo, sh

        signal_dir = int(dirs[-2] if len(dirs) >= 2 else dirs[-1])
        signal_dir_prev = int(dirs[-3] if len(dirs) >= 3 else signal_dir)
        fresh_buy = signal_dir == 1 and signal_dir_prev == -1
        fresh_sell = signal_dir == -1 and signal_dir_prev == 1

        # Vortex Cloud: average of SMA/EMA/WMA/VWMA/HMA/RMA, lengths 10/40.
        def ma_blend(series, length):
            vals = [
                ta.trend.sma_indicator(series, length),
                ta.trend.ema_indicator(series, length),
                ta.trend.wma_indicator(series, length),
                ta.volume.volume_weighted_average_price(h, l, c, volume=None) if False else None,
                ta.trend.ema_indicator(series, length),
                ta.trend.rma_indicator(series, length) if hasattr(ta.trend, 'rma_indicator') else ta.trend.sma_indicator(series, length),
            ]
            # ta has no generic VWMA/HMA in all versions; use exact formulas locally.
            sma, ema, wma = vals[0], vals[1], vals[2]
            vol = (volume.astype(float) if volume is not None else pd.Series(1.0, index=series.index))
            vol = vol.reindex(series.index).fillna(0.0)
            vwma = (series * vol).rolling(length).sum() / vol.rolling(length).sum().replace(0, pd.NA)
            # Hull MA: WMA(2*WMA(n/2)-WMA(n), sqrt(n))
            half = max(1, int(length / 2))
            root = max(1, int(math.sqrt(length)))
            hma_src = 2 * ta.trend.wma_indicator(series, half) - ta.trend.wma_indicator(series, length)
            hma = ta.trend.wma_indicator(hma_src, root)
            rma = ta.momentum.rsi(series, length) if False else series.ewm(alpha=1.0 / length, adjust=False).mean()
            return (sma + ema + wma + vwma + hma + rma) / 6.0

        ma2 = ma_blend(c, 10)
        ma3 = ma_blend(c, 40)
        cloud_bull = bool(float(ma2.iloc[-2]) > float(ma3.iloc[-2]))
        cloud = "BULLISH" if cloud_bull else "BEARISH"

        # EMA 12/26 ribbon.
        fast = ta.trend.ema_indicator(c, 12)
        slow = ta.trend.ema_indicator(c, 26)
        price_now = float(c.iloc[-2])
        fast_now = float(fast.iloc[-2])
        slow_now = float(slow.iloc[-2])
        green = fast_now > slow_now and price_now > fast_now
        red = fast_now < slow_now and price_now < fast_now
        ribbon = "BULLISH" if green else "BEARISH" if red else "SIDEWAYS"

        # WaveTrend trap/bottom-top context from the supplied script.
        wt_src = c
        chl = 5 * 5
        avg = 10 * 5
        esa = ta.trend.ema_indicator(wt_src, chl)
        d = ta.trend.ema_indicator((wt_src - esa).abs(), chl)
        ci = (wt_src - esa) / (0.015 * d.replace(0, pd.NA))
        wt1 = ta.trend.ema_indicator(ci, avg)
        wt2 = wt1.rolling(3).mean()
        wt = float(wt2.iloc[-2]) if pd.notna(wt2.iloc[-2]) else 0.0
        trap = "TOP" if wt >= 53 else "BOTTOM" if wt <= -53 else "NONE"

        # Score the direction rather than requiring a fresh crossover every scan.
        buy_score = 0
        sell_score = 0
        if signal_dir == 1: buy_score += 35
        if signal_dir == -1: sell_score += 35
        if st_dir == 1: buy_score += 20
        if st_dir == -1: sell_score += 20
        if cloud_bull: buy_score += 15
        else: sell_score += 15
        if green: buy_score += 15
        if red: sell_score += 15

        # The Pine trap detector explicitly warns against buying tops/selling bottoms.
        if trap == "TOP": buy_score -= 20
        if trap == "BOTTOM": sell_score -= 20

        buy_score = max(0, min(100, buy_score))
        sell_score = max(0, min(100, sell_score))
        if buy_score > sell_score and buy_score >= MONEY_STRUCTURE_MIN_SCORE:
            final_dir = 1
        elif sell_score > buy_score and sell_score >= MONEY_STRUCTURE_MIN_SCORE:
            final_dir = -1
        else:
            final_dir = 0

        reasons = []
        if fresh_buy: reasons.append("new BUY turn")
        if fresh_sell: reasons.append("new SELL turn")
        if st_dir == signal_dir and st_dir != 0: reasons.append("SuperTrend aligned")
        if (cloud_bull and final_dir == 1) or ((not cloud_bull) and final_dir == -1): reasons.append("cloud aligned")
        if (green and final_dir == 1) or (red and final_dir == -1): reasons.append("ribbon aligned")
        if trap != "NONE": reasons.append(f"trap={trap}")

        return {
            "buy": final_dir == 1,
            "sell": final_dir == -1,
            "direction": final_dir,
            "score": max(buy_score, sell_score),
            "buy_score": buy_score,
            "sell_score": sell_score,
            "supertrend": st_dir,
            "signal_direction": signal_dir,
            "fresh_buy": fresh_buy,
            "fresh_sell": fresh_sell,
            "ribbon": ribbon,
            "cloud": cloud,
            "trap": trap,
            "reason": ", ".join(reasons) if reasons else "No Money Structure alignment",
        }
    except Exception as e:
        print(f"Money Structure error: {e}")
        return neutral

# ============================================================
# MARKET DATA
# ============================================================

def get_data(symbol, interval="5m"):

    try:

        print(
            f"Downloading {symbol} "
            f"{interval} data..."
        )

        period = {
            "5m": "7d",
            "15m": "60d",
            "1h": "730d",
            "1m": "7d"
        }.get(
            interval,
            "60d"
        )

        data = yf.download(
            tickers=symbol,
            period=period,
            interval=interval,
            progress=False,
            auto_adjust=False,
            threads=False
        )

        if data is None or data.empty:

            print(
                f"{symbol}: EMPTY DATA "
                f"interval={interval}"
            )

            return None

        if getattr(
            data.columns,
            "nlevels",
            1
        ) > 1:

            data.columns = [
                col[0]
                if isinstance(col, tuple)
                else col
                for col in data.columns
            ]

        required = [
            "Open",
            "Close",
            "High",
            "Low",
            "Volume"
        ]

        missing = [
            c
            for c in required
            if c not in data.columns
        ]

        if missing:

            print(
                f"{symbol}: "
                f"missing columns {missing}"
            )

            return None

        data = data.dropna(
            subset=[
                "Open",
                "Close",
                "High",
                "Low"
            ]
        )

        if len(data) < 60:

            print(
                f"{symbol}: "
                f"insufficient data "
                f"({len(data)} candles)"
            )

            return None

        return data

    except Exception as e:

        print(
            f"Data error {symbol} "
            f"{interval}: {e}"
        )

        return None


def prepare_data(symbol, interval="5m"):

    data = get_data(
        symbol,
        interval
    )

    if data is None:
        return None

    try:

        open_price = data["Open"]
        close = data["Close"]
        high = data["High"]
        low = data["Low"]
        volume = data["Volume"]

        if hasattr(
            open_price,
            "columns"
        ):
            open_price = (
                open_price.iloc[:, 0]
            )

        if hasattr(
            close,
            "columns"
        ):
            close = close.iloc[:, 0]

        if hasattr(
            high,
            "columns"
        ):
            high = high.iloc[:, 0]

        if hasattr(
            low,
            "columns"
        ):
            low = low.iloc[:, 0]

        if hasattr(
            volume,
            "columns"
        ):
            volume = volume.iloc[:, 0]

        open_price = (
            open_price.dropna()
        )

        close = (
            close.dropna()
        )

        high = (
            high.dropna()
        )

        low = (
            low.dropna()
        )

        volume = (
            volume.fillna(0)
        )

        if len(close) < 220:

            print(
                f"{symbol}: "
                f"insufficient prepared "
                f"data ({len(close)})"
            )

            return None

        return {
            "open": open_price,
            "close": close,
            "high": high,
            "low": low,
            "volume": volume
        }

    except Exception as e:

        print(
            f"Prepare data error "
            f"{symbol}: {e}"
        )

        return None


# ============================================================
# 10-CANDLE OPENING RANGE ENGINE
# ============================================================
def analyze_opening_range(open_price, high, low, close):
    """Build the daily 10-candle M5 opening range using Iran time."""
    neutral = {
        "available": False, "direction": 0, "buy": False, "sell": False,
        "range_high": None, "range_low": None, "range_date": None,
        "last_close": None, "status": "UNAVAILABLE", "reason": "No valid 10-candle range"
    }
    try:
        df = pd.DataFrame({"open": open_price, "high": high, "low": low, "close": close}).dropna()
        if len(df) < OPENING_RANGE_CANDLES + 5:
            return neutral

        idx = pd.DatetimeIndex(df.index)
        if idx.tz is None:
            idx = idx.tz_localize("UTC")
        local_idx = idx.tz_convert(ZoneInfo(OPENING_RANGE_TIMEZONE))
        df = df.copy()
        df.index = local_idx
        df = df.sort_index()

        # Existing V4 logic treats the last row as potentially incomplete; use only closed bars.
        if len(df) > 1:
            df = df.iloc[:-1].copy()

        now_local = datetime.datetime.now(ZoneInfo(OPENING_RANGE_TIMEZONE))
        today = now_local.date()
        # This is a DAILY opening-range strategy: do not reuse yesterday's range.
        # Before 02:25 Iran time the 10th candle is not closed yet, so no signal.
        if now_local.time() < datetime.time(2, 25):
            neutral["status"] = "WAITING_RANGE"
            neutral["reason"] = "Waiting for Candle 10 to close at 02:25 Iran time"
            return neutral

        range_date = today
        day = df[df.index.date == range_date]
        expected = [
            datetime.datetime.combine(range_date, datetime.time(1, 30), tzinfo=ZoneInfo(OPENING_RANGE_TIMEZONE))
            + datetime.timedelta(minutes=5 * (i + 1))
            for i in range(OPENING_RANGE_CANDLES)
        ]
        # Exact 5-minute starts: no silent shifting to a nearby candle.
        bars = day[day.index.isin(expected)]
        if len(bars) != OPENING_RANGE_CANDLES:
            neutral["status"] = "WAITING_RANGE"
            neutral["reason"] = "Today's exact Candle 1..10 timestamps are not all available"
            return neutral

        range_high = float(bars["high"].max())
        range_low = float(bars["low"].min())
        if not (is_valid_number(range_high) and is_valid_number(range_low) and range_high > range_low):
            neutral["status"] = "INVALID_RANGE"
            return neutral

        after = df[(df.index.date == range_date) & (df.index.time >= datetime.time(2, 25))]
        if after.empty:
            neutral.update({"available": True, "range_high": range_high, "range_low": range_low, "range_date": str(range_date), "status": "WAITING_BREAKOUT", "reason": "Waiting for post-range M5 close"})
            return neutral

        last = after.iloc[-1]
        last_close = float(last["close"])
        prev_close = float(after["close"].iloc[-2]) if len(after) >= 2 else None
        # Signal only on the actual first close through a range boundary.
        # This prevents repeated signals hours after an old breakout.
        buy_breakout = last_close > range_high and (prev_close is None or prev_close <= range_high)
        sell_breakout = last_close < range_low and (prev_close is None or prev_close >= range_low)
        direction = 1 if buy_breakout else -1 if sell_breakout else 0
        neutral.update({
            "available": True, "direction": direction, "buy": buy_breakout, "sell": sell_breakout,
            "range_high": range_high, "range_low": range_low, "range_date": str(range_date),
            "last_close": last_close, "status": "BUY_BREAKOUT" if buy_breakout else "SELL_BREAKOUT" if sell_breakout else "NO_FRESH_BREAKOUT",
            "reason": "Fresh M5 close above 10-candle high" if buy_breakout else "Fresh M5 close below 10-candle low" if sell_breakout else "No fresh breakout on latest completed M5 candle"
        })
        return neutral
    except Exception as e:
        print(f"Opening Range error: {e}")
        return neutral


# ============================================================
# MARKET STRUCTURE
# ============================================================

def find_recent_swings(
    high,
    low,
    lookback=SWING_LOOKBACK
):

    highs = []
    lows = []

    start = max(
        lookback,
        len(high) - STRUCTURE_LOOKBACK
    )

    for i in range(
        start,
        len(high) - lookback
    ):

        current_high = float(
            high.iloc[i]
        )

        current_low = float(
            low.iloc[i]
        )

        left_high = float(
            high.iloc[
                i - lookback:i
            ].max()
        )

        right_high = float(
            high.iloc[
                i + 1:i + lookback + 1
            ].max()
        )

        left_low = float(
            low.iloc[
                i - lookback:i
            ].min()
        )

        right_low = float(
            low.iloc[
                i + 1:i + lookback + 1
            ].min()
        )

        if (
            current_high > left_high
            and current_high > right_high
        ):

            highs.append(
                (i, current_high)
            )

        if (
            current_low < left_low
            and current_low < right_low
        ):

            lows.append(
                (i, current_low)
            )

    return highs, lows


def analyze_structure(
    close,
    high,
    low
):

    try:

        last_i = len(close) - 2

        if last_i < 10:

            return {
                "bullish_bos": False,
                "bearish_bos": False,
                "bullish_choch": False,
                "bearish_choch": False
            }

        highs, lows = (
            find_recent_swings(
                high.iloc[
                    :last_i + 1
                ],
                low.iloc[
                    :last_i + 1
                ]
            )
        )

        recent_highs = highs[-3:]
        recent_lows = lows[-3:]

        swing_high = (
            recent_highs[-1][1]
            if recent_highs
            else None
        )

        swing_low = (
            recent_lows[-1][1]
            if recent_lows
            else None
        )

        last_close = float(
            close.iloc[last_i]
        )

        bullish_bos = (
            swing_high is not None
            and last_close > swing_high
        )

        bearish_bos = (
            swing_low is not None
            and last_close < swing_low
        )

        bullish_choch = (
            len(recent_highs) >= 2
            and last_close
            > recent_highs[-2][1]
        )

        bearish_choch = (
            len(recent_lows) >= 2
            and last_close
            < recent_lows[-2][1]
        )

        return {
            "bullish_bos": bullish_bos,
            "bearish_bos": bearish_bos,
            "bullish_choch": bullish_choch,
            "bearish_choch": bearish_choch
        }

    except Exception as e:

        print(
            f"Structure analysis error: {e}"
        )

        return {
            "bullish_bos": False,
            "bearish_bos": False,
            "bullish_choch": False,
            "bearish_choch": False
        }


# ============================================================
# LIQUIDITY SWEEP
# ============================================================

def detect_liquidity_sweep(
    close,
    high,
    low
):

    try:

        i = len(close) - 2

        start = max(
            0,
            i - LIQUIDITY_LOOKBACK
        )

        if i <= start:

            return {
                "bullish": False,
                "bearish": False
            }

        prior_high = float(
            high.iloc[start:i].max()
        )

        prior_low = float(
            low.iloc[start:i].min()
        )

        current_high = float(
            high.iloc[i]
        )

        current_low = float(
            low.iloc[i]
        )

        current_close = float(
            close.iloc[i]
        )

        bullish = (
            current_low < prior_low
            and current_close > prior_low
        )

        bearish = (
            current_high > prior_high
            and current_close < prior_high
        )

        return {
            "bullish": bullish,
            "bearish": bearish
        }

    except Exception as e:

        print(
            f"Liquidity sweep error: {e}"
        )

        return {
            "bullish": False,
            "bearish": False
        }


# ============================================================
# FAIR VALUE GAP
# ============================================================

def detect_fvg(
    close,
    high,
    low,
    atr_value
):

    try:

        i = len(close) - 2

        if (
            i < 2
            or atr_value <= 0
        ):

            return {
                "bullish": False,
                "bearish": False
            }

        bullish_gap = (
            float(low.iloc[i])
            - float(high.iloc[i - 2])
        )

        bearish_gap = (
            float(low.iloc[i - 2])
            - float(high.iloc[i])
        )

        minimum_gap = (
            atr_value * 0.05
        )

        return {
            "bullish": (
                bullish_gap > minimum_gap
            ),
            "bearish": (
                bearish_gap > minimum_gap
            )
        }

    except Exception as e:

        print(
            f"FVG detection error: {e}"
        )

        return {
            "bullish": False,
            "bearish": False
        }


# ============================================================
# DISPLACEMENT
# ============================================================

def detect_displacement(
    open_price,
    close,
    high,
    low,
    atr_value
):

    try:

        i = len(close) - 2

        if (
            i < 1
            or atr_value <= 0
        ):

            return {
                "bullish": False,
                "bearish": False
            }

        previous_close = float(
            close.iloc[i - 1]
        )

        current_close = float(
            close.iloc[i]
        )

        candle_range = float(
            high.iloc[i]
            - low.iloc[i]
        )

        current_open = float(open_price.iloc[i])
        body = abs(
            current_close
            - current_open
        )

        strong = (
            body >= atr_value * 0.60
            and candle_range
            >= atr_value * 0.80
        )

        return {
            "bullish": (
                current_close
                > previous_close
                and strong
            ),
            "bearish": (
                current_close
                < previous_close
                and strong
            )
        }

    except Exception as e:

        print(
            f"Displacement error: {e}"
        )

        return {
            "bullish": False,
            "bearish": False
        }


# ============================================================
# GAINZALGO V2
# ============================================================

def detect_gainzalgo_v2(
    open_price,
    close,
    high,
    low,
    rsi_value
):

    try:

        i = len(close) - 2

        if i < GAINZ_V2_DELTA:

            return {
                "buy": False,
                "sell": False,
                "bullish_engulfing": False,
                "bearish_engulfing": False,
                "stable_candle": False,
                "rsi_buy": False,
                "rsi_sell": False,
                "price_decrease": False,
                "price_increase": False
            }

        current_open = float(
            open_price.iloc[i]
        )

        current_close = float(
            close.iloc[i]
        )

        previous_open = float(
            open_price.iloc[i - 1]
        )

        previous_close = float(
            close.iloc[i - 1]
        )

        current_high = float(
            high.iloc[i]
        )

        current_low = float(
            low.iloc[i]
        )

        tr1 = (
            current_high
            - current_low
        )

        tr2 = abs(
            current_high
            - previous_close
        )

        tr3 = abs(
            current_low
            - previous_close
        )

        true_range = max(
            tr1,
            tr2,
            tr3
        )

        if true_range <= 0:

            return {
                "buy": False,
                "sell": False,
                "bullish_engulfing": False,
                "bearish_engulfing": False,
                "stable_candle": False,
                "rsi_buy": False,
                "rsi_sell": False,
                "price_decrease": False,
                "price_increase": False
            }

        stable_candle = (
            abs(
                current_close
                - current_open
            ) / true_range
            > GAINZ_V2_STABILITY
        )

        bullish_engulfing = (
            previous_close < previous_open
            and current_close > current_open
            and current_close > previous_open
        )

        bearish_engulfing = (
            previous_close > previous_open
            and current_close < current_open
            and current_close < previous_open
        )

        rsi_buy = (
            rsi_value < GAINZ_V2_RSI
        )

        rsi_sell = (
            rsi_value
            > 100 - GAINZ_V2_RSI
        )

        close_delta = float(
            close.iloc[
                i - GAINZ_V2_DELTA
            ]
        )

        price_decrease = (
            current_close
            < close_delta
        )

        price_increase = (
            current_close
            > close_delta
        )

        gainz_buy = (
            bullish_engulfing
            and stable_candle
            and rsi_buy
            and price_decrease
        )

        gainz_sell = (
            bearish_engulfing
            and stable_candle
            and rsi_sell
            and price_increase
        )

        return {
            "buy": gainz_buy,
            "sell": gainz_sell,
            "bullish_engulfing": bullish_engulfing,
            "bearish_engulfing": bearish_engulfing,
            "stable_candle": stable_candle,
            "rsi_buy": rsi_buy,
            "rsi_sell": rsi_sell,
            "price_decrease": price_decrease,
            "price_increase": price_increase
        }

    except Exception as e:

        print(
            f"GainzAlgo V2 error: {e}"
        )

        return {
            "buy": False,
            "sell": False,
            "bullish_engulfing": False,
            "bearish_engulfing": False,
            "stable_candle": False,
            "rsi_buy": False,
            "rsi_sell": False,
            "price_decrease": False,
            "price_increase": False
        }


# ============================================================
# GAINZALGO PRO
# ============================================================

def detect_gainzalgo_pro(
    open_price,
    close,
    high,
    low,
    rsi_value
):

    try:

        i = len(close) - 2

        if i < GAINZ_PRO_DELTA:

            return {
                "buy": False,
                "sell": False,
                "bullish_engulfing": False,
                "bearish_engulfing": False,
                "stable_candle": False,
                "rsi_buy": False,
                "rsi_sell": False,
                "price_decrease": False,
                "price_increase": False
            }

        current_open = float(
            open_price.iloc[i]
        )

        current_close = float(
            close.iloc[i]
        )

        previous_open = float(
            open_price.iloc[i - 1]
        )

        previous_close = float(
            close.iloc[i - 1]
        )

        current_high = float(
            high.iloc[i]
        )

        current_low = float(
            low.iloc[i]
        )

        tr1 = (
            current_high
            - current_low
        )

        tr2 = abs(
            current_high
            - previous_close
        )

        tr3 = abs(
            current_low
            - previous_close
        )

        true_range = max(
            tr1,
            tr2,
            tr3
        )

        if true_range <= 0:

            return {
                "buy": False,
                "sell": False,
                "bullish_engulfing": False,
                "bearish_engulfing": False,
                "stable_candle": False,
                "rsi_buy": False,
                "rsi_sell": False,
                "price_decrease": False,
                "price_increase": False
            }

        stable_candle = (
            abs(
                current_close
                - current_open
            ) / true_range
            > GAINZ_PRO_STABILITY
        )

        bullish_engulfing = (
            previous_close < previous_open
            and current_close > current_open
            and current_close > previous_open
        )

        bearish_engulfing = (
            previous_close > previous_open
            and current_close < current_open
            and current_close < previous_open
        )

        rsi_buy = (
            rsi_value < GAINZ_PRO_RSI
        )

        rsi_sell = (
            rsi_value
            > 100 - GAINZ_PRO_RSI
        )

        close_delta = float(
            close.iloc[
                i - GAINZ_PRO_DELTA
            ]
        )

        price_decrease = (
            current_close
            < close_delta
        )

        price_increase = (
            current_close
            > close_delta
        )

        gainz_buy = (
            bullish_engulfing
            and stable_candle
            and rsi_buy
            and price_decrease
        )

        gainz_sell = (
            bearish_engulfing
            and stable_candle
            and rsi_sell
            and price_increase
        )

        return {
            "buy": gainz_buy,
            "sell": gainz_sell,
            "bullish_engulfing": bullish_engulfing,
            "bearish_engulfing": bearish_engulfing,
            "stable_candle": stable_candle,
            "rsi_buy": rsi_buy,
            "rsi_sell": rsi_sell,
            "price_decrease": price_decrease,
            "price_increase": price_increase
        }

    except Exception as e:

        print(
            f"GainzAlgo Pro error: {e}"
        )

        return {
            "buy": False,
            "sell": False,
            "bullish_engulfing": False,
            "bearish_engulfing": False,
            "stable_candle": False,
            "rsi_buy": False,
            "rsi_sell": False,
            "price_decrease": False,
            "price_increase": False
        }


# ============================================================
# V3.1 MICROSTRUCTURE / HFT-STYLE LAYER
# ============================================================
# OHLCV-based microstructure. This is NOT true exchange order-book HFT.
# True HFT requires tick/order-book/bid-ask data from a suitable feed.

MICROSTRUCTURE_ENABLED = True
MICROSTRUCTURE_HARD_FILTER = False
MIN_MICRO_SCORE = 55
MICRO_BONUS = 5
MICRO_PENALTY = 5


def _safe_ratio(numerator, denominator, default=0.0):
    try:
        d = float(denominator)
        if abs(d) < 1e-12:
            return default
        return float(numerator) / d
    except Exception:
        return default


def analyze_microstructure(open_price, close, high, low, volume, atr_value):
    """Analyze the last completed candle and prior M5 candles only."""
    neutral = {
        "buy_score": 0, "sell_score": 0, "score": 50,
        "direction": "NEUTRAL", "impulse": 0.0, "velocity": 0.0,
        "range_ratio": 1.0, "volume_ratio": 0.0,
        "breakout_buy": False, "breakout_sell": False,
        "fake_breakout_buy": False, "fake_breakout_sell": False,
        "rejection_buy": False, "rejection_sell": False,
        "pullback_buy": False, "pullback_sell": False,
        "reason": "Microstructure unavailable",
    }
    try:
        i = len(close) - 2
        atr = float(atr_value)
        if i < 25 or atr <= 0:
            return neutral
        o, c = float(open_price.iloc[i]), float(close.iloc[i])
        h, l = float(high.iloc[i]), float(low.iloc[i])
        prev_c = float(close.iloc[i - 1])
        prev_o = float(open_price.iloc[i - 1])
        if h <= l:
            return neutral
        start = max(0, i - 20)
        prev_high20 = float(high.iloc[start:i].max())
        prev_low20 = float(low.iloc[start:i].min())
        ranges = (high - low).iloc[start:i].astype(float)
        avg_range = float(ranges.median()) if len(ranges) else 0.0
        vols = volume.iloc[start:i].astype(float)
        avg_volume = float(vols.mean()) if len(vols) else 0.0
        current_volume = float(volume.iloc[i])
        candle_range = h - l
        body = abs(c - o)
        body_ratio = _safe_ratio(body, candle_range)
        close_location = _safe_ratio(c - l, candle_range)
        upper_wick = h - max(o, c)
        lower_wick = min(o, c) - l
        impulse = _safe_ratio(c - o, atr)
        velocity = _safe_ratio(c - prev_c, atr)
        range_ratio = _safe_ratio(candle_range, avg_range, 1.0)
        volume_ratio = _safe_ratio(current_volume, avg_volume, 0.0)
        breakout_buy = c > prev_high20
        breakout_sell = c < prev_low20
        fake_breakout_buy = l < prev_low20 and c > prev_low20
        fake_breakout_sell = h > prev_high20 and c < prev_high20
        rejection_buy = lower_wick >= body * 1.2 and close_location >= 0.65
        rejection_sell = upper_wick >= body * 1.2 and close_location <= 0.35
        pullback_buy = (prev_c - prev_o) < 0 and (c - o) > 0 and c > prev_c
        pullback_sell = (prev_c - prev_o) > 0 and (c - o) < 0 and c < prev_c
        buy = sell = 0
        reasons = []
        if impulse >= 0.35 and velocity > 0:
            buy += 18; reasons.append("bullish impulse")
        elif impulse <= -0.35 and velocity < 0:
            sell += 18; reasons.append("bearish impulse")
        if velocity >= 0.20: buy += 12
        elif velocity <= -0.20: sell += 12
        if body_ratio >= 0.55 and close_location >= 0.70: buy += 12
        elif body_ratio >= 0.55 and close_location <= 0.30: sell += 12
        if range_ratio >= 1.25:
            if c > o: buy += 10
            elif c < o: sell += 10
        if volume_ratio >= 1.20:
            if c > o: buy += 12
            elif c < o: sell += 12
        elif volume_ratio >= 1.05:
            if c > o: buy += 5
            elif c < o: sell += 5
        if breakout_buy: buy += 15; reasons.append("20-bar upside breakout")
        if breakout_sell: sell += 15; reasons.append("20-bar downside breakout")
        if fake_breakout_buy: buy += 10; sell = max(0, sell - 8); reasons.append("bullish liquidity sweep")
        if fake_breakout_sell: sell += 10; buy = max(0, buy - 8); reasons.append("bearish liquidity sweep")
        if rejection_buy: buy += 8
        if rejection_sell: sell += 8
        if pullback_buy: buy += 8
        if pullback_sell: sell += 8
        buy, sell = max(0, min(100, buy)), max(0, min(100, sell))
        score = int(max(0, min(100, 50 + (buy - sell) * 0.5)))
        if buy > sell and buy >= MIN_MICRO_SCORE: direction = "BUY"
        elif sell > buy and sell >= MIN_MICRO_SCORE: direction = "SELL"
        else: direction = "NEUTRAL"
        return {
            "buy_score": buy, "sell_score": sell, "score": score,
            "direction": direction, "impulse": impulse, "velocity": velocity,
            "range_ratio": range_ratio, "volume_ratio": volume_ratio,
            "breakout_buy": breakout_buy, "breakout_sell": breakout_sell,
            "fake_breakout_buy": fake_breakout_buy, "fake_breakout_sell": fake_breakout_sell,
            "rejection_buy": rejection_buy, "rejection_sell": rejection_sell,
            "pullback_buy": pullback_buy, "pullback_sell": pullback_sell,
            "reason": ", ".join(reasons) if reasons else "No strong microstructure event",
        }
    except Exception as e:
        print(f"Microstructure error: {e}")
        return neutral


def microstructure_confirms(signal, micro):
    if signal == "🟢 BUY":
        return micro.get("direction") == "BUY" or micro.get("buy_score", 0) >= MIN_MICRO_SCORE
    if signal == "🔴 SELL":
        return micro.get("direction") == "SELL" or micro.get("sell_score", 0) >= MIN_MICRO_SCORE
    return False


# ============================================================
# SUB-$100 XAU/USD SCALP ENGINE
# ============================================================
def analyze_sp2l_pullback(m5):
    """SP2L: recent >2x ATR spike followed by a 50% body pullback."""
    neutral = {"buy": False, "sell": False, "direction": 0, "score": 0,
               "spike_found": False, "spike_type": "NONE", "spike_index": -1,
               "spike_high": 0.0, "spike_low": 0.0, "spike_close": 0.0,
               "mid_level": 0.0, "entry": 0.0, "sl": 0.0, "tp": 0.0,
               "reason": "SP2L unavailable"}
    try:
        if not SP2L_ENABLED or m5 is None:
            return neutral
        o,h,l,c = m5["open"],m5["high"],m5["low"],m5["close"]
        if len(c) < 30:
            return neutral
        current_i = len(c)-2
        current_price = float(c.iloc[current_i])
        body_series = (c-o).abs()
        tr = pd.concat([(h-l),(h-c.shift(1)).abs(),(l-c.shift(1)).abs()],axis=1).max(axis=1)
        atr = tr.rolling(14).mean()
        spike = None
        start=max(1,current_i-SP2L_LOOKBACK+1)
        for idx in range(current_i,start-1,-1):
            av=float(atr.iloc[idx]) if pd.notna(atr.iloc[idx]) else 0.0
            body=float(body_series.iloc[idx])
            prev_body=float(body_series.iloc[idx-1])
            if av>0 and body>av*SP2L_SPIKE_ATR_MULT and body>prev_body:
                spike=idx; break
        if spike is None:
            neutral["reason"]="No recent SP2L spike"
            return neutral
        so,sc,sh,sl=map(float,(o.iloc[spike],c.iloc[spike],h.iloc[spike],l.iloc[spike]))
        body=abs(sc-so); bullish=sc>so
        if bullish:
            mid=sl+body*0.5; valid=current_price<sc and current_price>mid
            direction=1; tp=current_price+(current_price-sl); stop=sl
            reason="Bullish spike + 50% pullback"
        else:
            mid=sh-body*0.5; valid=current_price>sc and current_price<mid
            direction=-1; tp=current_price-(sh-current_price); stop=sh
            reason="Bearish spike + 50% pullback"
        out=dict(neutral)
        out.update({"spike_found":True,"spike_type":"BULLISH" if bullish else "BEARISH",
                    "spike_index":current_i-spike,"spike_high":sh,"spike_low":sl,
                    "spike_close":sc,"mid_level":mid,"entry":current_price,"sl":stop,"tp":tp,
                    "direction":direction if valid else 0,"score":100 if valid else 0,
                    "buy":bool(valid and bullish),"sell":bool(valid and not bullish),
                    "reason":reason if valid else reason+" not in valid zone"})
        return out
    except Exception as e:
        print(f"SP2L error: {e}")
        return neutral


def analyze_scalp_trigger(m1, m5):
    """Closed-candle M1/M5 trigger engine for short-term XAU/USD scalping."""
    neutral = {
        "buy": False, "sell": False, "direction": 0,
        "score": 0, "m1_score": 0, "m5_score": 0,
        "m1_trend": 0, "m5_trend": 0,
        "reason": "Scalp trigger unavailable",
    }
    try:
        if m1 is None or m5 is None:
            return neutral
        c1,o1,h1,l1 = m1["close"],m1["open"],m1["high"],m1["low"]
        c5,o5,h5,l5 = m5["close"],m5["open"],m5["high"],m5["low"]
        if len(c1) < 60 or len(c5) < 60:
            return neutral
        i1, i5 = len(c1)-2, len(c5)-2
        def ema_pair(c):
            fast=ta.trend.ema_indicator(c,9); slow=ta.trend.ema_indicator(c,21)
            return float(fast.iloc[-2]), float(slow.iloc[-2]), float(fast.iloc[-3]), float(slow.iloc[-3])
        f1,s1,pf1,ps1=ema_pair(c1); f5,s5,pf5,ps5=ema_pair(c5)
        m1bull=f1>s1; m5bull=f5>s5
        r1=float(ta.momentum.rsi(c1,7).iloc[-2]); r5=float(ta.momentum.rsi(c5,7).iloc[-2])
        mac1=ta.trend.MACD(c1,window_fast=6,window_slow=13,window_sign=5)
        mac5=ta.trend.MACD(c5,window_fast=6,window_slow=13,window_sign=5)
        m1m=float(mac1.macd().iloc[-2]); m1s=float(mac1.macd_signal().iloc[-2])
        m5m=float(mac5.macd().iloc[-2]); m5s=float(mac5.macd_signal().iloc[-2])
        atr1=float(ta.volatility.average_true_range(h1,l1,c1,14).iloc[-2])
        atr5=float(ta.volatility.average_true_range(h5,l5,c5,14).iloc[-2])
        if atr1<=0 or atr5<=0: return neutral
        last1=float(c1.iloc[i1]); prev1=float(c1.iloc[i1-1])
        o=float(o1.iloc[i1]); hi=float(h1.iloc[i1]); lo=float(l1.iloc[i1])
        rng=hi-lo; body=abs(last1-o); loc=(last1-lo)/rng if rng>0 else .5
        # Short-term momentum/rejection/continuation components.
        buy1=sell1=0; buy5=sell5=0; reasons=[]
        if m1bull: buy1+=20
        else: sell1+=20
        if m5bull: buy5+=20
        else: sell5+=20
        if m1m>m1s: buy1+=15
        else: sell1+=15
        if m5m>m5s: buy5+=15
        else: sell5+=15
        if 48<=r1<=68: buy1+=15
        if 32<=r1<=52: sell1+=15
        if 45<=r5<=70: buy5+=10
        if 30<=r5<=55: sell5+=10
        if last1>prev1 and last1>o: buy1+=15
        if last1<prev1 and last1<o: sell1+=15
        if rng>=atr1*0.65 and body/rng>=0.55:
            if last1>o and loc>=0.70: buy1+=10
            if last1<o and loc<=0.30: sell1+=10
        # 5-minute candle direction adds context, not a hard trend lock.
        c5now=float(c5.iloc[i5]); c5prev=float(c5.iloc[i5-1]); o5now=float(o5.iloc[i5])
        if c5now>c5prev and c5now>o5now: buy5+=10
        if c5now<c5prev and c5now<o5now: sell5+=10
        # Avoid chasing an extreme M1 move; prefer pullback/continuation zones.
        if r1>74: buy1=max(0,buy1-15)
        if r1<26: sell1=max(0,sell1-15)
        buy=min(100,buy1+buy5//2); sell=min(100,sell1+sell5//2)
        if buy>sell:
            direction=1; score=int(buy); reasons.append("M1/M5 bullish scalp trigger")
        elif sell>buy:
            direction=-1; score=int(sell); reasons.append("M1/M5 bearish scalp trigger")
        else:
            direction=0; score=max(buy,sell)
        if abs(f1-s1)/atr1 < 0.08: reasons.append("M1 EMA compression")
        return {"buy":direction==1 and score>=SCALP_MIN_CANDIDATE_SCORE,
                "sell":direction==-1 and score>=SCALP_MIN_CANDIDATE_SCORE,
                "direction":direction,"score":score,
                "m1_score":int(max(buy1,sell1)),"m5_score":int(max(buy5,sell5)),
                "m1_trend":1 if m1bull else -1,"m5_trend":1 if m5bull else -1,
                "atr1":atr1,"atr5":atr5,"rsi1":r1,"rsi5":r5,
                "reason":", ".join(reasons)}
    except Exception as e:
        print(f"Scalp trigger error: {e}")
        return neutral


# ============================================================
# TP / SL VALIDATION
# ============================================================

def validate_trade_levels(
    signal,
    price,
    stop_loss,
    tp1,
    tp2,
    tp3
):

    try:

        values = [
            price,
            stop_loss,
            tp1,
            tp2,
            tp3
        ]

        if not all(
            is_valid_number(x)
            for x in values
        ):

            return (
                False,
                "Invalid price values"
            )

        if signal == "🟢 BUY":

            valid = (
                stop_loss < price
                and tp1 > price
                and tp2 > tp1
                and tp3 > tp2
            )

        elif signal == "🔴 SELL":

            valid = (
                stop_loss > price
                and tp1 < price
                and tp2 < tp1
                and tp3 < tp2
            )

        else:

            return (
                False,
                "Invalid signal"
            )

        if not valid:

            return (
                False,
                "Invalid TP/SL structure"
            )

        risk = abs(
            price - stop_loss
        )

        reward = abs(
            tp3 - price
        )

        if risk <= 0:

            return (
                False,
                "Zero risk"
            )

        rr = reward / risk

        if rr < 1.20:

            return (
                False,
                f"Risk/Reward too low ({rr:.2f})"
            )

        return (
            True,
            f"Valid TP/SL R:R={rr:.2f}"
        )

    except Exception as e:

        return (
            False,
            f"TP/SL validation error: {e}"
        )


# ============================================================
# V3 QUALITY SCORE
# ============================================================

def calculate_quality_score(
    signal,
    ema_bullish,
    m15_bullish,
    h1_bullish,
    macd_bullish,
    rsi_value,
    adx_value,
    volume_confirmed,
    news_risk,
    entry_quality,
    structure_confirmed=False,
    liquidity_confirmed=False,
    fvg_confirmed=False,
    displacement_confirmed=False,
    dxy_confirmed=False,
    gainz_v2_confirmed=False,
    gainz_pro_confirmed=False
):

    score = 0

    buy = (
        signal == "🟢 BUY"
    )

    sell = (
        signal == "🔴 SELL"
    )

    if (
        (buy and ema_bullish)
        or
        (sell and not ema_bullish)
    ):
        score += 15

    if (
        (buy and macd_bullish)
        or
        (sell and not macd_bullish)
    ):
        score += 15

    if (
        (buy and m15_bullish)
        or
        (sell and not m15_bullish)
    ):
        score += 10

    if (
        (buy and h1_bullish)
        or
        (sell and not h1_bullish)
    ):
        score += 10

    if adx_value >= 30:

        score += 15

    elif adx_value >= 25:

        score += 10

    elif adx_value >= 20:

        score += 5

    if volume_confirmed:
        score += 10

    if buy:

        if 45 < rsi_value < 70:
            score += 10

        elif 40 < rsi_value < 75:
            score += 5

    elif sell:

        if 30 < rsi_value < 55:
            score += 10

        elif 25 < rsi_value < 60:
            score += 5

    if news_risk == "HIGH":

        score -= 20

    elif news_risk == "MEDIUM":

        score += 5

    else:

        score += 10

    if entry_quality == "A":

        score += 10

    elif entry_quality == "B":

        score += 5

    else:

        score -= 10

    if structure_confirmed:
        score += 5

    if liquidity_confirmed:
        score += 5

    if fvg_confirmed:
        score += 5

    if displacement_confirmed:
        score += 5

    if dxy_confirmed:
        score += 5

    if gainz_v2_confirmed:
        score += GAINZ_V2_BONUS

    if gainz_pro_confirmed:
        score += GAINZ_PRO_BONUS

    return max(
        0,
        min(
            100,
            int(score)
        )
    )


# ============================================================
# MASTER V3 HARD FILTER
# ============================================================

def master_quality_filter(
    signal, ai_score, quality_score, entry_quality, adx_value,
    volume_confirmed, trend_aligned, rsi_valid, news_risk, tp_sl_valid,
    scalp=None, micro_score=0, money_score=0
):

    if SCALP_SUB100_ENABLED:
        if signal not in ["🟢 BUY", "🔴 SELL"]:
            return False, "No clear scalp signal"
        direction = 1 if signal == "🟢 BUY" else -1
        if ai_score < SCALP_MIN_AI_SCORE:
            return False, f"Scalp AI below {SCALP_MIN_AI_SCORE}"
        if quality_score < SCALP_MIN_QUALITY_SCORE:
            return False, f"Scalp quality below {SCALP_MIN_QUALITY_SCORE}"
        if adx_value < SCALP_MIN_ADX and micro_score < SCALP_MIN_MICRO_SCORE:
            return False, f"ADX {adx_value:.2f} too weak without micro confirmation"
        if scalp is None or scalp.get("direction") != direction:
            return False, "M1/M5 scalp direction conflict"
        if scalp.get("m1_score",0) < SCALP_MIN_M1_SCORE or scalp.get("m5_score",0) < SCALP_MIN_M5_SCORE:
            return False, "M1/M5 trigger confirmation too weak"
        if micro_score < SCALP_MIN_MICRO_SCORE and money_score < SCALP_MIN_MONEY_SCORE:
            return False, "Need Microstructure or Money Structure confirmation"
        if not trend_aligned:
            return False, "M1/M5 trend conflict"
        if not rsi_valid:
            return False, "M1 RSI not in scalp zone"
        if news_risk == "HIGH":
            return False, "HIGH news risk"
        if not tp_sl_valid:
            return False, "Invalid TP/SL"
        return True, "SUB-$100 SCALP FILTERS PASSED"

    if signal not in [
        "🟢 BUY",
        "🔴 SELL"
    ]:

        return (
            False,
            "No clear signal"
        )

    if ai_score < MIN_AI_SCORE:

        return (
            False,
            f"AI Score below {MIN_AI_SCORE}"
        )

    if quality_score < MIN_QUALITY_SCORE:

        return (
            False,
            f"Quality below {MIN_QUALITY_SCORE}"
        )

    if entry_quality != "A":

        return (
            False,
            f"Entry Quality {entry_quality}"
        )

    if adx_value < MIN_ADX:

        return (
            False,
            f"ADX below {MIN_ADX}"
        )

    if not volume_confirmed:

        return (
            False,
            "Volume confirmation missing"
        )

    if not trend_aligned:

        return (
            False,
            "M5/M15/H1 trend conflict"
        )

    if not rsi_valid:

        return (
            False,
            "RSI not valid"
        )

    if news_risk == "HIGH":

        return (
            False,
            "HIGH news risk"
        )

    if not tp_sl_valid:

        return (
            False,
            "Invalid TP/SL"
        )

    return (
        True,
        "ALL MASTER V3 HARD FILTERS PASSED"
    )


# ============================================================
# MARKET ANALYSIS
# ============================================================

def analyze_market(
    symbol,
    name
):

    try:

        print(
            f"\n{'=' * 60}\n"
            f"Analyzing {name}\n"
            f"{'=' * 60}"
        )

        if is_weekend() and symbol not in {x[0] for x in CRYPTO_MARKETS}:

            print(
                f"{name}: "
                f"Weekend - skipped"
            )

            return None

        # ====================================================
        # NEWS
        # ====================================================

        try:

            news = check_news() or {
                "risk": "HIGH"
            }

            news_risk = str(
                news.get(
                    "risk",
                    "HIGH"
                )
            ).upper()

        except Exception as e:

            print(
                f"{name}: "
                f"News error: {e}"
            )

            news_risk = "HIGH"

        # ====================================================
        # DATA
        # ====================================================

        m5 = prepare_data(
            symbol,
            "5m"
        )

        m15 = prepare_data(
            symbol,
            "15m"
        )

        h1 = prepare_data(
            symbol,
            "1h"
        )

        h4 = resample_h4(h1) if H4_ENABLED else None
        m1 = prepare_data(symbol, "1m") if M1_ENABLED else None

        # Core signal timeframes are M5/M15/H1. H4 and M1 are adaptive
        # context/timing layers and must never stop an otherwise valid scan.
        if m5 is None or m15 is None or h1 is None:
            print(f"{name}: Missing core timeframe data (M5/M15/H1)")
            return None

        if H4_ENABLED and h4 is None:
            print(f"{name}: H4 unavailable - continuing without H4 context")

        if M1_ENABLED and m1 is None:
            print(f"{name}: M1 unavailable - continuing without M1 timing")

        # ====================================================
        # V4 REGIME + MULTI-TIMEFRAME CONTEXT
        # ====================================================
        regime = market_regime(h1) if REGIME_ENABLED else {"name": "UNKNOWN", "trend": 0, "strength": 0.0, "volatility": "UNKNOWN"}
        h4_regime = market_regime(h4) if h4 is not None else {"trend": 0, "strength": 0.0, "name": "UNKNOWN", "volatility": "UNKNOWN"}
        m15_regime = market_regime(m15)
        m1_regime = market_regime(m1) if m1 is not None else {"trend": 0, "strength": 0.0, "name": "UNKNOWN", "volatility": "UNKNOWN"}
        risk_profile = adaptive_risk()
        print(f"{name}: V4 regime H4={h4_regime['name']}/{h4_regime['trend']} H1={regime['name']}/{regime['trend']} M15={m15_regime['trend']} M1={m1_regime['trend']} Risk={risk_profile['mode']} {risk_profile['risk_pct']:.2f}%")

        dxy = None

        if symbol == "GC=F":

            dxy = prepare_data(
                "DX-Y.NYB",
                "5m"
            )

        # ====================================================
        # M5 DATA
        # ====================================================

        open_price = m5["open"]
        close = m5["close"]
        high = m5["high"]
        low = m5["low"]
        volume = m5["volume"]

        # ====================================================
        # 10-CANDLE OPENING RANGE
        # ====================================================
        opening_range = (
            analyze_opening_range(open_price, high, low, close)
            if symbol == "GC=F" and OPENING_RANGE_ENABLED
            else {"available": False, "direction": 0, "buy": False, "sell": False, "range_high": None, "range_low": None, "status": "DISABLED", "reason": "disabled"}
        )
        print(
            f"{name}: 10C OR status={opening_range.get('status')} "
            f"date={opening_range.get('range_date')} "
            f"HIGH={opening_range.get('range_high')} LOW={opening_range.get('range_low')} "
            f"close={opening_range.get('last_close')}"
        )

        if symbol == "GC=F" and OPENING_RANGE_HARD_FILTER and not opening_range.get("available"):
            print(f"{name}: 10C opening range unavailable - no signal")
            return None

        # ====================================================
        # LIVE PRICE
        # ====================================================

        if symbol == "GC=F":

            price = (
                get_live_gold_price()
            )

        else:

            price = None

        if (
            price is None
            or not is_valid_number(price)
        ):

            price = safe_float(
                close,
                -2
            )

        if price is None:
            return None

        # ====================================================
        # SUPPORT / RESISTANCE
        # ====================================================

        sr = find_support_resistance(
            close
        )

        if not sr:

            print(
                f"{name}: "
                f"Support/Resistance "
                f"unavailable"
            )

            return None

        support = float(
            sr["support"]
        )

        resistance = float(
            sr["resistance"]
        )

        # ====================================================
        # INDICATORS
        # ====================================================

        ema50 = ta.trend.ema_indicator(
            close,
            50
        )

        ema200 = ta.trend.ema_indicator(
            close,
            200
        )

        rsi = ta.momentum.rsi(
            close,
            14
        )

        macd = ta.trend.MACD(
            close
        )

        atr = (
            ta.volatility.average_true_range(
                high,
                low,
                close,
                14
            )
        )

        adx = ta.trend.ADXIndicator(
            high,
            low,
            close,
            14
        )

        e50 = safe_float(
            ema50,
            -2
        )

        e200 = safe_float(
            ema200,
            -2
        )

        r = safe_float(
            rsi,
            -2
        )

        m = safe_float(
            macd.macd(),
            -2
        )

        ms = safe_float(
            macd.macd_signal(),
            -2
        )

        atr_value = safe_float(
            atr,
            -2
        )

        adx_value = safe_float(
            adx.adx(),
            -2
        )

        if any(
            x is None
            for x in [
                e50,
                e200,
                r,
                m,
                ms,
                atr_value,
                adx_value
            ]
        ):

            print(
                f"{name}: "
                f"Indicator data unavailable"
            )

            return None

        # ====================================================
        # GAINZALGO
        # ====================================================

        gainz_v2 = detect_gainzalgo_v2(
            open_price,
            close,
            high,
            low,
            r
        )

        gainz_v2_buy = (
            gainz_v2["buy"]
        )

        gainz_v2_sell = (
            gainz_v2["sell"]
        )

        gainz_pro = detect_gainzalgo_pro(
            open_price,
            close,
            high,
            low,
            r
        )

        gainz_pro_buy = (
            gainz_pro["buy"]
        )

        gainz_pro_sell = (
            gainz_pro["sell"]
        )

        print(
            f"{name}: "
            f"Gainz V2 BUY="
            f"{gainz_v2_buy} "
            f"SELL="
            f"{gainz_v2_sell}"
        )

        print(
            f"{name}: "
            f"Gainz Pro BUY="
            f"{gainz_pro_buy} "
            f"SELL="
            f"{gainz_pro_sell}"
        )

        # ====================================================
        # TREND
        # ====================================================

        ema_bullish = (
            e50 > e200
        )

        macd_bullish = (
            m > ms
        )

        # ====================================================
        # M15
        # ====================================================

        m15_ema50 = ta.trend.ema_indicator(
            m15["close"],
            50
        )

        m15_ema200 = ta.trend.ema_indicator(
            m15["close"],
            200
        )

        m15_e50 = safe_float(
            m15_ema50,
            -2
        )

        m15_e200 = safe_float(
            m15_ema200,
            -2
        )

        if (
            m15_e50 is None
            or m15_e200 is None
        ):
            return None

        m15_bullish = (
            m15_e50 > m15_e200
        )

        # ====================================================
        # H1
        # ====================================================

        h1_ema50 = ta.trend.ema_indicator(
            h1["close"],
            50
        )

        h1_ema200 = ta.trend.ema_indicator(
            h1["close"],
            200
        )

        h1_e50 = safe_float(
            h1_ema50,
            -2
        )

        h1_e200 = safe_float(
            h1_ema200,
            -2
        )

        if (
            h1_e50 is None
            or h1_e200 is None
        ):
            return None

        h1_bullish = (
            h1_e50 > h1_e200
        )

        # ====================================================
        # VOLUME
        # ====================================================

        v = volume.fillna(0)

        current_volume = (
            safe_float(v, -2)
            or 0.0
        )

        start_volume = max(
            0,
            len(v) - 52
        )

        end_volume = max(
            1,
            len(v) - 2
        )

        window = v.iloc[
            start_volume:end_volume
        ]

        avg_volume = (
            float(window.mean())
            if len(window)
            else 0.0
        )

        volume_confirmed = (
            avg_volume > 0
            and current_volume
            >= avg_volume * 1.05
        )

        # ====================================================
        # V3.1 MICROSTRUCTURE / HFT-STYLE ANALYSIS
        # ====================================================
        micro = analyze_microstructure(
            open_price, close, high, low, volume, atr_value
        )
        print(
            f"{name}: Microstructure BUY={micro['buy_score']} "
            f"SELL={micro['sell_score']} DIR={micro['direction']} "
            f"VOLx={micro['volume_ratio']:.2f} RANGEx={micro['range_ratio']:.2f}"
        )

        # ====================================================
        # MONEY STRUCTURE LEVEL
        # ====================================================
        money_structure = (
            analyze_money_structure(
                open_price, high, low, close, volume
            )
            if MONEY_STRUCTURE_ENABLED
            else {"direction": 0, "score": 0, "buy": False, "sell": False, "reason": "disabled"}
        )
        print(
            f"{name}: Money Structure BUY={money_structure.get('buy_score', 0)} "
            f"SELL={money_structure.get('sell_score', 0)} "
            f"DIR={money_structure.get('direction', 0)} "
            f"ST={money_structure.get('supertrend', 0)} "
            f"Ribbon={money_structure.get('ribbon', 'SIDEWAYS')} "
            f"Cloud={money_structure.get('cloud', 'SIDEWAYS')} "
            f"Trap={money_structure.get('trap', 'NONE')}"
        )

        # ====================================================
        # SMART MONEY
        # ====================================================

        structure = analyze_structure(
            close,
            high,
            low
        )

        liquidity = detect_liquidity_sweep(
            close,
            high,
            low
        )

        fvg = detect_fvg(
            close,
            high,
            low,
            atr_value
        )

        displacement = detect_displacement(
            open_price,
            close,
            high,
            low,
            atr_value
        )

        # ====================================================
        # SUB-$100 SCALP SCORING
        # ====================================================
        scalp = analyze_scalp_trigger(m1, m5) if SCALP_SUB100_ENABLED else {}
        sp2l = analyze_sp2l_pullback(m5) if SCALP_SUB100_ENABLED else {}
        print(f"{name}: SP2L BUY={sp2l.get('buy',False)} SELL={sp2l.get('sell',False)} DIR={sp2l.get('direction',0)} SPIKE={sp2l.get('spike_type','NONE')} SCORE={sp2l.get('score',0)}")
        print(f"{name}: SCALP M1={scalp.get('m1_score',0)} M5={scalp.get('m5_score',0)} DIR={scalp.get('direction',0)} SCORE={scalp.get('score',0)}")

        buy_score = 0
        sell_score = 0
        if scalp.get("direction") == 1:
            buy_score += int(scalp.get("score",0))
        elif scalp.get("direction") == -1:
            sell_score += int(scalp.get("score",0))

        # M5 remains the primary execution context; M15/H1 are soft context only.
        if ema_bullish: buy_score += 8
        else: sell_score += 8
        if macd_bullish: buy_score += 8
        else: sell_score += 8
        if m15_bullish: buy_score += 4
        else: sell_score += 4
        if h1_bullish: buy_score += 4
        else: sell_score += 4
        if h4_regime["trend"] > 0: buy_score += 3
        elif h4_regime["trend"] < 0: sell_score += 3
        if m1_regime["trend"] > 0: buy_score += 5
        elif m1_regime["trend"] < 0: sell_score += 5
        if gainz_v2_buy: buy_score += 5
        if gainz_v2_sell: sell_score += 5
        if gainz_pro_buy: buy_score += 5
        if gainz_pro_sell: sell_score += 5
        if structure["bullish_bos"] or structure["bullish_choch"]: buy_score += 8
        if structure["bearish_bos"] or structure["bearish_choch"]: sell_score += 8
        if liquidity["bullish"]: buy_score += 8
        if liquidity["bearish"]: sell_score += 8
        if displacement["bullish"]: buy_score += 5
        if displacement["bearish"]: sell_score += 5
        if fvg["bullish"]: buy_score += 4
        if fvg["bearish"]: sell_score += 4
        if money_structure.get("buy"): buy_score += 10
        if money_structure.get("sell"): sell_score += 10
        # Candle-10 levels are contextual only.
        rh,rl,lc=opening_range.get("range_high"),opening_range.get("range_low"),opening_range.get("last_close")
        if rh is not None and rl is not None and lc is not None:
            if lc>rh: buy_score += 5
            elif lc<rl: sell_score += 5

        if buy_score >= SCALP_MIN_CANDIDATE_SCORE and buy_score > sell_score:
            signal="🟢 BUY"; preliminary=min(100,buy_score)
        elif sell_score >= SCALP_MIN_CANDIDATE_SCORE and sell_score > buy_score:
            signal="🔴 SELL"; preliminary=min(100,sell_score)
        else:
            print(f"{name}: No scalp direction BUY={buy_score} SELL={sell_score}")
            return None

        # ====================================================
        # 10-CANDLE LEVEL CONFIRMATION (SOFT)
        # ====================================================
        # The video explicitly says its clips are for back-testing and
        # future use of the Candle-10 lines, not entry/SL/TP signals.
        # Therefore do NOT hard-reject an AI signal merely because a
        # Candle-10 breakout is absent. We only report alignment.
        if symbol == "GC=F" and OPENING_RANGE_ENABLED:
            rh = opening_range.get("range_high")
            rl = opening_range.get("range_low")
            lc = opening_range.get("last_close")
            if rh is not None and rl is not None and lc is not None:
                if lc > rh:
                    print(f"{name}: 10C LEVEL CONTEXT = ABOVE HIGH")
                elif lc < rl:
                    print(f"{name}: 10C LEVEL CONTEXT = BELOW LOW")
                else:
                    print(f"{name}: 10C LEVEL CONTEXT = INSIDE RANGE")

        print(
            f"{name}: "
            f"{signal} candidate "
            f"BUY={buy_score} "
            f"SELL={sell_score}"
        )

        # ====================================================
        # ADVANCED 16-MODULE SCALPING ENGINE
        # ====================================================
        advanced = None
        if ADVANCED_MODULES_ENABLED:
            advanced = advanced_module_analysis(
                open_price, close, high, low, atr_value,
                signal, structure, liquidity, fvg, displacement,
                money_structure, micro, gainz_v2, gainz_pro,
                regime, m15_regime, h1_regime, news_risk
            )
            advanced_score = advanced["score"]
            blended = int(round(
                (1.0 - ADVANCED_SCORE_WEIGHT) * preliminary
                + ADVANCED_SCORE_WEIGHT * advanced_score
            ))
            preliminary = min(100, blended)
            print(
                f"{name}: Advanced16 score={advanced_score}/100 "
                f"blend={preliminary}/100 aligned={len(advanced['aligned'])}/16 "
                f"OB={advanced['order_block'].get('valid')} "
                f"Breaker={advanced['breaker_block'].get('valid')} "
                f"KZ={advanced['kill_zone']['name']}"
            )

        # ====================================================
        # GAINZ CONFIRMATION
        # ====================================================

        if signal == "🟢 BUY":

            gainz_v2_confirmed = (
                gainz_v2_buy
            )

            gainz_pro_confirmed = (
                gainz_pro_buy
            )

        else:

            gainz_v2_confirmed = (
                gainz_v2_sell
            )

            gainz_pro_confirmed = (
                gainz_pro_sell
            )

        # ====================================================
        # ENTRY
        # ====================================================

        try:
            entry = check_entry(signal, price, support, resistance, r, preliminary)
        except Exception:
            entry = None

        # Legacy entry_filter is informational in the dedicated scalp profile.
        # M1/M5 trigger + structure + microstructure perform the execution gate.
        entry_quality = entry.get("quality", "B") if entry else "B"

        # ====================================================
        # RSI VALIDATION
        # ====================================================

        scalp_rsi = float(scalp.get("rsi1", r))
        if signal == "🟢 BUY":
            rsi_valid = 42 <= scalp_rsi <= 72
        else:
            rsi_valid = 28 <= scalp_rsi <= 58

        # ====================================================
        # TREND ALIGNMENT
        # ====================================================

        if signal == "🟢 BUY":
            trend_aligned = (scalp.get("m1_trend") == 1 and scalp.get("m5_trend") == 1)
        else:
            trend_aligned = (scalp.get("m1_trend") == -1 and scalp.get("m5_trend") == -1)

        # ====================================================
        # SMART MONEY DIRECTION
        # ====================================================

        if signal == "🟢 BUY":

            structure_confirmed = (
                structure["bullish_bos"]
                or structure["bullish_choch"]
            )

            liquidity_confirmed = (
                liquidity["bullish"]
            )

            fvg_confirmed = (
                fvg["bullish"]
            )

            displacement_confirmed = (
                displacement["bullish"]
            )

        else:

            structure_confirmed = (
                structure["bearish_bos"]
                or structure["bearish_choch"]
            )

            liquidity_confirmed = (
                liquidity["bearish"]
            )

            fvg_confirmed = (
                fvg["bearish"]
            )

            displacement_confirmed = (
                displacement["bearish"]
            )

        # ====================================================
        # TP / SL MULTIPLIERS
        # ====================================================

        if symbol == "GC=F" and SCALP_SUB100_ENABLED:
            sl_mult = SCALP_SL_ATR
            tp_mult = SCALP_TP3_ATR
        elif symbol == "GC=F":
            sl_mult = 2.0
            tp_mult = 3.0

        elif symbol in [
            "BTC-USD",
            "ETH-USD",
            "SOL-USD",
            "BNB-USD"
        ]:

            sl_mult = 3.0
            tp_mult = 5.0

        else:

            sl_mult = 2.0
            tp_mult = 3.0

        # ====================================================
        # TP / SL
        # ====================================================
        # Use M1 ATR for short-term execution; M5 ATR is a fallback.
        scalp_atr = float(scalp.get("atr1", 0.0) or 0.0)
        if scalp_atr <= 0:
            scalp_atr = float(scalp.get("atr5", 0.0) or atr_value)
        if SCALP_SUB100_ENABLED and symbol == "GC=F":
            atr_for_trade = scalp_atr
            tp1_mult = SCALP_TP1_ATR
            tp2_mult = SCALP_TP2_ATR
        else:
            atr_for_trade = atr_value
            tp1_mult = 1.0
            tp2_mult = 2.0

        # Smart Order-Block SL; M1/M5 ATR remains the fallback.
        direction_num = 1 if signal == "🟢 BUY" else -1
        ob_for_sl = advanced.get("order_block", {}) if advanced else {}
        stop_loss, sl_method = calculate_smart_stop_loss(
            price, atr_for_trade, direction_num, ob_for_sl
        )

        if signal == "🟢 BUY":
            tp1 = price + atr_for_trade * tp1_mult
            tp2 = price + atr_for_trade * tp2_mult
            tp3 = price + atr_for_trade * tp_mult
        else:
            tp1 = price - atr_for_trade * tp1_mult
            tp2 = price - atr_for_trade * tp2_mult
            tp3 = price - atr_for_trade * tp_mult

        valid_levels, level_reason = (
            validate_trade_levels(
                signal,
                price,
                stop_loss,
                tp1,
                tp2,
                tp3
            )
        )

        if not valid_levels:

            print(
                f"{name}: "
                f"TP/SL rejected - "
                f"{level_reason}"
            )

            return None

        risk_snapshot = risk_management_snapshot(
            price, stop_loss, atr_for_trade, direction_num, risk_profile
        )

        if not signal_slot_available():
            print(
                f"{name}: Signal slot blocked by "
                f"{SIGNAL_COOLDOWN_MINUTES}m cooldown / one-active-signal rule"
            )
            return None

        # ====================================================
        # DXY
        # ====================================================

        dxy_confirmed = False

        if (
            symbol == "GC=F"
            and dxy is not None
            and len(dxy["close"]) >= 22
        ):

            dxy_now = safe_float(
                dxy["close"],
                -2
            )

            dxy_old = safe_float(
                dxy["close"],
                -22
            )

            if (
                dxy_now is not None
                and dxy_old is not None
            ):

                if signal == "🟢 BUY":

                    dxy_confirmed = (
                        dxy_now < dxy_old
                    )

                else:

                    dxy_confirmed = (
                        dxy_now > dxy_old
                    )

        # ====================================================
        # SMART SCORE
        # ====================================================

        try:

            smart = calculate_score(
                name,
                signal,
                preliminary,
                price,
                support,
                resistance,
                news_risk
            )

            smart_score = int(
                max(
                    0,
                    min(
                        100,
                        float(
                            smart.get(
                                "score",
                                0
                            )
                        )
                    )
                )
            )

            smart_decision = smart.get(
                "decision",
                "Unknown"
            )

        except Exception as e:

            print(
                f"{name}: "
                f"Smart score error: {e}"
            )

            smart_score = 0

            smart_decision = (
                "Smart score unavailable"
            )

        # ====================================================
        # QUALITY SCORE
        # ====================================================

        quality_score = calculate_quality_score(
            signal,
            ema_bullish,
            m15_bullish,
            h1_bullish,
            macd_bullish,
            r,
            adx_value,
            volume_confirmed,
            news_risk,
            entry_quality,
            structure_confirmed,
            liquidity_confirmed,
            fvg_confirmed,
            displacement_confirmed,
            dxy_confirmed,
            gainz_v2_confirmed,
            gainz_pro_confirmed
        )

        # Soft Money Structure contribution.
        money_confirms = (
            (signal == "🟢 BUY" and money_structure.get("buy"))
            or (signal == "🔴 SELL" and money_structure.get("sell"))
        )
        if money_confirms:
            quality_score = min(100, quality_score + MONEY_STRUCTURE_BONUS)

        # Optional hard mode is disabled by default so the existing V4 logic
        # remains the primary decision engine.
        if MONEY_STRUCTURE_HARD_FILTER and not money_confirms:
            print(f"{name}: Money Structure hard filter rejected")
            return None

        # Soft microstructure contribution.
        micro_confirmed = microstructure_confirms(signal, micro)
        if micro_confirmed:
            quality_score = min(100, quality_score + MICRO_BONUS)
        elif micro.get("direction") not in ("NEUTRAL", None):
            quality_score = max(0, quality_score - MICRO_PENALTY)

        # Scalp-specific quality bonuses: M1/M5 trigger and structure matter more
        # than distant H1 alignment for this profile.
        if SCALP_SUB100_ENABLED:
            if scalp.get("direction") == (1 if signal == "🟢 BUY" else -1):
                quality_score = min(100, quality_score + 8)
            if micro_confirmed:
                quality_score = min(100, quality_score + 5)
            if money_confirms:
                quality_score = min(100, quality_score + 5)
            if sp2l.get("direction") == (1 if signal == "🟢 BUY" else -1):
                quality_score = min(100, quality_score + SP2L_BONUS)
            elif sp2l.get("direction") != 0:
                quality_score = max(0, quality_score - SP2L_BONUS)

        # ====================================================
        # FINAL AI SCORE
        # ====================================================

        if SCALP_SUB100_ENABLED:
            # Do not let a secondary smart-score model erase a valid M1/M5 scalp setup.
            final_ai_score = int(max(0, min(100, round(
                quality_score * 0.43 +
                scalp.get("score", 0) * 0.30 +
                micro.get("score", 50) * 0.15 +
                smart_score * 0.07 +
                sp2l.get("score", 0) * 0.05
            ))))
        else:
            final_ai_score = max(0, min(100, int(min(smart_score, quality_score))))

        # ====================================================
        # SCALP SAFETY GATE
        # ====================================================
        if SCALP_SUB100_ENABLED:
            filtered_signal = signal
            old_reason = "Dedicated M1/M5 scalp safety gate"
            if news_risk == "HIGH":
                print(f"{name}: Scalp safety rejected - HIGH news risk")
                return None
            if not trend_aligned:
                print(f"{name}: Scalp safety rejected - M1/M5 conflict")
                return None
            if scalp.get("score", 0) < SCALP_MIN_CANDIDATE_SCORE:
                print(f"{name}: Scalp safety rejected - trigger score low")
                return None
        else:
            try:
                old = apply_no_trade_filter(signal=signal, ai_score=final_ai_score, news_risk=news_risk,
                    entry_quality=entry_quality, quality_score=quality_score, adx_value=adx_value,
                    volume_confirmed=volume_confirmed, trend_aligned=trend_aligned,
                    rsi_valid=rsi_valid, tp_sl_valid=valid_levels)
                filtered_signal = old.get("signal", "⚪ WAIT")
                old_reason = old.get("reason", "")
            except Exception as e:
                print(f"{name}: No-trade filter error: {e}")
                filtered_signal="⚪ WAIT"; old_reason="No-trade filter error"
            if filtered_signal not in ["🟢 BUY","🔴 SELL"]:
                print(f"{name}: No-trade filter rejected: {old_reason}")
                return None

        # ====================================================
        # MASTER V3 HARD FILTER
        # ====================================================

        passed, reason = master_quality_filter(
            filtered_signal,
            final_ai_score,
            quality_score,
            entry_quality,
            adx_value,
            volume_confirmed,
            trend_aligned,
            rsi_valid,
            news_risk,
            valid_levels,
            scalp=scalp,
            micro_score=int(micro.get("score", 0)),
            money_score=int(money_structure.get("score", 0))
        )

        if not passed:

            print(
                f"\n{name}: "
                f"V3 REJECTED"
            )

            print(
                f"AI Score: "
                f"{final_ai_score}/100"
            )

            print(
                f"Quality: "
                f"{quality_score}/100"
            )

            print(
                f"Smart Score: "
                f"{smart_score}/100"
            )

            print(
                f"ADX: "
                f"{adx_value:.2f}"
            )

            print(
                f"Entry: "
                f"{entry_quality}"
            )

            print(
                f"Gainz V2: "
                f"{gainz_v2_confirmed}"
            )

            print(
                f"Gainz Pro: "
                f"{gainz_pro_confirmed}"
            )

            print(
                f"Structure: "
                f"{structure_confirmed}"
            )

            print(
                f"Liquidity: "
                f"{liquidity_confirmed}"
            )

            print(
                f"FVG: "
                f"{fvg_confirmed}"
            )

            print(
                f"Displacement: "
                f"{displacement_confirmed}"
            )

            print(
                f"Reason: "
                f"{reason}"
            )

            return None

        # Optional strict microstructure gate. OFF by default.
        if MICROSTRUCTURE_ENABLED and MICROSTRUCTURE_HARD_FILTER:
            if not microstructure_confirms(filtered_signal, micro):
                print(
                    f"{name}: V3.1 MICRO REJECTED - "
                    f"score={micro['score']} direction={micro['direction']}"
                )
                return None

        # ====================================================
        # FINAL TP / SL VALIDATION
        # ====================================================

        final_valid, _ = (
            validate_trade_levels(
                filtered_signal,
                price,
                stop_loss,
                tp1,
                tp2,
                tp3
            )
        )

        if not final_valid:
            return None

        # ====================================================
        # DUPLICATE SIGNAL FILTER
        # ====================================================

        try:

            allowed = allow_new_signal(
                filtered_signal,
                price
            )

        except Exception as e:

            print(
                f"{name}: "
                f"Duplicate filter error: {e}"
            )

            allowed = False

        if not allowed:

            print(
                f"{name}: "
                f"Duplicate signal blocked"
            )

            return None

        # ====================================================
        # SAVE
        # ====================================================

        try:

            save_last_signal(
                filtered_signal,
                price
            )

            save_trade(
                filtered_signal,
                price,
                final_ai_score,
                stop_loss,
                tp3
            )

            save_signal(
                filtered_signal
            )

        except Exception as e:

            print(
                f"{name}: "
                f"Save error: {e}"
            )

        mark_signal_slot(filtered_signal)

        # ====================================================
        # TELEGRAM MESSAGE - GOLD ONLY / V4.1 FORMAT
        # ====================================================

        direction = (
            "BUY"
            if filtered_signal == "🟢 BUY"
            else "SELL"
        )

        p = lambda x: format_price(
            x,
            symbol
        )

        # 0-100 trend alignment score across M5/MACD/M15/H1.
        trend_checks = [
            ema_bullish if direction == "BUY" else not ema_bullish,
            macd_bullish if direction == "BUY" else not macd_bullish,
            m15_bullish if direction == "BUY" else not m15_bullish,
            h1_bullish if direction == "BUY" else not h1_bullish,
        ]
        trend_alignment_score = int(
            round(100 * sum(bool(x) for x in trend_checks) / len(trend_checks))
        )

        micro_direction = micro.get("direction", "NEUTRAL")
        micro_score = int(float(micro.get("score", 0)))
        sp2l_status = "BUY CONFIRMED" if sp2l.get("buy") else "SELL CONFIRMED" if sp2l.get("sell") else "NO CONFIRMATION"
        advanced_score = advanced.get("score", 0) if advanced else 0
        aligned_count = len(advanced.get("aligned", [])) if advanced else 0
        kz_name = advanced.get("kill_zone", {}).get("name", "OFF") if advanced else "OFF"

        return f"""📊 GOLD SIGNAL (XAU/USD)

🟢 {direction}

⚠️ SL: {p(stop_loss)} ({sl_method})
🎯 TP1: {p(tp1)}
🎯 TP2: {p(tp2)}
🎯 TP3: {p(tp3)}

AI Score: {final_ai_score}/100
Quality: {quality_score}/100
Advanced 16: {advanced_score}/100 ({aligned_count}/16)
ADX: {adx_value:.2f} | RSI: {r:.2f}

Trend: {trend_alignment_score}/100
Micro: {micro_direction} {micro_score}/100
SP2L: {sp2l_status}
Kill Zone: {kz_name}

10C Status: {opening_range.get("status", "N/A")}
BE Trigger: {p(risk_snapshot['break_even_trigger'])}
Trailing: {p(risk_snapshot['trailing_trigger'])}
Risk: {risk_profile['risk_pct']:.2f}% | Mode: {risk_profile['mode']}

QuantumGold Adaptive Scalping V4.2"""

    except Exception as e:

        print(
            f"{name}: "
            f"Unexpected analysis error: "
            f"{e}"
        )

        return None


# ============================================================
# MAIN - GOLD ONLY
# ============================================================

async def main():

    print(
        "\n"
        "====================================================\n"
        "QuantumGold Adaptive Scalping V4.1 - GOLD ONLY\n"
        "===================================================="
    )

    print(f"Scalp Profile: XAU/USD M1+M5 | Balance < $100 | {'ENABLED' if SCALP_SUB100_ENABLED else 'DISABLED'}")
    print(f"Minimum AI Score: {SCALP_MIN_AI_SCORE if SCALP_SUB100_ENABLED else MIN_AI_SCORE}")
    print(f"Minimum Quality: {SCALP_MIN_QUALITY_SCORE if SCALP_SUB100_ENABLED else MIN_QUALITY_SCORE}")
    print(f"Minimum ADX: {SCALP_MIN_ADX if SCALP_SUB100_ENABLED else MIN_ADX}")
    print(f"Design Target Win Rate: {TARGET_WIN_RATE}%")
    print("Market: XAU/USD ONLY")
    print(
        "10-Candle Opening Range: "
        f"{'ENABLED' if OPENING_RANGE_ENABLED else 'DISABLED'} | "
        "Iran 01:30 anchor | Candle 1=01:35 | Candle 10=02:20 | "
        "Levels are context only; M1/M5 scalp trigger is the entry engine"
    )
    print("GainzAlgo V2: ENABLED")
    print("GainzAlgo Pro: ENABLED")
    print("Smart Money confirmations: SOFT / BONUS")
    print(
        "Microstructure V3.1: "
        f"{'ENABLED' if MICROSTRUCTURE_ENABLED else 'DISABLED'} | "
        f"Hard Gate={'ON' if MICROSTRUCTURE_HARD_FILTER else 'OFF'}"
    )
    print(
        "Advanced Scalping 16 Modules: "
        f"{'ENABLED' if ADVANCED_MODULES_ENABLED else 'DISABLED'} | "
        f"Weight={ADVANCED_SCORE_WEIGHT:.2f}"
    )
    print(
        "Risk Controls: BE + Trailing + Daily limits + "
        f"Cooldown={SIGNAL_COOLDOWN_MINUTES}m + One Active Signal"
    )

    if is_weekend():
        print("Weekend - Gold market closed; no signal scan")
        return

    if not TOKEN:
        print("ERROR: TELEGRAM_TOKEN not configured")
        return

    if not CHAT_ID:
        print("ERROR: TELEGRAM_CHAT_ID not configured")
        return

    bot = Bot(token=TOKEN)

    try:
        result = analyze_market("GC=F", "XAU/USD")
    except Exception as e:
        print(f"XAU/USD: Unexpected analysis error: {e}")
        result = None

    if not result:
        print("No qualifying XAU/USD signal")
        return

    try:
        await bot.send_message(
            chat_id=CHAT_ID,
            text=result
        )
        print("XAU/USD signal sent to Telegram")
    except Exception as e:
        print(f"Telegram error: {e}")


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":

    asyncio.run(main())