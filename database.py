import asyncpg
from config import DATABASE_URL

async def init_db():
    conn = await asyncpg.connect(DATABASE_URL)

    # ----- Serial va epizodlar -----
    await conn.execute('''
        CREATE TABLE IF NOT EXISTS series (
            id SERIAL PRIMARY KEY,
            name TEXT NOT NULL UNIQUE
        )
    ''')
    await conn.execute('''
        CREATE TABLE IF NOT EXISTS episodes (
            id SERIAL PRIMARY KEY,
            code INTEGER NOT NULL UNIQUE,
            serial_id INTEGER REFERENCES series(id) ON DELETE CASCADE,
            episode_number INTEGER NOT NULL,
            file_id TEXT NOT NULL,
            description TEXT,
            is_free BOOLEAN DEFAULT TRUE,
            UNIQUE(serial_id, episode_number)
        )
    ''')
    await conn.execute('''
        CREATE TABLE IF NOT EXISTS series_settings (
            serial_id INTEGER PRIMARY KEY REFERENCES series(id) ON DELETE CASCADE,
            free_episodes INTEGER DEFAULT 5
        )
    ''')

    # ----- Foydalanuvchilar -----
    await conn.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id BIGINT PRIMARY KEY,
            first_start TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_activity TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            referred_by TEXT
        )
    ''')

    # ----- Pullik obuna -----
    await conn.execute('''
        CREATE TABLE IF NOT EXISTS subscriptions (
            user_id BIGINT PRIMARY KEY REFERENCES users(user_id) ON DELETE CASCADE,
            start_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            is_active BOOLEAN DEFAULT TRUE,
            confirmed_by BIGINT
        )
    ''')

    # ----- Majburiy obuna -----
    await conn.execute('''
        CREATE TABLE IF NOT EXISTS mandatory_subscriptions (
            id SERIAL PRIMARY KEY,
            type TEXT NOT NULL,
            identifier TEXT NOT NULL,
            limit_count INTEGER NOT NULL,
            current_count INTEGER DEFAULT 0,
            is_active INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    await conn.execute('''
        CREATE TABLE IF NOT EXISTS user_completed_subs (
            user_id BIGINT NOT NULL,
            sub_id INTEGER NOT NULL,
            completed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (user_id, sub_id)
        )
    ''')

    # ----- Referallar -----
    await conn.execute('''
        CREATE TABLE IF NOT EXISTS referrals (
            code TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            count INTEGER DEFAULT 0
        )
    ''')

    # ----- Reklama -----
    await conn.execute('''
        CREATE TABLE IF NOT EXISTS ads (
            id INTEGER PRIMARY KEY DEFAULT 1,
            content_type TEXT NOT NULL,
            file_id TEXT,
            text TEXT,
            caption TEXT,
            send_count INTEGER DEFAULT 0
        )
    ''')
    await conn.execute('''
        INSERT INTO ads (id, content_type, file_id, text, caption, send_count)
        VALUES (1, 'empty', NULL, NULL, NULL, 0)
        ON CONFLICT (id) DO NOTHING
    ''')

    # ----- Tugma havolalari -----
    await conn.execute('''
        CREATE TABLE IF NOT EXISTS button_links (
            id INTEGER PRIMARY KEY DEFAULT 1,
            instagram_url TEXT DEFAULT 'https://instagram.com/yourpage',
            telegram_url TEXT DEFAULT 'https://t.me/yourchannel'
        )
    ''')
    await conn.execute('''
        INSERT INTO button_links (id, instagram_url, telegram_url)
        VALUES (1, 'https://instagram.com/yourpage', 'https://t.me/yourchannel')
        ON CONFLICT (id) DO NOTHING
    ''')

    await conn.close()

# -------------------- Foydalanuvchi --------------------
async def register_user_start(user_id, referral_code=None):
    conn = await asyncpg.connect(DATABASE_URL)
    async with conn.transaction():
        exists = await conn.fetchval("SELECT 1 FROM users WHERE user_id = $1", user_id)
        if not exists:
            await conn.execute(
                "INSERT INTO users (user_id, referred_by) VALUES ($1, $2)",
                user_id, referral_code
            )
            if referral_code:
                await conn.execute(
                    "UPDATE referrals SET count = count + 1 WHERE code = $1",
                    referral_code
                )
        else:
            await conn.execute(
                "UPDATE users SET last_activity = CURRENT_TIMESTAMP WHERE user_id = $1",
                user_id
            )
    await conn.close()

async def get_all_user_ids():
    conn = await asyncpg.connect(DATABASE_URL)
    rows = await conn.fetch("SELECT user_id FROM users")
    await conn.close()
    return [r["user_id"] for r in rows]

# -------------------- Serial --------------------
async def add_series(name: str) -> int:
    conn = await asyncpg.connect(DATABASE_URL)
    row = await conn.fetchrow(
        "INSERT INTO series (name) VALUES ($1) ON CONFLICT (name) DO NOTHING RETURNING id",
        name
    )
    if row:
        serial_id = row["id"]
        await conn.execute(
            "INSERT INTO series_settings (serial_id, free_episodes) VALUES ($1, 5) ON CONFLICT (serial_id) DO NOTHING",
            serial_id
        )
    else:
        row = await conn.fetchrow("SELECT id FROM series WHERE name = $1", name)
        serial_id = row["id"]
    await conn.close()
    return serial_id

async def get_all_series():
    conn = await asyncpg.connect(DATABASE_URL)
    rows = await conn.fetch("SELECT id, name FROM series ORDER BY name")
    await conn.close()
    return rows

async def get_series_id_by_name(name: str):
    conn = await asyncpg.connect(DATABASE_URL)
    row = await conn.fetchval("SELECT id FROM series WHERE name = $1", name)
    await conn.close()
    return row

# -------------------- Epizod --------------------
async def add_episode(serial_id: int, episode_number: int, file_id: str, description: str = "", is_free: bool = True) -> int:
    conn = await asyncpg.connect(DATABASE_URL)
    max_code = await conn.fetchval("SELECT COALESCE(MAX(code), 0) FROM episodes")
    new_code = max_code + 1
    await conn.execute(
        "INSERT INTO episodes (code, serial_id, episode_number, file_id, description, is_free) VALUES ($1, $2, $3, $4, $5, $6)",
        new_code, serial_id, episode_number, file_id, description, is_free
    )
    await conn.close()
    return new_code

async def get_episode_by_code(code: int):
    conn = await asyncpg.connect(DATABASE_URL)
    row = await conn.fetchrow(
        "SELECT e.*, s.name as serial_name FROM episodes e JOIN series s ON e.serial_id = s.id WHERE e.code = $1",
        code
    )
    await conn.close()
    return row

async def get_episode_by_serial_and_number(serial_id: int, episode_number: int):
    conn = await asyncpg.connect(DATABASE_URL)
    row = await conn.fetchrow(
        "SELECT e.*, s.name as serial_name FROM episodes e JOIN series s ON e.serial_id = s.id WHERE e.serial_id = $1 AND e.episode_number = $2",
        serial_id, episode_number
    )
    await conn.close()
    return row

async def get_episodes_count(serial_id: int) -> int:
    conn = await asyncpg.connect(DATABASE_URL)
    count = await conn.fetchval("SELECT COUNT(*) FROM episodes WHERE serial_id = $1", serial_id)
    await conn.close()
    return count or 0

async def get_free_episodes_count(serial_id: int) -> int:
    conn = await asyncpg.connect(DATABASE_URL)
    row = await conn.fetchval(
        "SELECT free_episodes FROM series_settings WHERE serial_id = $1",
        serial_id
    )
    await conn.close()
    return row or 5

async def set_free_episodes_count(serial_id: int, count: int):
    conn = await asyncpg.connect(DATABASE_URL)
    await conn.execute(
        "INSERT INTO series_settings (serial_id, free_episodes) VALUES ($1, $2) ON CONFLICT (serial_id) DO UPDATE SET free_episodes = $2",
        serial_id, count
    )
    await conn.close()

# -------------------- Pullik obuna --------------------
async def is_user_subscribed(user_id: int) -> bool:
    conn = await asyncpg.connect(DATABASE_URL)
    row = await conn.fetchval("SELECT is_active FROM subscriptions WHERE user_id = $1", user_id)
    await conn.close()
    return row is True

async def set_subscription(user_id: int, confirmed_by: int):
    conn = await asyncpg.connect(DATABASE_URL)
    await conn.execute(
        "INSERT INTO subscriptions (user_id, confirmed_by, is_active) VALUES ($1, $2, TRUE) "
        "ON CONFLICT (user_id) DO UPDATE SET is_active = TRUE, confirmed_by = $2",
        user_id, confirmed_by
    )
    await conn.close()

async def remove_subscription(user_id: int):
    conn = await asyncpg.connect(DATABASE_URL)
    await conn.execute("UPDATE subscriptions SET is_active = FALSE WHERE user_id = $1", user_id)
    await conn.close()

async def get_all_subscribed_users():
    conn = await asyncpg.connect(DATABASE_URL)
    rows = await conn.fetch("SELECT user_id FROM subscriptions WHERE is_active = TRUE")
    await conn.close()
    return [r["user_id"] for r in rows]

# -------------------- Majburiy obuna (TUZATILGAN) --------------------
async def get_active_mandatory_subs():
    conn = await asyncpg.connect(DATABASE_URL)
    rows = await conn.fetch(
        "SELECT id, type, identifier, limit_count, current_count FROM mandatory_subscriptions WHERE is_active = 1"
    )
    await conn.close()
    return [{"id": r["id"], "type": r["type"], "identifier": r["identifier"],
             "limit": r["limit_count"], "count": r["current_count"]} for r in rows]

async def is_user_completed_sub(user_id: int, sub_id: int) -> bool:
    conn = await asyncpg.connect(DATABASE_URL)
    row = await conn.fetchval(
        "SELECT 1 FROM user_completed_subs WHERE user_id = $1 AND sub_id = $2",
        user_id, sub_id
    )
    await conn.close()
    return row is not None

async def mark_user_completed_sub(user_id: int, sub_id: int) -> bool:
    """
    Foydalanuvchi obunani bajargan deb belgilaydi.
    Faqat birinchi marta bajargan foydalanuvchi hisobga olinadi.
    Agar limitga yetgan bo'lsa, obunani o'chiradi va True qaytaradi, aks holda False.
    """
    conn = await asyncpg.connect(DATABASE_URL)
    async with conn.transaction():
        # Avval foydalanuvchi bu obunani bajarganmi tekshiramiz
        existing = await conn.fetchval(
            "SELECT 1 FROM user_completed_subs WHERE user_id = $1 AND sub_id = $2",
            user_id, sub_id
        )
        if existing:
            # Allaqachon bajargan – hech narsa qilmaymiz
            await conn.close()
            return False

        # Yangi yozuv qo'shamiz
        await conn.execute(
            "INSERT INTO user_completed_subs (user_id, sub_id) VALUES ($1, $2)",
            user_id, sub_id
        )
        # Hisoblagichni oshiramiz (faqat birinchi marta)
        await conn.execute(
            "UPDATE mandatory_subscriptions SET current_count = current_count + 1 WHERE id = $1",
            sub_id
        )
        # Limitga yetganligini tekshiramiz
        row = await conn.fetchrow(
            "SELECT current_count, limit_count FROM mandatory_subscriptions WHERE id = $1",
            sub_id
        )
        deactivated = False
        if row and row["current_count"] >= row["limit_count"]:
            await conn.execute(
                "UPDATE mandatory_subscriptions SET is_active = 0 WHERE id = $1",
                sub_id
            )
            deactivated = True
        await conn.commit()
    await conn.close()
    return deactivated

async def add_mandatory_subscription(sub_type: str, identifier: str, limit_count: int):
    conn = await asyncpg.connect(DATABASE_URL)
    await conn.execute(
        "INSERT INTO mandatory_subscriptions (type, identifier, limit_count) VALUES ($1, $2, $3)",
        sub_type, identifier, limit_count
    )
    await conn.close()

async def remove_mandatory_subscription(sub_id: int):
    conn = await asyncpg.connect(DATABASE_URL)
    await conn.execute("DELETE FROM mandatory_subscriptions WHERE id = $1", sub_id)
    await conn.close()

async def list_mandatory_subscriptions():
    conn = await asyncpg.connect(DATABASE_URL)
    rows = await conn.fetch(
        "SELECT id, type, identifier, limit_count, current_count, is_active FROM mandatory_subscriptions ORDER BY id"
    )
    await conn.close()
    return rows

# -------------------- Referallar --------------------
async def create_referral(name, code):
    conn = await asyncpg.connect(DATABASE_URL)
    await conn.execute("INSERT INTO referrals (code, name) VALUES ($1, $2)", code, name)
    await conn.close()

async def check_referral_code(code):
    conn = await asyncpg.connect(DATABASE_URL)
    row = await conn.fetchrow("SELECT code FROM referrals WHERE code = $1", code)
    await conn.close()
    return row is not None

async def get_all_referrals():
    conn = await asyncpg.connect(DATABASE_URL)
    rows = await conn.fetch("SELECT code, name, count FROM referrals ORDER BY name")
    await conn.close()
    return [(r["code"], r["name"], r["count"]) for r in rows]

# -------------------- Reklama --------------------
async def set_ad(content_type, file_id=None, text=None, caption=None):
    conn = await asyncpg.connect(DATABASE_URL)
    await conn.execute("DELETE FROM ads WHERE id = 1")
    await conn.execute(
        "INSERT INTO ads (id, content_type, file_id, text, caption, send_count) VALUES (1, $1, $2, $3, $4, 0)",
        content_type, file_id, text, caption
    )
    await conn.close()

async def get_ad():
    conn = await asyncpg.connect(DATABASE_URL)
    row = await conn.fetchrow("SELECT content_type, file_id, text, caption, send_count FROM ads WHERE id = 1")
    await conn.close()
    if row and row["content_type"] != "empty":
        return row
    return None

async def remove_ad():
    conn = await asyncpg.connect(DATABASE_URL)
    await conn.execute("UPDATE ads SET content_type='empty', file_id=NULL, text=NULL, caption=NULL, send_count=0 WHERE id=1")
    await conn.close()

async def increment_ad_count():
    conn = await asyncpg.connect(DATABASE_URL)
    await conn.execute("UPDATE ads SET send_count = send_count + 1 WHERE id = 1")
    await conn.close()

# -------------------- Tugma havolalari --------------------
async def get_button_links():
    conn = await asyncpg.connect(DATABASE_URL)
    row = await conn.fetchrow("SELECT instagram_url, telegram_url FROM button_links WHERE id = 1")
    await conn.close()
    return row

async def set_button_links(instagram_url: str, telegram_url: str):
    conn = await asyncpg.connect(DATABASE_URL)
    await conn.execute(
        "UPDATE button_links SET instagram_url = $1, telegram_url = $2 WHERE id = 1",
        instagram_url, telegram_url
    )
    await conn.close()
