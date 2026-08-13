MIN_AI_SCORE = 80
MIN_QUALITY_SCORE = 80
MIN_ADX = 25


def apply_no_trade_filter(
    signal,
    ai_score,
    news_risk,
    entry_quality,
    quality_score=0,
    adx_value=0,
    volume_confirmed=True,
    trend_aligned=True,
    rsi_valid=True,
    tp_sl_valid=True
):

    # =====================================================
    # SIGNAL
    # =====================================================

    if signal not in [
        "🟢 BUY",
        "🔴 SELL"
    ]:

        return {
            "signal": "⚪ WAIT",
            "reason": "No clear BUY/SELL signal"
        }

    # =====================================================
    # AI SCORE
    # =====================================================

    if ai_score < MIN_AI_SCORE:

        return {
            "signal": "⚪ WAIT",
            "reason": (
                f"AI Score below {MIN_AI_SCORE}"
            )
        }

    # =====================================================
    # QUALITY SCORE
    # =====================================================

    if quality_score < MIN_QUALITY_SCORE:

        return {
            "signal": "⚪ WAIT",
            "reason": (
                f"Quality Score below "
                f"{MIN_QUALITY_SCORE}"
            )
        }

    # =====================================================
    # ENTRY QUALITY
    # =====================================================

    if entry_quality != "A":

        return {
            "signal": "⚪ WAIT",
            "reason": (
                f"Entry Quality {entry_quality}, "
                f"required A"
            )
        }

    # =====================================================
    # NEWS
    # =====================================================

    if news_risk == "HIGH":

        return {
            "signal": "⚪ WAIT",
            "reason": "HIGH news risk"
        }

    # =====================================================
    # ADX
    # =====================================================

    try:

        adx_value = float(adx_value)

    except Exception:

        adx_value = 0

    if adx_value < MIN_ADX:

        return {
            "signal": "⚪ WAIT",
            "reason": (
                f"ADX below {MIN_ADX}"
            )
        }

    # =====================================================
    # VOLUME
    # =====================================================

    if not volume_confirmed:

        return {
            "signal": "⚪ WAIT",
            "reason": "Volume confirmation missing"
        }

    # =====================================================
    # M5 / M15 / H1 TREND
    # =====================================================

    if not trend_aligned:

        return {
            "signal": "⚪ WAIT",
            "reason": (
                "M5/M15/H1 trend conflict"
            )
        }

    # =====================================================
    # RSI
    # =====================================================

    if not rsi_valid:

        return {
            "signal": "⚪ WAIT",
            "reason": "RSI not in valid entry zone"
        }

    # =====================================================
    # TP / SL
    # =====================================================

    if not tp_sl_valid:

        return {
            "signal": "⚪ WAIT",
            "reason": "Invalid TP/SL"
        }

    # =====================================================
    # FINAL APPROVAL
    # =====================================================

    return {
        "signal": signal,
        "reason": (
            "✅ MASTER FILTER PASSED - "
            "80+ QUALITY SETUP"
        )
    }
