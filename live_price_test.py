import requests


def get_gold_price():

    url = "https://api.gold-api.com/price/XAU"

    try:
        response = requests.get(
            url,
            timeout=10
        )

        data = response.json()

        return data["price"]

    except Exception as e:
        return f"Error: {e}"


print("Gold price:")
print(get_gold_price())
