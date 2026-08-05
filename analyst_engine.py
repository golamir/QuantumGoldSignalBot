def get_analyst_score():

    score = 0
    reasons = []


    try:

        # فعلاً ساختار آماده است.
        # در مرحله بعد می‌توانیم منابع واقعی
        # تحلیلگران و API ها را اضافه کنیم.


        analyst_view = "BULLISH"


        if analyst_view == "BULLISH":

            score += 5

            reasons.append(
                "✅ Analysts bullish"
            )


        elif analyst_view == "BEARISH":

            score -= 5

            reasons.append(
                "❌ Analysts bearish"
            )


        else:

            reasons.append(
                "⚪ Analysts neutral"
            )


    except Exception:

        reasons.append(
            "⚠️ Analyst data unavailable"
        )


    return {
        "score": score,
        "reasons": reasons
    }
