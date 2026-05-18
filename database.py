import sqlite3

DB_NAME = "movies.db"

def init_db():
    """Barcha jadvallarni yaratish"""
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    
    # Videolar jadvali
    c.execute('''
        CREATE TABLE IF NOT EXISTS videos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT UNIQUE NOT NULL,
            file_id TEXT NOT NULL,
            description TEXT
        )
    ''')
    
    # Foydalanuvchilar jadvali (statistika uchun)
    c.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            first_start DATETIME DEFAULT CURRENT_TIMESTAMP,
            last_activity DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    conn.commit()
    conn.close()

def add_video(code, file_id, description=""):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("INSERT INTO videos (code, file_id, description) VALUES (?, ?, ?)",
              (code, file_id, description))
    conn.commit()
    conn.close()

def get_video(code):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT file_id, description FROM videos WHERE code = ?", (code,))
    result = c.fetchone()
    conn.close()
    return result

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
    result = c.fetchall()
    conn.close()
    return result

# ----- Statistika funksiyalari -----
def register_user(user_id):
    """Yangi foydalanuvchini bazaga qo'shadi (agar mavjud bo'lmasa)"""
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (user_id,))
    c.execute("UPDATE users SET last_activity = CURRENT_TIMESTAMP WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()

def get_total_users():
    """Umumiy foydalanuvchilar soni (barcha vaqt davomida start bosganlar)"""
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM users")
    count = c.fetchone()[0]
    conn.close()
    return count

def get_today_users():
    """Bugun birinchi marta start bosgan foydalanuvchilar soni"""
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM users WHERE DATE(first_start) = DATE('now')")
    count = c.fetchone()[0]
    conn.close()
    return count

def get_week_users():
    """Oxirgi 7 kun ichida birinchi marta start bosganlar"""
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM users WHERE first_start >= DATE('now', '-7 days')")
    count = c.fetchone()[0]
    conn.close()
    return count

def get_active_users_last_24h():
    """Oxirgi 24 soat ichida botda faollik ko‘rsatganlar (last_activity)"""
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM users WHERE last_activity >= DATETIME('now', '-1 day')")
    count = c.fetchone()[0]
    conn.close()
    return count