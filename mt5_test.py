import MetaTrader5 as mt5


SERVER = "ePlanet-MT5"
LOGIN = 47010445


if not mt5.initialize():
    print("MT5 initialize failed")
    quit()


account = mt5.login(
    LOGIN,
    server=SERVER
)


if account:
    print("✅ MT5 connected")
    print(mt5.account_info())

else:
    print("❌ MT5 login failed")


mt5.shutdown()
