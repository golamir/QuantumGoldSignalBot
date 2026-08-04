import requests


def get_gold_price():

    url = "https://api.metals.live/v1/spot/gold"

    try:
        response = requests.get(url, timeout=10)

        data = response.json()

        price = data[0]["price"]

        return price

    except Exception as e:
        return f"Error: {e}"


print("Gold price:")
print(get_gold_price())
