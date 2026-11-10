import json
import os
import re
import threading
import time
import html
from datetime import datetime, timedelta

import telebot
from telebot import types

from tok import tok


# ============================================================
# НАСТРОЙКА
# ============================================================

API_TOKEN = tok
bot = telebot.TeleBot(API_TOKEN)

REMINDERS_FILE = "reminders.json"
USERS_FILE = "users.json"

user_states = {}

DATA_LOCK = threading.RLock()
STATE_LOCK = threading.Lock()


# ============================================================
# JSON / ДАННЫЕ
# ============================================================

def load_json(filename, default):
    try:
        with open(filename, "r", encoding="utf-8") as file:
            return json.load(file)
    except FileNotFoundError:
        return default
    except (json.JSONDecodeError, OSError):
        print(
            f"⚠️ Не удалось прочитать {filename}. "
            f"Используется значение по умолчанию."
        )
        return default


def save_json(filename, data):
    temp_filename = filename + ".tmp"

    with open(temp_filename, "w", encoding="utf-8") as file:
        json.dump(data, file, ensure_ascii=False, indent=2)

    os.replace(temp_filename, filename)


reminders = load_json(REMINDERS_FILE, {})
if not isinstance(reminders, dict):
    reminders = {}


def load_onboarded_users():
    """
    Загружает пользователей, которые уже нажали «Начать».

    Поддерживается старый формат users.json в виде списка.
    Старый формат считается устаревшим, чтобы после обновления
    пользователь один раз снова увидел приветствие.
    """
    data = load_json(USERS_FILE, {})

    if isinstance(data, dict):
        users = data.get("onboarded_users", [])
        if isinstance(users, list):
            return set(users)

    # Старый формат из предыдущей версии:
    # [12345, 67890]
    # Не используем его как доказательство завершённого onboarding.
    return set()


onboarded_users = load_onboarded_users()


try:
    next_id_counter = max(
        (int(reminder_id) for reminder_id in reminders.keys()),
        default=0,
    ) + 1
except (ValueError, TypeError):
    next_id_counter = 1


def save_reminders():
    with DATA_LOCK:
        save_json(REMINDERS_FILE, reminders)


def save_onboarded_users():
    with DATA_LOCK:
        save_json(
            USERS_FILE,
            {
                "onboarded_users": sorted(onboarded_users),
            },
        )


def mark_onboarding_completed(chat_id):
    with DATA_LOCK:
        if chat_id in onboarded_users:
            return False

        onboarded_users.add(chat_id)
        save_onboarded_users()
        return True


# ============================================================
# СОСТОЯНИЯ ПОЛЬЗОВАТЕЛЯ
# ============================================================

def set_state(chat_id, state):
    with STATE_LOCK:
        user_states[chat_id] = state


def get_state(chat_id):
    with STATE_LOCK:
        return user_states.get(chat_id)


def clear_state(chat_id):
    with STATE_LOCK:
        user_states.pop(chat_id, None)


# ============================================================
# КЛАВИАТУРЫ
# ============================================================

def onboarding_keyboard():
    """Для нового пользователя показывается ровно одна кнопка."""
    keyboard = types.InlineKeyboardMarkup()
    keyboard.add(
        types.InlineKeyboardButton(
            "🚀 Начать",
            callback_data="onboarding:start",
        )
    )
    return keyboard


def main_menu_keyboard():
    keyboard = types.InlineKeyboardMarkup(row_width=2)

    keyboard.add(
        types.InlineKeyboardButton(
            "⏰ Напоминание",
            callback_data="menu:remind",
        ),
        types.InlineKeyboardButton(
            "🔁 Расписание",
            callback_data="menu:schedule",
        ),
    )

    keyboard.add(
        types.InlineKeyboardButton(
            "📋 Мои задачи",
            callback_data="menu:list",
        ),
        types.InlineKeyboardButton(
            "🗑 Удалить",
            callback_data="menu:delete",
        ),
    )

    keyboard.add(
        types.InlineKeyboardButton(
            "💡 Помощь",
            callback_data="menu:help",
        ),
    )

    return keyboard


def back_keyboard(target="main"):
    keyboard = types.InlineKeyboardMarkup()
    keyboard.add(
        types.InlineKeyboardButton(
            "⬅️ Назад",
            callback_data=f"menu:{target}",
        )
    )
    return keyboard


def remind_type_keyboard():
    keyboard = types.InlineKeyboardMarkup(row_width=1)

    keyboard.add(
        types.InlineKeyboardButton(
            "⚡ Быстрое — выбрать время",
            callback_data="remind:quick",
        )
    )

    keyboard.add(
        types.InlineKeyboardButton(
            "✏️ Своё время",
            callback_data="remind:custom",
        )
    )

    keyboard.add(
        types.InlineKeyboardButton(
            "🔁 Повторяющееся",
            callback_data="menu:schedule",
        )
    )

    keyboard.add(
        types.InlineKeyboardButton(
            "⬅️ Назад",
            callback_data="menu:main",
        )
    )

    return keyboard


def quick_delay_keyboard():
    keyboard = types.InlineKeyboardMarkup(row_width=2)

    for title, delay in [
        ("⏱ 10 сек", 10),
        ("⏱ 30 сек", 30),
        ("🕐 1 мин", 60),
        ("🕐 5 мин", 300),
        ("🕑 10 мин", 600),
        ("🕒 30 мин", 1800),
        ("🕓 1 час", 3600),
    ]:
        keyboard.add(
            types.InlineKeyboardButton(
                title,
                callback_data=f"remind:preset:{delay}",
            )
        )

    keyboard.add(
        types.InlineKeyboardButton(
            "✏️ Другое время",
            callback_data="remind:custom",
        )
    )

    keyboard.add(
        types.InlineKeyboardButton(
            "⬅️ Назад",
            callback_data="menu:remind",
        )
    )

    return keyboard


def finish_keyboard():
    keyboard = types.InlineKeyboardMarkup(row_width=2)

    keyboard.add(
        types.InlineKeyboardButton(
            "➕ Создать ещё",
            callback_data="menu:remind",
        ),
        types.InlineKeyboardButton(
            "📋 Открыть список",
            callback_data="menu:list",
        ),
    )

    keyboard.add(
        types.InlineKeyboardButton(
            "🏠 Главное меню",
            callback_data="menu:main",
        )
    )

    return keyboard


def schedule_days_keyboard():
    keyboard = types.InlineKeyboardMarkup(row_width=2)

    for title, weekday in [
        ("Пн", 0),
        ("Вт", 1),
        ("Ср", 2),
        ("Чт", 3),
        ("Пт", 4),
        ("Сб", 5),
        ("Вс", 6),
        ("📆 Каждый день", -1),
    ]:
        keyboard.add(
            types.InlineKeyboardButton(
                title,
                callback_data=f"schedule:day:{weekday}",
            )
        )

    keyboard.add(
        types.InlineKeyboardButton(
            "⬅️ Назад",
            callback_data="menu:main",
        )
    )

    return keyboard


def delete_list_keyboard(chat_id):
    user_reminders = get_user_reminders(chat_id)

    keyboard = types.InlineKeyboardMarkup(row_width=1)

    for reminder_id, data in sorted(
        user_reminders.items(),
        key=lambda item: int(item[0]),
    ):
        title = str(data.get("text", "")).replace("\n", " ")
        title = title[:35]

        keyboard.add(
            types.InlineKeyboardButton(
                f"🗑 #{reminder_id} — {title}",
                callback_data=f"delete:confirm:{reminder_id}",
            )
        )

    keyboard.add(
        types.InlineKeyboardButton(
            "⬅️ Назад",
            callback_data="menu:main",
        )
    )

    return keyboard


# ============================================================
# ВРЕМЯ
# ============================================================

def parse_delay(text):
    """
    Примеры:
    10
    10s / 10с / 10sec / 10сек
    5m / 5м / 5min / 5мин
    2h / 2ч / 2час / 2hour / 2hours
    """
    text = text.strip().lower()

    match = re.fullmatch(
        r"(\d+)\s*(s|с|sec|сек|m|м|min|мин|h|ч|час|hour|hours)?",
        text,
    )

    if not match:
        return None

    value = int(match.group(1))
    unit = match.group(2) or "s"

    if unit in ("s", "с", "sec", "сек"):
        return value

    if unit in ("m", "м", "min", "мин"):
        return value * 60

    if unit in ("h", "ч", "час", "hour", "hours"):
        return value * 3600

    return value


def parse_clock_time(text):
    match = re.fullmatch(
        r"(\d{1,2}):(\d{2})",
        text.strip(),
    )

    if not match:
        return None

    hour = int(match.group(1))
    minute = int(match.group(2))

    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return None

    return hour, minute


DAYS_RU = {
    "пн": 0,
    "понедельник": 0,
    "mon": 0,
    "monday": 0,
    "вт": 1,
    "вторник": 1,
    "tue": 1,
    "tuesday": 1,
    "ср": 2,
    "среда": 2,
    "wed": 2,
    "wednesday": 2,
    "чт": 3,
    "четверг": 3,
    "thu": 3,
    "thursday": 3,
    "пт": 4,
    "пятница": 4,
    "fri": 4,
    "friday": 4,
    "сб": 5,
    "суббота": 5,
    "sat": 5,
    "saturday": 5,
    "вс": 6,
    "воскресенье": 6,
    "sun": 6,
    "sunday": 6,
    "каждый день": -1,
    "ежедневно": -1,
    "daily": -1,
    "everyday": -1,
}

DAY_NAMES = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]


# ============================================================
# НАПОМИНАНИЯ
# ============================================================

def create_once_reminder(chat_id, text, delay):
    if delay <= 0:
        raise ValueError("delay must be positive")

    reminder_id = get_next_id()
    fire_at = time.time() + delay

    with DATA_LOCK:
        reminders[str(reminder_id)] = {
            "type": "once",
            "chat_id": chat_id,
            "text": text,
            "fire_at": fire_at,
        }
        save_reminders()

    threading.Thread(
        target=one_time_thread,
        args=(reminder_id, chat_id, text, delay),
        daemon=True,
    ).start()

    return reminder_id


def create_schedule_reminder(
    chat_id,
    text,
    weekday,
    hour,
    minute,
):
    reminder_id = get_next_id()

    with DATA_LOCK:
        reminders[str(reminder_id)] = {
            "type": "scheduled",
            "chat_id": chat_id,
            "text": text,
            "weekday": weekday,
            "hour": hour,
            "minute": minute,
        }
        save_reminders()

    threading.Thread(
        target=scheduled_thread,
        args=(
            reminder_id,
            chat_id,
            text,
            weekday,
            hour,
            minute,
        ),
        daemon=True,
    ).start()

    return reminder_id


def one_time_thread(reminder_id, chat_id, text, delay):
    time.sleep(delay)

    with DATA_LOCK:
        if str(reminder_id) not in reminders:
            return

        del reminders[str(reminder_id)]
        save_reminders()

    try:
        bot.send_message(
            chat_id,
            "🔔 <b>Напоминание</b>\n\n"
            f"{html.escape(text)}",
            parse_mode="HTML",
        )
    except Exception as error:
        print(
            f"❌ Ошибка отправки напоминания "
            f"{reminder_id}: {error}"
        )


def scheduled_thread(
    reminder_id,
    chat_id,
    text,
    weekday,
    hour,
    minute,
):
    while True:
        with DATA_LOCK:
            if str(reminder_id) not in reminders:
                return

        now = datetime.now()

        target = now.replace(
            hour=hour,
            minute=minute,
            second=0,
            microsecond=0,
        )

        if weekday == -1:
            if target <= now:
                target += timedelta(days=1)
        else:
            days_ahead = (weekday - now.weekday()) % 7
            target += timedelta(days=days_ahead)

            if target <= now:
                target += timedelta(weeks=1)

        wait_seconds = (
            target - datetime.now()
        ).total_seconds()

        while wait_seconds > 0:
            with DATA_LOCK:
                if str(reminder_id) not in reminders:
                    return

            chunk = min(wait_seconds, 15)
            time.sleep(chunk)
            wait_seconds -= chunk

        with DATA_LOCK:
            if str(reminder_id) not in reminders:
                return

        try:
            bot.send_message(
                chat_id,
                "🔔 <b>Напоминание</b>\n\n"
                f"{html.escape(text)}",
                parse_mode="HTML",
            )
        except Exception as error:
            print(
                f"❌ Ошибка отправки расписания "
                f"{reminder_id}: {error}"
            )


def get_next_id():
    global next_id_counter

    with DATA_LOCK:
        reminder_id = next_id_counter
        next_id_counter += 1
        return reminder_id


def restore_reminders():
    for reminder_id, data in list(reminders.items()):
        try:
            if data["type"] == "once":
                fire_at = float(data["fire_at"])
                delay = fire_at - time.time()

                if delay <= 0:
                    delay = 1

                threading.Thread(
                    target=one_time_thread,
                    args=(
                        reminder_id,
                        data["chat_id"],
                        data["text"],
                        delay,
                    ),
                    daemon=True,
                ).start()

            elif data["type"] == "scheduled":
                threading.Thread(
                    target=scheduled_thread,
                    args=(
                        reminder_id,
                        data["chat_id"],
                        data["text"],
                        data["weekday"],
                        data["hour"],
                        data["minute"],
                    ),
                    daemon=True,
                ).start()

        except (KeyError, TypeError, ValueError) as error:
            print(
                f"⚠️ Пропущено некорректное напоминание "
                f"{reminder_id}: {error}"
            )


def get_user_reminders(chat_id):
    with DATA_LOCK:
        return {
            reminder_id: data.copy()
            for reminder_id, data in reminders.items()
            if data.get("chat_id") == chat_id
        }


# ============================================================
# ТЕКСТЫ
# ============================================================

WELCOME_TEXT = """
✨ <b>Добро пожаловать!</b>

Я — твой личный <b>бот-напоминалка</b>.

Я помогу вовремя вспомнить о делах, встречах и привычках.

<b>Что я умею:</b>

⏰ <b>Одноразовые напоминания</b>
Напомню через секунды, минуты или часы.

🔁 <b>Повторяющиеся напоминания</b>
Можно настроить день недели или ежедневное расписание.

📋 <b>Список</b>
Все активные напоминания находятся в одном месте.

🗑 <b>Удаление</b>
Ненужные напоминания можно удалить кнопкой.

💾 <b>Сохранение</b>
Напоминания сохраняются в файл и восстанавливаются после перезапуска.

🎯 <b>Всё управление — через кнопки.</b>

Нажми «Начать», чтобы открыть главное меню.
"""


HELP_TEXT = """
💡 <b>Как пользоваться ботом</b>

<b>⏰ Напоминание</b>
Можно выбрать готовое время:
10 секунд, 30 секунд, 1 минута, 5 минут и т.д.

Или ввести своё:
<code>45s</code> — 45 секунд
<code>15m</code> — 15 минут
<code>2h</code> — 2 часа

<b>🔁 Расписание</b>
Выбираешь день, вводишь время <code>ЧЧ:ММ</code>,
затем текст.

Пример:
Пн → 09:00 → Стендап

<b>📋 Мои задачи</b>
Показывает активные напоминания только этого пользователя.

<b>🗑 Удалить</b>
Выбираешь нужное напоминание и подтверждаешь удаление.

⬅️ Кнопка «Назад» возвращает на предыдущий уровень меню.
"""


# ============================================================
# ОТОБРАЖЕНИЕ МЕНЮ
# ============================================================

def show_main_menu(chat_id, message_id=None):
    clear_state(chat_id)

    text = (
        "🏠 <b>Главное меню</b>\n\n"
        "━━━━━━━━━━━━━━━━\n"
        "Выбери действие:\n\n"
        "⏰ Создай разовое напоминание\n"
        "🔁 Настрой повторяющееся\n"
        "📋 Посмотри свои напоминания\n"
        "🗑 Удали ненужное\n"
        "💡 Открой помощь\n"
        "━━━━━━━━━━━━━━━━"
    )

    if message_id is not None:
        bot.edit_message_text(
            text,
            chat_id=chat_id,
            message_id=message_id,
            reply_markup=main_menu_keyboard(),
            parse_mode="HTML",
        )
    else:
        bot.send_message(
            chat_id,
            text,
            reply_markup=main_menu_keyboard(),
            parse_mode="HTML",
        )


def show_remind_menu(call):
    clear_state(call.message.chat.id)

    bot.edit_message_text(
        "⏰ <b>Создать напоминание</b>\n\n"
        "━━━━━━━━━━━━━━━━\n"
        "Выбери способ установки времени.\n"
        "━━━━━━━━━━━━━━━━",
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        reply_markup=remind_type_keyboard(),
        parse_mode="HTML",
    )


def build_list_view(chat_id):
    user_reminders = get_user_reminders(chat_id)

    if not user_reminders:
        keyboard = types.InlineKeyboardMarkup()
        keyboard.add(
            types.InlineKeyboardButton(
                "⏰ Создать напоминание",
                callback_data="menu:remind",
            )
        )
        keyboard.add(
            types.InlineKeyboardButton(
                "🏠 Главное меню",
                callback_data="menu:main",
            )
        )

        return (
            "📭 <b>Активных напоминаний нет.</b>\n\n"
            "Самое время создать первое.",
            keyboard,
        )

    lines = [
        "📋 <b>Твои активные напоминания</b>\n"
        "━━━━━━━━━━━━━━━━"
    ]

    keyboard = types.InlineKeyboardMarkup(row_width=1)

    for reminder_id, data in sorted(
        user_reminders.items(),
        key=lambda item: int(item[0]),
    ):
        safe_text = html.escape(
            str(data.get("text", ""))
        )

        if data["type"] == "once":
            fire_dt = datetime.fromtimestamp(
                data["fire_at"]
            )
            when = fire_dt.strftime(
                "%d.%m.%Y %H:%M:%S"
            )

            lines.append(
                f"\n🔹 <b>#{reminder_id}</b>\n"
                f"📝 {safe_text}\n"
                f"⏰ {when} • один раз"
            )

        else:
            day_str = (
                "каждый день"
                if data["weekday"] == -1
                else DAY_NAMES[data["weekday"]]
            )

            lines.append(
                f"\n🔹 <b>#{reminder_id}</b>\n"
                f"📝 {safe_text}\n"
                f"📅 {day_str} • "
                f"{data['hour']:02d}:{data['minute']:02d} • повторяется"
            )

        keyboard.add(
            types.InlineKeyboardButton(
                f"🗑 Удалить #{reminder_id}",
                callback_data=f"delete:confirm:{reminder_id}",
            )
        )

    keyboard.add(
        types.InlineKeyboardButton(
            "🔄 Обновить",
            callback_data="menu:list",
        )
    )
    keyboard.add(
        types.InlineKeyboardButton(
            "⬅️ Назад",
            callback_data="menu:main",
        )
    )

    return "\n".join(lines), keyboard


# ============================================================
# /START
# ============================================================

@bot.message_handler(commands=["start"])
def cmd_start(message):
    chat_id = message.chat.id
    clear_state(chat_id)

    if chat_id not in onboarded_users:
        bot.send_message(
            chat_id,
            WELCOME_TEXT,
            reply_markup=onboarding_keyboard(),
            parse_mode="HTML",
        )
        return

    show_main_menu(chat_id)


# ============================================================
# /HELP
# ============================================================

@bot.message_handler(commands=["help"])
def cmd_help(message):
    clear_state(message.chat.id)

    bot.send_message(
        message.chat.id,
        HELP_TEXT,
        reply_markup=back_keyboard("main"),
        parse_mode="HTML",
    )


# ============================================================
# /REMIND — СТАРАЯ КОМАНДА СОХРАНЕНА
# ============================================================

@bot.message_handler(commands=["remind"])
def cmd_remind(message):
    parts = message.text.split(maxsplit=2)

    if len(parts) < 3:
        bot.reply_to(
            message,
            "❌ Формат: /remind <время> <текст>\n"
            "Пример: /remind 10m Позвонить другу",
        )
        return

    delay = parse_delay(parts[1])

    if delay is None or delay <= 0:
        bot.reply_to(
            message,
            "❌ Не понял время. Используй 10s, 5m или 2h.",
        )
        return

    reminder_id = create_once_reminder(
        message.chat.id,
        parts[2],
        delay,
    )

    bot.reply_to(
        message,
        f"✅ Напоминание создано.\n"
        f"🆔 ID: {reminder_id}",
    )


# ============================================================
# /SCHEDULE — СТАРАЯ КОМАНДА СОХРАНЕНА
# ============================================================

@bot.message_handler(commands=["schedule"])
def cmd_schedule(message):
    parts = message.text.split(maxsplit=1)

    if len(parts) < 2:
        bot.reply_to(
            message,
            "❌ Формат: /schedule <день> <ЧЧ:ММ> <текст>\n"
            "Пример: /schedule пн 09:00 Стендап",
        )
        return

    rest = parts[1].strip()

    time_match = re.search(
        r"(\d{1,2}):(\d{2})",
        rest,
    )

    if not time_match:
        bot.reply_to(
            message,
            "❌ Укажи время в формате ЧЧ:ММ.",
        )
        return

    parsed_time = parse_clock_time(
        time_match.group(0)
    )

    if parsed_time is None:
        bot.reply_to(
            message,
            "❌ Некорректное время.",
        )
        return

    hour, minute = parsed_time

    day_part = rest[:time_match.start()].strip().lower()
    reminder_text = rest[time_match.end():].strip()

    if not reminder_text:
        bot.reply_to(
            message,
            "❌ Укажи текст напоминания после времени.",
        )
        return

    weekday = DAYS_RU.get(day_part)

    if weekday is None:
        bot.reply_to(
            message,
            "❌ Не понял день. Используй пн, вт, ср, чт, пт, сб, вс "
            "или «каждый день».",
        )
        return

    reminder_id = create_schedule_reminder(
        message.chat.id,
        reminder_text,
        weekday,
        hour,
        minute,
    )

    day_str = (
        "каждый день"
        if weekday == -1
        else DAY_NAMES[weekday]
    )

    bot.reply_to(
        message,
        f"✅ Расписание создано!\n"
        f"📅 {day_str}\n"
        f"⏰ {hour:02d}:{minute:02d}\n"
        f"🆔 ID: {reminder_id}",
    )


# ============================================================
# /LIST
# ============================================================

@bot.message_handler(commands=["list"])
def cmd_list(message):
    clear_state(message.chat.id)

    text, keyboard = build_list_view(
        message.chat.id
    )

    bot.send_message(
        message.chat.id,
        text,
        reply_markup=keyboard,
        parse_mode="HTML",
    )


# ============================================================
# /DELETE
# ============================================================

@bot.message_handler(commands=["delete"])
def cmd_delete(message):
    parts = message.text.split()

    if len(parts) < 2:
        bot.reply_to(
            message,
            "❌ Укажи ID. Например: /delete 3",
        )
        return

    reminder_id = parts[1].strip()
    chat_id = message.chat.id

    with DATA_LOCK:
        reminder = reminders.get(reminder_id)

        if reminder is None:
            bot.reply_to(
                message,
                f"❌ Напоминание {reminder_id} не найдено.",
            )
            return

        if reminder.get("chat_id") != chat_id:
            bot.reply_to(
                message,
                "❌ Это не твоё напоминание.",
            )
            return

        del reminders[reminder_id]
        save_reminders()

    bot.reply_to(
        message,
        f"🗑 Напоминание {reminder_id} удалено.",
    )


# ============================================================
# ПОШАГОВЫЙ ВВОД
# ============================================================

@bot.message_handler(
    func=lambda message: True,
    content_types=["text"],
)
def handle_text(message):
    chat_id = message.chat.id
    state = get_state(chat_id)

    # Новый пользователь, который ещё не нажал «Начать».
    if chat_id not in onboarded_users:
        bot.send_message(
            chat_id,
            WELCOME_TEXT,
            reply_markup=onboarding_keyboard(),
            parse_mode="HTML",
        )
        return

    if state is None:
        bot.send_message(
            chat_id,
            "🏠 Используй главное меню:",
            reply_markup=main_menu_keyboard(),
        )
        return

    if (
        isinstance(state, dict)
        and state.get("state") == "remind_custom_time"
    ):
        delay = parse_delay(message.text)

        if delay is None or delay <= 0:
            bot.send_message(
                chat_id,
                "❌ Неверное время.\n\n"
                "Примеры: <code>30s</code>, "
                "<code>5m</code>, <code>2h</code>.",
                reply_markup=back_keyboard("remind"),
                parse_mode="HTML",
            )
            return

        set_state(
            chat_id,
            {
                "state": "remind_text",
                "delay": delay,
            },
        )

        bot.send_message(
            chat_id,
            "📝 <b>Шаг 2 из 2</b>\n\n"
            "Теперь введи текст напоминания.",
            reply_markup=back_keyboard("remind"),
            parse_mode="HTML",
        )
        return

    if (
        isinstance(state, dict)
        and state.get("state") == "remind_text"
    ):
        reminder_text = message.text.strip()

        if not reminder_text:
            bot.send_message(
                chat_id,
                "❌ Текст не может быть пустым.",
                reply_markup=back_keyboard("remind"),
            )
            return

        delay = state["delay"]

        reminder_id = create_once_reminder(
            chat_id,
            reminder_text,
            delay,
        )

        clear_state(chat_id)

        if delay < 60:
            when = f"{delay} сек."
        elif delay < 3600:
            when = f"{delay // 60} мин."
        else:
            when = (
                f"{delay // 3600} ч. "
                f"{(delay % 3600) // 60} мин."
            )

        bot.send_message(
            chat_id,
            "✅ <b>Напоминание создано!</b>\n\n"
            f"⏰ Через: {when}\n"
            f"📝 {html.escape(reminder_text)}\n"
            f"🆔 ID: <code>{reminder_id}</code>",
            reply_markup=finish_keyboard(),
            parse_mode="HTML",
        )
        return

    if (
        isinstance(state, dict)
        and state.get("state") == "schedule_time"
    ):
        parsed_time = parse_clock_time(message.text)

        if parsed_time is None:
            bot.send_message(
                chat_id,
                "❌ Неверное время.\n\n"
                "Используй формат <code>ЧЧ:ММ</code>, "
                "например <code>09:00</code>.",
                reply_markup=back_keyboard("schedule"),
                parse_mode="HTML",
            )
            return

        hour, minute = parsed_time

        set_state(
            chat_id,
            {
                "state": "schedule_text",
                "weekday": state["weekday"],
                "hour": hour,
                "minute": minute,
            },
        )

        bot.send_message(
            chat_id,
            "📝 <b>Последний шаг</b>\n\n"
            "Теперь введи текст напоминания.",
            reply_markup=back_keyboard("schedule"),
            parse_mode="HTML",
        )
        return

    if (
        isinstance(state, dict)
        and state.get("state") == "schedule_text"
    ):
        reminder_text = message.text.strip()

        if not reminder_text:
            bot.send_message(
                chat_id,
                "❌ Текст не может быть пустым.",
                reply_markup=back_keyboard("schedule"),
            )
            return

        reminder_id = create_schedule_reminder(
            chat_id,
            reminder_text,
            state["weekday"],
            state["hour"],
            state["minute"],
        )

        clear_state(chat_id)

        weekday = state["weekday"]

        day_str = (
            "каждый день"
            if weekday == -1
            else DAY_NAMES[weekday]
        )

        bot.send_message(
            chat_id,
            "✅ <b>Расписание создано!</b>\n\n"
            f"📅 {day_str}\n"
            f"⏰ {state['hour']:02d}:{state['minute']:02d}\n"
            f"📝 {html.escape(reminder_text)}\n"
            f"🆔 ID: <code>{reminder_id}</code>",
            reply_markup=finish_keyboard(),
            parse_mode="HTML",
        )
        return


# ============================================================
# CALLBACK-КНОПКИ
# ============================================================

@bot.callback_query_handler(func=lambda call: True)
def callback_handler(call):
    chat_id = call.message.chat.id
    data = call.data

    try:
        bot.answer_callback_query(call.id)

        # ----------------------------------------------------
        # НОВЫЙ ПОЛЬЗОВАТЕЛЬ → НАЧАТЬ
        # ----------------------------------------------------
        if data == "onboarding:start":
            mark_onboarding_completed(chat_id)
            clear_state(chat_id)

            bot.edit_message_text(
                "🎉 <b>Готово!</b>\n\n"
                "Теперь всё управление доступно через меню.\n\n"
                "Выбери, что будем делать:",
                chat_id=chat_id,
                message_id=call.message.message_id,
                reply_markup=main_menu_keyboard(),
                parse_mode="HTML",
            )
            return

        # ----------------------------------------------------
        # ГЛАВНОЕ МЕНЮ
        # ----------------------------------------------------
        if data == "menu:main":
            show_main_menu(
                chat_id,
                message_id=call.message.message_id,
            )
            return

        # ----------------------------------------------------
        # ПОМОЩЬ
        # ----------------------------------------------------
        if data == "menu:help":
            clear_state(chat_id)

            bot.edit_message_text(
                HELP_TEXT,
                chat_id=chat_id,
                message_id=call.message.message_id,
                reply_markup=back_keyboard("main"),
                parse_mode="HTML",
            )
            return

        # ----------------------------------------------------
        # НАПОМИНАНИЯ
        # ----------------------------------------------------
        if data == "menu:remind":
            show_remind_menu(call)
            return

        # ----------------------------------------------------
        # БЫСТРОЕ ВРЕМЯ
        # ----------------------------------------------------
        if data == "remind:quick":
            clear_state(chat_id)

            bot.edit_message_text(
                "⚡ <b>Быстрое напоминание</b>\n\n"
                "━━━━━━━━━━━━━━━━\n"
                "Выбери готовое время:\n"
                "━━━━━━━━━━━━━━━━",
                chat_id=chat_id,
                message_id=call.message.message_id,
                reply_markup=quick_delay_keyboard(),
                parse_mode="HTML",
            )
            return

        # ----------------------------------------------------
        # ГОТОВЫЕ ВАРИАНТЫ ВРЕМЕНИ
        # ----------------------------------------------------
        if data.startswith("remind:preset:"):
            delay = int(data.split(":")[-1])

            set_state(
                chat_id,
                {
                    "state": "remind_text",
                    "delay": delay,
                },
            )

            if delay < 60:
                when = f"{delay} сек."
            elif delay < 3600:
                when = f"{delay // 60} мин."
            else:
                when = f"{delay // 3600} ч."

            bot.edit_message_text(
                f"✅ <b>Время: {when}</b>\n\n"
                "📝 Теперь введи текст напоминания:",
                chat_id=chat_id,
                message_id=call.message.message_id,
                reply_markup=back_keyboard("remind"),
                parse_mode="HTML",
            )
            return

        # ----------------------------------------------------
        # СВОЁ ВРЕМЯ
        # ----------------------------------------------------
        if data == "remind:custom":
            set_state(
                chat_id,
                {
                    "state": "remind_custom_time",
                },
            )

            bot.edit_message_text(
                "✏️ <b>Своё время</b>\n\n"
                "Введи время:\n\n"
                "• <code>30s</code> — 30 секунд\n"
                "• <code>5m</code> — 5 минут\n"
                "• <code>2h</code> — 2 часа\n"
                "• <code>30</code> — 30 секунд",
                chat_id=chat_id,
                message_id=call.message.message_id,
                reply_markup=back_keyboard("remind"),
                parse_mode="HTML",
            )
            return

        # ----------------------------------------------------
        # РАСПИСАНИЕ
        # ----------------------------------------------------
        if data == "menu:schedule":
            clear_state(chat_id)

            bot.edit_message_text(
                "🔁 <b>Повторяющееся расписание</b>\n\n"
                "━━━━━━━━━━━━━━━━\n"
                "1️⃣ Выбери день.\n"
                "2️⃣ Введи время.\n"
                "3️⃣ Введи текст.\n"
                "━━━━━━━━━━━━━━━━",
                chat_id=chat_id,
                message_id=call.message.message_id,
                reply_markup=schedule_days_keyboard(),
                parse_mode="HTML",
            )
            return

        # ----------------------------------------------------
        # ВЫБОР ДНЯ
        # ----------------------------------------------------
        if data.startswith("schedule:day:"):
            weekday = int(data.split(":")[-1])

            if weekday not in [-1, 0, 1, 2, 3, 4, 5, 6]:
                bot.answer_callback_query(
                    call.id,
                    "Некорректный день.",
                    show_alert=True,
                )
                return

            set_state(
                chat_id,
                {
                    "state": "schedule_time",
                    "weekday": weekday,
                },
            )

            day_str = (
                "каждый день"
                if weekday == -1
                else DAY_NAMES[weekday]
            )

            bot.edit_message_text(
                f"📅 <b>{day_str}</b>\n\n"
                "⏰ Теперь введи время в формате "
                "<code>ЧЧ:ММ</code>.\n\n"
                "Например: <code>09:00</code>",
                chat_id=chat_id,
                message_id=call.message.message_id,
                reply_markup=back_keyboard("schedule"),
                parse_mode="HTML",
            )
            return

        # ----------------------------------------------------
        # СПИСОК
        # ----------------------------------------------------
        if data == "menu:list":
            clear_state(chat_id)

            text, keyboard = build_list_view(chat_id)

            bot.edit_message_text(
                text,
                chat_id=chat_id,
                message_id=call.message.message_id,
                reply_markup=keyboard,
                parse_mode="HTML",
            )
            return

        # ----------------------------------------------------
        # УДАЛЕНИЕ
        # ----------------------------------------------------
        if data == "menu:delete":
            clear_state(chat_id)

            user_reminders = get_user_reminders(chat_id)

            if not user_reminders:
                keyboard = types.InlineKeyboardMarkup()
                keyboard.add(
                    types.InlineKeyboardButton(
                        "⬅️ Главное меню",
                        callback_data="menu:main",
                    )
                )

                bot.edit_message_text(
                    "🗑 <b>Удаление</b>\n\n"
                    "📭 Активных напоминаний нет.",
                    chat_id=chat_id,
                    message_id=call.message.message_id,
                    reply_markup=keyboard,
                    parse_mode="HTML",
                )
                return

            bot.edit_message_text(
                "🗑 <b>Удаление напоминания</b>\n\n"
                "Нажми на нужное напоминание:",
                chat_id=chat_id,
                message_id=call.message.message_id,
                reply_markup=delete_list_keyboard(chat_id),
                parse_mode="HTML",
            )
            return

        # ----------------------------------------------------
        # ПОДТВЕРЖДЕНИЕ
        # ----------------------------------------------------
        if data.startswith("delete:confirm:"):
            reminder_id = data.split(":")[-1]

            with DATA_LOCK:
                reminder = reminders.get(reminder_id)

            if reminder is None:
                bot.answer_callback_query(
                    call.id,
                    "Напоминание уже удалено.",
                    show_alert=True,
                )
                return

            if reminder.get("chat_id") != chat_id:
                bot.answer_callback_query(
                    call.id,
                    "Это не твоё напоминание.",
                    show_alert=True,
                )
                return

            safe_text = html.escape(
                str(reminder.get("text", ""))
            )

            keyboard = types.InlineKeyboardMarkup(row_width=2)

            keyboard.add(
                types.InlineKeyboardButton(
                    "✅ Да, удалить",
                    callback_data=f"delete:yes:{reminder_id}",
                ),
                types.InlineKeyboardButton(
                    "❌ Отмена",
                    callback_data="menu:delete",
                ),
            )

            keyboard.add(
                types.InlineKeyboardButton(
                    "⬅️ Главное меню",
                    callback_data="menu:main",
                )
            )

            bot.edit_message_text(
                "❓ <b>Удалить напоминание?</b>\n\n"
                f"🆔 ID: <code>{reminder_id}</code>\n"
                f"📝 {safe_text}",
                chat_id=chat_id,
                message_id=call.message.message_id,
                reply_markup=keyboard,
                parse_mode="HTML",
            )
            return

        # ----------------------------------------------------
        # УДАЛЕНИЕ ПОДТВЕРЖДЕНО
        # ----------------------------------------------------
        if data.startswith("delete:yes:"):
            reminder_id = data.split(":")[-1]

            with DATA_LOCK:
                reminder = reminders.get(reminder_id)

                if reminder is None:
                    bot.answer_callback_query(
                        call.id,
                        "Напоминание уже удалено.",
                        show_alert=True,
                    )
                    return

                if reminder.get("chat_id") != chat_id:
                    bot.answer_callback_query(
                        call.id,
                        "Это не твоё напоминание.",
                        show_alert=True,
                    )
                    return

                del reminders[reminder_id]
                save_reminders()

            keyboard = types.InlineKeyboardMarkup(row_width=1)

            keyboard.add(
                types.InlineKeyboardButton(
                    "🗑 Удалить ещё",
                    callback_data="menu:delete",
                )
            )

            keyboard.add(
                types.InlineKeyboardButton(
                    "📋 Мои напоминания",
                    callback_data="menu:list",
                )
            )

            keyboard.add(
                types.InlineKeyboardButton(
                    "🏠 Главное меню",
                    callback_data="menu:main",
                )
            )

            bot.edit_message_text(
                f"✅ <b>Напоминание {reminder_id} удалено.</b>",
                chat_id=chat_id,
                message_id=call.message.message_id,
                reply_markup=keyboard,
                parse_mode="HTML",
            )
            return

        bot.answer_callback_query(
            call.id,
            "Неизвестная кнопка.",
            show_alert=True,
        )

    except Exception as error:
        print(
            f"❌ Ошибка обработки кнопки "
            f"{data}: {error}"
)

        try:
            bot.answer_callback_query(
                call.id,
                "Произошла ошибка. Попробуй ещё раз.",
                show_alert=True,
            )
        except Exception:
            pass


# ============================================================
# ЗАПУСК
# ============================================================

if __name__ == "__main__":
    print("Восстановление напоминаний...")
    restore_reminders()

    print("Бот запущен.")
    print("Для остановки нажми Ctrl+C.")

    bot.polling(
        none_stop=True,
        interval=0,
        timeout=20,
    )
