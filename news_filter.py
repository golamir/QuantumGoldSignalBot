from datetime import datetime


def check_news():
    """
    Economic news filter
    Later connected to real economic calendar API
    """

    hour = datetime.utcnow().hour

    # ساعات پرریسک تقریبی بازار آمریکا
    high_risk_hours = [12, 13, 14, 15]

    if hour in high_risk_hours:
        return {
            "risk": "HIGH",
            "message": "⚠️ Possible US news volatility"
        }

    return {
        "risk": "LOW",
        "message": "✅ No high risk period"
    }
