import os
import asyncio
import secrets
import time
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.requests import Request
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler, filters,
    ConversationHandler, CallbackContext, CallbackQueryHandler
)
from dotenv import load_dotenv

from config import BOT_TOKEN, ADMIN_ID
from database import (
    init_db, add_video, get_video, delete_video, list_all_videos,
    register_user_start, get_total_users, get_today_users,
    get_week_users, get_active_users_last_24h,
    get_all_user_ids, create_referral, check_referral_code, get_all_referrals,
    set_ad, get_ad, remove_ad, increment_ad_count,
    get_active_mandatory_subs, is_user_completed_sub, mark_user_completed_sub,
    add_mandatory_subscription, remove_mandatory_subscription, list_mandatory_subscriptions,
    set_user_completed_sub
)

load_dotenv()

# ======================== Holatlar ========================
WAITING_FOR_VIDEO, WAITING_FOR_CUSTOM_CODE, WAITING_FOR_DESCRIPTION = range(3)
WAITING_BROADCAST = 3
WAITING_REF_NAME = 4
WAITING_AD_CONTENT = 5

# ======================== Webhook ========================
WEBHOOK_PATH = "/webhook"
RENDER_EXTERNAL_HOSTNAME = os.environ.get("RENDER_EXTERNAL_HOSTNAME")
if not RENDER_EXTERNAL_HOSTNAME:
    raise ValueError("RENDER_EXTERNAL_HOSTNAME topilmadi")
WEBHOOK_URL = f"https://{RENDER_EXTERNAL_HOSTNAME}{WEBHOOK_PATH}"

# ======================== Reklama ========================
async def send_ad(bot, chat_id):
    ad = await get_ad()
    if not ad:
        return
    content_type = ad["content_type"]
    file_id = ad["file_id"]
    text = ad["text"]
    caption = ad["caption"] or ""
    try:
        if content_type == "text":
            await bot.send_message(chat_id=chat_id, text=text)
        elif content_type == "photo":
            await bot.send_photo(chat_id=chat_id, photo=file_id, caption=caption)
        elif content_type == "video":
            await bot.send_video(chat_id=chat_id, video=file_id, caption=caption)
        elif content_type == "document":
            await bot.send_document(chat_id=chat_id, document=file_id, caption=caption)
        elif content_type == "audio":
            await bot.send_audio(chat_id=chat_id, audio=file_id, caption=caption)
        elif content_type == "voice":
            await bot.send_voice(chat_id=chat_id, voice=file_id, caption=caption)
        elif content_type == "animation":
            await bot.send_animation(chat_id=chat_id, animation=file_id, caption=caption)
        await increment_ad_count()
    except Exception as e:
        print(f"Reklama yuborishda xatolik: {e}")


# ======================== Obuna tekshirish ========================
async def check_subscription_status(bot, user_id, identifier):
    """Foydalanuvchi kanalga a'zo ekanligini tekshiradi"""
    try:
        chat_id = identifier
        if not chat_id.startswith("@") and not chat_id.startswith("-100"):
            if chat_id.lstrip("-").isdigit():
                chat_id = int(chat_id)
            else:
                chat_id = "@" + chat_id.lstrip("@")
        
        member = await bot.get_chat_member(chat_id=chat_id, user_id=user_id)
        return member.status in ["member", "administrator", "creator"]
    except Exception as e:
        print(f"Tekshirish xatolik: {e}")
        return False


# ======================== Majburiy obuna interfeysi ========================
async def show_mandatory_subs(update: Update, context: CallbackContext):
    user_id = update.effective_user.id
    subs = await get_active_mandatory_subs()
    if not subs:
        return True

    incomplete = []
    for sub in subs:
        is_completed = await is_user_completed_sub(user_id, sub["id"])
        if not is_completed:
            incomplete.append(sub)

    if not incomplete:
        return True

    text = "🔔 <b>Botdan foydalanish uchun quyidagi kanallarga obuna bo'ling:</b>\n\n"
    url_buttons = []

    for idx, sub in enumerate(incomplete, start=1):
        identifier = sub["identifier"]
        button_text = f"📢 {idx}-kanal"
        
        if sub["type"] in ("telegram", "group"):
            if identifier.startswith("@"):
                url = f"https://t.me/{identifier[1:]}"
            elif identifier.startswith("-100"):
                url = f"https://t.me/c/{identifier[4:]}/1"
            elif identifier.startswith("https://"):
                url = identifier
            else:
                url = f"https://t.me/{identifier}"
        elif sub["type"] == "bot":
            bot_username = identifier.replace("@", "").replace("https://t.me/", "").split("?")[0].split("/")[-1]
            url = f"https://t.me/{bot_username}?start=start"
        else:
            url = identifier

        url_buttons.append([InlineKeyboardButton(button_text, url=url)])

    confirm_button = [[InlineKeyboardButton("✅ Obuna bo'ldim", callback_data="confirm_all_subs")]]
    reply_markup = InlineKeyboardMarkup(url_buttons + confirm_button)

    if "mandatory_msg_id" in context.user_data:
        try:
            await context.bot.delete_message(chat_id=user_id, message_id=context.user_data["mandatory_msg_id"])
        except:
            pass

    sent_msg = await update.message.reply_text(
        text, reply_markup=reply_markup, parse_mode="HTML", disable_web_page_preview=True
    )
    context.user_data["mandatory_msg_id"] = sent_msg.message_id
    return False


# ======================== Majburiy obuna tekshiruvi ========================
async def check_and_handle_mandatory_subs(update: Update, context: CallbackContext):
    user_id = update.effective_user.id

    subs = await get_active_mandatory_subs()
    if not subs:
        return False

    check_types = ["telegram", "group"]
    
    async def check_sub(sub):
        already = await is_user_completed_sub(user_id, sub["id"])
        
        if sub["type"] in check_types:
            result = await check_subscription_status(context.bot, user_id, sub["identifier"])
            
            if result is True:
                if not already:
                    await mark_user_completed_sub(user_id, sub["id"])
                return (sub, True)
            elif result is False:
                if already:
                    await set_user_completed_sub(user_id, sub["id"], False)
                return (sub, False)
        return (sub, already)

    results = await asyncio.gather(*[check_sub(sub) for sub in subs])

    incomplete = [sub for sub, ok in results if not ok]

    if incomplete:
        await show_mandatory_subs(update, context)
        return True
    return False


# ======================== Callback: obunani tasdiqlash ========================
async def confirm_all_subs_callback(update: Update, context: CallbackContext):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id

    subs = await get_active_mandatory_subs()
    if not subs:
        await query.edit_message_text("✅ Hech qanday majburiy obuna mavjud emas.")
        await start_after_subs(update, context)
        return

    await query.edit_message_text("⏳ Tekshirilmoqda...")

    check_types = ["telegram", "group"]
    
    async def check_single_sub(sub):
        if sub["type"] in check_types:
            result = await check_subscription_status(context.bot, user_id, sub["identifier"])
            if result:
                await mark_user_completed_sub(user_id, sub["id"])
                return (sub, True)
            return (sub, False)
        return (sub, True)

    results = await asyncio.gather(*[check_single_sub(sub) for sub in subs])

    failed = []
    for i, (sub, ok) in enumerate(results, start=1):
        if not ok:
            failed.append(f"❌ {i}-kanal")

    if failed:
        msg_text = "Quyidagi kanallarga obuna bo'lmagansiz:\n\n" + "\n".join(failed) + "\n\nIltimos, avval ularga obuna bo'ling va qayta tekshiring."
        await query.edit_message_text(msg_text, disable_web_page_preview=True)
        return

    await query.edit_message_text("✅ Ajoyib! Barcha kanallarga obuna bo'lgansiz. Botdan foydalanishingiz mumkin!")
    if "mandatory_msg_id" in context.user_data:
        del context.user_data["mandatory_msg_id"]
    await start_after_subs(update, context)


async def start_after_subs(update: Update, context: CallbackContext):
    user_id = update.effective_user.id
    message = update.callback_query.message if update.callback_query else update.message
    await message.reply_text("🎬 Kino botiga xush kelibsiz!\n📣 Kino kanalimiz: @kino_boru\n\nFilm kodini raqamlarda yuboring.\nAdmin: /admin")
    asyncio.create_task(send_ad(context.bot, user_id))


# ======================== Start ========================
async def start(update: Update, context: CallbackContext):
    user_id = update.effective_user.id
    referral_code = context.args[0] if context.args else None
    await register_user_start(user_id, referral_code)
    if await check_and_handle_mandatory_subs(update, context):
        return
    await start_after_subs(update, context)


# ======================== Admin panel ========================
async def admin(update: Update, context: CallbackContext):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⛔ Siz admin emassiz!")
        return
    await update.message.reply_text(
        "<b>🔧 Admin panel</b>\n\n"
        "/addvideo - yangi video qo'shish\n"
        "/delvideo &lt;kod&gt; - o'chirish\n"
        "/list - barcha videolar\n"
        "/stats - statistika\n"
        "/broadcast - obunachilarga xabar\n"
        "/createref - referal havola yaratish\n"
        "/refstats - referallar statistikasi\n"
        "/setad - reklama o'rnatish\n"
        "/removead - reklamani o'chirish\n"
        "/adstats - reklama statistikasi\n\n"
        "<b>📛 Majburiy obuna:</b>\n"
        "/add_mandatory &lt;tur&gt; &lt;havola&gt; &lt;limit&gt;\n"
        "Turlar: telegram, group, bot, youtube, instagram, website\n\n"
        "Masalan:\n"
        "/add_mandatory telegram @kino_kanal 5000\n"
        "/add_mandatory telegram -1001234567890 5000\n\n"
        "/remove_mandatory &lt;id&gt;\n"
        "/list_mandatory",
        parse_mode="HTML", disable_web_page_preview=True
    )


# ======================== Statistika ========================
async def stats(update: Update, context: CallbackContext):
    if update.effective_user.id != ADMIN_ID:
        return
    total = await get_total_users()
    today = await get_today_users()
    week = await get_week_users()
    active = await get_active_users_last_24h()
    await update.message.reply_text(f"📊 Statistika\n\n👥 Umumiy: {total}\n🆕 Bugun: {today}\n📅 7 kunda: {week}\n🟢 24 soatda faol: {active}")


# ======================== Broadcast ========================
async def broadcast_start(update: Update, context: CallbackContext):
    if update.effective_user.id != ADMIN_ID:
        return ConversationHandler.END
    await update.message.reply_text("📢 Xabarni yuboring.\n/cancel – bekor qilish")
    return WAITING_BROADCAST

async def broadcast_send(update: Update, context: CallbackContext):
    if update.effective_user.id != ADMIN_ID:
        return ConversationHandler.END
    msg = update.message
    user_ids = await get_all_user_ids()
    total = len(user_ids)
    progress_msg = await msg.reply_text(f"📤 {total} ta foydalanuvchiga jo'natish boshlandi...")
    asyncio.create_task(_broadcast_task(msg, progress_msg, user_ids, total))
    return ConversationHandler.END

async def _broadcast_task(msg, progress_msg, user_ids, total):
    semaphore = asyncio.Semaphore(25)
    async def send_to_user(uid):
        async with semaphore:
            try:
                await msg.copy(chat_id=uid)
            except:
                pass
    await asyncio.gather(*[asyncio.create_task(send_to_user(uid)) for uid in user_ids])
    await progress_msg.edit_text(f"✅ Xabar {total} ta foydalanuvchiga yuborildi.")


# ======================== Video qo'shish ========================
async def addvideo_start(update: Update, context: CallbackContext):
    if update.effective_user.id != ADMIN_ID:
        return ConversationHandler.END
    await update.message.reply_text("📹 Videoni yuboring (fayl sifatida)")
    return WAITING_FOR_VIDEO

async def addvideo_video(update: Update, context: CallbackContext):
    if not update.message.video:
        await update.message.reply_text("❌ Iltimos, video fayl yuboring")
        return WAITING_FOR_VIDEO
    context.user_data['file_id'] = update.message.video.file_id
    await update.message.reply_text("🔢 Kod kiriting (faqat raqamlar):")
    return WAITING_FOR_CUSTOM_CODE

async def addvideo_custom_code(update: Update, context: CallbackContext):
    code = update.message.text.strip()
    if not code.isdigit():
        await update.message.reply_text("❌ Kod faqat raqamlardan iborat bo'lishi kerak:")
        return WAITING_FOR_CUSTOM_CODE
    if await get_video(code):
        await update.message.reply_text(f"⚠️ {code} kodi mavjud. Boshqa kod kiriting:")
        return WAITING_FOR_CUSTOM_CODE
    context.user_data['code'] = code
    await update.message.reply_text("✍️ Tavsif yozing (yoki /skip)")
    return WAITING_FOR_DESCRIPTION

async def addvideo_description(update: Update, context: CallbackContext):
    await add_video(context.user_data['code'], context.user_data['file_id'], update.message.text)
    await update.message.reply_text(f"✅ Video saqlandi!\nKod: {context.user_data['code']}")
    context.user_data.clear()
    return ConversationHandler.END

async def addvideo_skip(update: Update, context: CallbackContext):
    await add_video(context.user_data['code'], context.user_data['file_id'], "")
    await update.message.reply_text(f"✅ Video saqlandi!\nKod: {context.user_data['code']}")
    context.user_data.clear()
    return ConversationHandler.END

async def cancel(update: Update, context: CallbackContext):
    await update.message.reply_text("Bekor qilindi.")
    return ConversationHandler.END


# ======================== Video o'chirish ========================
async def delvideo(update: Update, context: CallbackContext):
    if update.effective_user.id != ADMIN_ID:
        return
    if not context.args:
        await update.message.reply_text("📛 Kodni kiriting: /delvideo 123")
        return
    if await get_video(context.args[0]):
        await delete_video(context.args[0])
        await update.message.reply_text(f"✅ {context.args[0]} o'chirildi.")
    else:
        await update.message.reply_text(f"❌ {context.args[0]} topilmadi.")

async def listvideos(update: Update, context: CallbackContext):
    if update.effective_user.id != ADMIN_ID:
        return
    videos = await list_all_videos()
    if not videos:
        await update.message.reply_text("📭 Hech qanday video yo'q.")
        return
    text = "📋 Barcha videolar:\n"
    for code, desc in videos:
        text += f"🔹 Kod: {code} — {desc or 'Tavsifsiz'}\n"
    await update.message.reply_text(text)


# ======================== Referal ========================
async def createref_start(update: Update, context: CallbackContext):
    if update.effective_user.id != ADMIN_ID:
        return ConversationHandler.END
    await update.message.reply_text("🔗 Referal uchun nom bering:")
    return WAITING_REF_NAME

async def createref_get_name(update: Update, context: CallbackContext):
    if update.effective_user.id != ADMIN_ID:
        return ConversationHandler.END
    name = update.message.text.strip()
    if not name:
        await update.message.reply_text("❌ Bo'sh bo'lmagan nom kiriting.")
        return WAITING_REF_NAME
    while True:
        code = secrets.token_hex(3)
        if not await check_referral_code(code):
            break
    await create_referral(name, code)
    link = f"https://t.me/KINO_bor_botbot?start={code}"
    await update.message.reply_text(f"✅ Yangi referal havola yaratildi\n\n📌 Nomi: {name}\n🔗 Havola: {link}\n🆔 Kod: {code}")
    return ConversationHandler.END

async def refstats(update: Update, context: CallbackContext):
    if update.effective_user.id != ADMIN_ID:
        return
    referrals = await get_all_referrals()
    if not referrals:
        await update.message.reply_text("📭 Hali hech qanday referal havola yo'q.")
        return
    text = "📊 Referallar statistikasi\n\n"
    for code, name, count in referrals:
        text += f"• {name} (kod: {code}) – {count} ta\n"
    await update.message.reply_text(text)


# ======================== Reklama ========================
async def setad_start(update: Update, context: CallbackContext):
    if update.effective_user.id != ADMIN_ID:
        return ConversationHandler.END
    await update.message.reply_text("📢 Reklama kontentini yuboring.\n/cancel – bekor qilish")
    return WAITING_AD_CONTENT

async def setad_get_content(update: Update, context: CallbackContext):
    if update.effective_user.id != ADMIN_ID:
        return ConversationHandler.END
    msg = update.message
    content_type, file_id, text, caption = None, None, None, msg.caption or ""
    if msg.text and not msg.caption:
        content_type, text = "text", msg.text
    elif msg.photo:
        content_type, file_id = "photo", msg.photo[-1].file_id
    elif msg.video:
        content_type, file_id = "video", msg.video.file_id
    elif msg.document:
        content_type, file_id = "document", msg.document.file_id
    elif msg.audio:
        content_type, file_id = "audio", msg.audio.file_id
    elif msg.voice:
        content_type, file_id = "voice", msg.voice.file_id
    elif msg.animation:
        content_type, file_id = "animation", msg.animation.file_id
    else:
        await update.message.reply_text("❌ Qo'llab-quvvatlanmaydi.")
        return WAITING_AD_CONTENT
    await set_ad(content_type, file_id, text, caption)
    await update.message.reply_text(f"✅ Reklama saqlandi!\nTuri: {content_type}")
    return ConversationHandler.END

async def removead(update: Update, context: CallbackContext):
    if update.effective_user.id != ADMIN_ID:
        return
    await remove_ad()
    await update.message.reply_text("🗑️ Reklama o'chirildi.")

async def adstats(update: Update, context: CallbackContext):
    if update.effective_user.id != ADMIN_ID:
        return
    ad = await get_ad()
    await update.message.reply_text(f"📊 Reklama {ad['send_count']} marta yuborilgan." if ad else "📭 Reklama o'rnatilmagan.")


# ======================== Majburiy obuna admin ========================
async def add_mandatory(update: Update, context: CallbackContext):
    if update.effective_user.id != ADMIN_ID:
        return
    args = context.args
    if len(args) < 3:
        await update.message.reply_text("Ishlatish: /add_mandatory <type> <identifier> <limit>\n\nTurlar: telegram, group, bot, youtube, instagram, website\n\nMasalan:\n/add_mandatory telegram @kino_kanal 5000\n/add_mandatory telegram -1001234567890 5000")
        return
    sub_type, identifier, limit = args[0], args[1], int(args[2])
    if sub_type not in ["telegram", "group", "bot", "youtube", "instagram", "website"]:
        await update.message.reply_text("❌ Tur noto'g'ri.")
        return
    await add_mandatory_subscription(sub_type, identifier, limit)
    await update.message.reply_text(f"✅ Qo'shildi: {sub_type} | {identifier} | limit: {limit}")

async def remove_mandatory(update: Update, context: CallbackContext):
    if update.effective_user.id != ADMIN_ID or not context.args:
        return
    await remove_mandatory_subscription(int(context.args[0]))
    await update.message.reply_text(f"✅ ID {context.args[0]} o'chirildi.")

async def list_mandatory(update: Update, context: CallbackContext):
    if update.effective_user.id != ADMIN_ID:
        return
    rows = await list_mandatory_subscriptions()
    if not rows:
        await update.message.reply_text("Hech qanday majburiy obuna yo'q.")
        return
    text = "📋 Majburiy obunalar:\n\n"
    for r in rows:
        status = "✅ faol" if r["is_active"] else "❌ faol emas"
        text += f"ID {r['id']}: {r['type']} | {r['identifier']}\n  Limit: {r['limit_count']} | Bajargan: {r['current_count']} | {status}\n\n"
    await update.message.reply_text(text[:4000])


# ======================== Kod yuborish ========================
async def handle_code(update: Update, context: CallbackContext):
    if await check_and_handle_mandatory_subs(update, context):
        return
    text = update.message.text.strip()
    if not text.isdigit():
        await update.message.reply_text("🤔 Iltimos, faqat raqamlardan iborat kod yuboring.")
        return
    video = await get_video(text)
    if video:
        file_id, description = video
        caption = f"🎬 Kodi: {text}\n📖 {description}" if description else f"🎬 Kodi: {text}"
        await update.message.reply_video(video=file_id, caption=caption, supports_streaming=True, protect_content=True)
        await update.message.reply_text("📱 Instagram: https://instagram.com/Bear_uzb070\n📣 Kino kanal: @kino_boru")
        await send_ad(context.bot, update.effective_user.id)
    else:
        await update.message.reply_text(f"❌ {text} kodli video topilmadi.")


# ======================== Webhook ========================
async def webhook_handler(request: Request):
    data = await request.json()
    await bot_application.process_update(Update.de_json(data, bot_application.bot))
    return JSONResponse({"ok": True})

async def healthcheck(request: Request):
    return JSONResponse({"status": "ok"})

bot_application = None


# ======================== Main ========================
async def main():
    global bot_application
    await init_db()
    bot_application = Application.builder().token(BOT_TOKEN).build()

    pf = filters.ChatType.PRIVATE

    bot_application.add_handler(CommandHandler("start", start, filters=pf))
    bot_application.add_handler(CommandHandler("admin", admin, filters=pf))
    bot_application.add_handler(CommandHandler("stats", stats, filters=pf))
    bot_application.add_handler(CommandHandler("delvideo", delvideo, filters=pf))
    bot_application.add_handler(CommandHandler("list", listvideos, filters=pf))
    bot_application.add_handler(CommandHandler("refstats", refstats, filters=pf))
    bot_application.add_handler(CommandHandler("removead", removead, filters=pf))
    bot_application.add_handler(CommandHandler("adstats", adstats, filters=pf))
    bot_application.add_handler(CommandHandler("cancel", cancel, filters=pf))
    bot_application.add_handler(CommandHandler("add_mandatory", add_mandatory, filters=pf))
    bot_application.add_handler(CommandHandler("remove_mandatory", remove_mandatory, filters=pf))
    bot_application.add_handler(CommandHandler("list_mandatory", list_mandatory, filters=pf))
    bot_application.add_handler(CallbackQueryHandler(confirm_all_subs_callback, pattern="^confirm_all_subs$"))

    bot_application.add_handler(ConversationHandler(
        entry_points=[CommandHandler("addvideo", addvideo_start, filters=pf)],
        states={
            WAITING_FOR_VIDEO: [MessageHandler(filters.VIDEO & pf, addvideo_video)],
            WAITING_FOR_CUSTOM_CODE: [MessageHandler(filters.TEXT & ~filters.COMMAND & pf, addvideo_custom_code)],
            WAITING_FOR_DESCRIPTION: [
                CommandHandler("skip", addvideo_skip, filters=pf),
                MessageHandler(filters.TEXT & ~filters.COMMAND & pf, addvideo_description)
            ]
        },
        fallbacks=[CommandHandler("cancel", cancel, filters=pf)]
    ))

    bot_application.add_handler(ConversationHandler(
        entry_points=[CommandHandler("broadcast", broadcast_start, filters=pf)],
        states={WAITING_BROADCAST: [MessageHandler(filters.ALL & ~filters.COMMAND & pf, broadcast_send)]},
        fallbacks=[CommandHandler("cancel", cancel, filters=pf)]
    ))

    bot_application.add_handler(ConversationHandler(
        entry_points=[CommandHandler("createref", createref_start, filters=pf)],
        states={WAITING_REF_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND & pf, createref_get_name)]},
        fallbacks=[CommandHandler("cancel", cancel, filters=pf)]
    ))

    bot_application.add_handler(ConversationHandler(
        entry_points=[CommandHandler("setad", setad_start, filters=pf)],
        states={WAITING_AD_CONTENT: [MessageHandler(filters.ALL & ~filters.COMMAND & pf, setad_get_content)]},
        fallbacks=[CommandHandler("cancel", cancel, filters=pf)]
    ))

    bot_application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND & pf, handle_code))

    await bot_application.initialize()
    await bot_application.bot.set_webhook(WEBHOOK_URL)

    app = Starlette(debug=False, routes=[
        Route(WEBHOOK_PATH, webhook_handler, methods=["POST"]),
        Route("/healthcheck", healthcheck, methods=["GET"]),
    ])

    print(f"✅ Bot ishga tushdi, webhook: {WEBHOOK_URL}")
    import uvicorn
    await uvicorn.Server(uvicorn.Config(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))).serve()


if __name__ == "__main__":
    asyncio.run(main())
