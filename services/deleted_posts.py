"""
MUHIM CHEKLOV:
Telegram Bot API kanalga oid ikkita narsani BERMAYDI:
  1. Post o'chirilganda hech qanday event/update yubormaydi.
  2. Kanal tarixini (eski postlarni) o'qish uchun metod bermaydi.
(Bu ikkalasi ham faqat MTProto-based userbot, masalan Pyrogram/Telethon
orqali mumkin.)

Shu sababli /refresh buyrug'i (handlers/admin.py) ikkala yo'nalishda ham
QO'LDA tekshiruv o'tkazadi:

  A) refresh_posts()          - DB dagi postlar hali kanalda bormi, yo'qmi
                                 tekshiradi (o'chirilganlarini bazadan tozalaydi).
  B) discover_missing_posts() - kanalda bor-u, bazada yo'q postlarni topib
                                 qo'shadi (masalan bot ishga tushishidan oldin
                                 joylangan eski postlar). Bot API'da "shu
                                 kanaldagi barcha postlarni ber" degan metod
                                 yo'qligi sababli, avval kanalning HAQIQIY eng
                                 oxirgi message_id'si aniqlanadi (vaqtincha
                                 "." xabari yuborib, ID'sini o'qib, darhol
                                 o'chirish orqali), so'ng 1 dan shu ID'gacha
                                 bo'lgan HAMMA ID birma-bir forward qilinadi.
                                 Bu usul kanal tarixida (o'chirilgan eski
                                 xabarlar tufayli) bo'shliqlar bo'lsa ham
                                 ishonchli ishlaydi - taxminiy "N marta
                                 ketma-ket topilmasa to'xta" evristikasiga
                                 tayanmaydi.

Ikkala holatda ham post ADMIN_IDS[0] chatiga forward qilinadi (kanal
matni/captioni forwarddan olinadi), so'ng forward darhol o'chirib
tashlanadi - admin chatini ifloslamaslik uchun.
"""

import asyncio
import datetime
import logging

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramRetryAfter

from config import ADMIN_IDS, CHANNEL_ID
from database.db import add_post, delete_post, get_all_post_ids, get_posts_since

logger = logging.getLogger(__name__)


async def _post_still_exists(bot: Bot, admin_id: int, chat_id: int, message_id: int) -> bool:
    try:
        forwarded = await bot.forward_message(
            chat_id=admin_id,
            from_chat_id=chat_id,
            message_id=message_id,
            disable_notification=True,
        )
    except TelegramBadRequest as exc:
        if "message to forward not found" in exc.message.lower():
            return False
        logger.warning("Postni tekshirishda kutilmagan xato (message_id=%s): %s", message_id, exc)
        return True  # noaniq holatda bazadan o'chirib tashlamaymiz

    await bot.delete_message(chat_id=admin_id, message_id=forwarded.message_id)
    return True


async def refresh_posts(bot: Bot, since_iso: str | None) -> tuple[int, int]:
    """
    DB dagi (since_iso berilgan bo'lsa - shu sanadan boshlab yaratilgan)
    postlarni kanalda hali mavjudligini tekshiradi, o'chirilganlarini
    bazadan tozalaydi.

    Qaytaradi: (tekshirilgan postlar soni, o'chirib tashlangan postlar soni)
    """
    if not ADMIN_IDS:
        raise RuntimeError("ADMIN_IDS bo'sh, refresh ishlamaydi.")

    admin_id = ADMIN_IDS[0]
    posts = await get_posts_since(since_iso)

    checked = 0
    removed = 0
    for post in posts:
        exists = await _post_still_exists(bot, admin_id, post["chat_id"], post["message_id"])
        checked += 1
        if not exists:
            await delete_post(post["message_id"])
            removed += 1
            logger.info("O'chirilgan post bazadan tozalandi: message_id=%s", post["message_id"])
        await asyncio.sleep(0.1)  # flood-limitdan qochish

    return checked, removed


def _origin_date_to_iso(forwarded) -> str | None:
    origin = forwarded.forward_origin
    if origin is None or not hasattr(origin, "date"):
        return None
    dt = origin.date
    if dt.tzinfo is not None:
        dt = dt.astimezone(datetime.timezone.utc).replace(tzinfo=None)
    return dt.isoformat()


async def _get_latest_channel_message_id(bot: Bot) -> int:
    """
    Bot API kanal tarixini bermaydi, shuning uchun joriy eng oxirgi
    message_id'ni bilishning yagona yo'li - vaqtincha bitta xabar yuborib,
    uning ID'sini o'qib, darhol o'chirish. disable_notification=True
    obunachilarga push-bildirishnoma yuborilishining oldini oladi.
    """
    probe = await bot.send_message(CHANNEL_ID, ".", disable_notification=True)
    await bot.delete_message(chat_id=CHANNEL_ID, message_id=probe.message_id)
    return probe.message_id - 1


async def _forward_with_retry(bot: Bot, admin_id: int, message_id: int, attempts: int = 3):
    """TelegramRetryAfter (flood control) kelsa kutib qayta urinadi."""
    for attempt in range(attempts):
        try:
            return await bot.forward_message(
                chat_id=admin_id,
                from_chat_id=CHANNEL_ID,
                message_id=message_id,
                disable_notification=True,
            )
        except TelegramRetryAfter as exc:
            if attempt == attempts - 1:
                raise
            await asyncio.sleep(exc.retry_after + 0.5)


async def discover_missing_posts(bot: Bot, since_iso: str | None) -> tuple[int, int]:
    """
    Kanalda mavjud, lekin bazada yo'q postlarni topib qo'shadi.
    Avval kanalning haqiqiy eng oxirgi message_id'si aniqlanadi, so'ng
    1 dan shu ID'gacha bo'lgan barcha ID birma-bir forward qilinadi.

    since_iso berilsa, faqat postning HAQIQIY kanalga joylangan sanasi
    (forward_origin.date) shu sanadan katta/teng bo'lganlari bazaga qo'shiladi.

    Qaytaradi: (bazaga qo'shilgan yangi postlar soni, forward qilib ko'rilgan ID soni)
    """
    if not ADMIN_IDS:
        raise RuntimeError("ADMIN_IDS bo'sh, discover ishlamaydi.")

    admin_id = ADMIN_IDS[0]
    known_ids = {p["message_id"] for p in await get_all_post_ids()}

    try:
        latest_id = await _get_latest_channel_message_id(bot)
    except Exception as exc:
        raise RuntimeError(f"Kanaldagi oxirgi post ID'sini aniqlab bo'lmadi: {exc}") from exc

    found = 0
    scanned = 0

    for message_id in range(1, latest_id + 1):
        if message_id in known_ids:
            continue

        scanned += 1
        try:
            forwarded = await _forward_with_retry(bot, admin_id, message_id)
        except TelegramBadRequest as exc:
            if "message to forward not found" not in exc.message.lower():
                logger.warning("Postni skanerlashda kutilmagan xato (message_id=%s): %s", message_id, exc)
            await asyncio.sleep(0.05)
            continue

        text = forwarded.text or forwarded.caption
        if text:
            post_created_at = _origin_date_to_iso(forwarded)
            if since_iso is None or (post_created_at or "") >= since_iso:
                await add_post(message_id, CHANNEL_ID, text, created_at=post_created_at)
                found += 1
                logger.info("Kanaldan topilgan yangi post bazaga qo'shildi: message_id=%s", message_id)

        await bot.delete_message(chat_id=admin_id, message_id=forwarded.message_id)
        await asyncio.sleep(0.1)  # flood-limitdan qochish

    return found, scanned


async def sync_channel_posts(bot: Bot, since_iso: str | None) -> dict:
    """refresh_posts() + discover_missing_posts() ni birga ishga tushiradi."""
    checked, removed = await refresh_posts(bot, since_iso)
    found, scanned = await discover_missing_posts(bot, since_iso)
    return {
        "checked": checked,
        "removed": removed,
        "found": found,
        "scanned": scanned,
    }
