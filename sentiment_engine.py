def get_sentiment_score():

    score = 0
    reasons = []


    try:

        # فعلاً ساختار آماده است.
        # در مرحله بعد می‌توانیم API های واقعی
        # احساسات بازار را وصل کنیم.


        market_sentiment = "POSITIVE"


        if market_sentiment == "POSITIVE":

            score += 10

            reasons.append(
                "✅ Market sentiment positive"
            )


        elif market_sentiment == "NEGATIVE":

            score -= 10

            reasons.append(
                "❌ Market sentiment negative"
            )


        else:

            reasons.append(
                "⚪ Neutral sentiment"
            )


    except Exception:

        reasons.append(
            "⚠️ Sentiment unavailable"
        )


    return {
        "score": score,
        "reasons": reasons
    }
