import asyncio
import logging

import truststore

truststore.inject_into_ssl()  # Windows'da SSL sertifikat zanjiri topilmasligi muammosini oldini oladi

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand, BotCommandScopeChat, BotCommandScopeDefault

from config import ADMIN_IDS, BOT_TOKEN
from database.db import init_db
from handlers import admin, channel, user

logger = logging.getLogger(__name__)

DEFAULT_COMMANDS = [
    BotCommand(command="start", description="About this bot"),
]

ADMIN_COMMANDS = DEFAULT_COMMANDS + [
    BotCommand(command="db", description="Show database stats"),
    BotCommand(command="refresh", description="Refresh posts from the channel"),
    BotCommand(command="send_message", description="Send a message to a user"),
    BotCommand(command="cancel", description="Cancel the current action"),
]


async def setup_commands(bot: Bot) -> None:
    """Chap-pastdagi \"Menu\" tugmasida ko'rinadigan buyruqlar ro'yxatini sozlaydi.
    Oddiy userlarga faqat /start ko'rinadi, adminlarga esa to'liq ro'yxat -
    bu adminlarning shaxsiy chatida (BotCommandScopeChat) alohida o'rnatiladi."""
    await bot.set_my_commands(DEFAULT_COMMANDS, scope=BotCommandScopeDefault())

    for admin_id in ADMIN_IDS:
        try:
            await bot.set_my_commands(ADMIN_COMMANDS, scope=BotCommandScopeChat(chat_id=admin_id))
        except Exception as exc:
            logger.warning("Admin %s uchun buyruqlar menyusi o'rnatilmadi: %s", admin_id, exc)


async def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    await init_db()

    bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    await setup_commands(bot)

    dp = Dispatcher(storage=MemoryStorage())

    # Tartib muhim: admin FSM-holatlari birinchi tekshirilsin,
    # aks holda user.py dagi umumiy matn handleri ularni ushlab qoladi.
    dp.include_router(admin.router)
    dp.include_router(user.router)
    dp.include_router(channel.router)

    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logging.info("Bot to'xtatildi.")
