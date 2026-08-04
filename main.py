import os
import asyncio
from telegram import Bot

TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")


async def send_message():
    if not TOKEN or not CHAT_ID:
        print("ERROR: TOKEN or CHAT_ID is missing")
        return

    bot = Bot(token=TOKEN)

    message = (
        "✅ ربات با موفقیت اجرا شد\n"
        "🤖 Telegram Bot is online"
    )

    await bot.send_message(
        chat_id=CHAT_ID,
        text=message
    )

    print("Message sent successfully")


if __name__ == "__main__":
    asyncio.run(send_message())
