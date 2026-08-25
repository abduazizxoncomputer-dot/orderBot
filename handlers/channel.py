import logging

from aiogram import Bot, F, Router
from aiogram.types import Message

from config import CHANNEL_ID, GROUP_ID
from database.db import add_post, get_pending_orders_by_text, mark_order_fulfilled
from keyboards.inline import go_to_order_kb
from utils.links import build_post_link

logger = logging.getLogger(__name__)

router = Router(name="channel")


@router.channel_post(F.chat.id == CHANNEL_ID, F.text | F.caption)
async def on_new_channel_post(message: Message, bot: Bot) -> None:
    """
    Kanalga yangi post tushganda: DB ga yozadi va kutayotgan userlarga xabar beradi.
    Sof matnli postlarda matn `message.text`da, rasm/video kabi mediali
    postlarda esa `message.caption`da keladi - shuning uchun ikkalasi ham tekshiriladi.
    """
    text = message.text or message.caption
    await add_post(message_id=message.message_id, chat_id=message.chat.id, text=text)

    pending_orders = await get_pending_orders_by_text(text)
    if not pending_orders:
        return

    link = build_post_link(message.chat.id, message.message_id)
    kb = go_to_order_kb(link)

    for order in pending_orders:
        try:
            await bot.send_message(
                order["user_id"],
                "Siz so'ragan order kanalga joylandi!",
                reply_markup=kb,
            )
        except Exception as exc:  # user botni bloklagan yoki chat topilmagan bo'lishi mumkin
            logger.warning("Order %s uchun userga xabar yuborilmadi: %s", order["id"], exc)

        if GROUP_ID and order.get("group_message_id"):
            try:
                await bot.delete_message(GROUP_ID, order["group_message_id"])
            except Exception as exc:  # xabar allaqachon o'chirilgan bo'lishi mumkin
                logger.warning("Guruhdagi order xabari o'chirilmadi (order %s): %s", order["id"], exc)

        await mark_order_fulfilled(order["id"])
