import json
import os

FILE = "signals_report.json"


def load_report():

    if not os.path.exists(FILE):
        return {
            "total": 0,
            "buy": 0,
            "sell": 0
        }

    with open(FILE, "r") as f:
        return json.load(f)


def save_signal(signal):

    data = load_report()

    data["total"] += 1

    if "BUY" in signal:
        data["buy"] += 1

    elif "SELL" in signal:
        data["sell"] += 1

    with open(FILE, "w") as f:
        json.dump(data, f)


def get_report():

    return load_report()
