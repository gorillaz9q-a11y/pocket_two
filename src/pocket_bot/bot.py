"""Telegram bot entry points and handlers."""

from __future__ import annotations

import logging
import random
import re
import asyncio
from html import escape
from dataclasses import dataclass
from datetime import datetime, time as dt_time, timedelta
from pathlib import Path
from typing import Any, Final, cast
from zoneinfo import ZoneInfo

import httpx
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, InputFile, Message, Update
from telegram.constants import ChatMemberStatus, ParseMode
from telegram.error import TelegramError
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    Defaults,
    Job,
    MessageHandler,
    filters,
)

from .config import get_admin_ids, get_bot_token
from .storage import DatabaseConfig, Storage, create_storage

LOGGER = logging.getLogger(__name__)

ROOT_DIR: Final[Path] = Path(__file__).resolve().parents[2]
IMAGES_DIR: Final[Path] = ROOT_DIR / "images"

DEFAULT_LANGUAGE: Final[str] = "en"
STAGE_LANGUAGE: Final[str] = "language"
STAGE_INTRO: Final[str] = "intro"
STAGE_SUBSCRIPTION: Final[str] = "subscription"
STAGE_POCKET_ID: Final[str] = "pocket_id"
STAGE_PENDING: Final[str] = "pending"
STAGE_COMPLETED: Final[str] = "completed"
STAGE_REJECTED: Final[str] = "rejected"

LANGUAGE_KEY: Final[str] = "language"
VIEW_MESSAGE_KEY: Final[str] = "view_message_id"
ADMIN_VIEW_MESSAGE_KEY: Final[str] = "admin_view_message_id"
LANGUAGE_CHANGE_FLAG: Final[str] = "language_change_via_menu"
AWAITING_POCKET_ID_KEY: Final[str] = "awaiting_pocket_id"
ADMIN_INPUT_KEY: Final[str] = "admin_expected_input"
STORAGE_KEY: Final[str] = "storage_backend"
APPLICATION_USER_DATA_KEY: Final[str] = "application_user_data"

DEFAULT_WORKING_HOURS: Final[str] = "09:00-12:00"
DEFAULT_SIGNALS_RANGE: Final[str] = "6-10"
DEFAULT_SIGNALS_STATUS: Final[bool] = True
PERSONAL_SIGNALS_KEY: Final[str] = "personal_signals_enabled"
DEFAULT_PERSONAL_SIGNALS: Final[bool] = True

MANUAL_SIGNAL_STATE_KEY: Final[str] = "manual_signal_state"
MANUAL_SIGNAL_STAGE_KEY: Final[str] = "stage"
MANUAL_SIGNAL_STAGE_PAIR: Final[str] = "pair"
MANUAL_SIGNAL_STAGE_DIRECTION: Final[str] = "direction"
MANUAL_SIGNAL_STAGE_TIME: Final[str] = "time"
TELEGRAM_CAPTION_LIMIT: Final[int] = 1024
SIGNAL_MESSAGE_LANGUAGE: Final[str] = "en"
AUTO_SIGNAL_TIMEZONE: Final[ZoneInfo] = ZoneInfo("Europe/Kyiv")
AUTO_SIGNAL_WARNING_SECONDS: Final[int] = 10
AUTO_SIGNAL_START_TIME: Final[dt_time] = dt_time(hour=9, minute=0, tzinfo=AUTO_SIGNAL_TIMEZONE)
AUTO_SIGNAL_END_TIME: Final[dt_time] = dt_time(hour=12, minute=0, tzinfo=AUTO_SIGNAL_TIMEZONE)
AUTO_SIGNAL_STATE_KEY: Final[str] = "auto_signal_state"
AUTO_SIGNAL_JOBS_KEY: Final[str] = "auto_signal_jobs"
AUTO_SIGNAL_REFRESH_JOB_NAME: Final[str] = "auto-signal-refresh"
AUTO_SIGNAL_REFRESH_TIME: Final[dt_time] = dt_time(hour=0, minute=5, tzinfo=AUTO_SIGNAL_TIMEZONE)
JobType = Job[Any]
ApplicationType = Application[Any, Any, Any, Any, Any, Any]

MANUAL_SIGNAL_PAIRS: Final[list[str]] = [
    "GBPJPY",
    "USDCHF",
    "CADJPY",
    "CHFJPY",
    "EURJPY",
    "EURCHF",
    "EURUSD",
    "AUDCAD",
    "CADCHF",
    "EURGBP",
    "USDJPY",
    "GBPUSD",
    "EURCAD",
    "AUDJPY",
    "USDCAD",
    "AUDUSD",
    "EURAUD",
    "GBPAUD",
    "GBPCHF",
    "GBPCAD",
    "AUDCHF",
]

MANUAL_SIGNAL_TIME_OPTIONS: Final[list[float]] = [
    0.5,
    1.0,
    1.5,
    2.0,
    2.5,
    3.0,
    3.5,
    4.0,
    4.5,
    5.0,
]

TRADINGVIEW_SYMBOLS: Final[dict[str, str]] = {
    "GBPJPY": "FX:GBPJPY",
    "USDCHF": "FX:USDCHF",
    "CADJPY": "FX:CADJPY",
    "CHFJPY": "FX:CHFJPY",
    "EURJPY": "FX:EURJPY",
    "EURCHF": "FX:EURCHF",
    "EURUSD": "FX:EURUSD",
    "AUDCAD": "FX:AUDCAD",
    "CADCHF": "FX:CADCHF",
    "EURGBP": "FX:EURGBP",
    "USDJPY": "FX:USDJPY",
    "GBPUSD": "FX:GBPUSD",
    "EURCAD": "FX:EURCAD",
    "AUDJPY": "FX:AUDJPY",
    "USDCAD": "FX:USDCAD",
    "AUDUSD": "FX:AUDUSD",
    "EURAUD": "FX:EURAUD",
    "GBPAUD": "FX:GBPAUD",
    "GBPCHF": "FX:GBPCHF",
    "GBPCAD": "FX:GBPCAD",
    "AUDCHF": "FX:AUDCHF",
}

TRADINGVIEW_COLUMNS: Final[list[str]] = [
    "close",
    "Pivot.M.Classic.S1",
    "Pivot.M.Classic.R1",
    "RSI",
    "MACD.macd",
    "MACD.signal",
    "BB.upper",
    "BB.lower",
    "Mom",
]


@dataclass(slots=True)
class TradingViewSnapshot:
    close: float | None
    support: float | None
    resistance: float | None
    rsi: float | None
    macd: float | None
    macd_signal: float | None
    bollinger_upper: float | None
    bollinger_lower: float | None
    momentum: float | None

MARKET_VOLATILITY_OPTIONS: Final[list[dict[str, str]]] = [
    {"ru": "Низкая", "en": "Low"},
    {"ru": "Умеренная", "en": "Moderate"},
    {"ru": "Высокая", "en": "High"},
]

MARKET_SENTIMENT_OPTIONS: Final[list[dict[str, str]]] = [
    {"ru": "Бычий", "en": "Bullish"},
    {"ru": "Медвежий", "en": "Bearish"},
    {"ru": "Нейтральный", "en": "Neutral"},
]

MARKET_VOLUME_RANGE: Final[tuple[int, int]] = (2500, 7500)

TECHNICALS_CATEGORY_LABELS: Final[dict[str, dict[str, str]]] = {
    "rsi": {"ru": "RSI(14)", "en": "RSI(14)"},
    "macd": {"ru": "MACD", "en": "MACD"},
    "bollinger": {"ru": "Полосы Боллинджера", "en": "Bollinger Bands"},
    "pattern": {"ru": "Паттерн", "en": "Pattern"},
    "momentum": {"ru": "Импульс", "en": "Momentum"},
}

TECHNICALS_SUMMARIES: Final[dict[str, list[dict[str, str]]]] = {
    "rsi": [
        {"ru": "перекупленность", "en": "overbought"},
        {"ru": "перепроданность", "en": "oversold"},
        {"ru": "дивергенция", "en": "divergence"},
        {"ru": "нейтрально", "en": "neutral"},
    ],
    "macd": [
        {"ru": "бычий крест", "en": "bull cross"},
        {"ru": "медвежий крест", "en": "bear cross"},
        {"ru": "импульс падает", "en": "momentum fades"},
        {"ru": "тренд усилился", "en": "trend builds"},
    ],
    "bollinger": [
        {"ru": "верхняя полоса", "en": "upper band"},
        {"ru": "нижняя полоса", "en": "lower band"},
        {"ru": "полосы сжаты", "en": "bands tighten"},
        {"ru": "к средней", "en": "to middle"},
    ],
    "pattern": [
        {"ru": "Голова и плечи", "en": "Head & Shoulders"},
        {"ru": "Перевёрнутая голова", "en": "Inverse H&S"},
        {"ru": "Бычий флаг", "en": "Bull flag"},
        {"ru": "Нисходящий клин", "en": "Falling wedge"},
        {"ru": "Двойное дно", "en": "Double bottom"},
    ],
    "momentum": [
        {"ru": "импульс растёт", "en": "momentum up"},
        {"ru": "импульс падает", "en": "momentum down"},
        {"ru": "импульс ровный", "en": "momentum flat"},
        {"ru": "волатильность выше", "en": "volatility up"},
    ],
}

TECHNICALS_STATUS_TEXTS: Final[dict[str, dict[str, dict[str, str]]]] = {
    "rsi": {
        "overbought": {"ru": "перекупленность", "en": "overbought"},
        "oversold": {"ru": "перепроданность", "en": "oversold"},
        "neutral": {"ru": "нейтрально", "en": "neutral"},
        "bull_bias": {"ru": "бычий уклон", "en": "bull bias"},
        "bear_bias": {"ru": "медвежий уклон", "en": "bear bias"},
    },
    "macd": {
        "bull_cross": {"ru": "бычий крест", "en": "bull cross"},
        "bear_cross": {"ru": "медвежий крест", "en": "bear cross"},
        "trend_builds": {"ru": "тренд усилился", "en": "trend builds"},
        "momentum_fades": {"ru": "импульс падает", "en": "momentum fades"},
    },
    "bollinger": {
        "upper_band": {"ru": "верхняя полоса", "en": "upper band"},
        "lower_band": {"ru": "нижняя полоса", "en": "lower band"},
        "bands_tighten": {"ru": "полосы сжаты", "en": "bands tighten"},
        "to_middle": {"ru": "к средней", "en": "to middle"},
    },
    "pattern": {
        "falling_wedge": {"ru": "Нисходящий клин", "en": "Falling wedge"},
        "bull_flag": {"ru": "Бычий флаг", "en": "Bull flag"},
        "double_bottom": {"ru": "Двойное дно", "en": "Double bottom"},
        "head_shoulders": {"ru": "Голова и плечи", "en": "Head & Shoulders"},
        "inverse_hs": {"ru": "Перевёрнутая голова", "en": "Inverse H&S"},
        "breakout_watch": {"ru": "Ждём пробоя", "en": "Breakout watch"},
    },
    "momentum": {
        "momentum_up": {"ru": "импульс растёт", "en": "momentum up"},
        "momentum_down": {"ru": "импульс падает", "en": "momentum down"},
        "momentum_flat": {"ru": "импульс ровный", "en": "momentum flat"},
        "volatility_up": {"ru": "волатильность выше", "en": "volatility up"},
    },
}

TECHNICALS_CATEGORY_ORDER: Final[tuple[str, ...]] = (
    "rsi",
    "macd",
    "bollinger",
    "pattern",
    "momentum",
)

TECHNICALS_HEADER_LABELS: Final[dict[str, str]] = {
    "ru": "🔧 Технический обзор",
    "en": "🔧 Technical Snapshot",
}

PRICE_SECTION_LABELS: Final[dict[str, str]] = {
    "ru": "💵 Ценовые уровни",
    "en": "💵 Price Levels",
}

PRICE_VALUE_LABELS: Final[dict[str, dict[str, str]]] = {
    "current": {"ru": "Текущая цена", "en": "Current value"},
    "support": {"ru": "Поддержка S1", "en": "Support (S1)"},
    "resistance": {"ru": "Сопротивление R1", "en": "Resistance (R1)"},
}

PRICE_VALUE_ICONS: Final[dict[str, str]] = {
    "current": "💵",
    "support": "🔽",
    "resistance": "🔼",
}

SECTION_SEPARATOR: Final[str] = "━━━━━━━━━━━━━━━━━━"

_LANGUAGE_PROMPT: Final[str] = "Выберите язык / Choose your language:" # changed
_LANGUAGE_PROMPT: Final[str] = "Choose your language:"
_LANGUAGE_IMAGE_PATH: Final[Path] = IMAGES_DIR / "language.png"
_LANGUAGE_CALLBACK_PREFIX: Final[str] = "language:"

# _SUBSCRIPTION_CHAT_LINK: Final[str] = "https://t.me/pl_mastery_chat" # changed
_SUBSCRIPTION_CHANNEL_LINK: Final[str] = "https://t.me/fx_luna_channel"
# _SUBSCRIPTION_CHAT_USERNAME: Final[str] = "@pl_mastery_chat"  # changed
_SUBSCRIPTION_CHANNEL_USERNAME: Final[str] = "@fx_luna_channel"

_COMMUNITY_YOUTUBE_LINK: Final[str] = "https://www.youtube.com/@PLMASTERY"
_COMMUNITY_TIKTOK_LINK: Final[str] = "https://www.tiktok.com/@pl_company_"
_COMMUNITY_TELEGRAM_CHAT_LINK: Final[str] = "https://t.me/pl_mastery_chat"
_COMMUNITY_TELEGRAM_CHANNEL_LINK: Final[str] = "https://t.me/pl_mastery"
_POCKET_OPTION_LINK: Final[str] = (
    "https://u3.shortink.io/register?utm_campaign=776094&utm_source=affiliate&utm_medium=sr"
    "&a=99EXdPzMNDkf2f&ac=bot&code=MASTERY"
)

_MAIN_MENU_IMAGE_PATH: Final[Path] = IMAGES_DIR / "main.png"
_COMMUNITY_IMAGE_PATH: Final[Path] = IMAGES_DIR / "community.png"
_WORKSPACE_IMAGE_PATH: Final[Path] = IMAGES_DIR / "work.png"

_TEXTS: Final[dict[str, dict[str, str]]] = {
    "language_set": {
        "ru": "Язык установлен: Русский.",
        "en": "Language selected: English.",
    },
    "subscription_prompt": {
        "ru": "Подпишитесь на чат и канал ниже, затем нажмите «Проверить подписку».",
        "en": "Subscribe to the chat and channel below, then tap “Check subscription”.",
    },
    "subscription_missing": {
        "ru": "Подписка не найдена: {targets}. Пожалуйста, подпишитесь и попробуйте снова.",
        "en": "Could not verify subscription to {targets}. Please subscribe and try again.",
    },
    "subscription_success": {
        "ru": "Подписка подтверждена!",
        "en": "Subscription verified!",
    },
    "intro_description": {
        "ru": "🤖 PL MASTERY BOT\n\nЕсли вы ещё не знакомы с нашей командой — самое время присоединиться!\nПодписывайтесь и общайтесь с нами каждый день в прямых эфирах и чатах.\n\n📲 Telegram — новости, сигналы и общение с командой\n🎥 YouTube — разборы сделок и обучающие видео\n🎬 TikTok — ежедневные эфиры и быстрые обзоры рынка\n\n🚀 Будь в движении вместе с PL Mastery!",
        "en": "🤖 FX LUNA BOT\n\nIf you’re new to our orbit — now’s the perfect time to join!\nWe go live daily, exploring the markets and sharing insights across all platforms.\n\n📲 Telegram — news, signals, and trader community\n🎥 YouTube — market breakdowns and strategy sessions\n🎬 TikTok — daily clips and live trading insights\n\nTrade beyond limits. Join FX LUNA.🚀",
    },
    "enter_pocket_id": {
        "ru": "Введите ваш Pocket Option ID:",
        "en": "Please enter your Pocket Option ID:",
    },
    "invalid_pocket_id": {
        "ru": "ID должен содержать хотя бы одну цифру. Попробуйте ещё раз.",
        "en": "The ID must contain at least one digit. Please try again.",
    },
    "application_received": {
        "ru": "Ваша заявка в обработке, ожидайте.",
        "en": "Your request is being processed. Please wait.",
    },
    "application_rejected": {
        "ru": "Ваша заявка отклонена.",
        "en": "Your application has been rejected.",
    },
    "application_rejected_blocked": {
        "ru": "Ваша заявка ранее была отклонена. Дождитесь решения администратора или свяжитесь с поддержкой.",
        "en": "Your previous application was rejected. Please wait for an administrator or contact support.",
    },
    "application_approved": {
        "ru": "Ваша заявка принята!",
        "en": "Your application has been approved!",
    },
    "admin_panel_header": {
        "ru": "Админ-панель",
        "en": "Admin panel",
    },
    "admin_signals_header": {
        "ru": "Глобальный флаг сигналов: {status}",
        "en": "Global signal flag: {status}",
    },
    "admin_users_header": {
        "ru": "Список пользователей",
        "en": "User list",
    },
    "admin_settings_header": {
        "ru": "Настройки",
        "en": "Settings",
    },
    "admin_users_summary": {
        "ru": "Одобрено: {approved}\nОтклонено: {rejected}",
        "en": "Approved: {approved}\nRejected: {rejected}",
    },
    "pending_summary": {
        "ru": "Ожидающие заявки: {count}. Карточки отправлены ниже.",
        "en": "Pending applications: {count}. Cards sent below.",
    },
    "no_pending_applications": {
        "ru": "Нет новых заявок.",
        "en": "There are no new applications.",
    },
    "main_menu_caption": {
        "ru": "👋 Добро пожаловать в PL Mastery Signals Bot!\n\n📊 Здесь ты получаешь быстрые и чёткие торговые сигналы для Pocket Option.\n\n⚡️ Всё просто:\n1. Получаешь сигнал от бота\n2. Заходишь в сделку на 1 минуту\n3. Фиксируешь результат\n\n🚀 Начни использовать сигналы прямо сейчас и торгуй уверенно!",
        "en": "👋 Welcome to the FX LUNA Trade Bot!\n\n📊 Get fast and accurate trading signals designed for Pocket Option.\n\n⚡️ It’s easy:\n1. Receive a signal from the bot\n2. Enter a 1-minute trade\n3. Take your profit\n\nTrade smart. Trade lunar. Join FX LUNA!🚀",
    },
    "community_text": {
        "ru": "6 дней в неделю мы выходим в лайв, где вместе разбираем сделки, точки входа и актуальную ситуацию на рынке.\nНаша команда делится своими идеями, а вы можете наблюдать за нашей работой в Telegram, TikTok и YouTube.\n\n📈 Стань частью большой команды трейдеров-единомышленников!\nБудь всегда в среде, где ты растёшь, развиваешься и движешься к результату.\n\n🎥 TikTok\n4 трейдера в прямом эфире каждый день анализируют рынок\n\n📲 Telegram\n\nПубличный канал — новости и полезная информация о трейдинге\n\nVIP-канал — закрытые сигналы, обучающий материал и трансляция актуальных сделок\n\n▶️ YouTube\nРегулярные разборы и обучающие видео",
        "en": "We go live five days a week to review trades, entry points, and the latest market moves together.\nThe FX LUNA team shares insights while you watch the full process unfold on Telegram, TikTok, and YouTube.\n\n📈 Join a growing community of lunar-minded traders!\nStay in a space where you evolve, gain confidence, and move toward consistent results.\n\n🎥 TikTok\nOur traders stream live five days a week — analyzing markets and setups in real time.\n\n📲 Telegram\n\nPublic channel — news, updates, and valuable trading insights.\n\nVIP channel — exclusive signals, education, and live trade breakdowns.\n\n▶️ YouTube\nRegular market breakdowns, tutorials, and learning sessions from the FX LUNA crew.",
    },
    "support_text": {
        "ru": "Поддержка: напишите нам в чат или в Telegram @bigmember0.",
        "en": "Support: reach out in chat or on Telegram @bigmember0.",
    },
    "faq_caption": {
        "ru": "Как работает бот:\n\nЭто бот для сигналов Pocket Option.\n\nВажно: Автоматизированные торговые сигналы не являются инвестиционными рекомендациями. Торговля бинарными опционами сопряжена с высоким риском потерь. Мы рекомендуем торговать только теми средствами, которые вы можете позволить себе потерять. Всегда проводите собственное исследование, прежде чем принимать какие-либо решения.\n\nРабочий процесс:\n\n1) Получение сигнала\nБот присылает сообщение с:\n📊 Валютной парой (например, EUR/USD)\n📈 Направлением сделки (Вверх /  Вниз)\n⏱️ Экспирация: 1 минута\n\n2) Ваши действия\nПосле получения сигнала у вас есть всего несколько секунд, чтобы открыть сделку в Pocket Option.\n⚡️ Входите мгновенно, так как сигнал рассчитан на движение «здесь и сейчас».\n\n3) Результат\nДождитесь окончания сделки\n\nДля того что-бы вы получали сигналы вы должны включить уведомления!",
        "en": "🌕 How FX LUNA Bot Works\n\nThis bot provides Pocket Option trading signals in real time.\n\n⚠️ Important:\nAutomated signals are not financial advice.\nTrading binary options involves high risk of loss.\nTrade only with funds you can afford to lose and always do your own research before entering a position.\n\n🚀 Workflow\n\n1) Receiving a Signal\nThe bot sends a message containing:\n📊 Currency pair (e.g., EUR/USD)\n📈 Direction (Up / Down)\n⏱️ Expiration: 1 minute\n\n2) Your Action\nReact instantly — you have only a few seconds to place the trade in Pocket Option.\n⚡️ Enter immediately — the signal captures a real-time market move.\n\n3) Result\nWait for the 1-minute trade to close and track your outcome.\n\n💬 Tip:\nTurn on notifications to never miss a signal from FX LUNA!",
    },
    "workspace_text": {
        "ru": "Рабочая область: ознакомьтесь с материалами ниже.",
        "en": "Workspace: explore the materials below.",
    },
    "workspace_global_status": {
        "ru": "Глобальные сигналы: {status}",
        "en": "Global signals: {status}",
    },
    "workspace_personal_status": {
        "ru": "Ваши сигналы: {status}",
        "en": "Your signals: {status}",
    },
    "signals_status": {
        "ru": "Статус сигналов: {status}",
        "en": "Signals status: {status}",
    },
    "signals_status_on": {
        "ru": "включены",
        "en": "on",
    },
    "signals_status_off": {
        "ru": "выключены",
        "en": "off",
    },
    "signals_toggle_success_on": {
        "ru": "Сигналы включены.",
        "en": "Signals have been enabled.",
    },
    "signals_toggle_success_off": {
        "ru": "Сигналы выключены.",
        "en": "Signals have been disabled.",
    },
    "personal_signals_toggle_on": {
        "ru": "Локальные сигналы включены.",
        "en": "Personal signals enabled.",
    },
    "personal_signals_toggle_off": {
        "ru": "Локальные сигналы выключены.",
        "en": "Personal signals disabled.",
    },
    "signals_toggle_no_permission": {
        "ru": "Изменение статуса доступно только администраторам.",
        "en": "Only administrators can change the signal status.",
    },
    "signals_toggle_already": {
        "ru": "Статус сигналов уже: {status}.",
        "en": "Signals are already {status}.",
    },
    "auto_signal_status": {
        "ru": "Автосигналы на сегодня: отправлено {sent} из {target}. Осталось {remaining}.",
        "en": "Auto signals today: sent {sent} of {target}. Remaining {remaining}.",
    },
    "auto_signal_warning": {
        "ru": "⚡️ Финальный отсчёт: через 10 секунд прилетит свежий торговый сигнал. Проверьте площадку заранее!",
        "en": "⚡️ Final call: a fresh trading signal lands in 10 seconds. Stay sharp!",
    },
    "auto_signal_trigger_scheduled": {
        "ru": "Автосигнал запланирован. Осталось на сегодня: {remaining}.",
        "en": "Auto signal queued. Remaining for today: {remaining}.",
    },
    "auto_signal_trigger_no_remaining": {
        "ru": "На сегодня лимит автосигналов уже выполнен.",
        "en": "The auto-signal quota for today is already met.",
    },
    "auto_signal_not_configured": {
        "ru": "Автоматическая рассылка сигналов сейчас не активна.",
        "en": "Automatic signal scheduling is currently inactive.",
    },
    "user_list_approved_header": {
        "ru": "Одобренные пользователи:",
        "en": "Approved users:",
    },
    "user_list_rejected_header": {
        "ru": "Отклонённые пользователи:",
        "en": "Rejected users:",
    },
    "user_list_empty": {
        "ru": "Список пуст.",
        "en": "The list is empty.",
    },
    "user_list_actions_hint": {
        "ru": "Выберите пользователя ниже, чтобы выполнить действие.",
        "en": "Choose a user below to perform an action.",
    },
    "admin_user_removed": {
        "ru": "Пользователь {user_id} удалён из списка.",
        "en": "User {user_id} has been removed.",
    },
    "admin_user_remove_missing": {
        "ru": "Не удалось найти одобренного пользователя {user_id}.",
        "en": "Could not find approved user {user_id}.",
    },
    "user_removed_message": {
        "ru": "Ваш доступ к боту отключён администратором. Используйте /start, чтобы начать заново.",
        "en": "Your access to the bot was revoked by an administrator. Use /start to begin again.",
    },
    "admin_user_unblocked": {
        "ru": "Пользователь {user_id} разблокирован и переведён в ожидание.",
        "en": "User {user_id} has been unblocked and moved to pending review.",
    },
    "admin_user_unblock_missing": {
        "ru": "Не удалось найти отклонённого пользователя {user_id}.",
        "en": "Could not find rejected user {user_id}.",
    },
    "user_unblocked_message": {
        "ru": "Ваш доступ восстановлен. Заявка отправлена на повторное рассмотрение.",
        "en": "Your access has been restored. Your application is back under review.",
    },
    "settings_summary": {
        "ru": "Окно автосигналов (по Киеву): {hours}\nДиапазон сигналов: {signals_range}",
        "en": "Auto-signal window (Kyiv time): {hours}\nSignal range: {signals_range}",
    },
    "request_working_hours": {
        "ru": "Введите рабочие часы в формате ЧЧ:ММ-ЧЧ:ММ.",
        "en": "Enter working hours in the format HH:MM-HH:MM.",
    },
    "request_signals_range": {
        "ru": "Введите диапазон количества сигналов (например, 6-10).",
        "en": "Enter the signal count range (for example, 6-10).",
    },
    "working_hours_updated": {
        "ru": "Рабочие часы обновлены.",
        "en": "Working hours updated.",
    },
    "signals_range_updated": {
        "ru": "Диапазон сигналов обновлён.",
        "en": "Signal range updated.",
    },
    "invalid_settings_input": {
        "ru": "Неверный формат. Попробуйте снова.",
        "en": "Invalid format. Please try again.",
    },
    "manual_signal_pair_prompt": {
        "ru": "Выберите валютную пару для ручного сигнала.",
        "en": "Choose a currency pair for the manual signal.",
    },
    "manual_signal_direction_prompt": {
        "ru": "Выберите направление: вверх (покупка) или вниз (продажа).",
        "en": "Select the direction: up (buy) or down (sell).",
    },
    "manual_signal_time_prompt": {
        "ru": "Укажите время экспирации сигнала или введите своё значение.",
        "en": "Set the signal expiration or enter a custom value.",
    },
    "manual_signal_custom_time_prompt": {
        "ru": "Введите время экспирации в минутах (например, 2 или 1.5).",
        "en": "Enter expiration time in minutes (e.g. 2 or 1.5).",
    },
    "manual_signal_time_invalid": {
        "ru": "Не удалось распознать время. Используйте число больше нуля.",
        "en": "Unable to parse the time. Please provide a number greater than zero.",
    },
    "manual_signal_signals_disabled": {
        "ru": "Глобальные сигналы отключены. Включите их, чтобы отправить рассылку.",
        "en": "Global signals are disabled. Enable them before broadcasting.",
    },
    "manual_signal_no_recipients": {
        "ru": "Нет пользователей с активными сигналами.",
        "en": "There are no users with signals enabled.",
    },
    "manual_signal_fetch_error": {
        "ru": "Не удалось получить данные TradingView для выбранной пары.",
        "en": "Failed to fetch TradingView data for the selected pair.",
    },
    "manual_signal_data_unavailable": {
        "ru": "⚠️ Технические данные TradingView недоступны, отправляем сигнал без уровней.",
        "en": "⚠️ TradingView data is temporarily unavailable; sending the signal without levels.",
    },
    "manual_signal_sent": {
        "ru": "Сигнал отправлен {count} пользователям.",
        "en": "Signal delivered to {count} users.",
    },
    "manual_signal_failed_recipients": {
        "ru": "Не удалось доставить {count} пользователям: {ids}.",
        "en": "Failed to deliver to {count} users: {ids}.",
    },
    "manual_signal_image_missing": {
        "ru": "Не найдено изображение для выбранной пары и направления. Отправляется только текст.",
        "en": "Image for the chosen pair and direction is missing. Sending text only.",
    },
    "manual_signal_truncated": {
        "ru": "⚠️ Текст сигнала был сокращён до лимита Telegram.",
        "en": "⚠️ Signal text was shortened to fit Telegram limits.",
    },
    "manual_signal_ready": {
        "ru": "Сигнал готов к отправке.",
        "en": "Signal is ready to broadcast.",
    },
    "manual_signal_cancelled": {
        "ru": "Ручной сигнал отменён.",
        "en": "Manual signal cancelled.",
    },
    "manual_signal_unknown_error": {
        "ru": "Произошла ошибка при отправке сигнала. Попробуйте ещё раз.",
        "en": "An unexpected error occurred while sending the signal. Please try again.",
    },
    "not_admin": {
        "ru": "У вас нет доступа к админ-панели.",
        "en": "You don't have access to the admin panel.",
    },
    "default_reply": {
        "ru": "Используйте кнопки меню или /start, чтобы продолжить.",
        "en": "Use the menu buttons or /start to continue.",
    },
}

_LABELS: Final[dict[str, dict[str, str]]] = {
    "community": {"ru": "Сообщество", "en": "Community"},
    "support": {"ru": "Поддержка", "en": "Support"},
    "workspace": {"ru": "Рабочая область", "en": "Workspace"},
    "faq": {"ru": "FAQ", "en": "FAQ"},
    "change_language": {"ru": "Поменять язык", "en": "Change language"},
    "back": {"ru": "Назад", "en": "Back"},
    "enable_signals": {"ru": "Включить сигналы", "en": "Enable signals"},
    "disable_signals": {"ru": "Выключить сигналы", "en": "Disable signals"},
    "chat": {"ru": "Чат", "en": "Chat"},
    "channel": {"ru": "Канал", "en": "Channel"},
    "community_youtube": {"ru": "YouTube", "en": "YouTube"},
    "community_telegram_chat": {"ru": "Telegram чат", "en": "Telegram chat"},
    "community_tiktok": {"ru": "TikTok", "en": "TikTok"},
    "community_telegram_channel": {"ru": "Telegram канал", "en": "Telegram channel"},
    "pocket_option": {"ru": "Pocket Option", "en": "Pocket Option"},
    "check_subscription": {"ru": "Проверить подписку", "en": "Check subscription"},
    "admin_requests": {"ru": "Заявки", "en": "Applications"},
    "admin_signals": {
        "ru": "Глобальный флаг сигналов",
        "en": "Global signal flag",
    },
    "admin_users": {"ru": "Список пользователей", "en": "User list"},
    "admin_settings": {"ru": "Настройки", "en": "Settings"},
    "admin_enable": {"ru": "Включить", "en": "Enable"},
    "admin_disable": {"ru": "Выключить", "en": "Disable"},
    "admin_approved": {"ru": "Одобренные", "en": "Approved"},
    "admin_rejected": {"ru": "Отклонённые", "en": "Rejected"},
    "admin_working_hours": {"ru": "Рабочие часы", "en": "Working hours"},
    "admin_signals_range": {"ru": "Диапазон сигналов", "en": "Signal range"},
    "back_to_menu": {"ru": "Главное меню", "en": "Main menu"},
    "manual_signal": {"ru": "Ручной сигнал", "en": "Manual signal"},
    "direction_up": {"ru": "Вверх (Купить)", "en": "Up (Buy)"},
    "direction_down": {"ru": "Вниз (Продать)", "en": "Down (Sell)"},
    "manual_signal_custom_time": {
        "ru": "Ввести своё время",
        "en": "Enter custom time",
    },
    "manual_signal_send_again": {
        "ru": "Новый сигнал",
        "en": "New signal",
    },
    "manual_signal_cancel": {"ru": "Отмена", "en": "Cancel"},
    "intro_start": {"ru": "Приступить к работе", "en": "Get started"},
    "admin_remove": {"ru": "Удалить", "en": "Remove"},
    "admin_unblock": {"ru": "Разблокировать", "en": "Unblock"},
    "admin_auto_trigger": {"ru": "Отправить автосигнал", "en": "Send auto signal"},
    "community_youtube": {"ru": "YouTube", "en": "YouTube"},
    "community_telegram_chat": {"ru": "Telegram чат", "en": "Telegram chat"},
    "community_tiktok": {"ru": "TikTok", "en": "TikTok"},
    "faq": {"ru": "FAQ", "en": "FAQ"},
}

_TARGET_LABELS: Final[dict[str, dict[str, str]]] = {
    "chat": {"ru": "чат", "en": "chat"},
    "channel": {"ru": "канал", "en": "channel"},
}

ADMIN_IDS: Final[set[int]] = get_admin_ids()


def _label(key: str, language: str) -> str:
    values = _LABELS.get(key)
    if not values:
        return key
    return values.get(language) or values.get("ru") or next(iter(values.values()))


def _user_data(context: ContextTypes.DEFAULT_TYPE) -> dict[str, Any]:
    return cast(dict[str, Any], context.user_data)


def _application_user_data(
    context: ContextTypes.DEFAULT_TYPE, user_id: int
) -> dict[str, Any]:
    bot_data = cast(dict[str, Any], context.bot_data)
    store = cast(
        dict[int, dict[str, Any]],
        bot_data.setdefault(APPLICATION_USER_DATA_KEY, {}),
    )
    existing = store.get(user_id)
    if existing is None:
        existing = {}
        store[user_id] = existing
    return existing


def _get_storage_from_bot_data(bot_data: dict[str, Any]) -> Storage:
    storage = bot_data.get(STORAGE_KEY)
    if storage is None:
        raise RuntimeError("Storage backend is not initialized")
    return cast(Storage, storage)


def _get_personal_signals_setting(
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    user_data: dict[str, Any] | None = None,
) -> bool:
    storage = _get_storage_from_bot_data(context.bot_data)
    store = _application_user_data(context, user_id)
    if PERSONAL_SIGNALS_KEY in store:
        value = bool(store[PERSONAL_SIGNALS_KEY])
    else:
        persisted = storage.get_personal_signals(user_id)
        if persisted is None:
            value = DEFAULT_PERSONAL_SIGNALS
            storage.set_personal_signals(user_id, value)
        else:
            value = bool(persisted)
        store[PERSONAL_SIGNALS_KEY] = value
    if user_data is not None:
        user_data.setdefault(PERSONAL_SIGNALS_KEY, store[PERSONAL_SIGNALS_KEY])
    return bool(store[PERSONAL_SIGNALS_KEY])


def _set_personal_signals_setting(
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    value: bool,
    user_data: dict[str, Any] | None = None,
) -> None:
    storage = _get_storage_from_bot_data(context.bot_data)
    storage.set_personal_signals(user_id, value)
    store = _application_user_data(context, user_id)
    store[PERSONAL_SIGNALS_KEY] = value
    if user_data is not None:
        user_data[PERSONAL_SIGNALS_KEY] = value


def _manual_state(user_data: dict[str, Any]) -> dict[str, Any]:
    return cast(dict[str, Any], user_data.setdefault(MANUAL_SIGNAL_STATE_KEY, {}))


def _reset_manual_signal_state(user_data: dict[str, Any]) -> None:
    user_data.pop(MANUAL_SIGNAL_STATE_KEY, None)


def _ensure_bot_defaults(bot_data: dict[str, Any]) -> None:
    storage = _get_storage_from_bot_data(bot_data)
    storage.ensure_defaults(
        signals_enabled=DEFAULT_SIGNALS_STATUS,
        working_hours=DEFAULT_WORKING_HOURS,
        signals_range=DEFAULT_SIGNALS_RANGE,
    )


def _get_applications(bot_data: dict[str, Any]) -> dict[int, dict[str, Any]]:
    _ensure_bot_defaults(bot_data)
    storage = _get_storage_from_bot_data(bot_data)
    applications = storage.list_applications()
    return {int(app["user_id"]): app for app in applications}
def _set_user_stage(bot_data: dict[str, Any], user_id: int, stage: str) -> None:
    _ensure_bot_defaults(bot_data)
    storage = _get_storage_from_bot_data(bot_data)
    storage.set_user_stage(user_id, stage)


def _is_user_approved(bot_data: dict[str, Any], user_id: int) -> bool:
    storage = _get_storage_from_bot_data(bot_data)
    application = storage.get_application(user_id)
    if application and application.get("status") == "approved":
        return True
    return storage.get_user_stage(user_id) == STAGE_COMPLETED


def _get_text(key: str, language: str) -> str:
    translations = _TEXTS.get(key)
    if not translations:
        return ""
    return translations.get(language) or translations.get("en") or next(
        iter(translations.values())
    )


def _chunked(items: list[str], size: int) -> list[list[str]]:
    return [items[i : i + size] for i in range(0, len(items), size)]


def _is_private_chat(chat: Any | None) -> bool:
    return bool(chat and getattr(chat, "type", None) == "private")


def _bold(text: str | None) -> str | None:
    if not text:
        return text
    return f"<b>{escape(text)}</b>"


def _format_time_value(value: float, language: str) -> str:
    if language == "ru":
        # Display comma as decimal separator for Russian users
        return ("{:.2f}".format(value)).rstrip("0").rstrip(".").replace(".", ",")
    return ("{:.2f}".format(value)).rstrip("0").rstrip(".")


def _parse_time_input(text: str) -> float | None:
    normalized = text.strip().replace(" ", "").replace(",", ".")
    try:
        value = float(normalized)
    except ValueError:
        return None
    if value <= 0:
        return None
    return value


def _parse_signal_image_filename(path: Path) -> tuple[str | None, str | None]:
    tokens = path.stem.split()
    pair_token: str | None = None
    direction_token: str | None = None
    for token in tokens:
        upper = token.upper()
        if len(upper) == 6 and upper.isalpha():
            pair_token = upper
        if upper in {"BUY", "SELL"}:
            direction_token = upper
    return pair_token, direction_token


def _discover_pair_images() -> dict[str, dict[str, Path]]:
    mapping: dict[str, dict[str, Path]] = {}
    for image_path in IMAGES_DIR.glob("*.png"):
        pair, direction = _parse_signal_image_filename(image_path)
        if not pair or not direction:
            continue
        pair_mapping = mapping.setdefault(pair, {})
        pair_mapping[direction] = image_path
    return mapping


PAIR_IMAGE_MAP: Final[dict[str, dict[str, Path]]] = _discover_pair_images()


def _resolve_signal_image(pair: str, direction: str) -> Path | None:
    pair_key = pair.upper()
    direction_key = direction.upper()
    pair_mapping = PAIR_IMAGE_MAP.get(pair_key)
    if not pair_mapping:
        return None
    image_path = pair_mapping.get(direction_key)
    if image_path and image_path.exists():
        return image_path
    return None


def _build_price_levels_text(
    language: str,
    current_value: float | None,
    support: float | None,
    resistance: float | None,
) -> str:
    header = PRICE_SECTION_LABELS.get(language) or PRICE_SECTION_LABELS["en"]

    def _line(key: str, value: float | None) -> str:
        label = PRICE_VALUE_LABELS[key].get(language) or PRICE_VALUE_LABELS[key]["en"]
        icon = PRICE_VALUE_ICONS[key]
        formatted = f"{value:.5f}" if value is not None else "—"
        return f"   {icon} {label}: {formatted}"

    lines = [
        header,
        _line("current", current_value),
        _line("support", support),
        _line("resistance", resistance),
    ]
    return "\n".join(lines)


def _get_status_translation(category: str, status_key: str, language: str) -> str | None:
    category_map = TECHNICALS_STATUS_TEXTS.get(category)
    if not category_map:
        return None
    translations = category_map.get(status_key)
    if not translations:
        return None
    return translations.get(language) or translations.get("en")


def _determine_rsi_status(snapshot: TradingViewSnapshot) -> str | None:
    value = snapshot.rsi
    if value is None:
        return None
    if value <= 30:
        return "oversold"
    if value >= 70:
        return "overbought"
    if value >= 55:
        return "bull_bias"
    if value <= 45:
        return "bear_bias"
    return "neutral"


def _determine_macd_status(snapshot: TradingViewSnapshot) -> str | None:
    macd_value = snapshot.macd
    signal_value = snapshot.macd_signal
    if macd_value is None or signal_value is None:
        return None
    hist = macd_value - signal_value
    threshold = max(abs(macd_value), abs(signal_value), 0.0005) * 0.05
    if hist >= threshold:
        return "bull_cross"
    if hist <= -threshold:
        return "bear_cross"
    if hist > 0:
        return "trend_builds"
    if hist < 0:
        return "momentum_fades"
    return None


def _determine_bollinger_status(snapshot: TradingViewSnapshot) -> str | None:
    price = snapshot.close
    upper = snapshot.bollinger_upper
    lower = snapshot.bollinger_lower
    if price is None or upper is None or lower is None:
        return None
    if upper <= lower:
        return None
    width = upper - lower
    if price >= upper * 0.995:
        return "upper_band"
    if price <= lower * 1.005:
        return "lower_band"
    if width <= 0:
        return "to_middle"
    if price != 0 and (width / abs(price)) <= 0.005:
        return "bands_tighten"
    middle = (upper + lower) / 2
    if abs(price - middle) <= width * 0.15:
        return "to_middle"
    return "to_middle"


def _determine_momentum_status(snapshot: TradingViewSnapshot) -> str | None:
    value = snapshot.momentum
    if value is None:
        return None
    price = snapshot.close
    if price is None or abs(price) < 1e-9:
        baseline = 1.0
    else:
        baseline = abs(price)
    relative = abs(value) / baseline
    if relative >= 0.01:
        return "volatility_up"
    if value >= 0.0001:
        return "momentum_up"
    if value <= -0.0001:
        return "momentum_down"
    return "momentum_flat"


def _determine_pattern_status(snapshot: TradingViewSnapshot) -> str | None:
    price = snapshot.close
    support = snapshot.support
    resistance = snapshot.resistance
    if price is None or support is None or resistance is None:
        return None
    span = resistance - support
    if span <= 0:
        return None
    position = (price - support) / span
    momentum_value = snapshot.momentum or 0.0
    if position <= 0.2:
        return "double_bottom" if momentum_value > 0 else "falling_wedge"
    if position >= 0.8:
        return "bull_flag" if momentum_value >= 0 else "head_shoulders"
    if momentum_value >= 0.0001:
        return "inverse_hs"
    if momentum_value <= -0.0001:
        return "falling_wedge"
    return "breakout_watch"


def _determine_indicator_status(category: str, snapshot: TradingViewSnapshot) -> str | None:
    if category == "rsi":
        return _determine_rsi_status(snapshot)
    if category == "macd":
        return _determine_macd_status(snapshot)
    if category == "bollinger":
        return _determine_bollinger_status(snapshot)
    if category == "pattern":
        return _determine_pattern_status(snapshot)
    if category == "momentum":
        return _determine_momentum_status(snapshot)
    return None


def _build_technicals_text(language: str, snapshot: TradingViewSnapshot | None) -> str:
    header = TECHNICALS_HEADER_LABELS.get(language) or TECHNICALS_HEADER_LABELS["en"]
    categories = list(TECHNICALS_CATEGORY_ORDER)
    random.shuffle(categories)

    lines = [header]
    for key in categories:
        label = TECHNICALS_CATEGORY_LABELS[key].get(language) or TECHNICALS_CATEGORY_LABELS[key]["en"]
        summary_text: str
        if snapshot is not None:
            status_key = _determine_indicator_status(key, snapshot)
            if status_key:
                translated = _get_status_translation(key, status_key, language)
                if translated:
                    summary_text = translated
                else:
                    summary_text = ""
            else:
                summary_text = ""
        else:
            summary_text = ""

        if not summary_text:
            fallback = random.choice(TECHNICALS_SUMMARIES[key])
            summary_text = fallback.get(language) or fallback.get("en") or ""

        lines.append(f"   📊 {label}: {summary_text}")
    return "\n".join(lines)


def _build_market_overview_text(language: str) -> str:
    volatility = random.choice(MARKET_VOLATILITY_OPTIONS)["en"]
    sentiment = random.choice(MARKET_SENTIMENT_OPTIONS)["en"]
    volume = random.randint(*MARKET_VOLUME_RANGE)

    lines = [
        "🌍 Market Overview",
        f"   📈 Volatility: {volatility}",
        f"   😊 Sentiment: {sentiment}",
        f"   📊 Volume: {volume}",
    ]
    return "\n".join(lines)


def _format_manual_signal_message(
    *,
    pair: str,
    direction: str,
    time_minutes: float,
    language: str,
    current_value: float,
    support: float,
    resistance: float,
    technical_snapshot: TradingViewSnapshot | None,
) -> str:
    del language
    message_language = SIGNAL_MESSAGE_LANGUAGE
    direction_labels = {
        "buy": {"en": "Buy"},
        "sell": {"en": "Sell"},
    }
    direction_key = direction.lower()
    direction_label = direction_labels[direction_key]["en"]
    time_text = _format_time_value(time_minutes, message_language)
    header = f"📢 {pair} ({direction_label})"
    time_line = f"⏱️ Expiration: {time_text} min"

    price_block = _build_price_levels_text(message_language, current_value, support, resistance)
    technicals_block = _build_technicals_text(message_language, technical_snapshot)
    market_block = _build_market_overview_text(message_language)

    parts = [
        header,
        time_line,
        "",
        SECTION_SEPARATOR,
        price_block,
        SECTION_SEPARATOR,
        technicals_block,
        SECTION_SEPARATOR,
        market_block,
    ]
    return "\n".join(parts)


def _format_manual_signal_fallback(
    *,
    pair: str,
    direction: str,
    time_minutes: float,
    language: str,
    notice: str,
    technical_snapshot: TradingViewSnapshot | None,
    current_value: float | None = None,
    support: float | None = None,
    resistance: float | None = None,
) -> str:
    del language
    message_language = SIGNAL_MESSAGE_LANGUAGE
    direction_labels = {
        "buy": {"en": "Buy"},
        "sell": {"en": "Sell"},
    }
    direction_key = direction.lower()
    direction_label = direction_labels[direction_key]["en"]
    time_text = _format_time_value(time_minutes, message_language)
    header = f"📢 {pair} ({direction_label})"
    time_line = f"⏱️ Expiration: {time_text} min"

    price_block = _build_price_levels_text(message_language, current_value, support, resistance)
    technicals_block = _build_technicals_text(message_language, technical_snapshot)
    market_block = _build_market_overview_text(message_language)

    parts = [
        header,
        time_line,
        "",
    ]
    if notice:
        parts.extend([notice, ""])
    parts.extend(
        [
            SECTION_SEPARATOR,
            price_block,
            SECTION_SEPARATOR,
            technicals_block,
            SECTION_SEPARATOR,
            market_block,
        ]
    )
    return "\n".join(parts)


async def _fetch_tradingview_levels(pair: str) -> TradingViewSnapshot | None:
    symbol = TRADINGVIEW_SYMBOLS.get(pair.upper())
    if not symbol:
        return None

    payload: dict[str, Any] = {
        "symbols": {"tickers": [symbol], "query": {"types": []}},
        "columns": TRADINGVIEW_COLUMNS,
    }

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0 Safari/537.36",
    }

    try:
        async with httpx.AsyncClient(timeout=10.0, headers=headers) as client:
            response = await client.post(
                "https://scanner.tradingview.com/forex/scan",
                json=payload,
            )
            response.raise_for_status()
    except httpx.HTTPError as exc:
        LOGGER.error("TradingView request failed for %s: %s", pair, exc)
        return None

    try:
        data = response.json()
    except ValueError as exc:
        LOGGER.error("TradingView returned invalid JSON for %s: %s", pair, exc)
        return None

    items = data.get("data")
    if not items:
        LOGGER.warning("TradingView returned no data for %s", pair)
        return None

    first = items[0]
    values = first.get("d")
    if not values:
        LOGGER.warning("TradingView response missing column data for %s", pair)
        return None

    mapping: dict[str, Any] = {}
    for index, key in enumerate(TRADINGVIEW_COLUMNS):
        mapping[key] = values[index] if index < len(values) else None

    def _coerce_float(raw: Any) -> float | None:
        try:
            if raw is None:
                return None
            return float(raw)
        except (TypeError, ValueError):
            return None

    snapshot = TradingViewSnapshot(
        close=_coerce_float(mapping.get("close")),
        support=_coerce_float(mapping.get("Pivot.M.Classic.S1")),
        resistance=_coerce_float(mapping.get("Pivot.M.Classic.R1")),
        rsi=_coerce_float(mapping.get("RSI")),
        macd=_coerce_float(mapping.get("MACD.macd")),
        macd_signal=_coerce_float(mapping.get("MACD.signal")),
        bollinger_upper=_coerce_float(mapping.get("BB.upper")),
        bollinger_lower=_coerce_float(mapping.get("BB.lower")),
        momentum=_coerce_float(mapping.get("Mom")),
    )

    if (
        snapshot.close is None
        and snapshot.support is None
        and snapshot.resistance is None
        and snapshot.rsi is None
        and snapshot.macd is None
        and snapshot.macd_signal is None
        and snapshot.bollinger_upper is None
        and snapshot.bollinger_lower is None
        and snapshot.momentum is None
    ):
        LOGGER.warning("TradingView snapshot had no usable data for %s", pair)
        return None

    return snapshot

async def _safe_delete_message(message: Message | None) -> None:
    if not message:
        return
    try:
        await message.delete()
    except TelegramError:
        pass


def _clear_tracked_message_id(
    user_data: dict[str, Any], key: str, message_id: int | None
) -> None:
    stored = user_data.get(key)
    if stored is None:
        return
    if message_id is None or stored == message_id:
        user_data.pop(key, None)


async def _delete_tracked_message(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    user_data: dict[str, Any],
    key: str,
) -> None:
    message_id = user_data.pop(key, None)
    if not message_id:
        return
    try:
        await context.bot.delete_message(chat_id=chat_id, message_id=message_id)
    except TelegramError:
        pass


async def _send_tracked_message(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    user_data: dict[str, Any],
    *,
    text: str | None = None,
    photo_path: Path | None = None,
    caption: str | None = None,
    reply_markup: InlineKeyboardMarkup | None = None,
    key: str = VIEW_MESSAGE_KEY,
) -> Message:
    await _delete_tracked_message(context, chat_id, user_data, key)

    if photo_path and photo_path.exists():
        caption_text = _bold(caption or text or "") or ""
        with photo_path.open("rb") as image_fp:
            input_file = InputFile(image_fp, filename=photo_path.name)
            message = await context.bot.send_photo(
                chat_id=chat_id,
                photo=input_file,
                caption=caption_text,
                reply_markup=reply_markup,
            )
    elif photo_path:
        LOGGER.warning("Image not found at %s", photo_path)
        message = await context.bot.send_message(
            chat_id=chat_id,
            text=_bold(caption or text or "") or "",
            reply_markup=reply_markup,
        )
    else:
        message = await context.bot.send_message(
            chat_id=chat_id,
            text=_bold(text or caption or "") or "",
            reply_markup=reply_markup,
        )

    user_data[key] = message.message_id
    return message


def _build_language_keyboard(include_back: bool, language: str) -> InlineKeyboardMarkup:
    buttons = [
        [
            # InlineKeyboardButton("Русский", callback_data=f"{_LANGUAGE_CALLBACK_PREFIX}ru"), # changed
            InlineKeyboardButton("English", callback_data=f"{_LANGUAGE_CALLBACK_PREFIX}en"),
        ]
    ]
    if include_back:
        buttons.append(
            [InlineKeyboardButton(_label("back", language), callback_data="main:back")]
        )
    return InlineKeyboardMarkup(buttons)


def _build_subscription_keyboard(language: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(

        [
            [
                # InlineKeyboardButton(_label("chat", language), url=_SUBSCRIPTION_CHAT_LINK), # changed
                InlineKeyboardButton(
                    _label("channel", language), url=_SUBSCRIPTION_CHANNEL_LINK
                ),
            ],
            [
                InlineKeyboardButton(
                    _label("check_subscription", language), callback_data="check_subscription"
                )
            ],
        ]
    )


def _build_intro_keyboard(language: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                # InlineKeyboardButton(
                #     _label("community_telegram_chat", language),
                #     url=_COMMUNITY_TELEGRAM_CHAT_LINK,
                # ),
                InlineKeyboardButton(
                    _label("community_telegram_channel", language),
                    url=_COMMUNITY_TELEGRAM_CHANNEL_LINK,
                ),
            ],
            [
                InlineKeyboardButton(
                    _label("community_youtube", language),
                    url=_COMMUNITY_YOUTUBE_LINK,
                ),
                InlineKeyboardButton(
                    _label("community_tiktok", language),
                    url=_COMMUNITY_TIKTOK_LINK,
                ),
            ],
            [
                InlineKeyboardButton(
                    _label("pocket_option", language),
                    url=_POCKET_OPTION_LINK,
                )
            ],
            [InlineKeyboardButton(_label("intro_start", language), callback_data="intro:start")],
        ]
    )


def _build_main_menu_keyboard(language: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    _label("community", language), callback_data="main:community"
                ),
                InlineKeyboardButton(
                    _label("support", language), callback_data="main:support"
                ),
            ],
            [
                InlineKeyboardButton(
                    _label("workspace", language), callback_data="main:workspace"
                ),
                InlineKeyboardButton(_label("faq", language), callback_data="main:faq"),
            ],
            [
                InlineKeyboardButton(
                    _label("change_language", language),
                    callback_data="main:change_language",
                )
            ],
        ]
    )


def _build_workspace_keyboard(language: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    _label("enable_signals", language), callback_data="main:workspace:on"
                ),
                InlineKeyboardButton(
                    _label("disable_signals", language), callback_data="main:workspace:off"
                ),
            ],
            [InlineKeyboardButton(_label("back", language), callback_data="main:back")],
        ]
    )


def _build_community_keyboard(language: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    _label("community_youtube", language), url=_COMMUNITY_YOUTUBE_LINK
                ),
                InlineKeyboardButton(
                    _label("community_tiktok", language), url=_COMMUNITY_TIKTOK_LINK
                ),
            ],
            [
                InlineKeyboardButton(
                    _label("community_telegram_chat", language),
                    url=_COMMUNITY_TELEGRAM_CHAT_LINK,
                ),
                InlineKeyboardButton(
                    _label("community_telegram_channel", language),
                    url=_COMMUNITY_TELEGRAM_CHANNEL_LINK,
                ),
            ],
            [InlineKeyboardButton(_label("back", language), callback_data="main:back")],
        ]
    )


def _build_back_keyboard(callback_data: str, language: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton(_label("back", language), callback_data=callback_data)]]
    )


def _get_signals_status_text(bot_data: dict[str, Any], language: str) -> str:
    _ensure_bot_defaults(bot_data)
    storage = _get_storage_from_bot_data(bot_data)
    enabled = storage.get_global_signals()
    key = "signals_status_on" if enabled else "signals_status_off"
    return _get_text(key, language)


def _format_user_entry(application: dict[str, Any]) -> str:
    parts: list[str] = [str(application["user_id"])]
    full_name = " ".join(
        part for part in [application.get("first_name"), application.get("last_name")] if part
    )
    if full_name:
        parts.append(full_name)
    username = application.get("username")
    if username:
        parts.append(f"@{username}")
    parts.append(f"Pocket ID: {application['pocket_id']}")
    return " — ".join(parts)


def _format_admin_user_button(application: dict[str, Any], action_label: str) -> str:
    user_id = str(application["user_id"])
    pocket_id = application.get("pocket_id") or ""
    full_name = " ".join(
        part for part in [application.get("first_name"), application.get("last_name")] if part
    )

    tokens: list[str] = [user_id]
    if full_name:
        truncated_name = full_name if len(full_name) <= 20 else f"{full_name[:17]}…"
        tokens.append(truncated_name)
    if pocket_id:
        tokens.append(str(pocket_id))
    tokens.append(action_label)

    label = " · ".join(tokens)
    if len(label) <= 64:
        return label

    fallback_tokens = [user_id]
    if pocket_id:
        fallback_tokens.append(str(pocket_id))
    fallback_tokens.append(action_label)
    label = " · ".join(fallback_tokens)
    if len(label) <= 64:
        return label

    return f"{user_id} · {action_label}"


def _gather_signal_recipients(context: ContextTypes.DEFAULT_TYPE) -> list[int]:
    _ensure_bot_defaults(context.bot_data)
    storage = _get_storage_from_bot_data(context.bot_data)
    signals_enabled = storage.get_global_signals()
    if not signals_enabled:
        return []

    recipient_ids: set[int] = {
        user_id
        for user_id in storage.list_signal_recipient_ids(STAGE_COMPLETED)
        if user_id not in ADMIN_IDS
    }

    for user_id in list(recipient_ids):
        _get_personal_signals_setting(context, user_id)

    for admin_id in ADMIN_IDS:
        if _get_personal_signals_setting(context, admin_id):
            recipient_ids.add(admin_id)

    return sorted(recipient_ids)


def _resolve_user_language(context: ContextTypes.DEFAULT_TYPE, user_id: int) -> str:
    store = _application_user_data(context, user_id)
    language = store.get(LANGUAGE_KEY)
    if isinstance(language, str):
        return language

    application = _get_application(context.bot_data, user_id)
    if application:
        language = application.get("language", DEFAULT_LANGUAGE)
    else:
        language = DEFAULT_LANGUAGE

    store[LANGUAGE_KEY] = language
    return language


def _parse_working_hours_window(hours: str) -> tuple[dt_time, dt_time] | None:
    if not hours or "-" not in hours:
        return None
    start_raw, end_raw = hours.split("-", maxsplit=1)
    try:
        start_parts = [int(part) for part in start_raw.strip().split(":", maxsplit=1)]
        end_parts = [int(part) for part in end_raw.strip().split(":", maxsplit=1)]
        if len(start_parts) != 2 or len(end_parts) != 2:
            return None
        start_time = dt_time(hour=start_parts[0], minute=start_parts[1], tzinfo=AUTO_SIGNAL_TIMEZONE)
        end_time = dt_time(hour=end_parts[0], minute=end_parts[1], tzinfo=AUTO_SIGNAL_TIMEZONE)
    except ValueError:
        return None
    return start_time, end_time


def _parse_signal_range_bounds(range_value: str) -> tuple[int, int] | None:
    if not range_value or "-" not in range_value:
        return None
    start_raw, end_raw = range_value.split("-", maxsplit=1)
    try:
        lower = int(start_raw.strip())
        upper = int(end_raw.strip())
    except ValueError:
        return None
    if lower < 0 or upper < 0 or upper < lower:
        return None
    return lower, upper


def _auto_signal_today() -> datetime:
    return datetime.now(AUTO_SIGNAL_TIMEZONE)


def _auto_signal_state(bot_data: dict[str, Any]) -> dict[str, Any]:
    return cast(dict[str, Any], bot_data.setdefault(AUTO_SIGNAL_STATE_KEY, {}))


def _reset_auto_signal_jobs(job_list: list[dict[str, Any]] | None) -> None:
    if not job_list:
        return
    for entry in job_list:
        for job in entry.values():
            if job is not None:
                job.schedule_removal()


def _clear_auto_signal_jobs(bot_data: dict[str, Any]) -> None:
    job_entries = cast(list[dict[str, Any]] | None, bot_data.pop(AUTO_SIGNAL_JOBS_KEY, None))
    _reset_auto_signal_jobs(job_entries)


def _register_auto_signal_job(
    bot_data: dict[str, Any], warning_job: JobType | None, delivery_job: JobType | None
) -> None:
    entries = cast(list[dict[str, Any]], bot_data.setdefault(AUTO_SIGNAL_JOBS_KEY, []))
    entries.append({"warning": warning_job, "delivery": delivery_job})


def _unregister_auto_job_reference(bot_data: dict[str, Any], job: JobType | None) -> None:
    entries = cast(list[dict[str, Any]] | None, bot_data.get(AUTO_SIGNAL_JOBS_KEY))
    if not entries:
        return
    for entry in list(entries):
        if entry.get("warning") == job:
            entry["warning"] = None
        if entry.get("delivery") == job:
            entry["delivery"] = None
        if not entry.get("warning") and not entry.get("delivery"):
            entries.remove(entry)


def _cancel_one_scheduled_auto_job(bot_data: dict[str, Any]) -> bool:
    entries = cast(list[dict[str, Any]] | None, bot_data.get(AUTO_SIGNAL_JOBS_KEY))
    if not entries:
        return False
    while entries:
        entry = entries.pop()
        cancelled = False
        for job in entry.values():
            if job is not None:
                job.schedule_removal()
                cancelled = True
        if cancelled:
            return True
    return False


def _schedule_daily_auto_signal_refresh(application: ApplicationType) -> None:
    job_queue = application.job_queue
    if not job_queue:
        LOGGER.warning(
            "Job queue is not available; daily auto-signal refresh scheduling skipped."
        )
        return

    for existing in job_queue.get_jobs_by_name(AUTO_SIGNAL_REFRESH_JOB_NAME):
        existing.schedule_removal()

    job_queue.run_daily(
        _auto_signal_refresh_job,
        time=AUTO_SIGNAL_REFRESH_TIME,
        name=AUTO_SIGNAL_REFRESH_JOB_NAME,
    )


def _auto_signal_remaining(state: dict[str, Any]) -> int:
    target = int(state.get("target", 0))
    sent = int(state.get("sent", 0))
    remaining = target - sent
    return remaining if remaining > 0 else 0


def _resolve_auto_signal_window(storage: Storage) -> tuple[dt_time, dt_time]:
    hours = storage.get_working_hours()
    window = _parse_working_hours_window(hours)
    if window:
        return window

    storage.set_working_hours(DEFAULT_WORKING_HOURS)
    fallback_window = _parse_working_hours_window(DEFAULT_WORKING_HOURS)
    if fallback_window is None:
        return AUTO_SIGNAL_START_TIME, AUTO_SIGNAL_END_TIME
    return fallback_window


async def _setup_auto_signals_for_today(application: Any) -> None:
    bot_data = application.bot_data
    _clear_auto_signal_jobs(bot_data)

    _ensure_bot_defaults(bot_data)
    storage = _get_storage_from_bot_data(bot_data)

    if not storage.get_global_signals():
        state = _auto_signal_state(bot_data)
        state.update({"date": _auto_signal_today().date().isoformat(), "target": 0, "sent": 0})
        return

    range_bounds = _parse_signal_range_bounds(storage.get_signal_range())
    if not range_bounds:
        state = _auto_signal_state(bot_data)
        state.update({"date": _auto_signal_today().date().isoformat(), "target": 0, "sent": 0})
        return

    lower, upper = range_bounds
    target = random.randint(lower, upper)

    now = _auto_signal_today()
    today = now.date()
    start_time, end_time = _resolve_auto_signal_window(storage)
    start_dt = datetime.combine(today, start_time)
    end_dt = datetime.combine(today, end_time)

    if end_dt <= start_dt:
        state = _auto_signal_state(bot_data)
        state.update({"date": today.isoformat(), "target": 0, "sent": 0})
        return

    state = _auto_signal_state(bot_data)
    state.update({"date": today.isoformat(), "target": target, "sent": 0})

    if target <= 0:
        return

    earliest = max(start_dt, now + timedelta(seconds=AUTO_SIGNAL_WARNING_SECONDS + 1))
    latest = end_dt
    if latest <= earliest:
        return

    duration_seconds = (latest - earliest).total_seconds()
    if duration_seconds <= AUTO_SIGNAL_WARNING_SECONDS:
        return

    times: list[datetime] = []
    for _ in range(target):
        offset = random.random() * duration_seconds
        candidate = earliest + timedelta(seconds=offset)
        if candidate >= latest:
            candidate = latest - timedelta(seconds=1)
        times.append(candidate)

    times.sort()

    job_queue = application.job_queue
    if not job_queue:
        LOGGER.warning("Job queue is not available; auto signals will not be scheduled today.")
        return

    for delivery_time in times:
        warning_time = delivery_time - timedelta(seconds=AUTO_SIGNAL_WARNING_SECONDS)
        current_now = _auto_signal_today()

        warning_delay = (warning_time - current_now).total_seconds()
        if warning_delay < 0:
            warning_delay = 0.0

        delivery_delay = (delivery_time - current_now).total_seconds()
        if delivery_delay <= 0:
            continue

        warning_job = job_queue.run_once(
            _auto_signal_warning_job,
            when=warning_delay,
            name=f"auto-warning-{delivery_time.isoformat()}",
        )
        delivery_job = job_queue.run_once(
            _auto_signal_delivery_job,
            when=delivery_delay,
            name=f"auto-delivery-{delivery_time.isoformat()}",
        )
        _register_auto_signal_job(bot_data, warning_job, delivery_job)

    # All deliveries have been scheduled; remaining count persists via state values.


async def _ensure_auto_signal_state(application: Any) -> dict[str, Any]:
    bot_data = application.bot_data
    state = _auto_signal_state(bot_data)
    today = _auto_signal_today().date().isoformat()
    if state.get("date") != today:
        await _setup_auto_signals_for_today(application)
        state = _auto_signal_state(bot_data)
    return state


def _generate_price_levels_for_pair(pair: str) -> tuple[float, float, float]:
    if pair.endswith("JPY"):
        base = random.uniform(118.0, 165.0)
        spread = random.uniform(0.05, 0.35)
    else:
        base = random.uniform(0.85, 1.75)
        spread = random.uniform(0.003, 0.018)

    support = max(base - spread, 0.0001)
    resistance = base + spread
    return base, support, resistance


def _generate_auto_signal_payload() -> dict[str, Any]:
    pair = random.choice(MANUAL_SIGNAL_PAIRS)
    direction = random.choice(["buy", "sell"])
    current, support, resistance = _generate_price_levels_for_pair(pair)
    return {
        "pair": pair,
        "direction": direction,
        "time": 1.0,
        "current": current,
        "support": support,
        "resistance": resistance,
    }


def _format_auto_signal_caption(
    payload: dict[str, Any],
    technical_snapshot: TradingViewSnapshot | None,
) -> str:
    pair = payload["pair"]
    direction = payload["direction"]
    current_value = float(payload["current"])
    support = float(payload["support"])
    resistance = float(payload["resistance"])

    direction_label = "Buy" if direction == "buy" else "Sell"
    header = f"🤖 {pair} ({direction_label})"
    time_line = "⏱️ Expiration: 1 minute"

    price_block = _build_price_levels_text(
        SIGNAL_MESSAGE_LANGUAGE,
        current_value,
        support,
        resistance,
    )
    technicals_block = _build_technicals_text(SIGNAL_MESSAGE_LANGUAGE, technical_snapshot)
    market_block = _build_market_overview_text(SIGNAL_MESSAGE_LANGUAGE)

    parts = [
        header,
        time_line,
        "",
        SECTION_SEPARATOR,
        price_block,
        SECTION_SEPARATOR,
        technicals_block,
        SECTION_SEPARATOR,
        market_block,
    ]
    return "\n".join(parts)


async def _broadcast_auto_signal_warning(
    context: ContextTypes.DEFAULT_TYPE, recipients: list[int]
) -> None:
    if not recipients:
        return

    cached_texts: dict[str, str] = {}
    for user_id in recipients:
        language = _resolve_user_language(context, user_id)
        text = cached_texts.get(language)
        if text is None:
            text = _get_text("auto_signal_warning", language)
            cached_texts[language] = text
        try:
            await context.bot.send_message(chat_id=user_id, text=_bold(text) or "")
        except TelegramError as exc:
            LOGGER.warning("Failed to send auto-signal warning to %s: %s", user_id, exc)


async def _execute_auto_signal(
    context: ContextTypes.DEFAULT_TYPE,
    application: Any,
    *,
    payload: dict[str, Any] | None = None,
) -> tuple[int, list[int], dict[str, Any], bool]:
    storage = _get_storage_from_bot_data(application.bot_data)
    if not storage.get_global_signals():
        LOGGER.info("Skipping auto signal delivery because global signals are disabled.")
        state = _auto_signal_state(application.bot_data)
        state["sent"] = int(state.get("sent", 0)) + 1
        return 0, [], payload or {}, False

    recipients = _gather_signal_recipients(context)
    payload = payload or _generate_auto_signal_payload()
    snapshot = await _fetch_tradingview_levels(payload["pair"])
    if snapshot:
        if snapshot.close is not None:
            payload["current"] = snapshot.close
        if snapshot.support is not None:
            payload["support"] = snapshot.support
        if snapshot.resistance is not None:
            payload["resistance"] = snapshot.resistance
    payload["snapshot"] = snapshot

    raw_caption = _format_auto_signal_caption(payload, snapshot)
    caption, was_truncated = _prepare_caption_text(raw_caption)
    image_path = _resolve_signal_image(
        payload["pair"], "BUY" if payload["direction"] == "buy" else "SELL"
    )

    delivered = 0
    failed: list[int] = []
    if recipients:
        delivered, failed = await _broadcast_manual_signal(
            context,
            recipients,
            caption,
            image_path,
        )
    else:
        LOGGER.info("No recipients available for auto signal: %s", payload["pair"])

    state = _auto_signal_state(application.bot_data)
    state["sent"] = int(state.get("sent", 0)) + 1

    return delivered, failed, payload, was_truncated


async def _auto_signal_warning_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    job = cast(JobType | None, context.job)  # type: ignore[assignment]
    if job is None:
        return

    application = cast(ApplicationType, context.application)  # type: ignore[assignment]

    _unregister_auto_job_reference(application.bot_data, job)

    storage = _get_storage_from_bot_data(application.bot_data)
    if not storage.get_global_signals():
        return

    state = await _ensure_auto_signal_state(application)
    if _auto_signal_remaining(state) <= 0:
        return

    recipients = _gather_signal_recipients(context)
    await _broadcast_auto_signal_warning(context, recipients)


async def _auto_signal_delivery_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    job = cast(JobType | None, context.job)  # type: ignore[assignment]
    if job is None:
        return

    application = cast(ApplicationType, context.application)  # type: ignore[assignment]

    _unregister_auto_job_reference(application.bot_data, job)

    state = await _ensure_auto_signal_state(application)
    if _auto_signal_remaining(state) <= 0:
        return

    delivered, failed, payload, truncated = await _execute_auto_signal(context, application)
    LOGGER.info(
        "Auto signal sent: pair=%s direction=%s delivered=%s failed=%s truncated=%s",
        payload.get("pair"),
        payload.get("direction"),
        delivered,
        failed,
        truncated,
    )


async def _auto_signal_refresh_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    application = cast(ApplicationType, context.application)  # type: ignore[assignment]
    await _setup_auto_signals_for_today(application)


async def _application_post_init(application: ApplicationType) -> None:
    await _setup_auto_signals_for_today(application)
    _schedule_daily_auto_signal_refresh(application)


async def _handle_admin_auto_trigger(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    user_data: dict[str, Any],
    language: str,
) -> None:
    application = cast(ApplicationType, context.application)  # type: ignore[assignment]
    storage = _get_storage_from_bot_data(application.bot_data)
    if not storage.get_global_signals():
        await _send_admin_signals_view(
            context,
            chat_id,
            user_data,
            language,
            _get_text("auto_signal_not_configured", language),
        )
        return

    state = await _ensure_auto_signal_state(application)
    remaining_before = _auto_signal_remaining(state)
    if remaining_before <= 0:
        await _send_admin_signals_view(
            context,
            chat_id,
            user_data,
            language,
            _get_text("auto_signal_trigger_no_remaining", language),
        )
        return

    recipients = _gather_signal_recipients(context)
    if not recipients:
        await _send_admin_signals_view(
            context,
            chat_id,
            user_data,
            language,
            _get_text("manual_signal_no_recipients", language),
        )
        return

    cancelled = _cancel_one_scheduled_auto_job(application.bot_data)
    if not cancelled:
        LOGGER.info("Admin auto trigger executed without pending scheduled jobs.")

    await _broadcast_auto_signal_warning(context, recipients)
    await asyncio.sleep(AUTO_SIGNAL_WARNING_SECONDS)

    delivered, failed, payload, truncated = await _execute_auto_signal(context, application)
    state = _auto_signal_state(application.bot_data)
    remaining_after = _auto_signal_remaining(state)

    direction_key = "direction_up" if payload.get("direction") == "buy" else "direction_down"
    direction_label = _label(direction_key, language)
    pair = payload.get("pair", "?")

    notice_parts: list[str] = []
    notice_parts.append(f"{pair} — {direction_label}")
    notice_parts.append(
        _get_text("auto_signal_trigger_scheduled", language).format(remaining=remaining_after)
    )
    if delivered:
        notice_parts.append(_get_text("manual_signal_sent", language).format(count=delivered))
    if truncated:
        notice_parts.append(_get_text("manual_signal_truncated", language))
    if failed:
        limited_ids = ", ".join(str(uid) for uid in failed[:10])
        notice_parts.append(
            _get_text("manual_signal_failed_recipients", language).format(
                count=len(failed),
                ids=limited_ids,
            )
        )

    await _send_admin_signals_view(
        context,
        chat_id,
        user_data,
        language,
        "\n".join(notice_parts),
    )

    await _setup_auto_signals_for_today(application)

def _parse_working_hours(text: str) -> str | None:
    value = text.strip()
    if re.fullmatch(r"\d{2}:\d{2}-\d{2}:\d{2}", value):
        return value
    return None


def _parse_signals_range(text: str) -> str | None:
    value = text.strip()
    if re.fullmatch(r"\d+\s*-\s*\d+", value):
        return value.replace(" ", "")
    return None


def build_application(*, token: str | None = None):
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    resolved_token = token or get_bot_token()
    defaults = Defaults(parse_mode=ParseMode.HTML)
    application = Application.builder().token(resolved_token).defaults(defaults).build()
    if application.job_queue is None:
        raise RuntimeError(
            "Job queue is not available. Install python-telegram-bot with the job-queue extra, "
            "for example: pip install \"python-telegram-bot[job-queue]==21.4\"."
        )

    storage = create_storage(DatabaseConfig.from_env())
    application.bot_data[STORAGE_KEY] = storage

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("menu", main_menu_command))
    application.add_handler(CommandHandler("admin", admin_command))
    application.add_handler(
        CallbackQueryHandler(
            handle_language_selection,
            pattern=rf"^{_LANGUAGE_CALLBACK_PREFIX}(ru|en)$",
        )
    )
    application.add_handler(
        CallbackQueryHandler(handle_subscription_check, pattern=r"^check_subscription$")
    )
    application.add_handler(CallbackQueryHandler(handle_intro_actions, pattern=r"^intro:"))
    application.add_handler(CallbackQueryHandler(handle_admin_actions, pattern=r"^admin:"))
    application.add_handler(CallbackQueryHandler(handle_main_menu_actions, pattern=r"^main:"))

    application.add_handler(
        MessageHandler(filters.TEXT & (~filters.COMMAND), handle_text_message)
    )

    application.post_init = _application_post_init  # type: ignore[assignment]

    _ensure_bot_defaults(application.bot_data)
    LOGGER.info("Application configured. Ready to start polling.")
    if not ADMIN_IDS:
        LOGGER.warning("No admin IDs configured. Admin features will be unavailable.")
    return application


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat = update.effective_chat
    user = update.effective_user
    if not chat or not user or not _is_private_chat(chat):
        return

    user_data = _user_data(context)
    user_data.pop(AWAITING_POCKET_ID_KEY, None)
    user_data.pop(LANGUAGE_CHANGE_FLAG, None)
    _clear_tracked_message_id(user_data, VIEW_MESSAGE_KEY, None)

    _set_user_stage(context.bot_data, user.id, STAGE_LANGUAGE)
    await _send_language_prompt(context, chat.id, user_data, include_back=False)


async def main_menu_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat = update.effective_chat
    user = update.effective_user
    if not chat or not user or not _is_private_chat(chat):
        return

    user_data = _user_data(context)
    language = user_data.get(LANGUAGE_KEY, DEFAULT_LANGUAGE)
    await send_main_menu(context, chat.id, language, user_data=user_data)


async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat = update.effective_chat
    user = update.effective_user
    if not chat or not user or not _is_private_chat(chat):
        return

    user_data = _user_data(context)
    language = user_data.get(LANGUAGE_KEY, DEFAULT_LANGUAGE)
    if user.id not in ADMIN_IDS:
        message = _get_text("not_admin", language)
        if update.message:
            await update.message.reply_text(_bold(message) or "")
        else:
            await context.bot.send_message(chat_id=chat.id, text=_bold(message) or "")
        return

    await _send_admin_root(context, chat.id, user_data, language)


async def handle_language_selection(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    query = update.callback_query
    user = update.effective_user
    if not query or not user:
        return

    choice = query.data.removeprefix(_LANGUAGE_CALLBACK_PREFIX) if query.data else ""
    # language = choice if choice in {"ru","en"} else DEFAULT_LANGUAGE
    language = choice if choice in {"en"} else DEFAULT_LANGUAGE  # changed

    user_data = _user_data(context)
    user_data[LANGUAGE_KEY] = language
    user_data.pop(AWAITING_POCKET_ID_KEY, None)

    confirmation = _get_text("language_set", language)
    await query.answer(text=confirmation, show_alert=False)

    chat = update.effective_chat
    if not _is_private_chat(chat):
        return
    chat_id = chat.id if chat else user.id
    message = query.message
    if isinstance(message, Message):
        await _safe_delete_message(message)
        _clear_tracked_message_id(user_data, VIEW_MESSAGE_KEY, message.message_id)

    language_change = user_data.pop(LANGUAGE_CHANGE_FLAG, False)
    if language_change or _is_user_approved(context.bot_data, user.id):
        await send_main_menu(context, chat_id, language, user_data=user_data)
        return

    await _send_intro_prompt(context, chat_id, user.id, language, user_data)
    LOGGER.info(f"Конец handle_language_selection") # <-- ДОБАВЬТЕ ЭТО


async def handle_subscription_check(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    query = update.callback_query
    user = update.effective_user
    if not query or not user:
        return

    user_data = _user_data(context)
    language = user_data.get(LANGUAGE_KEY, DEFAULT_LANGUAGE)
    chat = update.effective_chat
    if not _is_private_chat(chat):
        await query.answer()
        return
    chat_id = chat.id if chat else user.id
    message = query.message

    missing_targets: list[str] = []
    for target_key, target_username, _ in (
        # ("chat", _SUBSCRIPTION_CHAT_USERNAME, _SUBSCRIPTION_CHAT_LINK),  # changed
        ("channel", _SUBSCRIPTION_CHANNEL_USERNAME, _SUBSCRIPTION_CHANNEL_LINK),
    ):
        try:
            member = await context.bot.get_chat_member(target_username, user.id)
        except TelegramError as exc:
            LOGGER.warning(
                "Failed to get chat member for %s and user %s: %s",
                target_username,
                user.id,
                exc,
            )
            missing_targets.append(target_key)
            continue

        if member.status in (ChatMemberStatus.LEFT, ChatMemberStatus.BANNED):
            missing_targets.append(target_key)

    if missing_targets:
        targets_text = ", ".join(
            _TARGET_LABELS[target][language] for target in missing_targets
        )
        text = _get_text("subscription_missing", language).format(targets=targets_text)
        try:
            await query.edit_message_text(
                text=text,
                reply_markup=_build_subscription_keyboard(language),
            )
        except TelegramError as exc:
            LOGGER.warning("Failed to edit subscription prompt: %s", exc)
        return

    await query.answer(text=_get_text("subscription_success", language), show_alert=False)
    if isinstance(message, Message):
        await _safe_delete_message(message)
        _clear_tracked_message_id(user_data, VIEW_MESSAGE_KEY, message.message_id)

    user_data[AWAITING_POCKET_ID_KEY] = True
    await _send_enter_pocket_id_prompt(context, chat_id, user.id, language, user_data)


async def handle_intro_actions(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    query = update.callback_query
    user = update.effective_user
    if not query or not user:
        return

    user_data = _user_data(context)
    language = user_data.get(LANGUAGE_KEY, DEFAULT_LANGUAGE)
    parts = (query.data or "").split(":")
    if len(parts) < 2:
        await query.answer()
        return

    action = parts[1]
    chat = update.effective_chat
    if not _is_private_chat(chat):
        await query.answer()
        return
    chat_id = chat.id if chat else user.id

    message = query.message
    if isinstance(message, Message):
        await _safe_delete_message(message)
        _clear_tracked_message_id(user_data, VIEW_MESSAGE_KEY, message.message_id)

    if action == "start":
        await query.answer()
        await _send_subscription_prompt(context, chat_id, user.id, language, user_data)
    else:
        await query.answer()


async def handle_text_message(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    message = update.message
    user = update.effective_user
    if not message or not user:
        return

    if not _is_private_chat(message.chat):
        return

    user_data = _user_data(context)
    language = user_data.get(LANGUAGE_KEY, DEFAULT_LANGUAGE)

    if user.id in ADMIN_IDS:
        admin_expectation = cast(dict[str, Any] | None, user_data.get(ADMIN_INPUT_KEY))
        if admin_expectation:
            await _process_admin_text_input(update, context, admin_expectation, user_data, language)
            return

    if user_data.get(AWAITING_POCKET_ID_KEY):
        pocket_id = (message.text or "").strip()
        if not _is_valid_pocket_id(pocket_id):
            await message.reply_text(_bold(_get_text("invalid_pocket_id", language)) or "")
            return

        user_data[AWAITING_POCKET_ID_KEY] = False
        existing_application = _get_application(context.bot_data, user.id)
        if existing_application and existing_application.get("status") == "rejected":
            _set_user_stage(context.bot_data, user.id, STAGE_REJECTED)
            await _send_tracked_message(
                context,
                message.chat_id,
                user_data,
                text=_get_text("application_rejected_blocked", language),
            )
            return
        application = _store_application(context, update, pocket_id, language)
        await _send_tracked_message(
            context,
            message.chat_id,
            user_data,
            text=_get_text("application_received", language),
        )
        await _notify_admins(context, application)
        return

    await message.reply_text(_bold(_get_text("default_reply", language)) or "")


async def handle_admin_actions(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    query = update.callback_query
    user = update.effective_user
    if not query or not user:
        return

    user_data = _user_data(context)
    language = user_data.get(LANGUAGE_KEY, DEFAULT_LANGUAGE)

    if user.id not in ADMIN_IDS:
        await query.answer(_get_text("not_admin", language), show_alert=True)
        return

    data = (query.data or "").split(":")
    if len(data) < 2:
        await query.answer()
        return

    action = data[1]
    sub_action = data[2] if len(data) > 2 else ""

    if action in {"approve", "reject"}:
        if len(data) < 3:
            await query.answer()
            return
        try:
            target_user_id = int(data[2])
        except ValueError:
            LOGGER.warning("Invalid user id in admin callback: %s", data[2])
            await query.answer()
            return

        application = _get_application(context.bot_data, target_user_id)
        if not application:
            await query.answer(_get_text("no_pending_applications", language), show_alert=True)
            return

        if action == "approve":
            await _approve_application(context, application)
            await query.edit_message_text("Заявка одобрена.")
        else:
            await _reject_application(context, application)
            await query.edit_message_text("Заявка отклонена.")
        return

    chat = update.effective_chat
    if not _is_private_chat(chat):
        await query.answer()
        return
    chat_id = chat.id if chat else user.id

    message = query.message
    if isinstance(message, Message):
        await _safe_delete_message(message)
        _clear_tracked_message_id(user_data, ADMIN_VIEW_MESSAGE_KEY, message.message_id)

    await query.answer()

    if action in {"open", "requests"}:
        await _send_admin_requests_view(context, chat_id, user_data, language)
    elif action in {"root"}:
        await _send_admin_root(context, chat_id, user_data, language)
    elif action == "manual":
        state = _manual_state(user_data)
        if not sub_action:
            await _send_admin_manual_signal_pair_selection(context, chat_id, user_data, language)
            return

        if sub_action == "pair":
            if len(data) < 4:
                await _send_admin_manual_signal_pair_selection(context, chat_id, user_data, language)
                return
            pair_choice = data[3].upper()
            if pair_choice not in MANUAL_SIGNAL_PAIRS:
                await _send_admin_manual_signal_pair_selection(context, chat_id, user_data, language)
                return
            state["pair"] = pair_choice
            state.pop("direction", None)
            state.pop("time", None)
            await _send_admin_manual_signal_direction(context, chat_id, user_data, language)
            return

        if sub_action == "direction":
            if len(data) < 4:
                await _send_admin_manual_signal_direction(context, chat_id, user_data, language)
                return
            direction_choice = data[3]
            if direction_choice not in {"buy", "sell"}:
                await _send_admin_manual_signal_direction(context, chat_id, user_data, language)
                return
            state["direction"] = direction_choice
            state.pop("time", None)
            await _send_admin_manual_signal_time(context, chat_id, user_data, language)
            return

        if sub_action == "time":
            if len(data) < 4:
                await _send_admin_manual_signal_time(context, chat_id, user_data, language)
                return
            time_choice = data[3]
            if time_choice == "custom":
                await _prompt_manual_time_input(context, chat_id, user_data, language)
                return
            try:
                time_value = float(time_choice)
            except ValueError:
                await _send_admin_manual_signal_time(context, chat_id, user_data, language)
                return
            state["time"] = time_value
            user_data.pop(ADMIN_INPUT_KEY, None)
            await _finalize_manual_signal(context, chat_id, user_data, language)
            return

        if sub_action == "back":
            target = data[3] if len(data) > 3 else ""
            if target == "pair":
                state.pop("direction", None)
                state.pop("time", None)
                await _send_admin_manual_signal_pair_selection(context, chat_id, user_data, language)
                return
            if target == "direction":
                state.pop("time", None)
                await _send_admin_manual_signal_direction(context, chat_id, user_data, language)
                return
            if target == "time":
                user_data.pop(ADMIN_INPUT_KEY, None)
                await _send_admin_manual_signal_time(context, chat_id, user_data, language)
                return
            await _send_admin_manual_signal_pair_selection(context, chat_id, user_data, language)
            return

        if sub_action == "cancel":
            _reset_manual_signal_state(user_data)
            user_data.pop(ADMIN_INPUT_KEY, None)
            await _send_admin_manual_summary(
                context,
                chat_id,
                user_data,
                language,
                _get_text("manual_signal_cancelled", language),
                allow_retry=True,
            )
            return

        await _send_admin_manual_signal_pair_selection(context, chat_id, user_data, language)
        return
    elif action == "signals":
        _ensure_bot_defaults(context.bot_data)
        if sub_action in {"on", "off"}:
            desired = sub_action == "on"
            storage = _get_storage_from_bot_data(context.bot_data)
            current = storage.get_global_signals()
            if current == desired:
                notice = _get_text("signals_toggle_already", language).format(
                    status=_get_signals_status_text(context.bot_data, language)
                )
            else:
                storage.set_global_signals(desired)
                application = context.application  # type: ignore[assignment]
                await _setup_auto_signals_for_today(application)
                notice = _get_text(
                    "signals_toggle_success_on" if desired else "signals_toggle_success_off",
                    language,
                )
            await _send_admin_signals_view(context, chat_id, user_data, language, notice)
        elif sub_action == "trigger":
            await _handle_admin_auto_trigger(context, chat_id, user_data, language)
        else:
            await _send_admin_signals_view(context, chat_id, user_data, language)
    elif action == "users":
        if sub_action == "approved":
            approved_notice: str | None = None
            if len(data) >= 4 and data[3] == "remove":
                if len(data) < 5:
                    approved_notice = _get_text("admin_user_remove_missing", language).format(
                        user_id="?"
                    )
                else:
                    target_raw = data[4]
                    try:
                        target_user_id = int(target_raw)
                    except ValueError:
                        LOGGER.warning("Invalid user id for removal: %s", target_raw)
                        approved_notice = _get_text("admin_user_remove_missing", language).format(
                            user_id=target_raw
                        )
                    else:
                        approved_notice = await _remove_approved_user(
                            context,
                            target_user_id,
                            admin_language=language,
                        )
            await _send_admin_user_list(
                context,
                chat_id,
                user_data,
                language,
                status="approved",
                notice=approved_notice,
            )
        elif sub_action == "rejected":
            rejected_notice: str | None = None
            if len(data) >= 4 and data[3] == "unblock":
                if len(data) < 5:
                    rejected_notice = _get_text("admin_user_unblock_missing", language).format(
                        user_id="?"
                    )
                else:
                    target_raw = data[4]
                    try:
                        target_user_id = int(target_raw)
                    except ValueError:
                        LOGGER.warning("Invalid user id for unblock: %s", target_raw)
                        rejected_notice = _get_text("admin_user_unblock_missing", language).format(
                            user_id=target_raw
                        )
                    else:
                        rejected_notice = await _unblock_rejected_user(
                            context,
                            target_user_id,
                            admin_language=language,
                        )
            await _send_admin_user_list(
                context,
                chat_id,
                user_data,
                language,
                status="rejected",
                notice=rejected_notice,
            )
        else:
            await _send_admin_users_view(context, chat_id, user_data, language)
    elif action == "settings":
        if sub_action == "working_hours":
            await _prompt_admin_input(context, chat_id, user_data, language, "working_hours")
        elif sub_action == "signals_range":
            await _prompt_admin_input(context, chat_id, user_data, language, "signals_range")
        else:
            await _send_admin_settings_summary(context, chat_id, user_data, language)
    elif action == "back_to_menu":
        await send_main_menu(context, chat_id, language, user_data=user_data)
    else:
        await _send_admin_root(context, chat_id, user_data, language)


async def handle_main_menu_actions(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    query = update.callback_query
    user = update.effective_user
    if not query or not user:
        return

    user_data = _user_data(context)
    language = user_data.get(LANGUAGE_KEY, DEFAULT_LANGUAGE)
    parts = (query.data or "").split(":")
    if len(parts) < 2:
        await query.answer()
        return

    action = parts[1]
    sub_action = parts[2] if len(parts) > 2 else ""

    chat = update.effective_chat
    if not _is_private_chat(chat):
        await query.answer()
        return
    chat_id = chat.id if chat else user.id

    message = query.message
    if isinstance(message, Message):
        await _safe_delete_message(message)
        _clear_tracked_message_id(user_data, VIEW_MESSAGE_KEY, message.message_id)

    if action == "community":
        await query.answer()
        await _send_community_view(context, chat_id, user_data, language)
    elif action == "support":
        await query.answer()
        await _send_support_view(context, chat_id, user_data, language)
    elif action == "faq":
        await query.answer()
        await _send_faq_view(context, chat_id, user_data, language)
    elif action == "workspace":
        _ensure_bot_defaults(context.bot_data)
        if sub_action in {"on", "off"}:
            desired = sub_action == "on"
            storage = _get_storage_from_bot_data(context.bot_data)
            if user.id in ADMIN_IDS:
                current_global = storage.get_global_signals()
                if current_global == desired:
                    notice = _get_text("signals_toggle_already", language).format(
                        status=_get_signals_status_text(context.bot_data, language)
                    )
                else:
                    storage.set_global_signals(desired)
                    notice = _get_text(
                        "signals_toggle_success_on" if desired else "signals_toggle_success_off",
                        language,
                    )
                await query.answer(notice, show_alert=False)
                await _send_workspace_view(context, chat_id, user.id, user_data, language, notice)
                return

            current_personal = _get_personal_signals_setting(context, user.id, user_data)
            if current_personal == desired:
                status_text = _get_text(
                    "signals_status_on" if current_personal else "signals_status_off",
                    language,
                )
                notice = _get_text("signals_toggle_already", language).format(status=status_text)
            else:
                _set_personal_signals_setting(context, user.id, desired, user_data)
                notice = _get_text(
                    "personal_signals_toggle_on" if desired else "personal_signals_toggle_off",
                    language,
                )
            await query.answer(notice, show_alert=False)
            await _send_workspace_view(context, chat_id, user.id, user_data, language, notice)
            return
        else:
            await query.answer()
            await _send_workspace_view(context, chat_id, user.id, user_data, language)
    elif action == "change_language":
        await query.answer()
        user_data[LANGUAGE_CHANGE_FLAG] = True
        await _send_language_prompt(context, chat_id, user_data, include_back=True)
    elif action == "back":
        await query.answer()
        await send_main_menu(context, chat_id, language, user_data=user_data)
    else:
        await query.answer()
        await send_main_menu(context, chat_id, language, user_data=user_data)


async def send_main_menu(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    language: str,
    *,
    user_data: dict[str, Any] | None = None,
) -> None:
    if user_data is None:
        user_data = _application_user_data(context, chat_id)
    _ensure_bot_defaults(context.bot_data)
    keyboard = _build_main_menu_keyboard(language)
    caption = _get_text("main_menu_caption", language)
    await _send_tracked_message(
        context,
        chat_id,
        user_data,
        photo_path=_MAIN_MENU_IMAGE_PATH,
        caption=caption,
        text=caption,
        reply_markup=keyboard,
    )
    _set_user_stage(context.bot_data, chat_id, STAGE_COMPLETED)


async def _send_language_prompt(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    user_data: dict[str, Any],
    *,
    include_back: bool,
) -> None:
    language = user_data.get(LANGUAGE_KEY, DEFAULT_LANGUAGE)
    keyboard = _build_language_keyboard(include_back, language)
    await _send_tracked_message(
        context,
        chat_id,
        user_data,
        photo_path=_LANGUAGE_IMAGE_PATH,
        caption=_LANGUAGE_PROMPT,
        text=_LANGUAGE_PROMPT,
        reply_markup=keyboard,
    )


async def _send_intro_prompt(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    user_id: int,
    language: str,
    user_data: dict[str, Any],
) -> None:
    _set_user_stage(context.bot_data, user_id, STAGE_INTRO)
    body = _get_text("intro_description", language)
    keyboard = _build_intro_keyboard(language)
    await _send_tracked_message(
        context,
        chat_id,
        user_data,
        photo_path=_MAIN_MENU_IMAGE_PATH,
        caption=body,
        text=body,
        reply_markup=keyboard,
    )


async def _send_subscription_prompt(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    user_id: int,
    language: str,
    user_data: dict[str, Any],
) -> None:
    _set_user_stage(context.bot_data, user_id, STAGE_SUBSCRIPTION)
    await _send_tracked_message(
        context,
        chat_id,
        user_data,
        text=_get_text("subscription_prompt", language),
        reply_markup=_build_subscription_keyboard(language),
    )


async def _send_enter_pocket_id_prompt(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    user_id: int,
    language: str,
    user_data: dict[str, Any],
) -> None:
    _set_user_stage(context.bot_data, user_id, STAGE_POCKET_ID)
    await _send_tracked_message(
        context,
        chat_id,
        user_data,
        text=_get_text("enter_pocket_id", language),
    )


async def _send_workspace_view(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    user_id: int,
    user_data: dict[str, Any],
    language: str,
    notice: str | None = None,
) -> None:
    _ensure_bot_defaults(context.bot_data)
    global_status_text = _get_signals_status_text(context.bot_data, language)
    personal_enabled = _get_personal_signals_setting(context, user_id, user_data)
    personal_status_text = _get_text(
        "signals_status_on" if personal_enabled else "signals_status_off",
        language,
    )

    description = _get_text("workspace_text", language)
    global_line = _get_text("workspace_global_status", language).format(
        status=global_status_text
    )
    personal_line = _get_text("workspace_personal_status", language).format(
        status=personal_status_text
    )
    body = f"{description}\n\n{global_line}\n{personal_line}"
    if notice:
        body = f"{notice}\n\n{body}"
    await _send_tracked_message(
        context,
        chat_id,
        user_data,
        photo_path=_WORKSPACE_IMAGE_PATH,
        caption=body,
        text=body,
        reply_markup=_build_workspace_keyboard(language),
    )


async def _send_support_view(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    user_data: dict[str, Any],
    language: str,
) -> None:
    await _send_tracked_message(
        context,
        chat_id,
        user_data,
        text=_get_text("support_text", language),
        reply_markup=_build_back_keyboard("main:back", language),
    )


async def _send_faq_view(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    user_data: dict[str, Any],
    language: str,
) -> None:
    caption = _get_text("faq_caption", language)
    await _send_tracked_message(
        context,
        chat_id,
        user_data,
        photo_path=_MAIN_MENU_IMAGE_PATH,
        caption=caption,
        text=caption,
        reply_markup=_build_back_keyboard("main:back", language),
    )


async def _send_community_view(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    user_data: dict[str, Any],
    language: str,
) -> None:
    caption = _get_text("community_text", language)
    await _send_tracked_message(
        context,
        chat_id,
        user_data,
        photo_path=_COMMUNITY_IMAGE_PATH,
        caption=caption,
        text=caption,
        reply_markup=_build_community_keyboard(language),
    )


async def _send_admin_root(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    user_data: dict[str, Any],
    language: str,
) -> None:
    user_data.pop(ADMIN_INPUT_KEY, None)
    _reset_manual_signal_state(user_data)
    keyboard = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(_label("manual_signal", language), callback_data="admin:manual")],
            [InlineKeyboardButton(_label("admin_requests", language), callback_data="admin:requests")],
            [InlineKeyboardButton(_label("admin_signals", language), callback_data="admin:signals")],
            [InlineKeyboardButton(_label("admin_users", language), callback_data="admin:users")],
            [InlineKeyboardButton(_label("admin_settings", language), callback_data="admin:settings")],
            [InlineKeyboardButton(_label("back_to_menu", language), callback_data="admin:back_to_menu")],
        ]
    )
    await _send_tracked_message(
        context,
        chat_id,
        user_data,
        text=_get_text("admin_panel_header", language),
        reply_markup=keyboard,
        key=ADMIN_VIEW_MESSAGE_KEY,
    )


async def _send_admin_manual_signal_pair_selection(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    user_data: dict[str, Any],
    language: str,
) -> None:
    _reset_manual_signal_state(user_data)
    state = _manual_state(user_data)
    state[MANUAL_SIGNAL_STAGE_KEY] = MANUAL_SIGNAL_STAGE_PAIR

    buttons: list[list[InlineKeyboardButton]] = []
    for chunk in _chunked(MANUAL_SIGNAL_PAIRS, 3):
        row = [
            InlineKeyboardButton(pair, callback_data=f"admin:manual:pair:{pair}")
            for pair in chunk
        ]
        buttons.append(row)

    buttons.append(
        [InlineKeyboardButton(_label("manual_signal_cancel", language), callback_data="admin:root")]
    )

    await _send_tracked_message(
        context,
        chat_id,
        user_data,
        text=_get_text("manual_signal_pair_prompt", language),
        reply_markup=InlineKeyboardMarkup(buttons),
        key=ADMIN_VIEW_MESSAGE_KEY,
    )


async def _send_admin_manual_signal_direction(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    user_data: dict[str, Any],
    language: str,
) -> None:
    state = _manual_state(user_data)
    pair = state.get("pair", "")
    state[MANUAL_SIGNAL_STAGE_KEY] = MANUAL_SIGNAL_STAGE_DIRECTION

    text = _get_text("manual_signal_direction_prompt", language)
    if pair:
        text = f"{text}\n\n{pair}"

    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    _label("direction_up", language), callback_data="admin:manual:direction:buy"
                ),
                InlineKeyboardButton(
                    _label("direction_down", language), callback_data="admin:manual:direction:sell"
                ),
            ],
            [InlineKeyboardButton(_label("back", language), callback_data="admin:manual:back:pair")],
        ]
    )

    await _send_tracked_message(
        context,
        chat_id,
        user_data,
        text=text,
        reply_markup=keyboard,
        key=ADMIN_VIEW_MESSAGE_KEY,
    )


def _build_time_keyboard(language: str) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for chunk in _chunked([str(value) for value in MANUAL_SIGNAL_TIME_OPTIONS], 3):
        row: list[InlineKeyboardButton] = []
        for value_str in chunk:
            value = float(value_str)
            label = _format_time_value(value, language)
            suffix = " мин" if language == "ru" else " min"
            row.append(
                InlineKeyboardButton(
                    f"{label}{suffix}", callback_data=f"admin:manual:time:{value_str}"
                )
            )
        rows.append(row)

    rows.append(
        [
            InlineKeyboardButton(
                _label("manual_signal_custom_time", language), callback_data="admin:manual:time:custom"
            )
        ]
    )
    rows.append([InlineKeyboardButton(_label("back", language), callback_data="admin:manual:back:direction")])
    return InlineKeyboardMarkup(rows)


async def _send_admin_manual_signal_time(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    user_data: dict[str, Any],
    language: str,
) -> None:
    state = _manual_state(user_data)
    state[MANUAL_SIGNAL_STAGE_KEY] = MANUAL_SIGNAL_STAGE_TIME
    pair = state.get("pair")
    direction = state.get("direction")
    direction_label = None
    if direction == "buy":
        direction_label = _label("direction_up", language)
    elif direction == "sell":
        direction_label = _label("direction_down", language)

    lines = [_get_text("manual_signal_time_prompt", language)]
    if pair or direction_label:
        details_parts: list[str] = []
        if pair:
            details_parts.append(pair)
        if direction_label:
            details_parts.append(direction_label)
        lines.append(" / ".join(details_parts))

    await _send_tracked_message(
        context,
        chat_id,
        user_data,
        text="\n".join(lines),
        reply_markup=_build_time_keyboard(language),
        key=ADMIN_VIEW_MESSAGE_KEY,
    )


async def _prompt_manual_time_input(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    user_data: dict[str, Any],
    language: str,
    notice: str | None = None,
) -> None:
    state = _manual_state(user_data)
    state[MANUAL_SIGNAL_STAGE_KEY] = MANUAL_SIGNAL_STAGE_TIME
    user_data[ADMIN_INPUT_KEY] = {"type": "manual_time"}

    base_text = _get_text("manual_signal_custom_time_prompt", language)
    text = f"{notice}\n\n{base_text}" if notice else base_text

    keyboard = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(_label("back", language), callback_data="admin:manual:back:time")]
        ]
    )

    await _send_tracked_message(
        context,
        chat_id,
        user_data,
        text=text,
        reply_markup=keyboard,
        key=ADMIN_VIEW_MESSAGE_KEY,
    )


async def _send_admin_manual_summary(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    user_data: dict[str, Any],
    language: str,
    text: str,
    *,
    allow_retry: bool,
) -> None:
    buttons: list[list[InlineKeyboardButton]] = []
    if allow_retry:
        buttons.append(
            [InlineKeyboardButton(_label("manual_signal_send_again", language), callback_data="admin:manual")]
        )
    buttons.append([InlineKeyboardButton(_label("back", language), callback_data="admin:root")])

    await _send_tracked_message(
        context,
        chat_id,
        user_data,
        text=text,
        reply_markup=InlineKeyboardMarkup(buttons),
        key=ADMIN_VIEW_MESSAGE_KEY,
    )


def _prepare_caption_text(text: str, *, limit: int = TELEGRAM_CAPTION_LIMIT) -> tuple[str, bool]:
    if len(text) <= limit:
        return text, False
    ellipsis = "…"
    slice_limit = max(0, limit - len(ellipsis))
    truncated = text[:slice_limit].rstrip()
    if not truncated:
        return ellipsis, True
    return f"{truncated}{ellipsis}", True


async def _broadcast_manual_signal(
    context: ContextTypes.DEFAULT_TYPE,
    recipients: list[int],
    caption: str,
    image_path: Path | None,
) -> tuple[int, list[int]]:
    delivered = 0
    failed: list[int] = []
    formatted_caption = _bold(caption) or ""
    for user_id in recipients:
        try:
            if image_path:
                with image_path.open("rb") as image_fp:
                    await context.bot.send_photo(
                        chat_id=user_id,
                        photo=InputFile(image_fp, filename=image_path.name),
                        caption=formatted_caption,
                    )
            else:
                await context.bot.send_message(chat_id=user_id, text=formatted_caption)
            delivered += 1
        except TelegramError as exc:
            LOGGER.warning("Failed to deliver manual signal to %s: %s", user_id, exc)
            failed.append(user_id)
    return delivered, failed


async def _finalize_manual_signal(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    user_data: dict[str, Any],
    language: str,
) -> None:
    try:
        state = _manual_state(user_data)
        pair = state.get("pair")
        direction = state.get("direction")
        time_value = state.get("time")

        if not pair or direction not in {"buy", "sell"} or not isinstance(time_value, (int, float)):
            await _send_admin_manual_signal_pair_selection(context, chat_id, user_data, language)
            return

        _ensure_bot_defaults(context.bot_data)
        storage = _get_storage_from_bot_data(context.bot_data)
        signals_enabled = storage.get_global_signals()
        if not signals_enabled:
            await _send_admin_manual_summary(
                context,
                chat_id,
                user_data,
                language,
                _get_text("manual_signal_signals_disabled", language),
                allow_retry=True,
            )
            return

        recipient_ids: set[int] = {
            user_id for user_id in storage.list_signal_recipient_ids(STAGE_COMPLETED) if user_id not in ADMIN_IDS
        }

        for user_id in list(recipient_ids):
            _get_personal_signals_setting(context, user_id)

        for admin_id in ADMIN_IDS:
            if _get_personal_signals_setting(context, admin_id):
                recipient_ids.add(admin_id)

        if not recipient_ids:
            await _send_admin_manual_summary(
                context,
                chat_id,
                user_data,
                language,
                _get_text("manual_signal_no_recipients", language),
                allow_retry=True,
            )
            return

        snapshot = await _fetch_tradingview_levels(pair)
        data_notice_summary: str | None = None
        if snapshot is None:
            data_notice_summary = _get_text("manual_signal_data_unavailable", language)
            notice_en = _get_text("manual_signal_data_unavailable", SIGNAL_MESSAGE_LANGUAGE)
            raw_caption = _format_manual_signal_fallback(
                pair=pair,
                direction=direction,
                time_minutes=float(time_value),
                language=SIGNAL_MESSAGE_LANGUAGE,
                notice=notice_en,
                technical_snapshot=None,
            )
        else:
            has_price_levels = (
                snapshot.close is not None
                and snapshot.support is not None
                and snapshot.resistance is not None
            )

            if not has_price_levels:
                data_notice_summary = _get_text("manual_signal_data_unavailable", language)
                notice_en = _get_text("manual_signal_data_unavailable", SIGNAL_MESSAGE_LANGUAGE)
                raw_caption = _format_manual_signal_fallback(
                    pair=pair,
                    direction=direction,
                    time_minutes=float(time_value),
                    language=SIGNAL_MESSAGE_LANGUAGE,
                    notice=notice_en,
                    technical_snapshot=snapshot,
                    current_value=snapshot.close,
                    support=snapshot.support,
                    resistance=snapshot.resistance,
                )
            else:
                close_value = cast(float, snapshot.close)
                support_value = cast(float, snapshot.support)
                resistance_value = cast(float, snapshot.resistance)
                raw_caption = _format_manual_signal_message(
                    pair=pair,
                    direction=direction,
                    time_minutes=float(time_value),
                    language=SIGNAL_MESSAGE_LANGUAGE,
                    current_value=close_value,
                    support=support_value,
                    resistance=resistance_value,
                    technical_snapshot=snapshot,
                )

        image_path = _resolve_signal_image(pair, "BUY" if direction == "buy" else "SELL")
        recipients = sorted(recipient_ids)
        caption, was_truncated = _prepare_caption_text(raw_caption)
        delivered, failed = await _broadcast_manual_signal(context, recipients, caption, image_path)

        summary_lines: list[str] = []
        if data_notice_summary:
            summary_lines.append(data_notice_summary)
        if not image_path:
            summary_lines.append(_get_text("manual_signal_image_missing", language))
        if was_truncated:
            summary_lines.append(_get_text("manual_signal_truncated", language))
        summary_lines.append(
            _get_text("manual_signal_sent", language).format(count=delivered)
        )
        if failed:
            limited_ids = ", ".join(str(uid) for uid in failed[:10])
            summary_lines.append(
                _get_text("manual_signal_failed_recipients", language).format(
                    count=len(failed),
                    ids=limited_ids,
                )
            )

        _reset_manual_signal_state(user_data)

        await _send_admin_manual_summary(
            context,
            chat_id,
            user_data,
            language,
            "\n\n".join(summary_lines) if summary_lines else _get_text("manual_signal_ready", language),
            allow_retry=True,
        )
    except Exception as exc:  # pragma: no cover - defensive logging
        LOGGER.exception("Manual signal broadcast failed: %s", exc)
        _reset_manual_signal_state(user_data)
        await _send_admin_manual_summary(
            context,
            chat_id,
            user_data,
            language,
            _get_text("manual_signal_unknown_error", language),
            allow_retry=True,
        )


async def _send_admin_requests_view(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    user_data: dict[str, Any],
    language: str,
) -> None:
    pending = _get_pending_applications(context.bot_data)
    keyboard = InlineKeyboardMarkup(
        [[InlineKeyboardButton(_label("back", language), callback_data="admin:root")]]
    )
    if not pending:
        await _send_tracked_message(
            context,
            chat_id,
            user_data,
            text=_get_text("no_pending_applications", language),
            reply_markup=keyboard,
            key=ADMIN_VIEW_MESSAGE_KEY,
        )
        return

    summary = _get_text("pending_summary", language).format(count=len(pending))
    await _send_tracked_message(
        context,
        chat_id,
        user_data,
        text=summary,
        reply_markup=keyboard,
        key=ADMIN_VIEW_MESSAGE_KEY,
    )
    for application in pending:
        await _send_admin_application_card(context, application, chat_id)


async def _send_admin_signals_view(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    user_data: dict[str, Any],
    language: str,
    notice: str | None = None,
) -> None:
    status_text = _get_signals_status_text(context.bot_data, language)
    header = _get_text("admin_signals_header", language).format(status=status_text)

    auto_status_line: str | None = None
    application = context.application  # type: ignore[assignment]
    state = await _ensure_auto_signal_state(application)
    target = int(state.get("target", 0))
    sent = int(state.get("sent", 0))
    remaining = _auto_signal_remaining(state)
    auto_status_line = _get_text("auto_signal_status", language).format(
        sent=sent,
        target=target,
        remaining=remaining,
    )

    body_lines = [header]
    if auto_status_line:
        body_lines.append("")
        body_lines.append(auto_status_line)
    text = "\n".join(body_lines)
    if notice:
        text = f"{notice}\n\n{text}"

    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(_label("admin_enable", language), callback_data="admin:signals:on"),
                InlineKeyboardButton(
                    _label("admin_disable", language), callback_data="admin:signals:off"
                ),
            ],
            [
                InlineKeyboardButton(
                    _label("admin_auto_trigger", language), callback_data="admin:signals:trigger"
                )
            ],
            [InlineKeyboardButton(_label("back", language), callback_data="admin:root")],
        ]
    )
    await _send_tracked_message(
        context,
        chat_id,
        user_data,
        text=text,
        reply_markup=keyboard,
        key=ADMIN_VIEW_MESSAGE_KEY,
    )


async def _send_admin_users_view(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    user_data: dict[str, Any],
    language: str,
) -> None:
    applications = _get_applications(context.bot_data)
    approved = sum(1 for app in applications.values() if app.get("status") == "approved")
    rejected = sum(1 for app in applications.values() if app.get("status") == "rejected")
    summary = _get_text("admin_users_summary", language).format(
        approved=approved,
        rejected=rejected,
    )
    text = f"{_get_text('admin_users_header', language)}\n\n{summary}"
    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    _label("admin_approved", language), callback_data="admin:users:approved"
                ),
                InlineKeyboardButton(
                    _label("admin_rejected", language), callback_data="admin:users:rejected"
                ),
            ],
            [InlineKeyboardButton(_label("back", language), callback_data="admin:root")],
        ]
    )
    await _send_tracked_message(
        context,
        chat_id,
        user_data,
        text=text,
        reply_markup=keyboard,
        key=ADMIN_VIEW_MESSAGE_KEY,
    )


async def _send_admin_user_list(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    user_data: dict[str, Any],
    language: str,
    *,
    status: str,
    notice: str | None = None,
) -> None:
    applications = _get_applications(context.bot_data)
    filtered = [
        app for app in applications.values() if app.get("status") == status
    ]
    if status == "approved":
        header = _get_text("user_list_approved_header", language)
        action_key = "admin_remove"
        action_token = "remove"
    else:
        header = _get_text("user_list_rejected_header", language)
        action_key = "admin_unblock"
        action_token = "unblock"

    body_lines: list[str] = [header]
    if filtered:
        hint = _get_text("user_list_actions_hint", language)
        if hint:
            body_lines.append(hint)
        body_lines.append("")
        for index, app in enumerate(filtered, start=1):
            body_lines.append(f"{index}. {_format_user_entry(app)}")
    else:
        body_lines.append("")
        body_lines.append(_get_text("user_list_empty", language))

    text = "\n".join(body_lines)
    if notice:
        text = f"{notice}\n\n{text}"

    buttons: list[list[InlineKeyboardButton]] = []
    if filtered:
        for app in filtered:
            action_label = _label(action_key, language)
            label = _format_admin_user_button(app, action_label)
            callback = f"admin:users:{status}:{action_token}:{app['user_id']}"
            buttons.append([InlineKeyboardButton(label, callback_data=callback)])
    buttons.append([InlineKeyboardButton(_label("back", language), callback_data="admin:users")])

    keyboard = InlineKeyboardMarkup(buttons)
    await _send_tracked_message(
        context,
        chat_id,
        user_data,
        text=text,
        reply_markup=keyboard,
        key=ADMIN_VIEW_MESSAGE_KEY,
    )


async def _send_admin_settings_summary(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    user_data: dict[str, Any],
    language: str,
    notice: str | None = None,
) -> None:
    _ensure_bot_defaults(context.bot_data)
    storage = _get_storage_from_bot_data(context.bot_data)
    summary = _get_text("settings_summary", language).format(
        hours=storage.get_working_hours(),
        signals_range=storage.get_signal_range(),
    )
    text = f"{notice}\n\n{summary}" if notice else summary
    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    _label("admin_working_hours", language),
                    callback_data="admin:settings:working_hours",
                )
            ],
            [
                InlineKeyboardButton(
                    _label("admin_signals_range", language),
                    callback_data="admin:settings:signals_range",
                )
            ],
            [InlineKeyboardButton(_label("back", language), callback_data="admin:root")],
        ]
    )
    await _send_tracked_message(
        context,
        chat_id,
        user_data,
        text=text,
        reply_markup=keyboard,
        key=ADMIN_VIEW_MESSAGE_KEY,
    )


async def _prompt_admin_input(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    user_data: dict[str, Any],
    language: str,
    input_type: str,
    notice: str | None = None,
) -> None:
    user_data[ADMIN_INPUT_KEY] = {"type": input_type}
    key = "request_working_hours" if input_type == "working_hours" else "request_signals_range"
    base = _get_text(key, language)
    text = f"{notice}\n\n{base}" if notice else base
    keyboard = InlineKeyboardMarkup(
        [[InlineKeyboardButton(_label("back", language), callback_data="admin:settings")]]
    )
    await _send_tracked_message(
        context,
        chat_id,
        user_data,
        text=text,
        reply_markup=keyboard,
        key=ADMIN_VIEW_MESSAGE_KEY,
    )


async def _process_admin_text_input(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    admin_expectation: dict[str, Any],
    user_data: dict[str, Any],
    language: str,
) -> None:
    message = update.message
    chat = update.effective_chat
    if not message or not chat:
        return

    value = (message.text or "").strip()
    input_type = admin_expectation.get("type")

    if input_type == "working_hours":
        parsed = _parse_working_hours(value)
        if not parsed:
            await _prompt_admin_input(
                context,
                chat.id,
                user_data,
                language,
                "working_hours",
                notice=_get_text("invalid_settings_input", language),
            )
            return
        storage = _get_storage_from_bot_data(context.bot_data)
        storage.set_working_hours(parsed)
        application = cast(ApplicationType, context.application)  # type: ignore[assignment]
        await _setup_auto_signals_for_today(application)
        user_data.pop(ADMIN_INPUT_KEY, None)
        await _send_admin_settings_summary(
            context,
            chat.id,
            user_data,
            language,
            notice=_get_text("working_hours_updated", language),
        )
    elif input_type == "signals_range":
        parsed = _parse_signals_range(value)
        if not parsed:
            await _prompt_admin_input(
                context,
                chat.id,
                user_data,
                language,
                "signals_range",
                notice=_get_text("invalid_settings_input", language),
            )
            return
        storage = _get_storage_from_bot_data(context.bot_data)
        storage.set_signal_range(parsed)
        application = cast(ApplicationType, context.application)  # type: ignore[assignment]
        await _setup_auto_signals_for_today(application)
        user_data.pop(ADMIN_INPUT_KEY, None)
        await _send_admin_settings_summary(
            context,
            chat.id,
            user_data,
            language,
            notice=_get_text("signals_range_updated", language),
        )
    elif input_type == "manual_time":
        parsed_time = _parse_time_input(value)
        if parsed_time is None:
            await _prompt_manual_time_input(
                context,
                chat.id,
                user_data,
                language,
                notice=_get_text("manual_signal_time_invalid", language),
            )
            return
        state = _manual_state(user_data)
        state["time"] = parsed_time
        user_data.pop(ADMIN_INPUT_KEY, None)
        await _finalize_manual_signal(context, chat.id, user_data, language)
    else:
        user_data.pop(ADMIN_INPUT_KEY, None)
        await _send_admin_root(context, chat.id, user_data, language)


def _is_valid_pocket_id(pocket_id: str) -> bool:
    return bool(pocket_id) and any(ch.isdigit() for ch in pocket_id)


def _store_application(
    context: ContextTypes.DEFAULT_TYPE,
    update: Update,
    pocket_id: str,
    language: str,
) -> dict[str, Any]:
    user = update.effective_user
    assert user is not None
    storage = _get_storage_from_bot_data(context.bot_data)
    application: dict[str, Any] = {
        "user_id": user.id,
        "language": language,
        "pocket_id": pocket_id,
        "status": "pending",
        "first_name": user.first_name,
        "last_name": user.last_name,
        "username": user.username,
    }
    application = storage.upsert_application(application)
    _set_user_stage(context.bot_data, user.id, STAGE_PENDING)
    return application


async def _notify_admins(
    context: ContextTypes.DEFAULT_TYPE, application: dict[str, Any]
) -> None:
    if not ADMIN_IDS:
        LOGGER.info("No admins configured; skipping notification")
        return

    text_lines = [
        "Новая заявка",
        f"ID пользователя: {application['user_id']}",
        f"Pocket Option ID: {application['pocket_id']}",
        f"Язык: {application['language']}",
    ]
    full_name = " ".join(
        part for part in [application.get("first_name"), application.get("last_name")] if part
    )
    if full_name:
        text_lines.insert(1, f"Имя: {full_name}")
    username = application.get("username")
    if username:
        text_lines.append(f"Username: @{username}")

    text = "\n".join(text_lines)
    formatted_text = _bold(text) or ""
    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "Одобрить", callback_data=f"admin:approve:{application['user_id']}"
                ),
                InlineKeyboardButton(
                    "Отклонить", callback_data=f"admin:reject:{application['user_id']}"
                ),
            ]
        ]
    )

    for admin_id in ADMIN_IDS:
        try:
            await context.bot.send_message(
                chat_id=admin_id,
                text=formatted_text,
                reply_markup=keyboard,
            )
        except TelegramError as exc:
            LOGGER.warning("Failed to notify admin %s: %s", admin_id, exc)


def _get_pending_applications(bot_data: dict[str, Any]) -> list[dict[str, Any]]:
    storage = _get_storage_from_bot_data(bot_data)
    return storage.list_applications(status="pending")


def _get_application(
    bot_data: dict[str, Any], user_id: int
) -> dict[str, Any] | None:
    storage = _get_storage_from_bot_data(bot_data)
    return storage.get_application(user_id)


async def _approve_application(
    context: ContextTypes.DEFAULT_TYPE, application: dict[str, Any]
) -> None:
    application["status"] = "approved"
    language = application.get("language", DEFAULT_LANGUAGE)
    user_id = application["user_id"]
    storage = _get_storage_from_bot_data(context.bot_data)
    storage.set_application_status(user_id, "approved")
    _set_user_stage(context.bot_data, user_id, STAGE_COMPLETED)

    user_data = _application_user_data(context, user_id)
    await _delete_tracked_message(context, user_id, user_data, VIEW_MESSAGE_KEY)
    try:
        await context.bot.send_message(
            chat_id=user_id,
            text=_bold(_get_text("application_approved", language)) or "",
        )
    except TelegramError as exc:
        LOGGER.warning("Failed to send approval message to %s: %s", user_id, exc)
    await send_main_menu(context, user_id, language, user_data=user_data)


async def _reject_application(
    context: ContextTypes.DEFAULT_TYPE, application: dict[str, Any]
) -> None:
    application["status"] = "rejected"
    language = application.get("language", DEFAULT_LANGUAGE)
    user_id = application["user_id"]
    storage = _get_storage_from_bot_data(context.bot_data)
    storage.set_application_status(user_id, "rejected")
    _set_user_stage(context.bot_data, user_id, STAGE_REJECTED)

    user_data = _application_user_data(context, user_id)
    await _delete_tracked_message(context, user_id, user_data, VIEW_MESSAGE_KEY)
    try:
        await context.bot.send_message(
            chat_id=user_id,
            text=_bold(_get_text("application_rejected", language)) or "",
        )
    except TelegramError as exc:
        LOGGER.warning("Failed to send rejection message to %s: %s", user_id, exc)


async def _remove_approved_user(
    context: ContextTypes.DEFAULT_TYPE,
    target_user_id: int,
    *,
    admin_language: str,
) -> str:
    storage = _get_storage_from_bot_data(context.bot_data)
    application = storage.get_application(target_user_id)
    if not application or application.get("status") != "approved":
        return _get_text("admin_user_remove_missing", admin_language).format(
            user_id=target_user_id
        )

    storage.delete_application(target_user_id)
    storage.set_personal_signals(target_user_id, False)
    _set_user_stage(context.bot_data, target_user_id, STAGE_LANGUAGE)

    cached_user_data = _application_user_data(context, target_user_id)
    await _delete_tracked_message(context, target_user_id, cached_user_data, VIEW_MESSAGE_KEY)
    cached_user_data.clear()

    user_language = application.get("language", DEFAULT_LANGUAGE)
    try:
        await context.bot.send_message(
            chat_id=target_user_id,
            text=_bold(_get_text("user_removed_message", user_language)) or "",
        )
    except TelegramError as exc:
        LOGGER.warning("Failed to notify removed user %s: %s", target_user_id, exc)

    return _get_text("admin_user_removed", admin_language).format(user_id=target_user_id)


async def _unblock_rejected_user(
    context: ContextTypes.DEFAULT_TYPE,
    target_user_id: int,
    *,
    admin_language: str,
) -> str:
    storage = _get_storage_from_bot_data(context.bot_data)
    application = storage.get_application(target_user_id)
    if not application or application.get("status") != "rejected":
        return _get_text("admin_user_unblock_missing", admin_language).format(
            user_id=target_user_id
        )

    storage.set_application_status(target_user_id, "pending")
    application["status"] = "pending"
    _set_user_stage(context.bot_data, target_user_id, STAGE_PENDING)

    cached_user_data = _application_user_data(context, target_user_id)
    await _delete_tracked_message(context, target_user_id, cached_user_data, VIEW_MESSAGE_KEY)
    cached_user_data.pop(PERSONAL_SIGNALS_KEY, None)

    user_language = application.get("language", DEFAULT_LANGUAGE)
    try:
        await context.bot.send_message(
            chat_id=target_user_id,
            text=_bold(_get_text("user_unblocked_message", user_language)) or "",
        )
    except TelegramError as exc:
        LOGGER.warning("Failed to notify unblocked user %s: %s", target_user_id, exc)

    for admin_id in ADMIN_IDS:
        await _send_admin_application_card(context, application, admin_id)

    return _get_text("admin_user_unblocked", admin_language).format(user_id=target_user_id)


async def _send_admin_application_card(
    context: ContextTypes.DEFAULT_TYPE,
    application: dict[str, Any],
    admin_id: int,
) -> None:
    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "Одобрить", callback_data=f"admin:approve:{application['user_id']}"
                ),
                InlineKeyboardButton(
                    "Отклонить", callback_data=f"admin:reject:{application['user_id']}"
                ),
            ]
        ]
    )

    text_lines = [
        f"Пользователь: {application['user_id']}",
        f"Pocket Option ID: {application['pocket_id']}",
    ]
    full_name = " ".join(
        part for part in [application.get("first_name"), application.get("last_name")] if part
    )
    if full_name:
        text_lines.insert(1, f"Имя: {full_name}")
    username = application.get("username")
    if username:
        text_lines.append(f"Username: @{username}")

    try:
        await context.bot.send_message(
            chat_id=admin_id,
            text=_bold("\n".join(text_lines)) or "",
            reply_markup=keyboard,
        )
    except TelegramError as exc:
        LOGGER.warning("Failed to send application card to admin %s: %s", admin_id, exc)
