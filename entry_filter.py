# ============================================================
# QuantumGold AI
# ENTRY FILTER V3.2
# M5 Entry + M15 Confirmation + H1 Trend
# Microstructure / Triangle / Breakout
# ============================================================

# ------------------------------------------------------------
# Minimum Quality
# ------------------------------------------------------------

MIN_QUALITY_SCORE = 80


# ============================================================
# CHECK ENTRY
# ============================================================

def check_entry(
    signal,
    price,
    support,
    resistance,
    rsi,
    confidence,
    triangle_breakout=False,
    breakout_volume=False,
    successful_retest=False,
    m15_confirmation=False,
    h1_trend_alignment=False
):

    # ========================================================
    # INITIALIZATION
    # ========================================================

    quality = "C"

    reasons = []

    quality_score = 0

    # ========================================================
    # SAFE NUMERIC CONVERSION
    # ========================================================

    try:
        price = float(price)
    except Exception:
        price = 0.0

    try:
        support = float(support)
    except Exception:
        support = 0.0

    try:
        resistance = float(resistance)
    except Exception:
        resistance = 0.0

    try:
        rsi = float(rsi)
    except Exception:
        rsi = 50.0

    try:
        confidence = float(confidence)
    except Exception:
        confidence = 0.0

    # ========================================================
    # SIGNAL NORMALIZATION
    # ========================================================

    signal = str(signal).strip().upper()

    if "BUY" in signal:

        signal = "BUY"

    elif "SELL" in signal:

        signal = "SELL"

    else:

        signal = "NONE"

    # ========================================================
    # BOOLEAN NORMALIZATION
    # ========================================================

    triangle_breakout = bool(
        triangle_breakout
    )

    breakout_volume = bool(
        breakout_volume
    )

    successful_retest = bool(
        successful_retest
    )

    m15_confirmation = bool(
        m15_confirmation
    )

    h1_trend_alignment = bool(
        h1_trend_alignment
    )

    # ========================================================
    # BUY
    # ========================================================

    if signal == "BUY":

        # ----------------------------------------------------
        # SUPPORT
        # ----------------------------------------------------

        if (
            support > 0
            and price > support
        ):

            quality_score += 20

            reasons.append(
                "✅ BUY: Price above support"
            )

        else:

            reasons.append(
                "⚠️ BUY: Price below/near support"
            )

        # ----------------------------------------------------
        # RESISTANCE
        # ----------------------------------------------------

        if (
            resistance > 0
            and price < resistance
        ):

            quality_score += 15

            reasons.append(
                "✅ BUY: Room to resistance"
            )

        else:

            reasons.append(
                "⚠️ BUY: Resistance nearby"
            )

        # ----------------------------------------------------
        # RSI
        # ----------------------------------------------------

        if 50 < rsi < 70:

            quality_score += 15

            reasons.append(
                "✅ RSI bullish"
            )

        elif rsi >= 70:

            quality_score -= 5

            reasons.append(
                "⚠️ RSI overbought"
            )

        else:

            reasons.append(
                "⚠️ RSI weak for BUY"
            )

        # ----------------------------------------------------
        # AI CONFIDENCE
        # ----------------------------------------------------

        if confidence >= 75:

            quality_score += 25

            reasons.append(
                "🔥 High AI confidence"
            )

        elif confidence >= 60:

            quality_score += 15

            reasons.append(
                "✅ Acceptable AI confidence"
            )

        else:

            reasons.append(
                "⚠️ Low AI confidence"
            )

        # ====================================================
        # TRIANGLE BREAKOUT
        # ====================================================

        if triangle_breakout:

            quality_score += 5

            reasons.append(
                "🚀 Bullish triangle breakout"
            )

        # ====================================================
        # BREAKOUT VOLUME
        # ====================================================

        if breakout_volume:

            quality_score += 5

            reasons.append(
                "📊 Breakout volume confirmed"
            )

        # ====================================================
        # SUCCESSFUL RETEST
        # ====================================================

        if successful_retest:

            quality_score += 5

            reasons.append(
                "🔄 Successful breakout retest"
            )

        # ====================================================
        # M15 CONFIRMATION
        # ====================================================

        if m15_confirmation:

            quality_score += 5

            reasons.append(
                "✅ M15 bullish confirmation"
            )

        # ====================================================
        # H1 TREND ALIGNMENT
        # ====================================================

        if h1_trend_alignment:

            quality_score += 5

            reasons.append(
                "✅ H1 bullish trend aligned"
            )

    # ========================================================
    # SELL
    # ========================================================

    elif signal == "SELL":

        # ----------------------------------------------------
        # RESISTANCE
        # ----------------------------------------------------

        if (
            resistance > 0
            and price < resistance
        ):

            quality_score += 20

            reasons.append(
                "✅ SELL: Price below resistance"
            )

        else:

            reasons.append(
                "⚠️ SELL: Price above/near resistance"
            )

        # ----------------------------------------------------
        # SUPPORT
        # ----------------------------------------------------

        if (
            support > 0
            and price > support
        ):

            quality_score += 15

            reasons.append(
                "✅ SELL: Room to support"
            )

        else:

            reasons.append(
                "⚠️ SELL: Support nearby"
            )

        # ----------------------------------------------------
        # RSI
        # ----------------------------------------------------

        if 30 < rsi < 50:

            quality_score += 15

            reasons.append(
                "✅ RSI bearish"
            )

        elif rsi <= 30:

            quality_score -= 5

            reasons.append(
                "⚠️ RSI oversold"
            )

        else:

            reasons.append(
                "⚠️ RSI weak for SELL"
            )

        # ----------------------------------------------------
        # AI CONFIDENCE
        # ----------------------------------------------------

        if confidence >= 75:

            quality_score += 25

            reasons.append(
                "🔥 High AI confidence"
            )

        elif confidence >= 60:

            quality_score += 15

            reasons.append(
                "✅ Acceptable AI confidence"
            )

        else:

            reasons.append(
                "⚠️ Low AI confidence"
            )

        # ====================================================
        # TRIANGLE BREAKDOWN
        # ====================================================

        if triangle_breakout:

            quality_score += 5

            reasons.append(
                "🔻 Bearish triangle breakdown"
            )

        # ====================================================
        # BREAKDOWN VOLUME
        # ====================================================

        if breakout_volume:

            quality_score += 5

            reasons.append(
                "📊 Breakdown volume confirmed"
            )

        # ====================================================
        # SUCCESSFUL RETEST
        # ====================================================

        if successful_retest:

            quality_score += 5

            reasons.append(
                "🔄 Successful breakdown retest"
            )

        # ====================================================
        # M15 CONFIRMATION
        # ====================================================

        if m15_confirmation:

            quality_score += 5

            reasons.append(
                "✅ M15 bearish confirmation"
            )

        # ====================================================
        # H1 TREND ALIGNMENT
        # ====================================================

        if h1_trend_alignment:

            quality_score += 5

            reasons.append(
                "✅ H1 bearish trend aligned"
            )

    # ========================================================
    # NO VALID SIGNAL
    # ========================================================

    else:

        return {

            "quality": "WAIT",

            "quality_score": 0,

            "reasons": [
                "❌ No valid BUY/SELL signal"
            ],

            "triangle_breakout": False,

            "breakout_volume": False,

            "successful_retest": False,

            "m15_confirmation": False,

            "h1_trend_alignment": False
        }

    # ========================================================
    # CLAMP QUALITY SCORE
    # ========================================================

    quality_score = max(
        0,
        min(
            100,
            int(round(quality_score))
        )
    )

    # ========================================================
    # QUALITY CLASSIFICATION
    # ========================================================

    if quality_score >= 85:

        quality = "A+"

    elif quality_score >= 75:

        quality = "A"

    elif quality_score >= 60:

        quality = "B"

    else:

        quality = "C"

    # ========================================================
    # FINAL ENTRY RESULT
    # ========================================================

    return {

        "quality": quality,

        "quality_score": quality_score,

        "reasons": reasons,

        # ----------------------------------------------------
        # MICROSTRUCTURE
        # ----------------------------------------------------

        "triangle_breakout": triangle_breakout,

        "breakout_volume": breakout_volume,

        "successful_retest": successful_retest,

        # ----------------------------------------------------
        # MULTI TIMEFRAME
        # ----------------------------------------------------

        "m15_confirmation": m15_confirmation,

        "h1_trend_alignment": h1_trend_alignment
    }


# ============================================================
# OPTIONAL HELPER
# ============================================================

def is_quality_passed(entry_result):

    """
    Check whether Entry Quality passes
    the MASTER FILTER minimum.
    """

    if not isinstance(
        entry_result,
        dict
    ):

        return False

    quality_score = entry_result.get(
        "quality_score",
        0
    )

    try:

        quality_score = float(
            quality_score
        )

    except Exception:

        return False

    return (
        quality_score >= MIN_QUALITY_SCORE
    )
