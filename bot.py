import os
import asyncio
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.requests import Request
from telegram import Update
from telegram.ext import (
    Application, CommandHandler, MessageHandler, filters,
    ConversationHandler, CallbackContext
)
from dotenv import load_dotenv

from config import BOT_TOKEN, ADMIN_ID
from database import (
    init_db, add_video, get_video, delete_video, list_all_videos,
    register_user, get_total_users, get_today_users,
    get_week_users, get_active_users_last_24h,
    get_all_user_ids
)

load_dotenv()

# -------------------- Holatlar --------------------
WAITING_FOR_VIDEO, WAITING_FOR_CUSTOM_CODE, WAITING_FOR_DESCRIPTION = range(3)
WAITING_BROADCAST = 3

# -------------------- Webhook --------------------
WEBHOOK_PATH = "/webhook"
RENDER_EXTERNAL_HOSTNAME = os.environ.get("RENDER_EXTERNAL_HOSTNAME")
if not RENDER_EXTERNAL_HOSTNAME:
    raise ValueError("RENDER_EXTERNAL_HOSTNAME topilmadi")
WEBHOOK_URL = f"https://{RENDER_EXTERNAL_HOSTNAME}{WEBHOOK_PATH}"

# -------------------- Handlerlar --------------------
async def start(update: Update, context: CallbackContext):
    user_id = update.effective_user.id
    await register_user(user_id)
    await update.message.reply_text(
        "🎬 **Kino botiga xush kelibsiz!**\n\n"
        "Film kodini raqamlarda yuboring.\n"
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
        "/delvideo <kod> - o'chirish\n"
        "/list - barcha videolar\n"
        "/stats - statistika\n"
        "/broadcast - obunachilarga xabar",
        parse_mode="Markdown"
    )

async def stats(update: Update, context: CallbackContext):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⛔ Siz admin emassiz!")
        return
    total = await get_total_users()
    today = await get_today_users()
    week = await get_week_users()
    active = await get_active_users_last_24h()
    await update.message.reply_text(
        f"📊 **Statistika**\n\n"
        f"👥 Umumiy: {total}\n"
        f"🆕 Bugun: {today}\n"
        f"📅 7 kunda: {week}\n"
        f"🟢 24 soatda faol: {active}",
        parse_mode="Markdown"
    )

# -------------------- Broadcast (barchaga xabar) --------------------
async def broadcast_start(update: Update, context: CallbackContext):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⛔ Siz admin emassiz!")
        return ConversationHandler.END
    await update.message.reply_text(
        "📢 Barcha obunachilarga yubormoqchi bo'lgan xabaringizni yuboring.\n"
        "Matn, rasm, video, link — istalgan kontent.\n"
        "/cancel – bekor qilish"
    )
    return WAITING_BROADCAST

async def broadcast_send(update: Update, context: CallbackContext):
    if update.effective_user.id != ADMIN_ID:
        return ConversationHandler.END

    msg = update.message
    user_ids = await get_all_user_ids()
    total = len(user_ids)

    progress_msg = await msg.reply_text(f"📤 {total} ta foydalanuvchiga jo‘natish boshlandi...")

    # Backgroundda jo‘natish, webhook bloklanmasligi uchun
    asyncio.create_task(
        _broadcast_task(
            msg=msg,
            progress_msg=progress_msg,
            user_ids=user_ids,
            total=total
        )
    )
    return ConversationHandler.END

async def _broadcast_task(msg, progress_msg, user_ids, total):
    semaphore = asyncio.Semaphore(25)  # Telegram limitiga tushmaslik uchun

    async def send_to_user(uid):
        async with semaphore:
            try:
                await msg.copy(chat_id=uid)
            except Exception:
                pass  # Bloklagan yoki xatolik bo'lsa, o'tkazib yuboramiz

    tasks = [asyncio.create_task(send_to_user(uid)) for uid in user_ids]
    await asyncio.gather(*tasks)

    # Yakuniy natija
    await progress_msg.edit_text(f"✅ Xabar {total} ta foydalanuvchiga yuborildi.")

# -------------------- Video qo'shish (o'zimiz kod kiritamiz) --------------------
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
    await update.message.reply_text("🔢 Ushbu video uchun **kod** kiriting (faqat raqamlar):")
    return WAITING_FOR_CUSTOM_CODE

async def addvideo_custom_code(update: Update, context: CallbackContext):
    code = update.message.text.strip()
    if not code.isdigit():
        await update.message.reply_text("❌ Kod faqat raqamlardan iborat bo‘lishi kerak. Qaytadan kiriting:")
        return WAITING_FOR_CUSTOM_CODE
    # Kod unikalligini tekshirish
    existing = await get_video(code)
    if existing:
        await update.message.reply_text(f"⚠️ `{code}` kodi allaqachon mavjud. Boshqa kod kiriting:", parse_mode="Markdown")
        return WAITING_FOR_CUSTOM_CODE
    context.user_data['code'] = code
    await update.message.reply_text("✍️ Tavsif yozing (yoki /skip o‘tkazib yuborish)")
    return WAITING_FOR_DESCRIPTION

async def addvideo_description(update: Update, context: CallbackContext):
    description = update.message.text
    file_id = context.user_data.get('file_id')
    code = context.user_data.get('code')
    if not file_id or not code:
        await update.message.reply_text("Xatolik, qaytadan /addvideo bosing")
        return ConversationHandler.END
    await add_video(code, file_id, description)
    await update.message.reply_text(
        f"✅ Video saqlandi!\n**Kod:** `{code}`\n**Tavsif:** {description}",
        parse_mode="Markdown"
    )
    context.user_data.clear()
    return ConversationHandler.END

async def addvideo_skip(update: Update, context: CallbackContext):
    file_id = context.user_data.get('file_id')
    code = context.user_data.get('code')
    if not file_id or not code:
        await update.message.reply_text("Xatolik, qaytadan /addvideo bosing")
        return ConversationHandler.END
    await add_video(code, file_id, "")
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
    video = await get_video(code)
    if video:
        await delete_video(code)
        await update.message.reply_text(f"✅ `{code}` o‘chirildi.", parse_mode="Markdown")
    else:
        await update.message.reply_text(f"❌ `{code}` topilmadi.", parse_mode="Markdown")

async def listvideos(update: Update, context: CallbackContext):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⛔ Ruxsat yo‘q")
        return
    videos = await list_all_videos()
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
    await register_user(user_id)
    text = update.message.text.strip()
    if not text.isdigit():
        await update.message.reply_text("🤔 Iltimos, faqat raqamlardan iborat kod yuboring.")
        return
    video = await get_video(text)
    if video:
        file_id, description = video
        caption = f"🎬 Kodi: {text}\n📖 {description}" if description else f"🎬 Kodi: {text}"
        try:
            await update.message.reply_video(video=file_id, caption=caption, supports_streaming=True, protect_content=True)
        except Exception as e:
            await context.bot.send_message(chat_id=ADMIN_ID, text=f"Video yuborish xatosi: {e}")
            await update.message.reply_text("❌ Video yuborishda xatolik yuz berdi.")
    else:
        await update.message.reply_text(f"❌ `{text}` kodli video topilmadi.", parse_mode="Markdown")

# -------------------- Webhook --------------------
async def webhook_handler(request: Request):
    data = await request.json()
    update = Update.de_json(data, bot_application.bot)
    await bot_application.process_update(update)
    return JSONResponse({"ok": True})

async def healthcheck(request: Request):
    return JSONResponse({"status": "ok"})

bot_application = None

async def main():
    global bot_application
    await init_db()
    bot_application = Application.builder().token(BOT_TOKEN).build()

    bot_application.add_handler(CommandHandler("start", start))
    bot_application.add_handler(CommandHandler("admin", admin))
    bot_application.add_handler(CommandHandler("stats", stats))
    bot_application.add_handler(CommandHandler("delvideo", delvideo))
    bot_application.add_handler(CommandHandler("list", listvideos))
    bot_application.add_handler(CommandHandler("cancel", cancel))

    # Video qo'shish ConversationHandler
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("addvideo", addvideo_start)],
        states={
            WAITING_FOR_VIDEO: [MessageHandler(filters.VIDEO, addvideo_video)],
            WAITING_FOR_CUSTOM_CODE: [MessageHandler(filters.TEXT & ~filters.COMMAND, addvideo_custom_code)],
            WAITING_FOR_DESCRIPTION: [
                CommandHandler("skip", addvideo_skip),
                MessageHandler(filters.TEXT & ~filters.COMMAND, addvideo_description)
            ]
        },
        fallbacks=[CommandHandler("cancel", cancel)]
    )
    bot_application.add_handler(conv_handler)

    # Broadcast ConversationHandler
    broadcast_conv = ConversationHandler(
        entry_points=[CommandHandler("broadcast", broadcast_start)],
        states={
            WAITING_BROADCAST: [
                MessageHandler(filters.ALL & ~filters.COMMAND, broadcast_send)
            ]
        },
        fallbacks=[CommandHandler("cancel", cancel)]
    )
    bot_application.add_handler(broadcast_conv)

    bot_application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_code))

    await bot_application.initialize()
    await bot_application.bot.set_webhook(WEBHOOK_URL)

    starlette_app = Starlette(debug=False, routes=[
        Route(WEBHOOK_PATH, webhook_handler, methods=["POST"]),
        Route("/healthcheck", healthcheck, methods=["GET"]),
    ])

    port = int(os.environ.get("PORT", 8080))
    print(f"✅ Bot ishga tushdi, webhook: {WEBHOOK_URL}")
    import uvicorn
    config = uvicorn.Config(starlette_app, host="0.0.0.0", port=port, log_level="info")
    server = uvicorn.Server(config)
    await server.serve()

if __name__ == "__main__":
    asyncio.run(main())
