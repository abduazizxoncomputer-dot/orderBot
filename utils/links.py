from config import CHANNEL_USERNAME


def build_post_link(chat_id: int, message_id: int) -> str:
    """
    Kanal postiga to'g'ridan-to'g'ri havola quradi.

    - Agar kanal public bo'lsa (CHANNEL_USERNAME .env da berilgan bo'lsa):
        https://t.me/<username>/<message_id>
    - Agar kanal private bo'lsa, chat_id (masalan -1001234567890) dan
      "-100" prefiksi olib tashlanadi:
        https://t.me/c/1234567890/<message_id>
      Bu link faqat kanal a'zolari uchun ochiladi.
    """
    if CHANNEL_USERNAME:
        return f"https://t.me/{CHANNEL_USERNAME}/{message_id}"

    raw_id = str(chat_id)
    if raw_id.startswith("-100"):
        raw_id = raw_id[4:]
    else:
        raw_id = raw_id.lstrip("-")
    return f"https://t.me/c/{raw_id}/{message_id}"
