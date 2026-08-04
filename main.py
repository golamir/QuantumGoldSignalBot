import os
import asyncio
from telegram import Bot

TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

async def main():
    print("TOKEN:", bool(TOKEN))
    print("CHAT_ID:", bool(CHAT_ID))

    bot = Bot(token=TOKEN)

    try:
        me = await bot.get_me()
        print("Bot username:", me.username)

        await bot.send_message(
            chat_id=CHAT_ID,
            text="✅ Test message from GitHub Actions"
        )

        print("Message sent")

    except Exception as e:
        print("ERROR:", e)

if __name__ == "__main__":
    asyncio.run(main())
