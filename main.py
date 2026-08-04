import os
import asyncio
from telegram import Bot

TOKEN = os.getenv("TELEGRAM_TOKEN")

async def main():
    if not TOKEN:
        print("Token not found")
        return

    bot = Bot(token=TOKEN)
    print("QuantumGoldSignalBot is running")

if __name__ == "__main__":
    asyncio.run(main())
