import asyncio
import logging

import truststore

truststore.inject_into_ssl()  # Windows'da SSL sertifikat zanjiri topilmasligi muammosini oldini oladi

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

from config import BOT_TOKEN
from database.db import init_db
from handlers import admin, channel, user


async def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    await init_db()

    bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
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
