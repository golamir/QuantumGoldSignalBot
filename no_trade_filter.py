def apply_no_trade_filter(
    signal,
    ai_score,
    news_risk,
    entry_quality
):

    if signal == "🟢 BUY" or signal == "🔴 SELL":

        if ai_score < 60:
            return {
                "signal": "⚪ WAIT",
                "reason": "AI Score too low"
            }


        if news_risk == "HIGH" and ai_score < 75:
            return {
                "signal": "⚪ WAIT",
                "reason": "High news risk"
            }


        if entry_quality == "C":
            return {
                "signal": "⚪ WAIT",
                "reason": "Entry quality weak"
            }


    return {
        "signal": signal,
        "reason": "Conditions acceptable"
    }
