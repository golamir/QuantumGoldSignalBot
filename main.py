import os

TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

print("TOKEN exists:", TOKEN is not None)
print("CHAT_ID exists:", CHAT_ID is not None)
print("CHAT_ID length:", len(CHAT_ID) if CHAT_ID else 0)
