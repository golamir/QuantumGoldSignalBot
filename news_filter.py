from datetime import datetime


def check_news():
    """
    Economic news filter
    Later connected to real economic calendar API
    """

    hour = datetime.utcnow().hour

    # ساعات پرریسک تقریبی بازار آمریکا
    high_risk_hours = [12, 13, 14, 15, 16]

    if hour in high_risk_hours:
        return {
    "risk": "HIGH",
    "message": "⚠️ High volatility risk - avoid aggressive entries"
}

    return {
        return {
    "risk": "LOW",
    "message": "✅ Safe trading period"
}
