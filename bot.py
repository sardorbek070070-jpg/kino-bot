import os
import random
import asyncio
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.requests import Request
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler, filters,
    ConversationHandler, CallbackContext
)
from telegram.request import HTTPXRequest
from dotenv import load_dotenv

from config import BOT_TOKEN, ADMIN_ID
from database import (
    init_db, add_video, get_video, delete_video, list_all_videos,
    register_user, get_total_users, get_today_users,
    get_week_users, get_active_users_last_24h
)

load_dotenv()

# -------------------- Holatlar --------------------
WAITING_FOR_VIDEO, WAITING_FOR_DESCRIPTION = range(2)

# -------------------- Bot va Webhook --------------------
WEBHOOK_PATH = "/webhook"
RENDER_EXTERNAL_HOSTNAME = os.environ.get("RENDER_EXTERNAL_HOSTNAME")
if not RENDER_EXTERNAL_HOSTNAME:
    raise ValueError("RENDER_EXTERNAL_HOSTNAME topilmadi. Render'da deploy qilganingizga ishonch hosil qiling.")
WEBHOOK_URL = f"https://{RENDER_EXTERNAL_HOSTNAME}{WEBHOOK_PATH}"

# -------------------- Yordamchi --------------------
def generate_unique_code():
    while True:
        code = str(random.randint(100, 9999))
        if get_video(code) is None:
            return code

# -------------------- Handlerlar --------------------
async def start(update: Update, context: CallbackContext):
    user_id = update.effective_user.id
    register_user(user_id)
    await update.message.reply_text(
        "🎬 **Kino botiga xush kelibsiz!**\n\n"
        "Film kodini raqamlarda yuboring (masalan: 123).\n"
        "Admin: /admin",
        parse_mode="Markdown"
    )

async def admin(update: Update, context: CallbackContext):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⛔ Siz admin emassiz!")
        return
    await update.message.reply_text(
        "🔧 **Admin panel**\n"
        "/addvideo - yangi video qo'shish\n"
        "/delvideo <kod> - videoni o'chirish\n"
        "/list - barcha videolar ro'yxati\n"
        "/stats - bot statistikasi",
        parse_mode="Markdown"
    )

async def stats(update: Update, context: CallbackContext):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⛔ Siz admin emassiz!")
        return
    total = get_total_users()
    today = get_today_users()
    week = get_week_users()
    active = get_active_users_last_24h()
    await update.message.reply_text(
        f"📊 **Statistika**\n\n"
        f"👥 Umumiy: {total}\n"
        f"🆕 Bugun: {today}\n"
        f"📅 7 kunda: {week}\n"
        f"🟢 24 soatda faol: {active}",
        parse_mode="Markdown"
    )

# -------------------- Video qo'shish (Conversation) --------------------
async def addvideo_start(update: Update, context: CallbackContext):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⛔ Ruxsat yo‘q")
        return ConversationHandler.END
    await update.message.reply_text("📹 Videoni yuboring (fayl sifatida)")
    return WAITING_FOR_VIDEO

async def addvideo_video(update: Update, context: CallbackContext):
    if not update.message.video:
        await update.message.reply_text("❌ Iltimos, video fayl yuboring")
        return WAITING_FOR_VIDEO
    file_id = update.message.video.file_id
    context.user_data['file_id'] = file_id
    await update.message.reply_text("✍️ Tavsif yozing (yoki /skip o‘tkazib yuborish)")
    return WAITING_FOR_DESCRIPTION

async def addvideo_description(update: Update, context: CallbackContext):
    description = update.message.text
    file_id = context.user_data.get('file_id')
    if not file_id:
        await update.message.reply_text("Xatolik, qaytadan /addvideo bosing")
        return ConversationHandler.END
    code = generate_unique_code()
    add_video(code, file_id, description)
    await update.message.reply_text(
        f"✅ Video saqlandi!\n**Kod:** `{code}`\n**Tavsif:** {description}",
        parse_mode="Markdown"
    )
    context.user_data.clear()
    return ConversationHandler.END

async def addvideo_skip(update: Update, context: CallbackContext):
    file_id = context.user_data.get('file_id')
    if not file_id:
        await update.message.reply_text("Xatolik, qaytadan /addvideo bosing")
        return ConversationHandler.END
    code = generate_unique_code()
    add_video(code, file_id, "")
    await update.message.reply_text(
        f"✅ Video saqlandi!\n**Kod:** `{code}`\nTavsifsiz",
        parse_mode="Markdown"
    )
    context.user_data.clear()
    return ConversationHandler.END

async def cancel(update: Update, context: CallbackContext):
    await update.message.reply_text("Bekor qilindi.")
    return ConversationHandler.END

# -------------------- Video o'chirish --------------------
async def delvideo(update: Update, context: CallbackContext):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⛔ Ruxsat yo‘q")
        return
    if not context.args:
        await update.message.reply_text("📛 Kodni kiriting: /delvideo 123")
        return
    code = context.args[0]
    video = get_video(code)
    if video:
        delete_video(code)
        await update.message.reply_text(f"✅ `{code}` o‘chirildi.", parse_mode="Markdown")
    else:
        await update.message.reply_text(f"❌ `{code}` topilmadi.", parse_mode="Markdown")

# -------------------- Barcha videolar --------------------
async def listvideos(update: Update, context: CallbackContext):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⛔ Ruxsat yo‘q")
        return
    videos = list_all_videos()
    if not videos:
        await update.message.reply_text("📭 Hech qanday video yo‘q.")
        return
    text = "📋 **Barcha videolar:**\n"
    for code, desc in videos:
        text += f"🔹 Kod: `{code}` — {desc or 'Tavsifsiz'}\n"
    await update.message.reply_text(text, parse_mode="Markdown")

# -------------------- Foydalanuvchi kod yuborganda --------------------
async def handle_code(update: Update, context: CallbackContext):
    user_id = update.effective_user.id
    register_user(user_id)
    text = update.message.text.strip()
    if not text.isdigit():
        await update.message.reply_text("🤔 Iltimos, faqat raqamlardan iborat kod yuboring.")
        return
    video = get_video(text)
    if video:
        file_id, description = video
        caption = f"🎬 Kodi: {text}\n📖 {description}" if description else f"🎬 Kodi: {text}"
        try:
            await update.message.reply_video(video=file_id, caption=caption, supports_streaming=True)
        except Exception as e:
            await context.bot.send_message(chat_id=ADMIN_ID, text=f"Video yuborish xatosi: {e}")
            await update.message.reply_text("❌ Video yuborishda xatolik yuz berdi.")
    else:
        await update.message.reply_text(f"❌ `{text}` kodli video topilmadi.", parse_mode="Markdown")

# -------------------- Webhook qabul qiluvchi --------------------
async def webhook_handler(request: Request):
    """Starlette uchun webhook handleri"""
    data = await request.json()
    update = Update.de_json(data, bot_application.bot)
    await bot_application.process_update(update)
    return JSONResponse({"ok": True})

async def healthcheck(request: Request):
    return JSONResponse({"status": "ok"})

# -------------------- Asosiy (Starlette + Webhook) --------------------
bot_application = None  # global o'zgaruvchi

async def main():
    global bot_application
    init_db()

    # Bot ilovasini yaratish
    bot_application = Application.builder().token(BOT_TOKEN).build()

    # Handlerlarni qo'shish
    bot_application.add_handler(CommandHandler("start", start))
    bot_application.add_handler(CommandHandler("admin", admin))
    bot_application.add_handler(CommandHandler("stats", stats))
    bot_application.add_handler(CommandHandler("delvideo", delvideo))
    bot_application.add_handler(CommandHandler("list", listvideos))
    bot_application.add_handler(CommandHandler("cancel", cancel))

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("addvideo", addvideo_start)],
        states={
            WAITING_FOR_VIDEO: [MessageHandler(filters.VIDEO, addvideo_video)],
            WAITING_FOR_DESCRIPTION: [
                CommandHandler("skip", addvideo_skip),
                MessageHandler(filters.TEXT & ~filters.COMMAND, addvideo_description)
            ]
        },
        fallbacks=[CommandHandler("cancel", cancel)]
    )
    bot_application.add_handler(conv_handler)
    bot_application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_code))

    # Webhook o'rnatish
    await bot_application.initialize()
    await bot_application.bot.set_webhook(WEBHOOK_URL)

    # Starlette ilovasini tuzish
    starlette_app = Starlette(debug=False, routes=[
        Route(WEBHOOK_PATH, webhook_handler, methods=["POST"]),
        Route("/healthcheck", healthcheck, methods=["GET"]),
    ])

    port = int(os.environ.get("PORT", 8080))
    print(f"✅ Bot ishga tushdi, webhook: {WEBHOOK_URL}")
    # Uvicorn ni ishga tushirish
    import uvicorn
    config = uvicorn.Config(starlette_app, host="0.0.0.0", port=port, log_level="info")
    server = uvicorn.Server(config)
    await server.serve()

if __name__ == "__main__":
    asyncio.run(main())
