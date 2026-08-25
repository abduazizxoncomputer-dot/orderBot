import os

from dotenv import load_dotenv

load_dotenv()


def _parse_admin_ids(raw: str) -> list[int]:
    return [int(x.strip()) for x in raw.split(",") if x.strip()]


BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")
ADMIN_IDS: list[int] = _parse_admin_ids(os.getenv("ADMIN_IDS", ""))

CHANNEL_ID: int = int(os.getenv("CHANNEL_ID", "0"))
CHANNEL_USERNAME: str = os.getenv("CHANNEL_USERNAME", "").lstrip("@")

GROUP_ID: int = int(os.getenv("GROUP_ID", "0"))

DB_PATH: str = os.getenv("DB_PATH", "ordermovies.db")

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN topilmadi. .env faylini tekshiring (.env.example dan nusxa oling).")
