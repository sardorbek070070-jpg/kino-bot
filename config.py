import os
from dotenv import load_dotenv

load_dotenv()  # .env faylini yuklash

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = os.getenv("ADMIN_ID")

# Agar muhit o'zgaruvchilari topilmasa, aniq xatolik chiqaramiz
if BOT_TOKEN is None:
    raise ValueError("BOT_TOKEN topilmadi. Iltimos, .env faylida BOT_TOKEN ni belgilang.")
if ADMIN_ID is None:
    raise ValueError("ADMIN_ID topilmadi. Iltimos, .env faylida ADMIN_ID ni belgilang.")

ADMIN_ID = int(ADMIN_ID)  # Stringni integerga o‘tkazamiz