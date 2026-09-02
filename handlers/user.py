import html

from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from config import GROUP_ID
from database.db import add_order, add_user, get_post_by_text, set_order_group_message_id
from keyboards.inline import go_to_order_kb, yes_no_kb
from states.states import OrderStates
from utils.links import build_post_link

router = Router(name="user")


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext) -> None:
    await state.clear()
    await add_user(message.from_user.id, message.from_user.username, message.from_user.full_name)
    await message.answer(
        "Hi! Send me the name of the order (movie/post) you're looking for, "
        "and I'll search the channel for it."
    )


@router.message(F.chat.type == "private", F.text, ~F.text.startswith("/"))
async def handle_order_text(message: Message, state: FSMContext) -> None:
    await add_user(message.from_user.id, message.from_user.username, message.from_user.full_name)

    query_text = message.text.strip()
    post = await get_post_by_text(query_text)

    if post:
        link = build_post_link(post["chat_id"], post["message_id"])
        await message.answer(
            f"Found: <b>{html.escape(query_text)}</b>",
            reply_markup=go_to_order_kb(link),
        )
        return

    await state.set_state(OrderStates.waiting_confirm)
    await state.update_data(pending_order_text=query_text)
    await message.answer(
        f"\"{html.escape(query_text)}\" was not found in the database. Would you like to place an order?",
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

    order_id = await add_order(user_id=call.from_user.id, text=text)

    if GROUP_ID:
        group_msg = await bot.send_message(
            GROUP_ID,
            f"🆕 New order: <b>{html.escape(text)}</b>\n👤 User ID: <code>{call.from_user.id}</code>",
        )
        await set_order_group_message_id(order_id, group_msg.message_id)

    await call.message.edit_text(
        "Your request has been received ✅. We'll notify you once it's posted to the channel."
    )
    await call.answer()


@router.callback_query(OrderStates.waiting_confirm, F.data == "order_no")
async def order_confirm_no(call: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await call.message.edit_text("Cancelled.")
    await call.answer()
