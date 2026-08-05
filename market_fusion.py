from news_engine import get_news_score
from sentiment_engine import get_sentiment_score
from analyst_engine import get_analyst_score


def get_market_fusion_score(technical_score):

    news = get_news_score()

    sentiment = get_sentiment_score()

    analyst = get_analyst_score()


    total_score = technical_score

    total_score += news["score"]
    total_score += sentiment["score"]
    total_score += analyst["score"]


    reasons = []

    reasons.extend(news["reasons"])
    reasons.extend(sentiment["reasons"])
    reasons.extend(analyst["reasons"])


    if total_score > 100:
        total_score = 100

    if total_score < 0:
        total_score = 0


    if total_score >= 85:
        decision = "✅ Very strong setup"

    elif total_score >= 70:
        decision = "⚠️ Strong setup"

    else:
        decision = "❌ Weak setup"


    return {

        "score": total_score,

        "decision": decision,

        "reasons": reasons,

        "details": {

            "technical": technical_score,

            "news": news["score"],

            "sentiment": sentiment["score"],

            "analyst": analyst["score"]

        }

    }
