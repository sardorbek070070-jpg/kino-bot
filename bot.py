import random
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import Message
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage

from config import BOT_TOKEN, ADMIN_ID
from database import (
    init_db, add_video, get_video, delete_video, list_all_videos,
    register_user, get_total_users, get_today_users, get_week_users, get_active_users_last_24h
)

bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

# ---------- FSM (admin uchun video qo'shish jarayoni) ----------
class AddVideoState(StatesGroup):
    waiting_for_video = State()
    waiting_for_description = State()

# ---------- Yordamchi funksiya: unikal kod yaratish ----------
def generate_code():
    while True:
        code = str(random.randint(100, 9999))
        if get_video(code) is None:
            return code

# ---------- /start (statistika qayd etiladi) ----------
@dp.message(Command("start"))
async def start_cmd(message: Message):
    user_id = message.from_user.id
    register_user(user_id)  # Foydalanuvchini ro'yxatga olish
    await message.answer(
        "🎬 **Kino botiga xush kelibsiz!**\n\n"
        "Botdan foydalanish uchun menga **film kodini** yuboring.\n"
        "Masalan: `123`\n\n"
        "Admin: /admin - boshqaruv paneli",
        parse_mode="Markdown"
    )

# ---------- Admin panel ----------
@dp.message(Command("admin"))
async def admin_panel(message: Message):
    if message.from_user.id != ADMIN_ID:
        await message.answer("⛔ Siz admin emassiz!")
        return
    await message.answer(
        "🔧 **Admin panel**\n"
        "/addvideo - yangi video qo'shish\n"
        "/delvideo - videoni o'chirish\n"
        "/listvideos - barcha videolar ro'yxati\n"
        "/stats - bot statistikasi",
        parse_mode="Markdown"
    )

# ---------- Statistika buyrug'i (faqat admin) ----------
@dp.message(Command("stats"))
async def stats_cmd(message: Message):
    if message.from_user.id != ADMIN_ID:
        await message.answer("⛔ Siz admin emassiz!")
        return
    
    total = get_total_users()
    today = get_today_users()
    week = get_week_users()
    active = get_active_users_last_24h()
    
    stats_text = (
        "📊 **Bot statistikasi**\n\n"
        f"👥 Umumiy foydalanuvchilar: `{total}`\n"
        f"🆕 Bugun qo'shilganlar: `{today}`\n"
        f"📅 Oxirgi 7 kunda: `{week}`\n"
        f"🟢 Oxirgi 24 soatda faol: `{active}`\n"
    )
    await message.answer(stats_text, parse_mode="Markdown")

# ---------- Video qo'shish (FSM) ----------
@dp.message(Command("addvideo"))
async def add_video_cmd(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    await message.answer("📹 Videoni yuboring (faqat video fayl)")
    await state.set_state(AddVideoState.waiting_for_video)

@dp.message(AddVideoState.waiting_for_video, F.video)
async def got_video(message: Message, state: FSMContext):
    file_id = message.video.file_id
    await state.update_data(file_id=file_id)
    await message.answer("✍️ Endi videoga tavsif yozing (ixtiyoriy, /skip o'tkazib yuborish mumkin)")
    await state.set_state(AddVideoState.waiting_for_description)

@dp.message(AddVideoState.waiting_for_video)
async def wrong_video(message: Message):
    await message.answer("❌ Iltimos, video fayl yuboring.")

@dp.message(AddVideoState.waiting_for_description, Command("skip"))
async def skip_description(message: Message, state: FSMContext):
    await save_video_with_description(message, state, description="")

@dp.message(AddVideoState.waiting_for_description)
async def got_description(message: Message, state: FSMContext):
    description = message.text
    await save_video_with_description(message, state, description)

async def save_video_with_description(message: Message, state: FSMContext, description: str):
    data = await state.get_data()
    file_id = data["file_id"]
    code = generate_code()
    add_video(code, file_id, description)
    await message.answer(
        f"✅ Video saqlandi!\n"
        f"**Kod:** `{code}`\n"
        f"**Tavsif:** {description if description else 'Yo‘q'}",
        parse_mode="Markdown"
    )
    await state.clear()

# ---------- Video o'chirish ----------
@dp.message(Command("delvideo"))
async def delete_video_cmd(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        await message.answer("📛 Iltimos, o'chirmoqchi bo'lgan kodni kiriting:\n/delvideo 123")
        return
    code = parts[1]
    video = get_video(code)
    if video:
        delete_video(code)
        await message.answer(f"✅ Video `{code}` o'chirildi.", parse_mode="Markdown")
    else:
        await message.answer(f"❌ `{code}` kodli video topilmadi.", parse_mode="Markdown")

# ---------- Barcha videolar ro'yxati ----------
@dp.message(Command("listvideos"))
async def list_videos(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    videos = list_all_videos()
    if not videos:
        await message.answer("📭 Hozircha hech qanday video yo'q.")
        return
    text = "📋 **Barcha videolar:**\n\n"
    for code, desc in videos:
        text += f"🔹 Kod: `{code}` — {desc if desc else 'Tavsifsiz'}\n"
    await message.answer(text, parse_mode="Markdown")

# ---------- Foydalanuvchi kod yuborganda (faqat raqam) ----------
@dp.message(F.text.regexp(r"^\d+$"))
async def get_video_by_code(message: Message):
    code = message.text.strip()
    video = get_video(code)
    if video:
        file_id, description = video
        await bot.send_video(
            chat_id=message.chat.id,
            video=file_id,
            caption=f"🎬 Kodi: {code}\n📖 {description}" if description else f"🎬 Kodi: {code}",
            protect_content=False
        )
    else:
        await message.answer(f"❌ `{code}` kodli video topilmadi. Iltimos, to'g'ri kod yuboring.", parse_mode="Markdown")

# ---------- Boshqa xabarlarga javob (ixtiyoriy) ----------
@dp.message()
async def unknown(message: Message):
    if message.from_user.id == ADMIN_ID:
        return  # Adminlarga aralashmaymiz
    await message.answer("🤔 Film kodini raqamlarda yuboring (masalan, 123). /start yordam beradi.")

# ---------- Botni ishga tushirish ----------
async def main():
    init_db()
    print("✅ Bot ishga tushdi. Statistika tayyor.")
    await dp.start_polling(bot)

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())