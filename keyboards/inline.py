from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder


def go_to_order_kb(url: str, text: str = "Go to order") -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text=text, url=url)
    return builder.as_markup()


def yes_no_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Yes", callback_data="order_yes")
    builder.button(text="❌ No", callback_data="order_no")
    builder.adjust(2)
    return builder.as_markup()


def optional_url_kb(text: str, url: str) -> InlineKeyboardMarkup:
    """Admin broadcast uchun ixtiyoriy tugma bilan klaviatura."""
    builder = InlineKeyboardBuilder()
    builder.button(text=text, url=url)
    return builder.as_markup()
