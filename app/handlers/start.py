"""Главное меню, /start, /help."""

from __future__ import annotations

import logging

from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    WebAppInfo,
)

from app import db
from app import licensing
from app.config import CONFIG
from app.keyboards import back_to, main_menu_with_app
from app.states import LicenseFlow
from app.utils import plural

log = logging.getLogger("start")
router = Router(name="start")


HELP = """<b>Как работать со мной</b>

Я тренажёр словацкого. Внутри — 41 урок из твоего тренажёра, 847 слов с интервальным повторением, письма, аудирование, чтение и разговор.

<b>Команды</b>
/start — меню
/lesson — текущий урок
/vocab — слова на сегодня
/quiz — мини-тест
/progress — статистика
/errors — твои ошибки
/speak — поговорить по-словацки
/write — письмо
/help — эта справка

<b>Как я оцениваю</b>
✅ Верно
🟡 Почти — опечатка или потерянная диакритика (я скажу, какая буква)
❌ Неверно — объясню правило и запишу ошибку в «Мои ошибки»

<b>Голос</b>
Кнопка 🔊 озвучивает словацкий текст. В «Говорить» присылай голосом — я послушаю и отвечу по-словацки.

<b>Главное правило</b>
Каждый день понемногу лучше, чем 5 часов раз в неделю. 15 минут слов + 20 минут урока = результат."""


@router.message(CommandStart())
async def cmd_start(message: Message, bot: Bot, state: FSMContext) -> None:
    db.init_db()
    db.ensure_user(message.from_user.id, message.from_user.username, message.from_user.first_name)

    if not licensing.is_active(message.from_user.id):
        await state.set_state(LicenseFlow.key)
        await message.answer(
            CONFIG.license_welcome,
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="🔑 Ввести ключ", callback_data="nav:license")],
                    [InlineKeyboardButton(text="ℹ️ Что это", callback_data="nav:license_info")],
                ]
            ),
        )
        return

    await state.clear()
    await state.set_state(None)
    await _send_main_menu(message, "Привет! 👋 Я твой тренажёр словацкого.\n"
                         "Внутри — уроки из твоего тренажёра, слова с повторением, "
                         "аудирование, письмо и разговор.\n\n"
                         "Начни с урока — или выбери, что делаем сегодня.")


@router.callback_query(F.data == "nav:license")
async def cb_license_prompt(cb: CallbackQuery, state: FSMContext) -> None:
    await cb.answer()
    await state.set_state(LicenseFlow.key)
    await cb.message.answer(
        "Пришли ключ сюда сообщением. Я активирую его — и доступ останется навсегда.",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="⬅️ Назад", callback_data="nav:menu")]]
        ),
    )


@router.callback_query(F.data == "nav:license_info")
async def cb_license_info(cb: CallbackQuery) -> None:
    await cb.answer()
    await cb.message.answer(
        "🔑 <b>Как это работает</b>\n\n"
        "• Ключ выдаётся один раз и сразу привязывается к твоему Telegram-аккаунту.\n"
        "• После активации ключ больше не нужен — доступ работает автоматически.\n"
        "• Твой прогресс, слова и ошибки хранятся только у тебя и больше нигде не появятся.\n\n"
        "Если ключ не подошёл — напиши в поддержку.",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="🔑 Ввести ключ", callback_data="nav:license")]]
        ),
    )


@router.message(LicenseFlow.key, F.text)
async def msg_license_key(message: Message, bot: Bot, state: FSMContext) -> None:
    """Приём ключа доступа."""
    code = (message.text or "").strip()
    ok, text = licensing.redeem(code, message.from_user.id)
    if not ok:
        await message.answer(
            "❌ %s\n\nПопробуй ещё раз — ключ выглядит так: SLOV-XXXXX-XXXXX-XXXXX" % text,
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="🔑 Ввести ключ", callback_data="nav:license")],
                    [InlineKeyboardButton(text="⬅️ В меню", callback_data="nav:menu")],
                ]
            ),
        )
        return

    await state.clear()
    await state.set_state(None)
    await message.answer(
        "%s\n\n%s" % (text, _license_footer(message.from_user.id)),
        reply_markup=main_menu_with_app(CONFIG.webapp_base_url),
    )


def _license_footer(user_id: int) -> str:
    days = licensing.remaining_days(user_id)
    if days is None:
        return "♾️ Доступ: бессрочно"
    return "🗓 Подписка активна ещё %d %s" % (days, plural(days, "день", "дня", "дней"))


async def _send_main_menu(message: Message, text: str) -> None:
    await message.answer(text, reply_markup=main_menu_with_app(CONFIG.webapp_base_url))


@router.message(Command("app", "приложение"))
async def cmd_app(message: Message) -> None:
    """Кнопка запуска Mini App."""
    if not CONFIG.webapp_base_url:
        await message.answer(
            "Приложение ещё не подключено: нужно публичный HTTPS-адрес.\n"
            "Почитай deploy/miniapp.md — там три варианта за 5 минут."
        )
        return
    await message.answer(
        "Открываю приложение 👇",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="📱 Открыть",
                        web_app=WebAppInfo(url=CONFIG.webapp_base_url),
                    )
                ]
            ]
        ),
    )


@router.message(Command("help", "помощь"))
async def cmd_help(message: Message) -> None:
    await message.answer(HELP, reply_markup=back_to())


@router.callback_query(F.data == "nav:menu")
async def cb_menu(cb: CallbackQuery, state: FSMContext) -> None:
    await cb.answer()
    await state.set_state(None)
    await cb.message.edit_text(
        "Главное меню. Что делаем?", reply_markup=main_menu_with_app(CONFIG.webapp_base_url)
    )
