import aiosqlite
from config import DB_PATH

db = None

async def init_db():
    global db
    db = await aiosqlite.connect(DB_PATH)
    # Foydalanuvchilar
    await db.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            first_seen TEXT,
            last_active TEXT,
            referral_code TEXT
        )
    """)
    # Videolar
    await db.execute("""
        CREATE TABLE IF NOT EXISTS videos (
            code TEXT PRIMARY KEY,
            file_id TEXT,
            description TEXT
        )
    """)
    # Referallar
    await db.execute("""
        CREATE TABLE IF NOT EXISTS referrals (
            code TEXT PRIMARY KEY,
            name TEXT,
            count INTEGER DEFAULT 0
        )
    """)
    # Reklama
    await db.execute("""
        CREATE TABLE IF NOT EXISTS ad (
            id INTEGER PRIMARY KEY CHECK(id=1),
            content_type TEXT,
            file_id TEXT,
            text TEXT,
            caption TEXT,
            send_count INTEGER DEFAULT 0
        )
    """)
    # Majburiy kanallar
    await db.execute("""
        CREATE TABLE IF NOT EXISTS required_channels (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            channel_username TEXT NOT NULL UNIQUE
        )
    """)
    await db.commit()

# ========== Foydalanuvchilar ==========
async def register_user_start(user_id: int, referral_code: str = None):
    now = __import__("datetime").datetime.now().isoformat()
    async with db.execute("SELECT user_id FROM users WHERE user_id = ?", (user_id,)) as cursor:
        exists = await cursor.fetchone()
    if not exists:
        await db.execute("INSERT INTO users (user_id, first_seen, last_active, referral_code) VALUES (?, ?, ?, ?)",
                         (user_id, now, now, referral_code))
        if referral_code:
            await db.execute("UPDATE referrals SET count = count + 1 WHERE code = ?", (referral_code,))
    else:
        await db.execute("UPDATE users SET last_active = ? WHERE user_id = ?", (now, user_id))
    await db.commit()

async def get_total_users():
    async with db.execute("SELECT COUNT(*) FROM users") as cursor:
        row = await cursor.fetchone()
        return row[0] if row else 0

async def get_today_users():
    today = __import__("datetime").datetime.now().strftime("%Y-%m-%d")
    async with db.execute("SELECT COUNT(*) FROM users WHERE first_seen LIKE ?", (today + "%",)) as cursor:
        row = await cursor.fetchone()
        return row[0] if row else 0

async def get_week_users():
    import datetime
    week_ago = (datetime.datetime.now() - datetime.timedelta(days=7)).isoformat()
    async with db.execute("SELECT COUNT(*) FROM users WHERE first_seen >= ?", (week_ago,)) as cursor:
        row = await cursor.fetchone()
        return row[0] if row else 0

async def get_active_users_last_24h():
    import datetime
    since = (datetime.datetime.now() - datetime.timedelta(hours=24)).isoformat()
    async with db.execute("SELECT COUNT(*) FROM users WHERE last_active >= ?", (since,)) as cursor:
        row = await cursor.fetchone()
        return row[0] if row else 0

async def get_all_user_ids():
    async with db.execute("SELECT user_id FROM users") as cursor:
        rows = await cursor.fetchall()
    return [row[0] for row in rows]

# ========== Videolar ==========
async def add_video(code: str, file_id: str, description: str):
    await db.execute("INSERT OR REPLACE INTO videos (code, file_id, description) VALUES (?, ?, ?)",
                     (code, file_id, description))
    await db.commit()

async def get_video(code: str):
    async with db.execute("SELECT file_id, description FROM videos WHERE code = ?", (code,)) as cursor:
        row = await cursor.fetchone()
    return (row[0], row[1]) if row else None

async def delete_video(code: str):
    await db.execute("DELETE FROM videos WHERE code = ?", (code,))
    await db.commit()

async def list_all_videos():
    async with db.execute("SELECT code, description FROM videos ORDER BY code") as cursor:
        rows = await cursor.fetchall()
    return rows

# ========== Referallar ==========
async def create_referral(name: str, code: str):
    await db.execute("INSERT INTO referrals (code, name, count) VALUES (?, ?, 0)", (code, name))
    await db.commit()

async def check_referral_code(code: str):
    async with db.execute("SELECT code FROM referrals WHERE code = ?", (code,)) as cursor:
        row = await cursor.fetchone()
        return row is not None

async def get_all_referrals():
    async with db.execute("SELECT code, name, count FROM referrals") as cursor:
        rows = await cursor.fetchall()
    return rows

# ========== Reklama ==========
async def set_ad(content_type: str, file_id: str, text: str, caption: str):
    # Avvalgi reklamani o'chiramiz
    await db.execute("DELETE FROM ad")
    await db.execute("INSERT INTO ad (id, content_type, file_id, text, caption, send_count) VALUES (1, ?, ?, ?, ?, 0)",
                     (content_type, file_id, text, caption))
    await db.commit()

async def get_ad():
    async with db.execute("SELECT content_type, file_id, text, caption, send_count FROM ad WHERE id = 1") as cursor:
        row = await cursor.fetchone()
    return row  # tuple yoki None

async def remove_ad():
    await db.execute("DELETE FROM ad")
    await db.commit()

async def increment_ad_count():
    await db.execute("UPDATE ad SET send_count = send_count + 1 WHERE id = 1")
    await db.commit()

# ========== Majburiy kanallar ==========
async def add_required_channel(username: str):
    await db.execute("INSERT OR IGNORE INTO required_channels (channel_username) VALUES (?)", (username,))
    await db.commit()

async def remove_required_channel(username: str):
    await db.execute("DELETE FROM required_channels WHERE channel_username = ?", (username,))
    await db.commit()

async def get_all_required_channels():
    async with db.execute("SELECT channel_username FROM required_channels") as cursor:
        rows = await cursor.fetchall()
    return [row[0] for row in rows]
