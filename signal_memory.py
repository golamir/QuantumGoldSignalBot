import os
import json
import time


FILE = "last_signal.json"


def save_last_signal(signal, price):
    data = {
        "signal": signal,
        "price": price,
        "time": time.time()
    }

    with open(FILE, "w") as f:
        json.dump(data, f)


def get_last_signal():

    if not os.path.exists(FILE):
        return None

    with open(FILE, "r") as f:
        return json.load(f)


def allow_new_signal(signal, price):

    last = get_last_signal()

    if last is None:
        return True


    # اگر سیگنال قبلی مخالف باشد اجازه بده
    if last["signal"] != signal:
        return True


    old_price = float(last["price"])


    change = abs(price - old_price) / old_price * 100


    # ادامه روند فقط با حرکت حداقل 0.15 درصد
    if change >= 0.15:
        return True


    return False
