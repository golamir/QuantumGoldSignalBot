import os
import asyncio
from telegram import Bot

TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")


async def main():
    print("Starting bot")

    print("TOKEN exists:", bool(TOKEN))
    print("CHAT_ID exists:", bool(CHAT_ID))

    try:
        bot = Bot(token=TOKEN)

        await bot.send_message(
            chat_id=CHAT_ID,
            text="✅ QuantumGoldSignalBot وصل شد"
        )

        print("Message sent successfully")

    except Exception as e:
        print("ERROR:", e)


if __name__ == "__main__":
    asyncio.run(main())
