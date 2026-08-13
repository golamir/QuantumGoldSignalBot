import os
import json
import datetime


FILE_NAME = "signal_history.json"


# =========================================================
# LOAD HISTORY
# =========================================================

def load_history():

    if not os.path.exists(FILE_NAME):
        return []

    try:

        with open(
            FILE_NAME,
            "r",
            encoding="utf-8"
        ) as f:

            data = json.load(f)

            if isinstance(data, list):
                return data

            return []

    except Exception as e:

        print(
            f"Signal history load error: {e}"
        )

        return []


# =========================================================
# SAVE HISTORY
# =========================================================

def save_history(history):

    try:

        with open(
            FILE_NAME,
            "w",
            encoding="utf-8"
        ) as f:

            json.dump(
                history,
                f,
                ensure_ascii=False,
                indent=2
            )

        return True

    except Exception as e:

        print(
            f"Signal history save error: {e}"
        )

        return False


# =========================================================
# RECORD SIGNAL
# =========================================================

def record_signal(
    symbol,
    name,
    signal,
    entry,
    stop_loss,
    tp1,
    tp2,
    tp3,
    ai_score,
    quality_score,
    entry_quality,
    adx,
    rsi,
    volume_confirmed
):

    history = load_history()

    trade_id = len(history) + 1

    trade = {

        "id": trade_id,

        "symbol": symbol,
        "name": name,
        "signal": signal,

        "entry": float(entry),

        "stop_loss": float(
            stop_loss
        ),

        "tp1": float(tp1),
        "tp2": float(tp2),
        "tp3": float(tp3),

        "ai_score": int(
            ai_score
        ),

        "quality_score": int(
            quality_score
        ),

        "entry_quality":
            str(entry_quality),

        "adx": float(adx),

        "rsi": float(rsi),

        "volume_confirmed":
            bool(volume_confirmed),

        "status": "OPEN",

        "tp1_hit": False,
        "tp2_hit": False,
        "tp3_hit": False,
        "sl_hit": False,

        "result": None,

        "created_at":
            datetime.datetime.utcnow().isoformat(),

        "closed_at": None
    }

    history.append(trade)

    save_history(history)

    print(
        f"Signal tracked: "
        f"{name} {signal} "
        f"ID={trade_id}"
    )

    return trade


# =========================================================
# UPDATE TRADE
# =========================================================

def update_trade(
    trade_id,
    status=None,
    tp1_hit=None,
    tp2_hit=None,
    tp3_hit=None,
    sl_hit=None,
    result=None
):

    history = load_history()

    for trade in history:

        if trade.get("id") != trade_id:
            continue

        if status is not None:
            trade["status"] = status

        if tp1_hit is not None:
            trade["tp1_hit"] = bool(
                tp1_hit
            )

        if tp2_hit is not None:
            trade["tp2_hit"] = bool(
                tp2_hit
            )

        if tp3_hit is not None:
            trade["tp3_hit"] = bool(
                tp3_hit
            )

        if sl_hit is not None:
            trade["sl_hit"] = bool(
                sl_hit
            )

        if result is not None:

            trade["result"] = result

        if status == "CLOSED":

            trade["closed_at"] = (
                datetime.datetime.utcnow()
                .isoformat()
            )

        save_history(history)

        return True

    return False


# =========================================================
# GET OPEN TRADES
# =========================================================

def get_open_trades():

    history = load_history()

    return [
        trade
        for trade in history
        if trade.get("status") == "OPEN"
    ]


# =========================================================
# GET ALL TRADES
# =========================================================

def get_all_trades():

    return load_history()


# =========================================================
# PERFORMANCE
# =========================================================

def get_performance():

    history = load_history()

    total = len(history)

    closed = [
        trade
        for trade in history
        if trade.get("status") == "CLOSED"
    ]

    wins = [
        trade
        for trade in closed
        if trade.get("result") == "WIN"
    ]

    losses = [
        trade
        for trade in closed
        if trade.get("result") == "LOSS"
    ]

    total_closed = len(closed)

    if total_closed > 0:

        win_rate = (
            len(wins)
            /
            total_closed
            *
            100
        )

    else:

        win_rate = 0

    return {

        "total": total,

        "open": len(
            [
                trade
                for trade in history
                if trade.get(
                    "status"
                ) == "OPEN"
            ]
        ),

        "closed": total_closed,

        "wins": len(wins),

        "losses": len(losses),

        "win_rate": round(
            win_rate,
            2
        ),

        "tp1": sum(
            1
            for trade in history
            if trade.get(
                "tp1_hit"
            )
        ),

        "tp2": sum(
            1
            for trade in history
            if trade.get(
                "tp2_hit"
            )
        ),

        "tp3": sum(
            1
            for trade in history
            if trade.get(
                "tp3_hit"
            )
        ),

        "sl": sum(
            1
            for trade in history
            if trade.get(
                "sl_hit"
            )
        )
    }
