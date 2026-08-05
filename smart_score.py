from market_fusion import get_market_fusion_score
def calculate_score(
    signal,
    confidence,
    price,
    support,
    resistance,
    news_risk
):

    score = confidence

    reasons = []


    if signal == "🟢 BUY":

        if price > support:
            score += 10
            reasons.append("✅ Above support")
        else:
            score -= 10
            reasons.append("⚠️ Below support")


        if price < resistance:
            score += 5
            reasons.append("✅ Room to resistance")
        else:
            score -= 5
            reasons.append("⚠️ Resistance nearby")


    elif signal == "🔴 SELL":

        if price < resistance:
            score += 10
            reasons.append("✅ Below resistance")
        else:
            score -= 10
            reasons.append("⚠️ Above resistance")


        if price > support:
            score += 5
            reasons.append("✅ Room to support")
        else:
            score -= 5
            reasons.append("⚠️ Support nearby")


    if news_risk == "HIGH":
        score -= 15
        reasons.append("⚠️ News risk")


    fusion = get_market_fusion_score(score)

score = fusion["score"]

reasons.extend(fusion["reasons"])

    if score >= 80:

        decision = "✅ Strong setup"


    elif score >= 70:

        decision = "⚠️ Medium setup"


    else:

        decision = "❌ Weak setup"


    return {
        "score": score,
        "decision": decision,
        "reasons": reasons
    }
