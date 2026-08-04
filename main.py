import os
import asyncio
from telegram import Bot


TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")


async def main():
    print("Starting bot")

    print("TOKEN exists:", bool(TOKEN))
    print("CHAT_ID exists:", bool(CHAT_ID))

    if not TOKEN or not CHAT_ID:
        print("Missing TOKEN or CHAT_ID")
        return

    try:
        bot = Bot(token=TOKEN)

        print("Trying to send message...")

        await bot.send_message(
            chat_id=CHAT_ID,
            text="✅ ربات QuantumGoldSignalBot با موفقیت وصل شد"
        )

        print("Message sent successfully")

    except Exception as e:
        print("ERROR:", e)


if __name__ == "__main__":
    asyncio.run(main())
