import sqlite3

DB_NAME = "movies.db"

def init_db():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS videos (
            code TEXT PRIMARY KEY,
            file_id TEXT NOT NULL,
            description TEXT
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            first_start TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_activity TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.commit()
    conn.close()

def add_video(code, file_id, description=""):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO videos (code, file_id, description) VALUES (?,?,?)",
              (code, file_id, description))
    conn.commit()
    conn.close()

def get_video(code):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT file_id, description FROM videos WHERE code = ?", (code,))
    row = c.fetchone()
    conn.close()
    return row

def delete_video(code):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("DELETE FROM videos WHERE code = ?", (code,))
    conn.commit()
    conn.close()

def list_all_videos():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT code, description FROM videos")
    rows = c.fetchall()
    conn.close()
    return rows

def register_user(user_id):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (user_id,))
    c.execute("UPDATE users SET last_activity = CURRENT_TIMESTAMP WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()

def get_total_users():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM users")
    count = c.fetchone()[0]
    conn.close()
    return count

def get_today_users():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM users WHERE DATE(first_start) = DATE('now')")
    count = c.fetchone()[0]
    conn.close()
    return count

def get_week_users():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM users WHERE first_start >= DATE('now', '-7 days')")
    count = c.fetchone()[0]
    conn.close()
    return count

def get_active_users_last_24h():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM users WHERE last_activity >= DATETIME('now', '-1 day')")
    count = c.fetchone()[0]
    conn.close()
    return count
