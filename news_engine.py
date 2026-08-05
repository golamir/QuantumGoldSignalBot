import requests


def get_news_score():

    score = 0
    reasons = []


    try:

        # فعلاً ساختار آماده است.
        # در مرحله بعد API خبر اقتصادی را وصل می‌کنیم.

        news_status = "NORMAL"


        if news_status == "HIGH":

            score -= 15

            reasons.append(
                "⚠️ High impact news"
            )


        else:

            score += 5

            reasons.append(
                "✅ No major news risk"
            )


    except Exception:

        reasons.append(
            "⚠️ News unavailable"
        )


    return {
        "score": score,
        "reasons": reasons
    }
