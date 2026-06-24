import os
import asyncio
import secrets
from datetime import datetime

from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.requests import Request
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler, filters,
    ConversationHandler, CallbackContext, CallbackQueryHandler
)
from telegram.error import TelegramError
from dotenv import load_dotenv

from config import BOT_TOKEN, ADMIN_ID
from database import (
    init_db, add_video, get_video, delete_video, list_all_videos,
    register_user_start, get_total_users, get_today_users,
    get_week_users, get_active_users_last_24h,
    get_all_user_ids, create_referral, check_referral_code, get_all_referrals,
    set_ad, get_ad, remove_ad, increment_ad_count,
    add_required_channel, remove_required_channel, get_all_required_channels
)

load_dotenv()

# -------------------- Holatlar --------------------
WAITING_FOR_VIDEO, WAITING_FOR_CUSTOM_CODE, WAITING_FOR_DESCRIPTION = range(3)
WAITING_BROADCAST = 3
WAITING_REF_NAME = 4
WAITING_AD_CONTENT = 5

# -------------------- Webhook --------------------
WEBHOOK_PATH = "/webhook"
RENDER_EXTERNAL_HOSTNAME = os.environ.get("RENDER_EXTERNAL_HOSTNAME")
if not RENDER_EXTERNAL_HOSTNAME:
    raise ValueError("RENDER_EXTERNAL_HOSTNAME topilmadi")
WEBHOOK_URL = f"https://{RENDER_EXTERNAL_HOSTNAME}{WEBHOOK_PATH}"

# -------------------- Reklama yuborish --------------------
async def send_ad(bot, chat_id):
    ad = await get_ad()
    if not ad:
        return
    content_type, file_id, text, caption, _ = ad
    try:
        if content_type == "text":
            await bot.send_message(chat_id=chat_id, text=text)
        elif content_type == "photo":
            await bot.send_photo(chat_id=chat_id, photo=file_id, caption=caption or "")
        elif content_type == "video":
            await bot.send_video(chat_id=chat_id, video=file_id, caption=caption or "")
        elif content_type == "document":
            await bot.send_document(chat_id=chat_id, document=file_id, caption=caption or "")
        elif content_type == "audio":
            await bot.send_audio(chat_id=chat_id, audio=file_id, caption=caption or "")
        elif content_type == "voice":
            await bot.send_voice(chat_id=chat_id, voice=file_id, caption=caption or "")
        elif content_type == "animation":
            await bot.send_animation(chat_id=chat_id, animation=file_id, caption=caption or "")
        else:
            return
        await increment_ad_count()
    except Exception as e:
        print(f"Reklama yuborishda xatolik: {e}")

# -------------------- Obuna tizimi yordamchilari --------------------
async def is_subscribed_to_all(bot, user_id: int) -> bool:
    channels = await get_all_required_channels()
    if not channels:
        return True
    for ch in channels:
        try:
            member = await bot.get_chat_member(chat_id=ch, user_id=user_id)
            if member.status not in ("member", "administrator", "creator"):
                return False
        except TelegramError:
            return False
    return True

async def show_channels(update, context, channels):
    keyboard = []
    for ch in channels:
        url = f"https://t.me/{ch.lstrip('@')}"
        keyboard.append([InlineKeyboardButton(f"📢 {ch}", url=url)])
    keyboard.append([InlineKeyboardButton("✅ Obuna bo‘ldim", callback_data="check_sub")])

    await update.message.reply_text(
        "🔔 *Botdan foydalanish uchun quyidagi kanallarga obuna bo‘ling:*",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )

async def ask_subscription(update: Update, context: CallbackContext):
    channels = await get_all_required_channels()
    if not channels:
        return True
    context.user_data.pop("remaining_channels", None)
    await show_channels(update, context, channels)
    return False

# -------------------- Callback: Obuna tekshirish --------------------
async def check_sub_callback(update: Update, context: CallbackContext):
    query = update.callback_query
    await query.answer()

    await query.edit_message_text("⏳ Obuna tekshirilmoqda...")
    await asyncio.sleep(5)

    user_id = query.from_user.id
    bot = context.bot

    remaining = context.user_data.get("remaining_channels")
    if remaining is None:
        channels_to_check = await get_all_required_channels()
    else:
        current_all = await get_all_required_channels()
        valid_remaining = [ch for ch in remaining if ch in current_all]
        if len(valid_remaining) != len(remaining):
            channels_to_check = current_all
            context.user_data.pop("remaining_channels", None)
        else:
            channels_to_check = valid_remaining

    not_subscribed = []
    for ch in channels_to_check:
        try:
            member = await bot.get_chat_member(chat_id=ch, user_id=user_id)
            if member.status not in ("member", "administrator", "creator"):
                not_subscribed.append(ch)
        except TelegramError:
            not_subscribed.append(ch)

    if not not_subscribed:
        await query.edit_message_text("✅ Obuna tasdiqlandi! Botdan foydalanishingiz mumkin.")
        context.user_data.pop("remaining_channels", None)

        pending_code = context.user_data.pop("pending_code", None)
        if pending_code:
            await context.bot.send_message(
                chat_id=user_id,
                text=f"✅ Obuna tasdiqlandi! Kodni qayta yuborishingiz mumkin: `{pending_code}`",
                parse_mode="Markdown"
            )
        else:
            await context.bot.send_message(
                chat_id=user_id,
                text="✅ Obuna tasdiqlandi! Endi botdan foydalanishingiz mumkin."
            )
    else:
        context.user_data["remaining_channels"] = not_subscribed
        await query.delete_message()
        keyboard = []
        for ch in not_subscribed:
            url = f"https://t.me/{ch.lstrip('@')}"
            keyboard.append([InlineKeyboardButton(f"📢 {ch}", url=url)])
        keyboard.append([InlineKeyboardButton("✅ Obuna bo‘ldim", callback_data="check_sub")])

        await context.bot.send_message(
            chat_id=user_id,
            text="❌ Siz hali quyidagi kanallarga obuna bo‘lmadingiz:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

# -------------------- Start --------------------
async def start(update: Update, context: CallbackContext):
    user_id = update.effective_user.id
    context.user_data.pop("remaining_channels", None)

    # Obuna tekshiruvi
    if user_id != ADMIN_ID and not await is_subscribed_to_all(context.bot, user_id):
        await ask_subscription(update, context)
        return

    referral_code = context.args[0] if context.args else None
    await register_user_start(user_id, referral_code)
    await update.message.reply_text(
        "🎬 **Kino botiga xush kelibsiz!**\n"
        "📣 Kino kanalimiz: @mega\\_kino\\_n1\n\n"
        "Film kodini raqamlarda yuboring.\n"
        "Admin: /admin",
        parse_mode="Markdown"
    )
    await send_ad(context.bot, user_id)

# -------------------- Admin panel --------------------
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
        "/broadcast - obunachilarga xabar\n"
        "/createref - referal havola yaratish\n"
        "/refstats - referallar statistikasi\n"
        "/setad - start/kino reklama o'rnatish\n"
        "/removead - reklamani o'chirish\n"
        "/adstats - reklama statistikasi\n"
        "/addchannel <@kanal> - majburiy kanal qo'shish\n"
        "/removechannel <@kanal> - majburiy kanalni o'chirish\n"
        "/listchannels - majburiy kanallar ro'yxati",
        parse_mode="Markdown"
    )

# -------------------- Statistika --------------------
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

# -------------------- Broadcast --------------------
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
    asyncio.create_task(
        _broadcast_task(msg=msg, progress_msg=progress_msg, user_ids=user_ids, total=total)
    )
    return ConversationHandler.END

async def _broadcast_task(msg, progress_msg, user_ids, total):
    semaphore = asyncio.Semaphore(25)
    async def send_to_user(uid):
        async with semaphore:
            try:
                await msg.copy(chat_id=uid)
            except Exception:
                pass
    tasks = [asyncio.create_task(send_to_user(uid)) for uid in user_ids]
    await asyncio.gather(*tasks)
    await progress_msg.edit_text(f"✅ Xabar {total} ta foydalanuvchiga yuborildi.")

# -------------------- Video qo'shish --------------------
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

# -------------------- Video o'chirish / ro'yxat --------------------
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

# -------------------- Referal tizimi --------------------
async def createref_start(update: Update, context: CallbackContext):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⛔ Siz admin emassiz!")
        return ConversationHandler.END
    await update.message.reply_text("🔗 Referal uchun nom bering (masalan, 'instagram'):")
    return WAITING_REF_NAME

async def createref_get_name(update: Update, context: CallbackContext):
    if update.effective_user.id != ADMIN_ID:
        return ConversationHandler.END
    name = update.message.text.strip()
    if not name:
        await update.message.reply_text("❌ Iltimos, bo‘sh bo‘lmagan nom kiriting.")
        return WAITING_REF_NAME

    bot_username = "KINO_bor_botbot"
    while True:
        code = secrets.token_hex(3)
        if not await check_referral_code(code):
            break
    await create_referral(name, code)
    link = f"https://t.me/{bot_username}?start={code}"
    await update.message.reply_text(
        f"✅ **Yangi referal havola yaratildi**\n\n"
        f"📌 Nomi: `{name}`\n"
        f"🔗 Havola: {link}\n"
        f"🆔 Kod: `{code}`",
        parse_mode="Markdown"
    )
    return ConversationHandler.END

async def refstats(update: Update, context: CallbackContext):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⛔ Ruxsat yo‘q")
        return
    referrals = await get_all_referrals()
    if not referrals:
        await update.message.reply_text("📭 Hali hech qanday referal havola yo‘q.")
        return
    text = "📊 **Referallar statistikasi**\n\n"
    for code, name, count in referrals:
        text += f"• `{name}` (kod: `{code}`) – {count} ta foydalanuvchi\n"
    await update.message.reply_text(text, parse_mode="Markdown")

# -------------------- Reklama tizimi --------------------
async def setad_start(update: Update, context: CallbackContext):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⛔ Siz admin emassiz!")
        return ConversationHandler.END
    await update.message.reply_text(
        "📢 Reklama sifatida yubormoqchi bo'lgan kontentni yuboring.\n"
        "Matn, rasm, video, hujjat, audio, animatsiya — ixtiyoriy.\n"
        "/cancel – bekor qilish"
    )
    return WAITING_AD_CONTENT

async def setad_get_content(update: Update, context: CallbackContext):
    if update.effective_user.id != ADMIN_ID:
        return ConversationHandler.END
    msg = update.message
    content_type = None
    file_id = None
    text = None
    caption = msg.caption or ""

    if msg.text and not msg.caption:
        content_type = "text"
        text = msg.text
    elif msg.photo:
        content_type = "photo"
        file_id = msg.photo[-1].file_id
    elif msg.video:
        content_type = "video"
        file_id = msg.video.file_id
    elif msg.document:
        content_type = "document"
        file_id = msg.document.file_id
    elif msg.audio:
        content_type = "audio"
        file_id = msg.audio.file_id
    elif msg.voice:
        content_type = "voice"
        file_id = msg.voice.file_id
    elif msg.animation:
        content_type = "animation"
        file_id = msg.animation.file_id
    else:
        await update.message.reply_text("❌ Ushbu kontent turi qo'llab-quvvatlanmaydi. Boshqa narsa yuboring.")
        return WAITING_AD_CONTENT

    await set_ad(content_type, file_id, text, caption)
    await update.message.reply_text(
        f"✅ Reklama saqlandi!\n"
        f"Turi: {content_type}\n"
        f"Endi har bir /start va kino kodidan keyin avtomatik yuboriladi.",
        parse_mode="Markdown"
    )
    return ConversationHandler.END

async def removead(update: Update, context: CallbackContext):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⛔ Ruxsat yo‘q")
        return
    await remove_ad()
    await update.message.reply_text("🗑️ Reklama o'chirildi. Endi start va kodlardan keyin ko'rsatilmaydi.")

async def adstats(update: Update, context: CallbackContext):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⛔ Ruxsat yo‘q")
        return
    ad = await get_ad()
    if ad:
        count = ad[4]  # send_count
        await update.message.reply_text(f"📊 Reklama {count} marta yuborilgan.")
    else:
        await update.message.reply_text("📭 Hozirda hech qanday reklama o‘rnatilmagan.")

# -------------------- Majburiy kanal boshqaruvi (admin) --------------------
async def addchannel(update: Update, context: CallbackContext):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⛔ Siz admin emassiz!")
        return
    if not context.args:
        await update.message.reply_text("❌ Iltimos, kanal username kiriting: /addchannel @kanal")
        return
    username = context.args[0]
    if not username.startswith("@"):
        username = "@" + username
    await add_required_channel(username)
    await update.message.reply_text(f"✅ {username} majburiy kanallar ro‘yxatiga qo‘shildi.")

async def removechannel(update: Update, context: CallbackContext):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⛔ Siz admin emassiz!")
        return
    if not context.args:
        await update.message.reply_text("❌ Iltimos, kanal username kiriting: /removechannel @kanal")
        return
    username = context.args[0]
    if not username.startswith("@"):
        username = "@" + username
    await remove_required_channel(username)
    await update.message.reply_text(f"🗑️ {username} majburiy kanallar ro‘yxatidan o‘chirildi.")

async def listchannels(update: Update, context: CallbackContext):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⛔ Siz admin emassiz!")
        return
    channels = await get_all_required_channels()
    if channels:
        text = "📋 *Majburiy kanallar:*\n" + "\n".join(f"• {ch}" for ch in channels)
    else:
        text = "📭 Hozircha hech qanday kanal majburiy emas."
    await update.message.reply_text(text, parse_mode="Markdown")

# -------------------- Kod yuborish (video + havolalar + reklama) --------------------
async def handle_code(update: Update, context: CallbackContext):
    user_id = update.effective_user.id
    context.user_data.pop("remaining_channels", None)

    # Obuna tekshiruvi
    if user_id != ADMIN_ID and not await is_subscribed_to_all(context.bot, user_id):
        context.user_data["pending_code"] = update.message.text
        await ask_subscription(update, context)
        return

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
            return
        links_msg = (
            "📱 Instagram: https://instagram.com/mega_kino_n1\n"
            "📣 Kino kanal: @mega_kino_n1"
        )
        await update.message.reply_text(links_msg)
        await send_ad(context.bot, user_id)
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

    # Handlerlar
    bot_application.add_handler(CommandHandler("start", start))
    bot_application.add_handler(CommandHandler("admin", admin))
    bot_application.add_handler(CommandHandler("stats", stats))
    bot_application.add_handler(CommandHandler("delvideo", delvideo))
    bot_application.add_handler(CommandHandler("list", listvideos))
    bot_application.add_handler(CommandHandler("refstats", refstats))
    bot_application.add_handler(CommandHandler("removead", removead))
    bot_application.add_handler(CommandHandler("adstats", adstats))
    bot_application.add_handler(CommandHandler("cancel", cancel))
    bot_application.add_handler(CommandHandler("addchannel", addchannel))
    bot_application.add_handler(CommandHandler("removechannel", removechannel))
    bot_application.add_handler(CommandHandler("listchannels", listchannels))

    # Video qo'shish
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

    # Broadcast
    broadcast_conv = ConversationHandler(
        entry_points=[CommandHandler("broadcast", broadcast_start)],
        states={
            WAITING_BROADCAST: [MessageHandler(filters.ALL & ~filters.COMMAND, broadcast_send)]
        },
        fallbacks=[CommandHandler("cancel", cancel)]
    )
    bot_application.add_handler(broadcast_conv)

    # Referal yaratish
    ref_conv = ConversationHandler(
        entry_points=[CommandHandler("createref", createref_start)],
        states={
            WAITING_REF_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, createref_get_name)]
        },
        fallbacks=[CommandHandler("cancel", cancel)]
    )
    bot_application.add_handler(ref_conv)

    # Reklama o'rnatish
    ad_conv = ConversationHandler(
        entry_points=[CommandHandler("setad", setad_start)],
        states={
            WAITING_AD_CONTENT: [MessageHandler(filters.ALL & ~filters.COMMAND, setad_get_content)]
        },
        fallbacks=[CommandHandler("cancel", cancel)]
    )
    bot_application.add_handler(ad_conv)

    # Obuna callback
    bot_application.add_handler(CallbackQueryHandler(check_sub_callback, pattern="check_sub"))

    # Kod qabul qilish (oddiy matn)
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
