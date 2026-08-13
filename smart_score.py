from market_fusion import get_market_fusion_score


MIN_AI_SCORE = 80


def calculate_score(
    symbol,
    signal,
    confidence,
    price,
    support,
    resistance,
    news_risk
):

    score = float(confidence)
    reasons = []

    # =====================================================
    # DIRECTION
    # =====================================================

    if signal == "🟢 BUY":

        if price > support:
            score += 10
            reasons.append("✅ Price above support")
        else:
            score -= 10
            reasons.append("⚠️ Price below support")

        if price < resistance:
            score += 5
            reasons.append("✅ Room to resistance")
        else:
            score -= 5
            reasons.append("⚠️ Resistance nearby")

    elif signal == "🔴 SELL":

        if price < resistance:
            score += 10
            reasons.append("✅ Price below resistance")
        else:
            score -= 10
            reasons.append("⚠️ Price above resistance")

        if price > support:
            score += 5
            reasons.append("✅ Room to support")
        else:
            score -= 5
            reasons.append("⚠️ Support nearby")

    else:

        return {
            "score": 0,
            "decision": "❌ Weak setup",
            "reasons": ["No valid BUY/SELL"],
            "details": {}
        }

    # =====================================================
    # NEWS RISK
    # =====================================================

    if news_risk == "HIGH":

        score -= 15
        reasons.append("❌ HIGH news risk")

    elif news_risk == "MEDIUM":

        score -= 5
        reasons.append("⚠️ Medium news risk")

    else:

        score += 5
        reasons.append("✅ Low news risk")

    # =====================================================
    # CLAMP BEFORE FUSION
    # =====================================================

    score = max(0, min(100, score))

    # =====================================================
    # MARKET FUSION
    # =====================================================

    try:

        fusion = get_market_fusion_score(
            symbol,
            score
        )

    except Exception as e:

        print(
            f"{symbol}: Market fusion error: {e}"
        )

        fusion = {
            "score": score,
            "reasons": [],
            "details": {}
        }

    # =====================================================
    # FUSION SCORE
    # =====================================================

    fusion_score = fusion.get(
        "score",
        score
    )

    try:

        fusion_score = float(fusion_score)

    except Exception:

        fusion_score = score

    # =====================================================
    # FINAL SCORE
    # =====================================================

    score = max(
        0,
        min(
            100,
            int(round(fusion_score))
        )
    )

    fusion_reasons = fusion.get(
        "reasons",
        []
    )

    if isinstance(fusion_reasons, list):

        reasons.extend(
            fusion_reasons
        )

    # =====================================================
    # DECISION
    # =====================================================

    if score >= 90:

        decision = "🔥 Very strong setup"

    elif score >= 80:

        decision = "✅ Strong setup"

    elif score >= 70:

        decision = "⚠️ Medium setup"

    else:

        decision = "❌ Weak setup"

    # =====================================================
    # RESULT
    # =====================================================

    return {

        "score": score,

        "decision": decision,

        "reasons": reasons,

        "details": fusion.get(
            "details",
            {}
        )
    }
