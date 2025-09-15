import logging
import asyncio
import schedule
import time
from datetime import timedelta, datetime
import os
import argparse
from dotenv import load_dotenv

from telethon import TelegramClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from .models import Base
from .parser import sync_channel

# ---- CLI args ----
parser = argparse.ArgumentParser(description="Tbilisi Rent Parser")
parser.add_argument("--reset", action="store_true", help="Drop all DB content before sync")
args = parser.parse_args()
RESET_DB = args.reset

# ---- Load API keys ----
load_dotenv()
API_ID = int(os.getenv("TELEGRAM_API_ID"))
API_HASH = os.getenv("TELEGRAM_API_HASH")

# ---- Config ----
CHANNEL = "rent_tbilisi_ge"
DATABASE_URL = "sqlite:///bloodhound.db"
SYNC_LOOKBACK = timedelta(days=7)
SYNC_INTERVAL_MINUTES = 30

# ---- Logging ----
logging.basicConfig(level=logging.DEBUG,
                    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("bloodhound")

# ---- DB ----
engine = create_engine(DATABASE_URL)
Base.metadata.create_all(engine)
Session = sessionmaker(bind=engine)

# ---- Sync job ----
async def sync_job():
    logger.info("Starting sync job")
    session = Session()
    try:
        async with TelegramClient("bloodhound", API_ID, API_HASH) as client:
            cutoff_date = datetime.utcnow() - SYNC_LOOKBACK
            await sync_channel(client, session, CHANNEL, cutoff_date, reset=RESET_DB)
    finally:
        session.close()
    logger.info("Sync job finished")

# ---- Scheduler wrapper ----
def schedule_sync():
    asyncio.run(sync_job())

# ---- Main ----
if __name__ == "__main__":
    schedule.every(SYNC_INTERVAL_MINUTES).minutes.do(schedule_sync)
    logger.info("Scheduler started")
    schedule_sync()  # run once immediately

    while True:
        schedule.run_pending()
        time.sleep(1)