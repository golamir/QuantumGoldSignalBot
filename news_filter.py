from datetime import datetime


def check_news():
    """
    Economic news filter
    """

    hour = datetime.utcnow().hour

    high_risk_hours = [12, 13, 14, 15, 16]

    if hour in high_risk_hours:

        return {
            "risk": "HIGH",
            "message": "⚠️ High volatility risk - avoid aggressive entries"
        }

    return {
        "risk": "LOW",
        "message": "✅ Safe trading period"
    }
