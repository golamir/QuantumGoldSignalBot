# ============================================================
# QuantumGold HFT ENGINE V3.2
# OHLCV-based Microstructure / HFT-style
#
# IMPORTANT:
# This is NOT true exchange HFT.
# It uses candle + volume data only.
# ============================================================

import math


# ============================================================
# SETTINGS
# ============================================================

HFT_ENABLED = True

HFT_MIN_SCORE = 60

HFT_STRONG_SCORE = 75

HFT_CONFIRM_BONUS = 5

HFT_CONFLICT_PENALTY = 7

HFT_LOOKBACK = 20

HFT_VOLUME_SPIKE = 1.20

HFT_RANGE_EXPANSION = 1.25

HFT_IMPULSE_ATR = 0.35

HFT_EXHAUSTION_WICK = 0.45


# ============================================================
# HELPERS
# ============================================================

def _safe_float(value, default=0.0):

    try:

        value = float(value)

        if math.isfinite(value):
            return value

        return default

    except Exception:

        return default


def _ratio(a, b, default=0.0):

    try:

        b = float(b)

        if abs(b) < 1e-12:
            return default

        return float(a) / b

    except Exception:

        return default


# ============================================================
# MAIN ENGINE
# ============================================================

def analyze_hft(
    open_price,
    close,
    high,
    low,
    volume,
    atr_value
):

    neutral = {
        "score": 50,
        "buy_score": 0,
        "sell_score": 0,
        "direction": "NEUTRAL",

        "impulse": 0.0,
        "velocity": 0.0,

        "volume_ratio": 0.0,
        "range_ratio": 0.0,

        "buy_pressure": 0.0,
        "sell_pressure": 0.0,

        "breakout_buy": False,
        "breakout_sell": False,

        "fake_breakout_buy": False,
        "fake_breakout_sell": False,

        "rejection_buy": False,
        "rejection_sell": False,

        "pullback_buy": False,
        "pullback_sell": False,

        "exhaustion_buy": False,
        "exhaustion_sell": False,

        "strong_buy": False,
        "strong_sell": False,

        "reason": "No HFT data"
    }

    try:

        i = len(close) - 2

        atr = _safe_float(atr_value)

        if i < HFT_LOOKBACK + 3 or atr <= 0:

            return neutral

        # ====================================================
        # CURRENT CLOSED CANDLE
        # ====================================================

        o = _safe_float(
            open_price.iloc[i]
        )

        c = _safe_float(
            close.iloc[i]
        )

        h = _safe_float(
            high.iloc[i]
        )

        l = _safe_float(
            low.iloc[i]
        )

        previous_close = _safe_float(
            close.iloc[i - 1]
        )

        previous_open = _safe_float(
            open_price.iloc[i - 1]
        )

        if h <= l:

            return neutral

        candle_range = h - l

        body = abs(c - o)

        upper_wick = h - max(o, c)

        lower_wick = min(o, c) - l

        body_ratio = _ratio(
            body,
            candle_range
        )

        close_location = _ratio(
            c - l,
            candle_range
        )

        # ====================================================
        # HISTORY
        # ====================================================

        start = max(
            0,
            i - HFT_LOOKBACK
        )

        previous_high = _safe_float(
            high.iloc[start:i].max()
        )

        previous_low = _safe_float(
            low.iloc[start:i].min()
        )

        historical_ranges = (
            high.iloc[start:i]
            - low.iloc[start:i]
        )

        avg_range = _safe_float(
            historical_ranges.median()
        )

        historical_volume = (
            volume.iloc[start:i]
        )

        avg_volume = _safe_float(
            historical_volume.mean()
        )

        current_volume = _safe_float(
            volume.iloc[i]
        )

        # ====================================================
        # MOMENTUM
        # ====================================================

        impulse = _ratio(
            c - o,
            atr
        )

        velocity = _ratio(
            c - previous_close,
            atr
        )

        range_ratio = _ratio(
            candle_range,
            avg_range,
            1.0
        )

        volume_ratio = _ratio(
            current_volume,
            avg_volume
        )

        # ====================================================
        # PRESSURE
        # ====================================================

        close_location = max(
            0.0,
            min(
                1.0,
                close_location
            )
        )

        buy_pressure = (
            close_location
            * body_ratio
            * 100
        )

        sell_pressure = (
            (1.0 - close_location)
            * body_ratio
            * 100
        )

        # ====================================================
        # BREAKOUT
        # ====================================================

        breakout_buy = (
            c > previous_high
        )

        breakout_sell = (
            c < previous_low
        )

        # ====================================================
        # LIQUIDITY / FAKE BREAKOUT
        # ====================================================

        fake_breakout_buy = (
            l < previous_low
            and c > previous_low
        )

        fake_breakout_sell = (
            h > previous_high
            and c < previous_high
        )

        # ====================================================
        # REJECTION
        # ====================================================

        rejection_buy = (
            lower_wick >= candle_range * 0.30
            and close_location >= 0.65
        )

        rejection_sell = (
            upper_wick >= candle_range * 0.30
            and close_location <= 0.35
        )

        # ====================================================
        # PULLBACK
        # ====================================================

        previous_bearish = (
            previous_close < previous_open
        )

        previous_bullish = (
            previous_close > previous_open
        )

        current_bullish = (
            c > o
        )

        current_bearish = (
            c < o
        )

        pullback_buy = (
            previous_bearish
            and current_bullish
            and c > previous_close
        )

        pullback_sell = (
            previous_bullish
            and current_bearish
            and c < previous_close
        )

        # ====================================================
        # EXHAUSTION
        # ====================================================

        exhaustion_buy = (
            c > o
            and upper_wick >= candle_range
            * HFT_EXHAUSTION_WICK
            and body_ratio < 0.55
        )

        exhaustion_sell = (
            c < o
            and lower_wick >= candle_range
            * HFT_EXHAUSTION_WICK
            and body_ratio < 0.55
        )

        # ====================================================
        # SCORING
        # ====================================================

        buy = 0
        sell = 0

        reasons = []

        # ----------------------------------------------------
        # IMPULSE
        # ----------------------------------------------------

        if impulse >= HFT_IMPULSE_ATR:

            buy += 18

            reasons.append(
                "bullish impulse"
            )

        elif impulse <= -HFT_IMPULSE_ATR:

            sell += 18

            reasons.append(
                "bearish impulse"
            )

        # ----------------------------------------------------
        # VELOCITY
        # ----------------------------------------------------

        if velocity >= 0.20:

            buy += 12

        elif velocity <= -0.20:

            sell += 12

        # ----------------------------------------------------
        # CANDLE PRESSURE
        # ----------------------------------------------------

        if (
            body_ratio >= 0.55
            and close_location >= 0.70
        ):

            buy += 12

        elif (
            body_ratio >= 0.55
            and close_location <= 0.30
        ):

            sell += 12

        # ----------------------------------------------------
        # RANGE EXPANSION
        # ----------------------------------------------------

        if range_ratio >= HFT_RANGE_EXPANSION:

            if current_bullish:

                buy += 10

            elif current_bearish:

                sell += 10

        # ----------------------------------------------------
        # VOLUME
        # ----------------------------------------------------

        if volume_ratio >= 1.50:

            if current_bullish:

                buy += 15

            elif current_bearish:

                sell += 15

        elif volume_ratio >= HFT_VOLUME_SPIKE:

            if current_bullish:

                buy += 10

            elif current_bearish:

                sell += 10

        # ----------------------------------------------------
        # BREAKOUT
        # ----------------------------------------------------

        if breakout_buy:

            buy += 15

            reasons.append(
                "upside breakout"
            )

        if breakout_sell:

            sell += 15

            reasons.append(
                "downside breakout"
            )

        # ----------------------------------------------------
        # LIQUIDITY SWEEP
        # ----------------------------------------------------

        if fake_breakout_buy:

            buy += 12

            sell = max(
                0,
                sell - 8
            )

            reasons.append(
                "bullish liquidity sweep"
            )

        if fake_breakout_sell:

            sell += 12

            buy = max(
                0,
                buy - 8
            )

            reasons.append(
                "bearish liquidity sweep"
            )

        # ----------------------------------------------------
        # REJECTION
        # ----------------------------------------------------

        if rejection_buy:

            buy += 8

        if rejection_sell:

            sell += 8

        # ----------------------------------------------------
        # PULLBACK
        # ----------------------------------------------------

        if pullback_buy:

            buy += 8

        if pullback_sell:

            sell += 8

        # ----------------------------------------------------
        # EXHAUSTION PENALTY
        # ----------------------------------------------------

        if exhaustion_buy:

            buy = max(
                0,
                buy - 12
            )

            reasons.append(
                "bullish exhaustion"
            )

        if exhaustion_sell:

            sell = max(
                0,
                sell - 12
            )

            reasons.append(
                "bearish exhaustion"
            )

        # ====================================================
        # LIMIT
        # ====================================================

        buy = int(
            max(
                0,
                min(
                    100,
                    buy
                )
            )
        )

        sell = int(
            max(
                0,
                min(
                    100,
                    sell
                )
            )
        )

        # ====================================================
        # FINAL SCORE
        # ====================================================

        score = int(
            max(
                0,
                min(
                    100,
                    50
                    + (buy - sell) * 0.5
                )
            )
        )

        # ====================================================
        # DIRECTION
        # ====================================================

        if (
            buy > sell
            and buy >= HFT_MIN_SCORE
        ):

            direction = "BUY"

        elif (
            sell > buy
            and sell >= HFT_MIN_SCORE
        ):

            direction = "SELL"

        else:

            direction = "NEUTRAL"

        strong_buy = (
            direction == "BUY"
            and buy >= HFT_STRONG_SCORE
        )

        strong_sell = (
            direction == "SELL"
            and sell >= HFT_STRONG_SCORE
        )

        return {

            "score": score,

            "buy_score": buy,

            "sell_score": sell,

            "direction": direction,

            "impulse": impulse,

            "velocity": velocity,

            "volume_ratio": volume_ratio,

            "range_ratio": range_ratio,

            "buy_pressure": buy_pressure,

            "sell_pressure": sell_pressure,

            "breakout_buy": breakout_buy,

            "breakout_sell": breakout_sell,

            "fake_breakout_buy":
                fake_breakout_buy,

            "fake_breakout_sell":
                fake_breakout_sell,

            "rejection_buy":
                rejection_buy,

            "rejection_sell":
                rejection_sell,

            "pullback_buy":
                pullback_buy,

            "pullback_sell":
                pullback_sell,

            "exhaustion_buy":
                exhaustion_buy,

            "exhaustion_sell":
                exhaustion_sell,

            "strong_buy":
                strong_buy,

            "strong_sell":
                strong_sell,

            "reason":
                ", ".join(reasons)
                if reasons
                else "No strong microstructure event"
        }

    except Exception as e:

        print(
            f"HFT engine error: {e}"
        )

        return neutral


# ============================================================
# SIGNAL CONFIRMATION
# ============================================================

def hft_confirms(signal, hft):

    if not HFT_ENABLED:

        return False

    direction = hft.get(
        "direction",
        "NEUTRAL"
    )

    buy_score = hft.get(
        "buy_score",
        0
    )

    sell_score = hft.get(
        "sell_score",
        0
    )

    if signal == "🟢 BUY":

        return (
            direction == "BUY"
            and buy_score >= HFT_MIN_SCORE
        )

    if signal == "🔴 SELL":

        return (
            direction == "SELL"
            and sell_score >= HFT_MIN_SCORE
        )

    return False


def hft_conflicts(signal, hft):

    direction = hft.get(
        "direction",
        "NEUTRAL"
    )

    if signal == "🟢 BUY":

        return direction == "SELL"

    if signal == "🔴 SELL":

        return direction == "BUY"

    return False
