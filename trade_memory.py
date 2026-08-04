import os
import csv
from datetime import datetime


FILE = "trade_history.csv"


def save_trade(signal, price, confidence, sl, tp):

    file_exists = os.path.isfile(FILE)

    with open(FILE, "a", newline="", encoding="utf-8") as f:

        writer = csv.writer(f)

        if not file_exists:
            writer.writerow([
                "time",
                "signal",
                "price",
                "confidence",
                "stop_loss",
                "take_profit"
            ])

        writer.writerow([
            datetime.now(),
            signal,
            price,
            confidence,
            sl,
            tp
        ])


def get_trade_count():

    if not os.path.isfile(FILE):
        return 0

    with open(FILE, "r", encoding="utf-8") as f:
        return sum(1 for row in f) - 1
