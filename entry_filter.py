def check_entry(
    signal,
    price,
    support,
    resistance,
    rsi,
    confidence
):

    quality = "C"
    reasons = []


    if signal == "🟢 BUY":

        if price > support:
            reasons.append("✅ Price above support")
        else:
            reasons.append("⚠️ Price below support")


        if price < resistance:
            reasons.append("✅ Room to resistance")
        else:
            reasons.append("⚠️ Resistance nearby")


        if rsi > 50:
            reasons.append("✅ Momentum positive")


        if confidence >= 60:
            quality = "B"


        if confidence >= 75 and price > support:
            quality = "A"



    elif signal == "🔴 SELL":

        if price < resistance:
            reasons.append("✅ Price below resistance")
        else:
            reasons.append("⚠️ Price above resistance")


        if price > support:
            reasons.append("✅ Room to support")
        else:
            reasons.append("⚠️ Support nearby")


        if rsi < 50:
            reasons.append("✅ Momentum negative")


        if confidence >= 60:
            quality = "B"


        if confidence >= 75 and price < resistance:
            quality = "A"



    else:

        quality = "WAIT"
        reasons.append("No clear signal")


    return {
        "quality": quality,
        "reasons": reasons
    }
