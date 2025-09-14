from telethon import TelegramClient
import asyncio
import os
from dotenv import load_dotenv

from src.bloodhound.parser import parse_post
from tests.test_parser import make_msg

load_dotenv()
API_ID = int(os.getenv("TELEGRAM_API_ID"))
API_HASH = os.getenv("TELEGRAM_API_HASH")

async def do_connect():
    async with TelegramClient("bloodhound", API_ID, API_HASH) as client:
        entity = await client.get_entity("rent_tbilisi_ge")
        async for msg in client.iter_messages(entity, limit=25):
            if msg.text:
                print(msg.id, msg.date, msg.text[:5000])
                post = parse_post(make_msg(msg.text, msg_id=100), channel_id="12345")
                print("\n Parsed post:")
                print(post)
                print("\n")

if __name__ == "__main__":
    asyncio.run(do_connect())