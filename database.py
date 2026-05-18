import asyncpg
from config import DATABASE_URL

async def init_db():
    conn = await asyncpg.connect(DATABASE_URL)
    await conn.execute('''
        CREATE TABLE IF NOT EXISTS videos (
            code TEXT PRIMARY KEY,
            file_id TEXT NOT NULL,
            description TEXT
        )
    ''')
    await conn.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id BIGINT PRIMARY KEY,
            first_start TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_activity TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    await conn.close()

async def add_video(code, file_id, description=""):
    conn = await asyncpg.connect(DATABASE_URL)
    await conn.execute(
        "INSERT INTO videos (code, file_id, description) VALUES ($1, $2, $3) ON CONFLICT (code) DO UPDATE SET file_id=$2, description=$3",
        code, file_id, description
    )
    await conn.close()

async def get_video(code):
    conn = await asyncpg.connect(DATABASE_URL)
    row = await conn.fetchrow("SELECT file_id, description FROM videos WHERE code = $1", code)
    await conn.close()
    return row  # (file_id, description) yoki None

async def delete_video(code):
    conn = await asyncpg.connect(DATABASE_URL)
    await conn.execute("DELETE FROM videos WHERE code = $1", code)
    await conn.close()

async def list_all_videos():
    conn = await asyncpg.connect(DATABASE_URL)
    rows = await conn.fetch("SELECT code, description FROM videos")
    await conn.close()
    return [(r["code"], r["description"]) for r in rows]

async def register_user(user_id):
    conn = await asyncpg.connect(DATABASE_URL)
    await conn.execute(
        "INSERT INTO users (user_id) VALUES ($1) ON CONFLICT (user_id) DO NOTHING",
        user_id
    )
    await conn.execute(
        "UPDATE users SET last_activity = CURRENT_TIMESTAMP WHERE user_id = $1",
        user_id
    )
    await conn.close()

async def get_total_users():
    conn = await asyncpg.connect(DATABASE_URL)
    val = await conn.fetchval("SELECT COUNT(*) FROM users")
    await conn.close()
    return val

async def get_today_users():
    conn = await asyncpg.connect(DATABASE_URL)
    val = await conn.fetchval("SELECT COUNT(*) FROM users WHERE DATE(first_start) = CURRENT_DATE")
    await conn.close()
    return val

async def get_week_users():
    conn = await asyncpg.connect(DATABASE_URL)
    val = await conn.fetchval("SELECT COUNT(*) FROM users WHERE first_start >= CURRENT_DATE - INTERVAL '7 days'")
    await conn.close()
    return val

async def get_active_users_last_24h():
    conn = await asyncpg.connect(DATABASE_URL)
    val = await conn.fetchval("SELECT COUNT(*) FROM users WHERE last_activity >= CURRENT_TIMESTAMP - INTERVAL '1 day'")
    await conn.close()
    return val
