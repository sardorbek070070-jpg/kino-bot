import os

BOT_TOKEN = os.getenv("BOT_TOKEN", "8729235570:AAGjhnGcHzJwALSbgbkovpLuwcmBFR_KoYg")
ADMIN_ID = int(os.getenv("ADMIN_ID", "2010030869"))
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://kino_8beg_user:0jaK2UwP2i5BHD4CgakZKWTU43cfSNnL@dpg-d85go7hkh4rs73dtrdag-a.oregon-postgres.render.com/kino_8beg")

# Telethon uchun
API_ID = int(os.getenv("API_ID", "38486800"))
API_HASH = os.getenv("API_HASH", "c5fc7e4d2190b89e5ce8ea01c0369f09")
