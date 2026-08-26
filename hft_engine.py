# ============================================================
# QuantumGold HFT-STYLE ENGINE
# V3.2
#
# IMPORTANT:
# This is NOT true exchange HFT.
# It is OHLCV-based short-term microstructure analysis.
# ============================================================

import math


def _safe_float(value, default=0.0):

    try:
        value = float(value)

        if math.isfinite(value):
            return value

        return default

    except Exception:
        return default


def _safe_ratio(a, b, default=0.0):

    b = _safe_float(b, 0.0)

    if abs(b) < 1e-12:
        return default

    return _safe_float(a, 0.0) / b


def _clamp(value, low=0, high=100):

    try:
        return max(
            low,
            min(
                high,
                int(round(float(value)))
            )
        )

    except Exception:
        return low


def analyze_hft_style(
    open_price,
    close,
    high,
    low,
    volume,
    atr_value
):

    neutral = {
        "buy_score": 0,
        "sell_score": 0,
        "score": 50,
        "direction": "NEUTRAL",
        "confirmed": False,
        "conflict": False,
        "velocity": 0.0,
        "acceleration": 0.0,
        "range_ratio": 1.0,
        "volume_ratio": 0.0,
        "body_ratio": 0.0,
        "pressure": 0.0,
        "breakout_buy": False,
        "breakout_sell": False,
        "volume_surge": False,
        "range_expansion": False,
        "momentum_buy": False,
        "momentum_sell": False,
        "exhaustion_buy": False,
        "exhaustion_sell": False,
        "reason": "HFT-style unavailable"
    }

    try:

        i = len(close) - 2

        atr = _safe_float(
            atr_value,
            0.0
        )

        if i < 25 or atr <= 0:
            return neutral

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

        pc = _safe_float(
            close.iloc[i - 1]
        )

        ppc = _safe_float(
            close.iloc[i - 2]
        )

        if h <= l:
            return neutral

        candle_range = h - l
        body = abs(c - o)

        body_ratio = _safe_ratio(
            body,
            candle_range
        )

        close_location = _safe_ratio(
            c - l,
            candle_range
        )

        velocity = _safe_ratio(
            c - pc,
            atr
        )

        previous_velocity = _safe_ratio(
            pc - ppc,
            atr
        )

        acceleration = (
            velocity
            - previous_velocity
        )

        start = max(
            0,
            i - 20
        )

        ranges = []

        for x in range(start, i):

            r = (
                _safe_float(high.iloc[x])
                -
                _safe_float(low.iloc[x])
            )

            if r > 0:
                ranges.append(r)

        avg_range = (
            sum(ranges) / len(ranges)
            if ranges
            else candle_range
        )

        range_ratio = _safe_ratio(
            candle_range,
            avg_range,
            1.0
        )

        volumes = []

        for x in range(start, i):

            v = _safe_float(
                volume.iloc[x]
            )

            if v > 0:
                volumes.append(v)

        avg_volume = (
            sum(volumes) / len(volumes)
            if volumes
            else 0.0
        )

        current_volume = _safe_float(
            volume.iloc[i]
        )

        volume_ratio = _safe_ratio(
            current_volume,
            avg_volume,
            0.0
        )

        prev_high = max(
            _safe_float(high.iloc[x])
            for x in range(start, i)
        )

        prev_low = min(
            _safe_float(low.iloc[x])
            for x in range(start, i)
        )

        breakout_buy = (
            c > prev_high
        )

        breakout_sell = (
            c < prev_low
        )

        upper_wick = (
            h - max(o, c)
        )

        lower_wick = (
            min(o, c) - l
        )

        pressure = (
            close_location * 2
            - 1
        )

        volume_surge = (
            volume_ratio >= 1.50
        )

        range_expansion = (
            range_ratio >= 1.35
        )

        momentum_buy = (
            velocity >= 0.25
            and acceleration >= 0
        )

        momentum_sell = (
            velocity <= -0.25
            and acceleration <= 0
        )

        # ----------------------------------------------------
        # Momentum exhaustion
        # ----------------------------------------------------

        exhaustion_buy = (
            velocity >= 0.80
            and upper_wick > body
            and close_location < 0.70
        )

        exhaustion_sell = (
            velocity <= -0.80
            and lower_wick > body
            and close_location > 0.30
        )

        buy = 0
        sell = 0

        reasons = []

        # ----------------------------------------------------
        # VELOCITY
        # ----------------------------------------------------

        if velocity >= 0.25:
            buy += 15
            reasons.append("bullish velocity")

        elif velocity <= -0.25:
            sell += 15
            reasons.append("bearish velocity")

        # ----------------------------------------------------
        # ACCELERATION
        # ----------------------------------------------------

        if acceleration >= 0.12:
            buy += 15
            reasons.append("bullish acceleration")

        elif acceleration <= -0.12:
            sell += 15
            reasons.append("bearish acceleration")

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

        if range_expansion:

            if c > o:

                buy += 10

            elif c < o:

                sell += 10

        # ----------------------------------------------------
        # VOLUME SURGE
        # ----------------------------------------------------

        if volume_surge:

            if c > o:

                buy += 15
                reasons.append("volume surge BUY")

            elif c < o:

                sell += 15
                reasons.append("volume surge SELL")

        elif volume_ratio >= 1.20:

            if c > o:
                buy += 7

            elif c < o:
                sell += 7

        # ----------------------------------------------------
        # BREAKOUT
        # ----------------------------------------------------

        if breakout_buy:

            buy += 18
            reasons.append("upside breakout")

        if breakout_sell:

            sell += 18
            reasons.append("downside breakout")

        # ----------------------------------------------------
        # EXHAUSTION
        # ----------------------------------------------------

        if exhaustion_buy:

            buy = max(
                0,
                buy - 12
            )

            sell += 8

            reasons.append(
                "bullish exhaustion risk"
            )

        if exhaustion_sell:

            sell = max(
                0,
                sell - 12
            )

            buy += 8

            reasons.append(
                "bearish exhaustion risk"
            )

        # ----------------------------------------------------
        # SCORE
        # ----------------------------------------------------

        buy = _clamp(buy)
        sell = _clamp(sell)

        score = _clamp(
            50 + (buy - sell) * 0.50
        )

        if (
            buy > sell
            and buy >= 65
        ):

            direction = "BUY"

        elif (
            sell > buy
            and sell >= 65
        ):

            direction = "SELL"

        else:

            direction = "NEUTRAL"

        return {
            "buy_score": buy,
            "sell_score": sell,
            "score": score,
            "direction": direction,
            "confirmed": direction != "NEUTRAL",
            "conflict": False,
            "velocity": velocity,
            "acceleration": acceleration,
            "range_ratio": range_ratio,
            "volume_ratio": volume_ratio,
            "body_ratio": body_ratio,
            "pressure": pressure,
            "breakout_buy": breakout_buy,
            "breakout_sell": breakout_sell,
            "volume_surge": volume_surge,
            "range_expansion": range_expansion,
            "momentum_buy": momentum_buy,
            "momentum_sell": momentum_sell,
            "exhaustion_buy": exhaustion_buy,
            "exhaustion_sell": exhaustion_sell,
            "reason": (
                ", ".join(reasons)
                if reasons
                else "No strong HFT-style event"
            )
        }

    except Exception as e:

        print(
            f"HFT-style engine error: {e}"
        )

        return neutral


def hft_confirms(
    signal,
    hft
):

    if signal == "🟢 BUY":

        return (
            hft.get("direction") == "BUY"
            and
            hft.get("buy_score", 0)
            >= 65
        )

    if signal == "🔴 SELL":

        return (
            hft.get("direction") == "SELL"
            and
            hft.get("sell_score", 0)
            >= 65
        )

    return False


def hft_conflicts(
    signal,
    hft
):

    if signal == "🟢 BUY":

        return (
            hft.get("direction") == "SELL"
            and
            hft.get("sell_score", 0)
            >= 65
        )

    if signal == "🔴 SELL":

        return (
            hft.get("direction") == "BUY"
            and
            hft.get("buy_score", 0)
            >= 65
        )

    return False
