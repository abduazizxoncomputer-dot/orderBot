import asyncio
import datetime
import html
import logging

from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from config import ADMIN_IDS
from database.db import get_all_users, get_recent_orders, get_recent_posts, get_stats, user_exists
from services.deleted_posts import sync_channel_posts
from states.states import RefreshStates, SendMessageStates

logger = logging.getLogger(__name__)

router = Router(name="admin")
router.message.filter(F.from_user.id.in_(ADMIN_IDS))
router.callback_query.filter(F.from_user.id.in_(ADMIN_IDS))


def _confirm_kb():
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Send", callback_data="sendmsg_send")
    builder.button(text="❌ Cancel", callback_data="sendmsg_cancel")
    builder.adjust(2)
    return builder.as_markup()


@router.message(Command("cancel"))
async def cancel_any(message: Message, state: FSMContext) -> None:
    if await state.get_state() is None:
        return
    await state.clear()
    await message.answer("Cancelled.")


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
        "<b>DB status</b>",
        f"Posts: {stats['posts']}",
        f"Users: {stats['users']}",
        f"Orders: {stats['orders']} (pending: {stats['orders_pending']}, fulfilled: {stats['orders_fulfilled']})",
        "",
        "<b>Recent posts (max 10):</b>",
    ]
    if recent_posts:
        for p in recent_posts:
            lines.append(f"#{p['message_id']} — {_preview(p['text'])}")
    else:
        lines.append("— none —")

    lines.append("")
    lines.append("<b>Recent orders (max 10):</b>")
    if recent_orders:
        for o in recent_orders:
            icon = "⏳" if o["status"] == "pending" else "✅"
            lines.append(f"{icon} [{o['user_id']}] {_preview(o['text'])}")
    else:
        lines.append("— none —")

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
    label = "all posts" if since_iso is None else f"posts since {since_iso}"
    status_msg = await message.answer(f"Refreshing ({label}), please wait...")

    try:
        result = await sync_channel_posts(bot, since_iso)
    except RuntimeError as exc:
        await status_msg.edit_text(f"Error: {exc}")
        return

    await status_msg.edit_text(
        "Refresh completed ✅\n\n"
        f"DB posts checked: {result['checked']}\n"
        f"Removed (deleted from channel): {result['removed']}\n\n"
        f"Channel IDs scanned: {result['scanned']}\n"
        f"New posts added to DB: {result['found']}"
    )


@router.message(Command("refresh"))
async def cmd_refresh(message: Message, command: CommandObject, state: FSMContext, bot: Bot) -> None:
    if command.args:
        try:
            since_iso = _parse_since(command.args)
        except ValueError:
            await message.answer(
                "Invalid date format. Example:\n"
                "<code>/refresh 2026-08-20 15:30</code>\n"
                "<code>/refresh 2026-08-20</code>\n"
                "<code>/refresh all</code>"
            )
            return
        await _run_refresh_and_report(message, bot, since_iso)
        return

    await state.set_state(RefreshStates.waiting_datetime)
    await message.answer(
        "From which date/time should the DB be refreshed?\n\n"
        "Format: <code>YYYY-MM-DD HH:MM</code> (e.g. <code>2026-08-20 15:30</code>)\n"
        "Date/time is in UTC.\n"
        "Type <code>all</code> to check every post.\n"
        "Send /cancel to cancel."
    )


@router.message(RefreshStates.waiting_datetime, F.text)
async def refresh_get_datetime(message: Message, state: FSMContext, bot: Bot) -> None:
    try:
        since_iso = _parse_since(message.text)
    except ValueError:
        await message.answer(
            "Invalid format. Example: <code>2026-08-20 15:30</code> or <code>all</code>.\n"
            "Try again or send /cancel."
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
        "Enter the Telegram user_id of the recipient.\n"
        "(You can also pass it directly: <code>/send_message 123456789</code>)\n\n"
        "You can get the user_id from the \"New order\" message posted in the group.\n"
        "Send /cancel to cancel."
    )


@router.message(Command("broadcast"))
async def cmd_broadcast(message: Message, state: FSMContext) -> None:
    user_count = len(await get_all_users())
    await state.update_data(target_user_id=None, is_broadcast=True)
    await state.set_state(SendMessageStates.waiting_text)
    await message.answer(
        f"This message will be sent to ALL users who started the bot ({user_count} users).\n\n"
        "Enter the message text.\nSend /cancel to cancel."
    )


async def _start_send_message_flow(message: Message, state: FSMContext, target_id: int) -> None:
    exists = await user_exists(target_id)
    warning = "" if exists else "\n⚠️ This user hasn't pressed /start on the bot yet, the message may not be delivered."

    await state.update_data(target_user_id=target_id, is_broadcast=False)
    await state.set_state(SendMessageStates.waiting_text)
    await message.answer(
        f"Recipient: <code>{target_id}</code>{warning}\n\n"
        "Enter the message text.\nSend /cancel to cancel."
    )


@router.message(SendMessageStates.waiting_user_id, F.text)
async def send_message_get_user_id(message: Message, state: FSMContext) -> None:
    raw = message.text.strip()
    if not raw.lstrip("-").isdigit():
        await message.answer(
            "user_id must contain digits only. Try again or send /cancel."
        )
        return

    await _start_send_message_flow(message, state, int(raw))


@router.message(SendMessageStates.waiting_text, F.text)
async def send_message_get_text(message: Message, state: FSMContext) -> None:
    await state.update_data(message_text=message.text)
    await state.set_state(SendMessageStates.waiting_button)
    await message.answer(
        "Would you like to add a button under the message?\n\n"
        "To add one, use this format:\n"
        "<code>Button text | https://t.me/channel_username/123</code>\n\n"
        "Send /skip to send without a button."
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
            "Invalid format. Example: <code>Button text | https://t.me/channel/123</code>\n"
            "Or send /skip to send without a button."
        )
        return

    btn_text, btn_url = (part.strip() for part in raw.split("|", 1))
    if not btn_url.startswith("http"):
        await message.answer("The link must start with http/https. Try again.")
        return

    await state.update_data(button_text=btn_text, button_url=btn_url)
    await _show_send_message_preview(message, state)


async def _show_send_message_preview(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    await state.set_state(SendMessageStates.confirm)

    if data.get("is_broadcast"):
        recipient_line = "Recipient: <b>ALL USERS</b>"
    else:
        recipient_line = f"Recipient: <code>{data['target_user_id']}</code>"

    preview = f"{recipient_line}\n\nMessage text:\n\n{data['message_text']}"
    if data.get("button_url"):
        preview += f"\n\nButton: {data['button_text']} -> {data['button_url']}"

    await message.answer(preview, reply_markup=_confirm_kb())


@router.callback_query(SendMessageStates.confirm, F.data == "sendmsg_cancel")
async def send_message_cancel(call: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await call.message.edit_text("Message sending cancelled.")
    await call.answer()


@router.callback_query(SendMessageStates.confirm, F.data == "sendmsg_send")
async def send_message_send(call: CallbackQuery, state: FSMContext, bot: Bot) -> None:
    data = await state.get_data()
    await state.clear()

    text = data["message_text"]
    button_text = data.get("button_text")
    button_url = data.get("button_url")

    reply_markup = None
    if button_url:
        builder = InlineKeyboardBuilder()
        builder.button(text=button_text, url=button_url)
        reply_markup = builder.as_markup()

    if data.get("is_broadcast"):
        await call.message.edit_text("Broadcasting, please wait...")

        user_ids = await get_all_users()
        sent, failed = 0, 0
        for user_id in user_ids:
            try:
                await bot.send_message(user_id, text, reply_markup=reply_markup)
                sent += 1
            except Exception as exc:
                failed += 1
                logger.info("Broadcast to %s failed: %s", user_id, exc)
            await asyncio.sleep(0.05)  # Telegram flood-limitidan qochish uchun

        await call.message.answer(f"Broadcast finished ✅\nSent: {sent}\nFailed: {failed}")
        await call.answer()
        return

    target_id = data["target_user_id"]
    try:
        await bot.send_message(target_id, text, reply_markup=reply_markup)
        await call.message.edit_text(f"Sent ✅ (user_id: <code>{target_id}</code>)")
    except Exception as exc:
        logger.warning("Message to %s failed: %s", target_id, exc)
        await call.message.edit_text(f"Error ❌: message not sent.\n<code>{html.escape(str(exc))}</code>")

    await call.answer()
