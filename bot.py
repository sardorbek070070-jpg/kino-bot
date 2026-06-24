import os
import asyncio
import secrets
import re
import logging
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
    add_mandatory_subscription, remove_mandatory_subscription, list_mandatory_subscriptions
)

load_dotenv()

# Logging sozlash
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

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

# -------------------- Yordamchi funksiyalar --------------------
def extract_telegram_username(identifier: str) -> str:
    """Telegram identifikatoridan sof usernameni ajratib oladi."""
    match = re.search(r'(?:https?://)?(?:t\.me/)([a-zA-Z0-9_]+)', identifier)
    if match:
        return match.group(1)
    if identifier.startswith("@"):
        return identifier[1:]
    return identifier

async def check_telegram_membership(bot, user_id: int, chat_identifier: str) -> bool:
    """Foydalanuvchi Telegram kanal/chat a'zoligini tekshiradi."""
    username = extract_telegram_username(chat_identifier)
    if not username:
        logger.warning(f"Yaroqsiz Telegram identifikatori: {chat_identifier}")
        return False
    try:
        member = await bot.get_chat_member(chat_id=username, user_id=user_id)
        return member.status in ["member", "administrator", "creator"]
    except Exception as e:
        logger.error(f"Telegram a'zolik tekshiruvi xatosi: {e}")
        return False

# -------------------- Reklama yuborish (eski reklama o'chiriladi) --------------------
async def send_ad(bot, chat_id: int, context: CallbackContext = None):
    """Reklamani yuboradi. Eski reklama xabarini o'chiradi."""
    ad = await get_ad()
    if not ad:
        return
    content_type = ad["content_type"]
    file_id = ad["file_id"]
    text = ad["text"]
    caption = ad["caption"] or ""

    # Eski reklama xabarini o'chirish
    if context and "ad_msg_id" in context.user_data:
        old_id = context.user_data.pop("ad_msg_id", None)
        if old_id:
            try:
                await bot.delete_message(chat_id=chat_id, message_id=old_id)
            except Exception:
                pass

    try:
        if content_type == "text":
            msg = await bot.send_message(chat_id=chat_id, text=text)
        elif content_type == "photo":
            msg = await bot.send_photo(chat_id=chat_id, photo=file_id, caption=caption)
        elif content_type == "video":
            msg = await bot.send_video(chat_id=chat_id, video=file_id, caption=caption)
        elif content_type == "document":
            msg = await bot.send_document(chat_id=chat_id, document=file_id, caption=caption)
        elif content_type == "audio":
            msg = await bot.send_audio(chat_id=chat_id, audio=file_id, caption=caption)
        elif content_type == "voice":
            msg = await bot.send_voice(chat_id=chat_id, voice=file_id, caption=caption)
        elif content_type == "animation":
            msg = await bot.send_animation(chat_id=chat_id, animation=file_id, caption=caption)
        else:
            return
        if context:
            context.user_data["ad_msg_id"] = msg.message_id
        await increment_ad_count()
    except Exception as e:
        logger.error(f"Reklama yuborishda xatolik: {e}")

# -------------------- Majburiy obuna interfeysi --------------------
async def show_mandatory_subs(update: Update, context: CallbackContext) -> bool:
    user_id = update.effective_user.id
    subs = await get_active_mandatory_subs()
    if not subs:
        return True

    incomplete = []
    for sub in subs:
        if sub["type"] != "telegram":
            logger.warning(f"Qo'llab-quvvatlanmaydigan tur: {sub['type']} (ID: {sub['id']})")
            continue
        if not await is_user_completed_sub(user_id, sub["id"]):
            incomplete.append(sub)

    if not incomplete:
        return True

    # Eski asosiy menyu xabarini o'chirish
    main_id = context.user_data.pop("main_msg_id", None)
    if main_id:
        try:
            await context.bot.delete_message(chat_id=user_id, message_id=main_id)
        except Exception:
            pass

    text = "🎬 Botdan foydalanish uchun quyidagi kanallarga a'zo bo'lishingiz kerak:\n\n"
    url_buttons = []
    for idx, sub in enumerate(incomplete, start=1):
        username = extract_telegram_username(sub["identifier"])
        url = f"https://t.me/{username}" if username else sub["identifier"]
        url_buttons.append([InlineKeyboardButton(f"{idx}-kanal", url=url)])

    confirm_button = [[InlineKeyboardButton("✅ Obunani tasdiqlash", callback_data="confirm_all_subs")]]
    reply_markup = InlineKeyboardMarkup(url_buttons + confirm_button)

    # Eski majburiy obuna xabarini o'chirish
    old_mandatory = context.user_data.pop("mandatory_msg_id", None)
    if old_mandatory:
        try:
            await context.bot.delete_message(chat_id=user_id, message_id=old_mandatory)
        except Exception:
            pass

    chat_id = update.effective_chat.id
    sent_msg = await context.bot.send_message(
        chat_id=chat_id,
        text=text,
        reply_markup=reply_markup
    )
    context.user_data["mandatory_msg_id"] = sent_msg.message_id
    return False

# -------------------- Callback: barcha obunalarni tasdiqlash --------------------
async def confirm_all_subs_callback(update: Update, context: CallbackContext):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id

    subs = await get_active_mandatory_subs()
    incomplete = []
    for sub in subs:
        if sub["type"] != "telegram":
            continue
        if not await is_user_completed_sub(user_id, sub["id"]):
            incomplete.append(sub)

    if not incomplete:
        await query.edit_message_text("Siz barcha obunalarni avval tasdiqlagansiz.")
        await start_after_subs(update, context)
        return

    failed = []
    for sub in incomplete:
        username = extract_telegram_username(sub["identifier"])
        if not username:
            failed.append(sub["identifier"])
            continue
        member = await check_telegram_membership(context.bot, user_id, username)
        if not member:
            failed.append(sub["identifier"])

    if failed:
        await query.edit_message_text(
            f"❌ Siz quyidagi Telegram kanal(lar)ga a'zo emassiz:\n" + "\n".join(failed) +
            "\n\nIltimos, a'zo bo'ling va qayta urining."
        )
        return

    deactivated_any = False
    for sub in incomplete:
        deactivated = await mark_user_completed_sub(user_id, sub["id"])
        if deactivated:
            deactivated_any = True

    await query.edit_message_text("✅ Tabriklaymiz! Siz barcha majburiy obunalarni bajardingiz. Endi botdan to‘liq foydalanishingiz mumkin.")
    context.user_data.pop("mandatory_msg_id", None)

    if deactivated_any:
        await context.bot.send_message(
            chat_id=ADMIN_ID,
            text="⚠️ Bir yoki bir nechta majburiy obuna o‘z limitiga yetdi va avtomatik o‘chirildi."
        )

    await start_after_subs(update, context)

# -------------------- Startdan keyingi asosiy menyu (TAHRIRLANADI) --------------------
async def start_after_subs(update: Update, context: CallbackContext):
    """Asosiy menyuni ko'rsatadi, eski xabarni tahrirlaydi yoki yangisini yuboradi."""
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id

    # Majburiy obuna xabarini o'chirish
    mandatory_id = context.user_data.pop("mandatory_msg_id", None)
    if mandatory_id:
        try:
            await context.bot.delete_message(chat_id=user_id, message_id=mandatory_id)
        except Exception:
            pass

    # Asosiy menyu matni
    text = (
        "🎬 Kino botiga xush kelibsiz!\n"
        "📣 Kino kanalimiz: @kino_boru\n\n"
        "Film kodini raqamlarda yuboring.\n"
        "Admin: /admin"
    )

    # Eski asosiy menyu xabarini tahrirlash yoki yangi yuborish
    main_id = context.user_data.get("main_msg_id")
    if main_id:
        try:
            await context.bot.edit_message_text(
                chat_id=user_id,
                message_id=main_id,
                text=text
            )
        except Exception:
            try:
                await context.bot.delete_message(chat_id=user_id, message_id=main_id)
            except Exception:
                pass
            sent_msg = await context.bot.send_message(chat_id=chat_id, text=text)
            context.user_data["main_msg_id"] = sent_msg.message_id
    else:
        sent_msg = await context.bot.send_message(chat_id=chat_id, text=text)
        context.user_data["main_msg_id"] = sent_msg.message_id

    # Reklama yuborish (eski reklama xabarini o'chiradi)
    await send_ad(context.bot, user_id, context)

# -------------------- Start --------------------
async def start(update: Update, context: CallbackContext):
    user_id = update.effective_user.id
    referral_code = context.args[0] if context.args else None
    await register_user_start(user_id, referral_code)

    # Eski xabarlarni tozalash
    for key in ["mandatory_msg_id", "main_msg_id", "ad_msg_id"]:
        msg_id = context.user_data.pop(key, None)
        if msg_id:
            try:
                await context.bot.delete_message(chat_id=user_id, message_id=msg_id)
            except Exception:
                pass

    all_subs = await get_active_mandatory_subs()
    telegram_subs = [s for s in all_subs if s["type"] == "telegram"]
    if not telegram_subs:
        await start_after_subs(update, context)
        return

    completed_ids = []
    for sub in telegram_subs:
        if await is_user_completed_sub(user_id, sub["id"]):
            completed_ids.append(sub["id"])

    if len(completed_ids) == len(telegram_subs):
        await start_after_subs(update, context)
        return

    await show_mandatory_subs(update, context)

# -------------------- Admin panel --------------------
async def admin(update: Update, context: CallbackContext):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⛔️ Siz admin emassiz!")
        return
    await update.message.reply_text(
        "<b>🔧 Admin panel</b>\n"
        "/addvideo - yangi video qo'shish\n"
        "/delvideo &lt;kod&gt; - o'chirish\n"
        "/list - barcha videolar\n"
        "/stats - statistika\n"
        "/broadcast - obunachilarga xabar\n"
        "/createref - referal havola yaratish\n"
        "/refstats - referallar statistikasi\n"
        "/setad - start/kino reklama o'rnatish\n"
        "/removead - reklamani o'chirish\n"
        "/adstats - reklama statistikasi\n\n"
        "<b>📛 Majburiy obuna</b>\n"
        "/add_mandatory &lt;type&gt; &lt;identifier&gt; &lt;limit&gt;\n"
        "/remove_mandatory &lt;id&gt;\n"
        "/list_mandatory",
        parse_mode="HTML"
    )

# -------------------- Statistika --------------------
async def stats(update: Update, context: CallbackContext):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⛔️ Siz admin emassiz!")
        return
    total = await get_total_users()
    today = await get_today_users()
    week = await get_week_users()
    active = await get_active_users_last_24h()
    await update.message.reply_text(
        f"📊 Statistika\n\n"
        f"👥 Umumiy: {total}\n"
        f"🆕 Bugun: {today}\n"
        f"📅 7 kunda: {week}\n"
        f"🟢 24 soatda faol: {active}"
    )

# -------------------- Broadcast --------------------
async def broadcast_start(update: Update, context: CallbackContext):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⛔️ Siz admin emassiz!")
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
    asyncio.create_task(_broadcast_task(msg, progress_msg, user_ids, total))
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
        await update.message.reply_text("⛔️ Ruxsat yo‘q")
        return ConversationHandler.END
    await update.message.reply_text("📹 Videoni yuboring (fayl sifatida)")
    return WAITING_FOR_VIDEO

async def addvideo_video(update: Update, context: CallbackContext):
    if not update.message.video:
        await update.message.reply_text("❌ Iltimos, video fayl yuboring")
        return WAITING_FOR_VIDEO
    file_id = update.message.video.file_id
    context.user_data['file_id'] = file_id
    await update.message.reply_text("🔢 Ushbu video uchun kod kiriting (faqat raqamlar):")
    return WAITING_FOR_CUSTOM_CODE

async def addvideo_custom_code(update: Update, context: CallbackContext):
    code = update.message.text.strip()
    if not code.isdigit():
        await update.message.reply_text("❌ Kod faqat raqamlardan iborat bo‘lishi kerak. Qaytadan kiriting:")
        return WAITING_FOR_CUSTOM_CODE
    existing = await get_video(code)
    if existing:
        await update.message.reply_text(f"⚠️ {code} kodi allaqachon mavjud. Boshqa kod kiriting:")
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
    await update.message.reply_text(f"✅ Video saqlandi!\nKod: {code}\nTavsif: {description}")
    context.user_data.clear()
    return ConversationHandler.END

async def addvideo_skip(update: Update, context: CallbackContext):
    file_id = context.user_data.get('file_id')
    code = context.user_data.get('code')
    if not file_id or not code:
        await update.message.reply_text("Xatolik, qaytadan /addvideo bosing")
        return ConversationHandler.END
    await add_video(code, file_id, "")
    await update.message.reply_text(f"✅ Video saqlandi!\nKod: {code}\nTavsifsiz")
    context.user_data.clear()
    return ConversationHandler.END

async def cancel(update: Update, context: CallbackContext):
    await update.message.reply_text("Bekor qilindi.")
    return ConversationHandler.END

# -------------------- Video o'chirish --------------------
async def delvideo(update: Update, context: CallbackContext):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⛔️ Ruxsat yo‘q")
        return
    if not context.args:
        await update.message.reply_text("📛 Kodni kiriting: /delvideo 123")
        return
    code = context.args[0]
    video = await get_video(code)
    if video:
        await delete_video(code)
        await update.message.reply_text(f"✅ {code} o‘chirildi.")
    else:
        await update.message.reply_text(f"❌ {code} topilmadi.")

async def listvideos(update: Update, context: CallbackContext):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⛔️ Ruxsat yo‘q")
        return
    videos = await list_all_videos()
    if not videos:
        await update.message.reply_text("📭 Hech qanday video yo‘q.")
        return
    text = "📋 Barcha videolar:\n"
    for code, desc in videos:
        line = f"🔹 Kod: {code} — {desc or 'Tavsifsiz'}\n"
        if len(text) + len(line) > 4000:
            await update.message.reply_text(text)
            text = ""
        text += line
    if text:
        await update.message.reply_text(text)

# -------------------- Referal tizimi --------------------
async def createref_start(update: Update, context: CallbackContext):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⛔️ Siz admin emassiz!")
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
    bot_username = context.bot.username
    if not bot_username:
        await update.message.reply_text("❌ Bot username topilmadi.")
        return ConversationHandler.END
    while True:
        code = secrets.token_hex(3)
        if not await check_referral_code(code):
            break
    await create_referral(name, code)
    link = f"https://t.me/{bot_username}?start={code}"
    await update.message.reply_text(
        f"✅ Yangi referal havola yaratildi\n\n"
        f"📌 Nomi: {name}\n"
        f"🔗 Havola: {link}\n"
        f"🆔 Kod: {code}"
    )
    return ConversationHandler.END

async def refstats(update: Update, context: CallbackContext):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⛔️ Ruxsat yo‘q")
        return
    referrals = await get_all_referrals()
    if not referrals:
        await update.message.reply_text("📭 Hali hech qanday referal havola yo‘q.")
        return
    text = "📊 Referallar statistikasi\n\n"
    for code, name, count in referrals:
        line = f"• {name} (kod: {code}) – {count} ta foydalanuvchi\n"
        if len(text) + len(line) > 4000:
            await update.message.reply_text(text)
            text = ""
        text += line
    if text:
        await update.message.reply_text(text)

# -------------------- Reklama tizimi --------------------
async def setad_start(update: Update, context: CallbackContext):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⛔️ Siz admin emassiz!")
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
        f"Endi har bir /start va kino kodidan keyin avtomatik yuboriladi."
    )
    return ConversationHandler.END

async def removead(update: Update, context: CallbackContext):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⛔️ Ruxsat yo‘q")
        return
    await remove_ad()
    await update.message.reply_text("🗑 Reklama o'chirildi. Endi start va kodlardan keyin ko'rsatilmaydi.")

async def adstats(update: Update, context: CallbackContext):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⛔️ Ruxsat yo‘q")
        return
    ad = await get_ad()
    if ad:
        count = ad["send_count"]
        await update.message.reply_text(f"📊 Reklama {count} marta yuborilgan.")
    else:
        await update.message.reply_text("📭 Hozirda hech qanday reklama o‘rnatilmagan.")

# -------------------- Majburiy obuna admin buyruqlari --------------------
async def add_mandatory(update: Update, context: CallbackContext):
    if update.effective_user.id != ADMIN_ID:
        return
    args = context.args
    if len(args) < 3:
        await update.message.reply_text("Ishlatish: /add_mandatory <type> <identifier> <limit>\nMasalan: /add_mandatory telegram @my_channel 2000")
        return
    sub_type, identifier, limit_str = args[0], args[1], args[2]
    if sub_type not in ("telegram", "youtube", "instagram"):
        await update.message.reply_text("❌ type faqat: telegram, youtube, instagram")
        return
    if sub_type != "telegram":
        await update.message.reply_text("⚠️ Hozircha faqat 'telegram' turi qo'llab-quvvatlanadi. Boshqa turlar uchun tekshiruv mavjud emas.")
        return
    try:
        limit = int(limit_str)
    except ValueError:
        await update.message.reply_text("❌ Limit son bo‘lishi kerak!")
        return
    await add_mandatory_subscription(sub_type, identifier, limit)
    await update.message.reply_text(f"✅ Qo‘shildi: {sub_type} – {identifier} (limit {limit})")

async def remove_mandatory(update: Update, context: CallbackContext):
    if update.effective_user.id != ADMIN_ID:
        return
    if not context.args:
        await update.message.reply_text("Ishlatish: /remove_mandatory <id>")
        return
    try:
        sub_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ ID son bo‘lishi kerak!")
        return
    await remove_mandatory_subscription(sub_id)
    await update.message.reply_text(f"✅ ID {sub_id} o‘chirildi.")

async def list_mandatory(update: Update, context: CallbackContext):
    if update.effective_user.id != ADMIN_ID:
        return
    rows = await list_mandatory_subscriptions()
    if not rows:
        await update.message.reply_text("Hech qanday majburiy obuna yo‘q.")
        return
    text = "📋 Majburiy obunalar:\n"
    for row in rows:
        line = (f"ID {row['id']}: {row['type']} {row['identifier']} | "
                f"limit {row['limit_count']} | hozir {row['current_count']} | "
                f"{'✅ faol' if row['is_active'] else '❌ faol emas'}\n")
        if len(text) + len(line) > 4000:
            await update.message.reply_text(text)
            text = ""
        text += line
    if text:
        await update.message.reply_text(text)

# -------------------- Kod yuborish --------------------
async def handle_code(update: Update, context: CallbackContext):
    user_id = update.effective_user.id

    all_subs = await get_active_mandatory_subs()
    telegram_subs = [s for s in all_subs if s["type"] == "telegram"]
    if telegram_subs:
        incomplete = []
        for sub in telegram_subs:
            if not await is_user_completed_sub(user_id, sub["id"]):
                incomplete.append(sub)
        if incomplete:
            try:
                await update.message.delete()
            except Exception:
                pass
            await show_mandatory_subs(update, context)
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
            logger.error(f"Video yuborish xatosi: {e}")
            await context.bot.send_message(chat_id=ADMIN_ID, text=f"Video yuborish xatosi: {e}")
            await update.message.reply_text("❌ Video yuborishda xatolik yuz berdi.")
            return
        links_msg = (
            "📱 Instagram: https://instagram.com/Bear_uzb070\n"
            "📣 Kino kanal: @kino_boru"
        )
        await update.message.reply_text(links_msg)
        await send_ad(context.bot, user_id, context)
    else:
        await update.message.reply_text(f"❌ {text} kodli video topilmadi.")

# -------------------- Webhook handlerlar (main dan oldin) --------------------
async def webhook_handler(request: Request):
    data = await request.json()
    update = Update.de_json(data, bot_application.bot)
    await bot_application.process_update(update)
    return JSONResponse({"ok": True})

async def healthcheck(request: Request):
    return JSONResponse({"status": "ok"})

# -------------------- Asosiy ishga tushirish --------------------
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
    bot_application.add_handler(CommandHandler("refstats", refstats))
    bot_application.add_handler(CommandHandler("removead", removead))
    bot_application.add_handler(CommandHandler("adstats", adstats))
    bot_application.add_handler(CommandHandler("cancel", cancel))

    bot_application.add_handler(CommandHandler("add_mandatory", add_mandatory))
    bot_application.add_handler(CommandHandler("remove_mandatory", remove_mandatory))
    bot_application.add_handler(CommandHandler("list_mandatory", list_mandatory))
    bot_application.add_handler(CallbackQueryHandler(confirm_all_subs_callback, pattern="^confirm_all_subs$"))

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

    broadcast_conv = ConversationHandler(
        entry_points=[CommandHandler("broadcast", broadcast_start)],
        states={
            WAITING_BROADCAST: [MessageHandler(filters.ALL & ~filters.COMMAND, broadcast_send)]
        },
        fallbacks=[CommandHandler("cancel", cancel)]
    )
    bot_application.add_handler(broadcast_conv)

    ref_conv = ConversationHandler(
        entry_points=[CommandHandler("createref", createref_start)],
        states={
            WAITING_REF_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, createref_get_name)]
        },
        fallbacks=[CommandHandler("cancel", cancel)]
    )
    bot_application.add_handler(ref_conv)

    ad_conv = ConversationHandler(
        entry_points=[CommandHandler("setad", setad_start)],
        states={
            WAITING_AD_CONTENT: [MessageHandler(filters.ALL & ~filters.COMMAND, setad_get_content)]
        },
        fallbacks=[CommandHandler("cancel", cancel)]
    )
    bot_application.add_handler(ad_conv)

    bot_application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_code))

    await bot_application.initialize()
    await bot_application.bot.set_webhook(WEBHOOK_URL)

    starlette_app = Starlette(debug=False, routes=[
        Route(WEBHOOK_PATH, webhook_handler, methods=["POST"]),
        Route("/healthcheck", healthcheck, methods=["GET"]),
        Route("/", healthcheck, methods=["GET", "HEAD"]),
    ])

    port = int(os.environ.get("PORT", 8080))
    logger.info(f"✅ Bot ishga tushdi, webhook: {WEBHOOK_URL}")
    import uvicorn
    config = uvicorn.Config(starlette_app, host="0.0.0.0", port=port, log_level="info")
    server = uvicorn.Server(config)
    await server.serve()

if __name__ == "__main__":
    asyncio.run(main())
