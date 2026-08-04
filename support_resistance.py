def find_support_resistance(close):

    recent = close.tail(50)

    support = float(recent.min())
    resistance = float(recent.max())

    price = float(close.iloc[-1])

    distance_support = abs(price - support)
    distance_resistance = abs(resistance - price)

    return {
        "support": support,
        "resistance": resistance,
        "near_support": distance_support < (price * 0.002),
        "near_resistance": distance_resistance < (price * 0.002)
    }
