import requests


def get_live_gold_price():

    url = "https://api.gold-api.com/price/XAU"

    try:
        response = requests.get(
            url,
            timeout=10
        )

        data = response.json()

        return float(data["price"])

    except Exception:
        return None
