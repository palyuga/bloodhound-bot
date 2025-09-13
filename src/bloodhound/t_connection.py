from telethon import TelegramClient
import asyncio
import os
from dotenv import load_dotenv

load_dotenv()
API_ID = int(os.getenv("TELEGRAM_API_ID"))
API_HASH = os.getenv("TELEGRAM_API_HASH")

async def do_connect():
    async with TelegramClient("bloodhound", API_ID, API_HASH) as client:
        entity = await client.get_entity("rent_tbilisi_ge")
        async for msg in client.iter_messages(entity, limit=5):
            print(msg.id, msg.date, msg.text[:50])

if __name__ == "__main__":
    asyncio.run(do_connect())