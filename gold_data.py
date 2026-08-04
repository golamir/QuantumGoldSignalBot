import requests
import pandas as pd


def get_gold_candles():

    url = "https://api.twelvedata.com/time_series"

    params = {
        "symbol": "XAU/USD",
        "interval": "15min",
        "outputsize": 100,
        "apikey": "YOUR_API_KEY"
    }

    try:
        response = requests.get(
            url,
            params=params,
            timeout=10
        )

        data = response.json()

        if "values" not in data:
            return None

        df = pd.DataFrame(data["values"])

        df = df.rename(columns={
            "datetime": "time",
            "open": "Open",
            "high": "High",
            "low": "Low",
            "close": "Close"
        })

        df["Open"] = df["Open"].astype(float)
        df["High"] = df["High"].astype(float)
        df["Low"] = df["Low"].astype(float)
        df["Close"] = df["Close"].astype(float)

        df = df.sort_values("time")

        return df


    except Exception as e:
        print("Gold data error:", e)
        return None
