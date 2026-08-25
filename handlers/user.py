import html

from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from config import GROUP_ID
from database.db import add_order, add_user, get_post_by_text
from keyboards.inline import go_to_order_kb, yes_no_kb
from states.states import OrderStates
from utils.links import build_post_link

router = Router(name="user")


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext) -> None:
    await state.clear()
    await add_user(message.from_user.id, message.from_user.username, message.from_user.full_name)
    await message.answer(
        "Salom! Kerakli order (film/post) nomini menga matn ko'rinishida yuboring, "
        "men uni kanaldan qidirib beraman."
    )


@router.message(F.chat.type == "private", F.text, ~F.text.startswith("/"))
async def handle_order_text(message: Message, state: FSMContext) -> None:
    await add_user(message.from_user.id, message.from_user.username, message.from_user.full_name)

    query_text = message.text.strip()
    post = await get_post_by_text(query_text)

    if post:
        link = build_post_link(post["chat_id"], post["message_id"])
        await message.answer(
            f"Topildi: <b>{html.escape(query_text)}</b>",
            reply_markup=go_to_order_kb(link),
        )
        return

    await state.set_state(OrderStates.waiting_confirm)
    await state.update_data(pending_order_text=query_text)
    await message.answer(
        f"\"{html.escape(query_text)}\" bazada topilmadi. Buyurtma qilmoqchimisiz?",
        reply_markup=yes_no_kb(),
    )


@router.callback_query(OrderStates.waiting_confirm, F.data == "order_yes")
async def order_confirm_yes(call: CallbackQuery, state: FSMContext, bot: Bot) -> None:
    data = await state.get_data()
    text = data.get("pending_order_text")
    await state.clear()

    if not text:
        await call.answer()
        return

    await add_order(user_id=call.from_user.id, text=text)

    if GROUP_ID:
        await bot.send_message(
            GROUP_ID,
            f"🆕 New order: <b>{html.escape(text)}</b>\n👤 User ID: <code>{call.from_user.id}</code>",
        )

    await call.message.edit_text(
        "So'rovingiz qabul qilindi ✅. Kanalga joylanishi bilan sizga xabar beramiz."
    )
    await call.answer()


@router.callback_query(OrderStates.waiting_confirm, F.data == "order_no")
async def order_confirm_no(call: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await call.message.edit_text("Bekor qilindi.")
    await call.answer()
