```python
import math
import yfinance as yf


# ============================================================
# QuantumGold HFT / MICROSTRUCTURE ENGINE V1
#
# Current data source:
#   Yahoo Finance 1m OHLCV
#
# Current capabilities:
#   - Short-term momentum
#   - Volume impulse
#   - Range impulse
#   - Price acceleration
#   - Directional pressure
#
# NOT available through yfinance:
#   - Real tick data
#   - Real bid/ask
#   - Real spread
#   - Real order book
#   - Level 2 liquidity
#
# Therefore this engine is:
#   HFT / MICROSTRUCTURE-STYLE
#
# HFT confirmation:
#   SOFT
#
# It does NOT independently reject a signal.
# It adds confirmation to the MASTER FILTER score.
# ============================================================


# ============================================================
# SETTINGS
# ============================================================

HFT_LOOKBACK = 20

MIN_MOMENTUM = 0.00015

VOLUME_IMPULSE_MULTIPLIER = 1.20

RANGE_IMPULSE_MULTIPLIER = 1.20

HFT_BONUS = 10


# ============================================================
# SAFE FLOAT
# ============================================================

def _safe_float(value):

    try:

        value = float(value)

        if math.isfinite(value):

            return value

    except Exception:

        pass

    return None


# ============================================================
# GET HFT 1M DATA
# ============================================================

def get_hft_data(symbol):

    try:

        print(
            f"{symbol}: "
            f"HFT downloading 1m data..."
        )

        data = yf.download(
            tickers=symbol,
            period="1d",
            interval="1m",
            progress=False,
            auto_adjust=False,
            threads=False
        )

        if data is None or data.empty:

            print(
                f"{symbol}: "
                f"HFT empty 1m data"
            )

            return None

        # ----------------------------------------------------
        # Flatten MultiIndex columns
        # ----------------------------------------------------

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
            "High",
            "Low",
            "Close",
            "Volume"
        ]

        missing = [
            column
            for column in required
            if column not in data.columns
        ]

        if missing:

            print(
                f"{symbol}: "
                f"HFT missing columns "
                f"{missing}"
            )

            return None

        data = data.dropna(
            subset=[
                "Open",
                "High",
                "Low",
                "Close"
            ]
        )

        if len(data) < HFT_LOOKBACK + 5:

            print(
                f"{symbol}: "
                f"HFT insufficient data "
                f"({len(data)} candles)"
            )

            return None

        return data

    except Exception as e:

        print(
            f"{symbol}: "
            f"HFT data error: {e}"
        )

        return None


# ============================================================
# HFT ANALYSIS
# ============================================================

def analyze_hft(
    symbol,
    expected_direction
):

    result = {

        "enabled": True,

        "confirmed": False,

        "direction": None,

        "score": 0,

        "momentum": 0.0,

        "volume_impulse": False,

        "range_impulse": False,

        "acceleration": False,

        "liquidity_pressure": False,

        "spread_available": False,

        "orderbook_available": False,

        "reason": "No HFT confirmation"
    }

    try:

        # ----------------------------------------------------
        # DOWNLOAD DATA
        # ----------------------------------------------------

        data = get_hft_data(
            symbol
        )

        if data is None:

            result["reason"] = (
                "HFT 1m data unavailable"
            )

            return result

        close = data["Close"]
        high = data["High"]
        low = data["Low"]
        volume = data["Volume"].fillna(0)

        # ----------------------------------------------------
        # CLOSED 1M CANDLE
        #
        # Never use the currently forming candle.
        # ----------------------------------------------------

        i = len(data) - 2

        if i < HFT_LOOKBACK + 3:

            result["reason"] = (
                "Insufficient HFT candles"
            )

            return result

        current_close = _safe_float(
            close.iloc[i]
        )

        previous_close = _safe_float(
            close.iloc[i - 1]
        )

        old_close = _safe_float(
            close.iloc[
                i - HFT_LOOKBACK
            ]
        )

        if any(
            value is None
            for value in [
                current_close,
                previous_close,
                old_close
            ]
        ):

            result["reason"] = (
                "Invalid HFT prices"
            )

            return result

        # ----------------------------------------------------
        # MOMENTUM
        # ----------------------------------------------------

        momentum = (
            current_close
            - old_close
        ) / old_close

        result["momentum"] = momentum

        # ----------------------------------------------------
        # CURRENT RANGE
        # ----------------------------------------------------

        current_high = _safe_float(
            high.iloc[i]
        )

        current_low = _safe_float(
            low.iloc[i]
        )

        if (
            current_high is None
            or current_low is None
        ):

            result["reason"] = (
                "Invalid HFT range"
            )

            return result

        current_range = (
            current_high
            - current_low
        )

        # ----------------------------------------------------
        # HISTORICAL RANGE
        # ----------------------------------------------------

        historical_ranges = []

        range_start = max(
            0,
            i - HFT_LOOKBACK
        )

        for j in range(
            range_start,
            i
        ):

            h = _safe_float(
                high.iloc[j]
            )

            l = _safe_float(
                low.iloc[j]
            )

            if (
                h is not None
                and l is not None
                and h > l
            ):

                historical_ranges.append(
                    h - l
                )

        if historical_ranges:

            avg_range = (
                sum(historical_ranges)
                / len(historical_ranges)
            )

        else:

            avg_range = 0.0

        range_impulse = (
            avg_range > 0
            and current_range
            >= (
                avg_range
                * RANGE_IMPULSE_MULTIPLIER
            )
        )

        result["range_impulse"] = (
            range_impulse
        )

        # ----------------------------------------------------
        # VOLUME IMPULSE
        # ----------------------------------------------------

        current_volume = (
            _safe_float(
                volume.iloc[i]
            )
            or 0.0
        )

        historical_volume = volume.iloc[
            max(
                0,
                i - HFT_LOOKBACK
            ):i
        ]

        if len(historical_volume):

            avg_volume = float(
                historical_volume.mean()
            )

        else:

            avg_volume = 0.0

        volume_impulse = (
            avg_volume > 0
            and current_volume
            >= (
                avg_volume
                * VOLUME_IMPULSE_MULTIPLIER
            )
        )

        result["volume_impulse"] = (
            volume_impulse
        )

        # ----------------------------------------------------
        # PREVIOUS MOMENTUM
        # ----------------------------------------------------

        momentum_previous = (
            previous_close
            - old_close
        ) / old_close

        # ----------------------------------------------------
        # ACCELERATION
        # ----------------------------------------------------

        acceleration = (
            abs(momentum)
            > abs(momentum_previous)
        )

        result["acceleration"] = (
            acceleration
        )

        # ----------------------------------------------------
        # DIRECTIONAL PRESSURE
        # ----------------------------------------------------

        bullish_pressure = (
            momentum > MIN_MOMENTUM
            and current_close
            > previous_close
        )

        bearish_pressure = (
            momentum < -MIN_MOMENTUM
            and current_close
            < previous_close
        )

        # ----------------------------------------------------
        # DIRECTION
        # ----------------------------------------------------

        if expected_direction == "BUY":

            result["direction"] = "BUY"

        elif expected_direction == "SELL":

            result["direction"] = "SELL"

        else:

            result["direction"] = None

            result["reason"] = (
                "Invalid HFT direction"
            )

            return result

        # ----------------------------------------------------
        # HFT SCORE
        #
        # Maximum = 10
        # ----------------------------------------------------

        score = 0

        if expected_direction == "BUY":

            if bullish_pressure:

                score += 4

            if volume_impulse:

                score += 2

            if range_impulse:

                score += 1

            if acceleration:

                score += 2

            if current_close > previous_close:

                score += 1

        elif expected_direction == "SELL":

            if bearish_pressure:

                score += 4

            if volume_impulse:

                score += 2

            if range_impulse:

                score += 1

            if acceleration:

                score += 2

            if current_close < previous_close:

                score += 1

        # ----------------------------------------------------
        # LIQUIDITY PRESSURE
        #
        # Current approximation using price + volume.
        # Real order book will be added later.
        # ----------------------------------------------------

        liquidity_pressure = (
            volume_impulse
            and (
                bullish_pressure
                or bearish_pressure
            )
        )

        result["liquidity_pressure"] = (
            liquidity_pressure
        )

        # ----------------------------------------------------
        # SAVE SCORE
        # ----------------------------------------------------

        result["score"] = int(
            max(
                0,
                min(
                    10,
                    score
                )
            )
        )

        # ----------------------------------------------------
        # SOFT CONFIRMATION
        # ----------------------------------------------------

        if score >= 6:

            result["confirmed"] = True

            result["reason"] = (
                f"HFT confirmation "
                f"score={score}/10"
            )

        else:

            result["confirmed"] = False

            result["reason"] = (
                f"HFT weak "
                f"score={score}/10"
            )

        return result

    except Exception as e:

        print(
            f"{symbol}: "
            f"HFT analysis error: {e}"
        )

        result["reason"] = (
            f"HFT error: {e}"
        )

        return result
```
