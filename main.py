import os
import asyncio
from telegram import Bot

TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

async def main():
    if not TOKEN or not CHAT_ID:
        print("Missing Telegram settings")
        return

    bot = Bot(token=TOKEN)

    await bot.send_message(
        chat_id=CHAT_ID,
        text="✅ QuantumGoldSignalBot online!\n\nاتصال تلگرام موفق شد."
    )

    print("Message sent")

if __name__ == "__main__":
    asyncio.run(main())
