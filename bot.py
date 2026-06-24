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

# -------------------- Reklama yuborish (tahrirlash qo'shildi) --------------------
async def send_ad(bot, chat_id: int, context: CallbackContext = None):
    """Reklamani yuboradi va statistikani yangilaydi. Agar context berilsa, eski reklama xabarini o'chiradi."""
    ad = await get_ad()
    if not ad:
        return
    content_type = ad["content_type"]
    file_id = ad["file_id"]
    text = ad["text"]
    caption = ad["caption"] or ""

    # Eski reklama xabarini o'chirish (agar context va id mavjud bo'lsa)
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
        # Yangi reklama xabar ID sini saqlash
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
            # Tahrirlash muvaffaqiyatli -> yangi xabar qo'shilmaydi
        except Exception:
            # Tahrirlash xato bo'lsa, eski xabarni o'chirib, yangisini yuboramiz
            try:
                await context.bot.delete_message(chat_id=user_id, message_id=main_id)
            except Exception:
                pass
            sent_msg = await context.bot.send_message(chat_id=chat_id, text=text)
            context.user_data["main_msg_id"] = sent_msg.message_id
    else:
        # Hali xabar yo'q, yangi yuboramiz
        sent_msg = await context.bot.send_message(chat_id=chat_id, text=text)
        context.user_data["main_msg_id"] = sent_msg.message_id

    # Reklama yuborish (eski reklama xabarini o'chiradi)
    await send_ad(context.bot, user_id, context)

# -------------------- Start --------------------
async def start(update: Update, context: CallbackContext):
    user_id = update.effective_user.id
    referral_code = context.args[0] if context.args else None
    await register_user_start(user_id, referral_code)

    # Eski xabarlarni tozalash (agar mavjud bo'lsa)
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

# -------------------- Admin panel va boshqa buyruqlar (o'zgarishsiz) --------------------
# (Qolgan funksiyalar avvalgidek, faqat kichik tuzatishlar bilan)
# Ularni to‘liq joylashtirmaslik uchun qisqartirib keltiraman, 
# lekin asosiy faylda yuqoridagi o‘zgarishlar bilan birga ishlatilishi kerak.

# ... (admin, stats, broadcast, video qo'shish, o'chirish, referal, reklama, majburiy obuna admin buyruqlari, handle_code) ...

# Eslatma: handle_code da ham start_after_subs dan oldin foydalanuvchi xabarini o'chirish qo'shilgan, 
# lekin bu yerda to'liq ko'rsatilmagan, asosiy faylda bo'lishi kerak.

# -------------------- Webhook va asosiy --------------------
bot_application = None

async def main():
    global bot_application
    await init_db()
    bot_application = Application.builder().token(BOT_TOKEN).build()

    # ... barcha handlerlar (avvalgidek) ...

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
