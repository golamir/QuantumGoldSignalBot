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

    quality = "C"
    reasons = []

    # =========================================================
    # BUY
    # =========================================================

    if signal == "🟢 BUY":

        # Support
        if price > support:
            reasons.append("✅ Price above support")
        else:
            reasons.append("⚠️ Price below support")

        # Resistance
        if price < resistance:
            reasons.append("✅ Room to resistance")
        else:
            reasons.append("⚠️ Resistance nearby")

        # RSI
        if 50 < rsi < 70:
            reasons.append("✅ RSI bullish")
        elif rsi >= 70:
            reasons.append("⚠️ RSI overbought")
        else:
            reasons.append("⚠️ RSI weak")

        # Confidence
        if confidence >= 60:
            quality = "B"

        if confidence >= 75 and price > support:
            quality = "A"

        # =====================================================
        # CRYPTO TRIANGLE BREAKOUT
        # =====================================================

        if triangle_breakout:
            reasons.append("🚀 Bullish triangle breakout")

            # Soft confirmation
            if quality == "B" and confidence >= 70:
                quality = "A"

        if breakout_volume:
            reasons.append("📊 Breakout volume confirmed")

        if successful_retest:
            reasons.append("🔄 Successful breakout retest")

        if m15_confirmation:
            reasons.append("✅ M15 breakout confirmation")

        if h1_trend_alignment:
            reasons.append("✅ H1 bullish trend aligned")

    # =========================================================
    # SELL
    # =========================================================

    elif signal == "🔴 SELL":

        # Resistance
        if price < resistance:
            reasons.append("✅ Price below resistance")
        else:
            reasons.append("⚠️ Price above resistance")

        # Support
        if price > support:
            reasons.append("✅ Room to support")
        else:
            reasons.append("⚠️ Support nearby")

        # RSI
        if 30 < rsi < 50:
            reasons.append("✅ RSI bearish")
        elif rsi <= 30:
            reasons.append("⚠️ RSI oversold")
        else:
            reasons.append("⚠️ RSI weak")

        # Confidence
        if confidence >= 60:
            quality = "B"

        if confidence >= 75 and price < resistance:
            quality = "A"

        # =====================================================
        # CRYPTO TRIANGLE BREAKDOWN
        # =====================================================

        if triangle_breakout:
            reasons.append("🔻 Bearish triangle breakdown")

            # Soft confirmation
            if quality == "B" and confidence >= 70:
                quality = "A"

        if breakout_volume:
            reasons.append("📊 Breakdown volume confirmed")

        if successful_retest:
            reasons.append("🔄 Successful breakdown retest")

        if m15_confirmation:
            reasons.append("✅ M15 breakdown confirmation")

        if h1_trend_alignment:
            reasons.append("✅ H1 bearish trend aligned")

    # =========================================================
    # NO SIGNAL
    # =========================================================

    else:

        quality = "WAIT"
        reasons.append("No clear signal")

    # =========================================================
    # RETURN
    # =========================================================

    return {
        "quality": quality,
        "reasons": reasons,

        # Triangle information
        "triangle_breakout": triangle_breakout,
        "breakout_volume": breakout_volume,
        "successful_retest": successful_retest,
        "m15_confirmation": m15_confirmation,
        "h1_trend_alignment": h1_trend_alignment
    }
