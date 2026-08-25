import datetime
import html
import logging

from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from config import ADMIN_IDS
from database.db import get_recent_orders, get_recent_posts, get_stats, user_exists
from services.deleted_posts import sync_channel_posts
from states.states import RefreshStates, SendMessageStates

logger = logging.getLogger(__name__)

router = Router(name="admin")
router.message.filter(F.from_user.id.in_(ADMIN_IDS))
router.callback_query.filter(F.from_user.id.in_(ADMIN_IDS))


def _confirm_kb():
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Yuborish", callback_data="sendmsg_send")
    builder.button(text="❌ Bekor qilish", callback_data="sendmsg_cancel")
    builder.adjust(2)
    return builder.as_markup()


@router.message(Command("cancel"))
async def cancel_any(message: Message, state: FSMContext) -> None:
    if await state.get_state() is None:
        return
    await state.clear()
    await message.answer("Bekor qilindi.")


def _preview(text: str, limit: int = 50) -> str:
    text = text.replace("\n", " ").strip()
    if len(text) > limit:
        text = text[:limit] + "…"
    return html.escape(text)


@router.message(Command("db"))
async def cmd_db(message: Message) -> None:
    stats = await get_stats()
    recent_posts = await get_recent_posts(10)
    recent_orders = await get_recent_orders(10)

    lines = [
        "<b>DB holati</b>",
        f"Postlar: {stats['posts']}",
        f"Userlar: {stats['users']}",
        f"Orderlar: {stats['orders']} (kutilmoqda: {stats['orders_pending']}, bajarilgan: {stats['orders_fulfilled']})",
        "",
        "<b>Oxirgi postlar (max 10):</b>",
    ]
    if recent_posts:
        for p in recent_posts:
            lines.append(f"#{p['message_id']} — {_preview(p['text'])}")
    else:
        lines.append("— yo'q —")

    lines.append("")
    lines.append("<b>Oxirgi orderlar (max 10):</b>")
    if recent_orders:
        for o in recent_orders:
            icon = "⏳" if o["status"] == "pending" else "✅"
            lines.append(f"{icon} [{o['user_id']}] {_preview(o['text'])}")
    else:
        lines.append("— yo'q —")

    await message.answer("\n".join(lines))


_DATETIME_FORMATS = ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d")


def _parse_since(raw: str) -> str | None:
    """
    "hammasi" -> None (barcha postlarni tekshirish).
    "YYYY-MM-DD[ HH:MM[:SS]]" -> DB dagi created_at bilan solishtiriladigan
    ISO satr (created_at UTC da, utcnow().isoformat() bilan saqlangan,
    shuning uchun kiritilgan sana-soat ham UTC deb qabul qilinadi).
    """
    text = raw.strip()
    if text.lower() in ("hammasi", "barchasi", "all"):
        return None

    for fmt in _DATETIME_FORMATS:
        try:
            dt = datetime.datetime.strptime(text, fmt)
            return dt.isoformat()
        except ValueError:
            continue

    raise ValueError("format")


async def _run_refresh_and_report(message: Message, bot: Bot, since_iso: str | None) -> None:
    label = "barcha postlar" if since_iso is None else f"{since_iso} dan keyingi postlar"
    status_msg = await message.answer(f"Yangilanmoqda ({label}), kuting...")

    try:
        result = await sync_channel_posts(bot, since_iso)
    except RuntimeError as exc:
        await status_msg.edit_text(f"Xato: {exc}")
        return

    await status_msg.edit_text(
        "Yangilash yakunlandi ✅\n\n"
        f"DB dagi postlar tekshirildi: {result['checked']} ta\n"
        f"O'chirilgani aniqlanib bazadan tozalandi: {result['removed']} ta\n\n"
        f"Kanaldan skanerlangan ID'lar: {result['scanned']} ta\n"
        f"Bazaga yangi qo'shilgan postlar: {result['found']} ta"
    )


@router.message(Command("refresh"))
async def cmd_refresh(message: Message, command: CommandObject, state: FSMContext, bot: Bot) -> None:
    if command.args:
        try:
            since_iso = _parse_since(command.args)
        except ValueError:
            await message.answer(
                "Sana formati noto'g'ri. Namuna:\n"
                "<code>/refresh 2026-08-20 15:30</code>\n"
                "<code>/refresh 2026-08-20</code>\n"
                "<code>/refresh hammasi</code>"
            )
            return
        await _run_refresh_and_report(message, bot, since_iso)
        return

    await state.set_state(RefreshStates.waiting_datetime)
    await message.answer(
        "DB qaysi sana-soatdan boshlab yangilansin?\n\n"
        "Format: <code>YYYY-MM-DD HH:MM</code> (masalan: <code>2026-08-20 15:30</code>)\n"
        "Sana-soat UTC bo'yicha kiritiladi.\n"
        "Barcha postlarni tekshirish uchun <code>hammasi</code> deb yozing.\n"
        "Bekor qilish uchun /cancel."
    )


@router.message(RefreshStates.waiting_datetime, F.text)
async def refresh_get_datetime(message: Message, state: FSMContext, bot: Bot) -> None:
    try:
        since_iso = _parse_since(message.text)
    except ValueError:
        await message.answer(
            "Format noto'g'ri. Namuna: <code>2026-08-20 15:30</code> yoki <code>hammasi</code>.\n"
            "Qaytadan urinib ko'ring yoki /cancel yuboring."
        )
        return

    await state.clear()
    await _run_refresh_and_report(message, bot, since_iso)


@router.message(Command("send_message"))
async def cmd_send_message(message: Message, command: CommandObject, state: FSMContext) -> None:
    if command.args:
        first_token = command.args.strip().split()[0]
        if first_token.lstrip("-").isdigit():
            await _start_send_message_flow(message, state, int(first_token))
            return

    await state.set_state(SendMessageStates.waiting_user_id)
    await message.answer(
        "Xabar yuboriladigan userning Telegram user_id'sini kiriting.\n"
        "(To'g'ridan-to'g'ri ham berish mumkin: <code>/send_message 123456789</code>)\n\n"
        "user_id'ni guruhga tushgan \"New order\" xabaridan olishingiz mumkin.\n"
        "Bekor qilish uchun /cancel."
    )


async def _start_send_message_flow(message: Message, state: FSMContext, target_id: int) -> None:
    exists = await user_exists(target_id)
    warning = "" if exists else "\n⚠️ Bu user hali botga /start bosmagan, xabar yetib bormasligi mumkin."

    await state.update_data(target_user_id=target_id)
    await state.set_state(SendMessageStates.waiting_text)
    await message.answer(
        f"Qabul qiluvchi: <code>{target_id}</code>{warning}\n\n"
        "Xabar matnini kiriting.\nBekor qilish uchun /cancel."
    )


@router.message(SendMessageStates.waiting_user_id, F.text)
async def send_message_get_user_id(message: Message, state: FSMContext) -> None:
    raw = message.text.strip()
    if not raw.lstrip("-").isdigit():
        await message.answer(
            "user_id faqat raqamlardan iborat bo'lishi kerak. Qaytadan urinib ko'ring yoki /cancel."
        )
        return

    await _start_send_message_flow(message, state, int(raw))


@router.message(SendMessageStates.waiting_text, F.text)
async def send_message_get_text(message: Message, state: FSMContext) -> None:
    await state.update_data(message_text=message.text)
    await state.set_state(SendMessageStates.waiting_button)
    await message.answer(
        "Xabar ostiga tugma qo'shmoqchimisiz?\n\n"
        "Qo'shish uchun quyidagi formatda yozing:\n"
        "<code>Tugma matni | https://t.me/kanal_username/123</code>\n\n"
        "Tugmasiz yuborish uchun /skip deb yozing."
    )


@router.message(SendMessageStates.waiting_button, Command("skip"))
async def send_message_skip_button(message: Message, state: FSMContext) -> None:
    await state.update_data(button_text=None, button_url=None)
    await _show_send_message_preview(message, state)


@router.message(SendMessageStates.waiting_button, F.text)
async def send_message_get_button(message: Message, state: FSMContext) -> None:
    raw = message.text
    if "|" not in raw:
        await message.answer(
            "Format noto'g'ri. Namuna: <code>Tugma matni | https://t.me/kanal/123</code>\n"
            "Yoki tugmasiz yuborish uchun /skip yuboring."
        )
        return

    btn_text, btn_url = (part.strip() for part in raw.split("|", 1))
    if not btn_url.startswith("http"):
        await message.answer("Havola http/https bilan boshlanishi kerak. Qaytadan urinib ko'ring.")
        return

    await state.update_data(button_text=btn_text, button_url=btn_url)
    await _show_send_message_preview(message, state)


async def _show_send_message_preview(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    await state.set_state(SendMessageStates.confirm)

    preview = f"Qabul qiluvchi: <code>{data['target_user_id']}</code>\n\nXabar matni:\n\n{data['message_text']}"
    if data.get("button_url"):
        preview += f"\n\nTugma: {data['button_text']} -> {data['button_url']}"

    await message.answer(preview, reply_markup=_confirm_kb())


@router.callback_query(SendMessageStates.confirm, F.data == "sendmsg_cancel")
async def send_message_cancel(call: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await call.message.edit_text("Xabar yuborish bekor qilindi.")
    await call.answer()


@router.callback_query(SendMessageStates.confirm, F.data == "sendmsg_send")
async def send_message_send(call: CallbackQuery, state: FSMContext, bot: Bot) -> None:
    data = await state.get_data()
    await state.clear()

    target_id = data["target_user_id"]
    text = data["message_text"]
    button_text = data.get("button_text")
    button_url = data.get("button_url")

    reply_markup = None
    if button_url:
        builder = InlineKeyboardBuilder()
        builder.button(text=button_text, url=button_url)
        reply_markup = builder.as_markup()

    try:
        await bot.send_message(target_id, text, reply_markup=reply_markup)
        await call.message.edit_text(f"Yuborildi ✅ (user_id: <code>{target_id}</code>)")
    except Exception as exc:
        logger.warning("Xabar %s ga yuborilmadi: %s", target_id, exc)
        await call.message.edit_text(f"Xato ❌: xabar yuborilmadi.\n<code>{html.escape(str(exc))}</code>")

    await call.answer()
