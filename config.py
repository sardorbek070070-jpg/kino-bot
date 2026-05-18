import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = os.getenv("ADMIN_ID")

if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN topilmadi")
if not ADMIN_ID:
    raise ValueError("ADMIN_ID topilmadi")

ADMIN_ID = int(ADMIN_ID)