# ============================================================
# QuantumGold - NO TRADE FILTER
# MASTER FILTER V3 COMPATIBLE
# ============================================================

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

    # ========================================================
    # IMPORTANT V3 DESIGN
    # ========================================================
    #
    # AI Score
    # Quality Score
    # ADX
    # Volume
    # M5/M15/H1 Trend
    # RSI
    # TP/SL
    #
    # are NOT rejected here.
    #
    # These are handled by:
    #
    # master_quality_filter()
    #
    # in main_master_v3.py
    #
    # This prevents the No-Trade Filter from rejecting a
    # candidate before MASTER FILTER V3 gets the final decision.
    #
    # GainzAlgo V2 / Pro are also handled by MASTER V3
    # scoring as BONUS confirmations.
    #
    # ========================================================


    # ========================================================
    # SIGNAL VALIDATION
    # ========================================================

    if signal not in [
        "🟢 BUY",
        "🔴 SELL"
    ]:

        return {
            "signal": "⚪ WAIT",
            "reason": "No clear BUY/SELL signal"
        }


    # ========================================================
    # NEWS RISK
    # ========================================================

    try:

        normalized_news = str(
            news_risk
        ).upper().strip()

    except Exception:

        normalized_news = "HIGH"


    # HIGH NEWS RISK = NO TRADE
    #
    # Master V3 also checks this later.
    # Keeping it here provides an early safety stop.

    if normalized_news == "HIGH":

        return {
            "signal": "⚪ WAIT",
            "reason": "HIGH news risk"
        }


    # ========================================================
    # FINAL CANDIDATE APPROVAL
    # ========================================================
    #
    # IMPORTANT:
    #
    # We intentionally DO NOT check:
    #
    # ai_score
    # quality_score
    # entry_quality
    # adx_value
    # volume_confirmed
    # trend_aligned
    # rsi_valid
    # tp_sl_valid
    #
    # here.
    #
    # Those checks belong to MASTER FILTER V3.
    #
    # This allows the candidate to reach:
    #
    # master_quality_filter()
    #
    # where all V3 hard filters are evaluated together.
    #
    # ========================================================

    return {
        "signal": signal,
        "reason": (
            "No-Trade basic filter passed; "
            "MASTER V3 hard filters pending"
        )
    }
