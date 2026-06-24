import asyncpg
import datetime
from config import DATABASE_URL

pool = None

async def init_db():
    global pool
    pool = await asyncpg.create_pool(DATABASE_URL)
    async with pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id BIGINT PRIMARY KEY,
                first_seen TEXT,
                last_active TEXT,
                referral_code TEXT
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS videos (
                code TEXT PRIMARY KEY,
                file_id TEXT,
                description TEXT
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS referrals (
                code TEXT PRIMARY KEY,
                name TEXT,
                count INTEGER DEFAULT 0
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS ad (
                id INTEGER PRIMARY KEY CHECK(id=1),
                content_type TEXT,
                file_id TEXT,
                text TEXT,
                caption TEXT,
                send_count INTEGER DEFAULT 0
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS required_channels (
                id SERIAL PRIMARY KEY,
                channel_username TEXT NOT NULL UNIQUE
            )
        """)

async def register_user_start(user_id: int, referral_code: str = None):
    now = datetime.datetime.now().isoformat()
    async with pool.acquire() as conn:
        existing = await conn.fetchval("SELECT user_id FROM users WHERE user_id = $1", user_id)
        if not existing:
            await conn.execute(
                "INSERT INTO users (user_id, first_seen, last_active, referral_code) VALUES ($1, $2, $3, $4)",
                user_id, now, now, referral_code
            )
            if referral_code:
                await conn.execute("UPDATE referrals SET count = count + 1 WHERE code = $1", referral_code)
        else:
            await conn.execute("UPDATE users SET last_active = $1 WHERE user_id = $2", now, user_id)

async def get_total_users():
    async with pool.acquire() as conn:
        return await conn.fetchval("SELECT COUNT(*) FROM users")

async def get_today_users():
    today = datetime.datetime.now().strftime("%Y-%m-%d")
    async with pool.acquire() as conn:
        return await conn.fetchval("SELECT COUNT(*) FROM users WHERE first_seen LIKE $1", today + "%")

async def get_week_users():
    week_ago = (datetime.datetime.now() - datetime.timedelta(days=7)).isoformat()
    async with pool.acquire() as conn:
        return await conn.fetchval("SELECT COUNT(*) FROM users WHERE first_seen >= $1", week_ago)

async def get_active_users_last_24h():
    since = (datetime.datetime.now() - datetime.timedelta(hours=24)).isoformat()
    async with pool.acquire() as conn:
        return await conn.fetchval("SELECT COUNT(*) FROM users WHERE last_active >= $1", since)

async def get_all_user_ids():
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT user_id FROM users")
    return [row['user_id'] for row in rows]

async def add_video(code: str, file_id: str, description: str):
    async with pool.acquire() as conn:
        await conn.execute("INSERT INTO videos (code, file_id, description) VALUES ($1, $2, $3) ON CONFLICT (code) DO UPDATE SET file_id=$2, description=$3", code, file_id, description)

async def get_video(code: str):
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT file_id, description FROM videos WHERE code = $1", code)
    return (row['file_id'], row['description']) if row else None

async def delete_video(code: str):
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM videos WHERE code = $1", code)

async def list_all_videos():
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT code, description FROM videos ORDER BY code")
    return [(row['code'], row['description']) for row in rows]

async def create_referral(name: str, code: str):
    async with pool.acquire() as conn:
        await conn.execute("INSERT INTO referrals (code, name, count) VALUES ($1, $2, 0)", code, name)

async def check_referral_code(code: str):
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT code FROM referrals WHERE code = $1", code)
    return row is not None

async def get_all_referrals():
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT code, name, count FROM referrals")
    return [(row['code'], row['name'], row['count']) for row in rows]

async def set_ad(content_type: str, file_id: str, text: str, caption: str):
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM ad")
        await conn.execute("INSERT INTO ad (id, content_type, file_id, text, caption, send_count) VALUES (1, $1, $2, $3, $4, 0)", content_type, file_id, text, caption)

async def get_ad():
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT content_type, file_id, text, caption, send_count FROM ad WHERE id = 1")
    return row

async def remove_ad():
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM ad")

async def increment_ad_count():
    async with pool.acquire() as conn:
        await conn.execute("UPDATE ad SET send_count = send_count + 1 WHERE id = 1")

async def add_required_channel(username: str):
    async with pool.acquire() as conn:
        await conn.execute("INSERT INTO required_channels (channel_username) VALUES ($1) ON CONFLICT DO NOTHING", username)

async def remove_required_channel(username: str):
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM required_channels WHERE channel_username = $1", username)

async def get_all_required_channels():
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT channel_username FROM required_channels")
    return [row['channel_username'] for row in rows]
