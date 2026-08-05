def apply_no_trade_filter(
    signal,
    ai_score,
    news_risk,
    entry_quality
):

    if signal not in ["🟢 BUY", "🔴 SELL"]:

        return {
            "signal": "⚪ WAIT",
            "reason": "No clear signal"
        }


    if ai_score < 70:

        return {
            "signal": "⚪ WAIT",
            "reason": "AI Score too low"
        }


    if news_risk == "HIGH" and ai_score < 80:

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
        "reason": "High quality setup"
    }
