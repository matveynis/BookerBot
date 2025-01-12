import sqlite3
import os
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, MessageHandler, filters
import datetime
import asyncio

admins = [int(os.getenv("ADMIN_ID"))]
print("Список администраторов:", admins)
db_file = 'appointments.db'  

async def log_task():
    while True:
        print(f"[{datetime.datetime.now()}] Бот работает и ждет событий...")
        await asyncio.sleep(60)  
	    
def get_db_connection():
    conn = sqlite3.connect(db_file)
    conn.row_factory = sqlite3.Row
    return conn

def create_table():
    conn = get_db_connection()
    conn.execute('''
        CREATE TABLE IF NOT EXISTS appointments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user TEXT,
            chat_id INTEGER,
            time TEXT,
            duration INTEGER,
            message TEXT,
            status TEXT
        )
    ''')
    conn.commit()
    conn.close()


def add_appointment(user, chat_id, time, duration, message, status='pending'):
    conn = get_db_connection()
    conn.execute('''
        INSERT INTO appointments (user, chat_id, time, duration, message, status)
        VALUES (?, ?, ?, ?, ?, ?)
    ''', (user, chat_id, time, duration, message, status))
    conn.commit()
    conn.close()

def get_all_appointments():
    conn = get_db_connection()
    appointments = conn.execute('SELECT * FROM appointments').fetchall()
    conn.close()
    return appointments


def get_occupied_dates():
    conn = get_db_connection()
    occupied_dates = conn.execute(
        'SELECT DISTINCT time FROM appointments WHERE status IN ("pending", "accepted")'
    ).fetchall()
    conn.close()
    return [date['time'].split(' ')[0] for date in occupied_dates]


def update_appointment_status(appointment_id, status):
    conn = get_db_connection()
    conn.execute('UPDATE appointments SET status = ? WHERE id = ?', (status, appointment_id))
    conn.commit()
    conn.close()


async def start(update: Update, context):
    user_id = update.message.from_user.id
    if user_id not in admins:
        await update.message.reply_text(
            "Привет! Я бот для записи на встречи.\n"
            "Вот доступные команды:\n"
            "/book - Записаться на встречу.\n"
        )
    else:
        await update.message.reply_text(
            "Привет, администратор! Вот доступные команды:\n"
            "/book - Записаться на встречу.\n"
	    "/upcoming_requests - Ближайшие мероприятия.\n"
            "/view_requests - Просмотр всех заявок.\n"
        )


def create_calendar_markup(year, month, occupied_dates):
    first_day_of_month = datetime.date(year, month, 1)
    start_day = first_day_of_month.weekday()
    days_in_month = (datetime.date(year, month + 1, 1) - first_day_of_month).days if month < 12 else (datetime.date(year + 1, 1, 1) - first_day_of_month).days


    keyboard = []
    day = 1

    for row in range(6):  
        keyboard_row = []
        for col in range(7): 
            if row == 0 and col < start_day:  
                keyboard_row.append(InlineKeyboardButton(" ", callback_data="empty"))
            elif day <= days_in_month:  
                date_str = f'{year}-{month:02d}-{day:02d}'
                if date_str in occupied_dates:
                    keyboard_row.append(
                        InlineKeyboardButton(f'❌ {day}', callback_data=f'occupied_{date_str}')
                    )
                else:
                    keyboard_row.append(
                        InlineKeyboardButton(f'{day}', callback_data=f'date_{date_str}')
                    )
                day += 1
            else:  
                keyboard_row.append(InlineKeyboardButton(" ", callback_data="empty"))
        keyboard.append(keyboard_row)

    return InlineKeyboardMarkup(keyboard)


async def book(update: Update, context):
    occupied_dates = get_occupied_dates()

    today = datetime.date.today()
    calendar_markup = create_calendar_markup(today.year, today.month, occupied_dates)

    await update.message.reply_text("Выберите дату для записи:", reply_markup=calendar_markup)

async def date_handler(update: Update, context):
    query = update.callback_query

    if query.data.startswith('occupied_'):
        await query.answer("Эта дата уже занята. Выберите другую.", show_alert=True)
        return

    date_str = query.data.split('_')[1]
    selected_date = datetime.datetime.strptime(date_str, '%Y-%m-%d').date()

    today = datetime.date.today()
    if selected_date < today:
        await query.answer("Вы не можете выбрать прошедшую дату.", show_alert=True)
        return

    conn = get_db_connection()
    occupied_times = conn.execute(
        'SELECT time FROM appointments WHERE time LIKE ? AND status IN ("pending", "accepted")',
        (f"{date_str}%",)
    ).fetchall()
    conn.close()

    occupied_times = [time['time'].split(' ')[1] for time in occupied_times]

    time_slots = [f"{hour:02d}:00" for hour in range(12, 23)]
    keyboard = [
        [InlineKeyboardButton(
            time, callback_data=f"time_{time}_{date_str}"
        ) if time not in occupied_times else InlineKeyboardButton(
            f"⛔ {time}", callback_data="occupied"
        )]
        for time in time_slots
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.answer()
    await query.edit_message_text(f"Вы выбрали дату: {selected_date}. Теперь выберите время для встречи:", reply_markup=reply_markup)

async def time_handler(update: Update, context):
    query = update.callback_query

    if query.data == "occupied":
        await query.answer("Это время уже занято. Выберите другое.", show_alert=True)
        return

    time_chosen, date_chosen = query.data.split('_')[1], query.data.split('_')[2]
    context.user_data['time'] = time_chosen
    context.user_data['date'] = date_chosen

    keyboard = [
        [InlineKeyboardButton("По работе", callback_data="reason_work")],
        [InlineKeyboardButton("По учебе", callback_data="reason_study")],
        [InlineKeyboardButton("Свидание", callback_data="reason_date")],
        [InlineKeyboardButton("Другое", callback_data="reason_other")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.answer()
    await query.edit_message_text(f"Вы выбрали время: {time_chosen}. Теперь выберите причину встречи:", reply_markup=reply_markup)

async def message_handler(update: Update, context):
    user_id = update.message.from_user.id
    chat_id = update.message.chat_id
    message = update.message.text
    time = context.user_data.get('time', 'не выбрано')
    date = context.user_data.get('date', 'не выбрано')
    reason = context.user_data.get('reason', 'не выбрано')

    add_appointment(update.message.from_user.username, chat_id, f"{date} {time}", reason, message)

    for admin_id in admins:
        try:
            await context.bot.send_message(
                admin_id,
                f"Новая заявка от {update.message.from_user.username} на {date} в {time}. Причина: {reason}.\nСообщение: {message}\n\nПринять или отклонить?"
            )
        except Exception as e:
            print(f"Ошибка отправки сообщения администратору {admin_id}: {e}")

    await update.message.reply_text(f"Заявка отправлена. Дата: {date}, время: {time}, причина: {reason}. Сообщение: {message}.")

async def view_requests(update: Update, context):
    user_id = update.message.from_user.id

    if user_id in admins:
        conn = get_db_connection()
        pending_appointments = conn.execute(
            'SELECT * FROM appointments WHERE status = "pending"'
        ).fetchall()
        conn.close()

        if pending_appointments:
            for appointment in pending_appointments:
                status = "Ожидает" 
                keyboard = [
                    [InlineKeyboardButton("Принять", callback_data=f"accept_{appointment['id']}"),
                     InlineKeyboardButton("Отклонить", callback_data=f"reject_{appointment['id']}")]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)

                await update.message.reply_text(
                    f"Заявка от @{appointment['user']} на {appointment['time']}.\n"
                    f"Причина: {appointment['duration']}\n" 
                    f"Сообщение: {appointment['message']}\n"
                    f"Статус: {status}",
                    reply_markup=reply_markup
                )
        else:
            await update.message.reply_text("Нет ожидающих заявок.")
    else:
        await update.message.reply_text("Вы не администратор!")

async def upcoming_requests(update: Update, context):
    user_id = update.message.from_user.id

    if user_id in admins:
        conn = get_db_connection()
        upcoming_appointments = conn.execute(
            'SELECT * FROM appointments WHERE status = "accepted" ORDER BY time ASC'
        ).fetchall()
        conn.close()

        if upcoming_appointments:
            for appointment in upcoming_appointments:
                await update.message.reply_text(
                    f"Ближайшая встреча:\n"
                    f"Дата и время: {appointment['time']}\n"
                    f"Пользователь: @{appointment['user']}\n"
                    f"Причина: {appointment['duration']}\n"  
                    f"Сообщение: {appointment['message']}\n"
                )
        else:
            await update.message.reply_text("Нет ближайших встреч.")
    else:
        await update.message.reply_text("Вы не администратор!")

async def reason_handler(update: Update, context):
    query = update.callback_query
    reason = query.data.split('_')[1]

    reason_dict = {
        'work': "По работе",
        'study': "По учебе",
        'date': "Свидание",
        'other': "Другое"
    }

    selected_reason = reason_dict.get(reason, "Не указано")
    context.user_data['reason'] = selected_reason

    await query.answer()
    await query.edit_message_text(f"Вы выбрали причину: {selected_reason}. Оставьте сообщение для администратора:")
    await query.message.reply_text("Напишите сообщение для администратора.")

async def appointment_action(update: Update, context):
    query = update.callback_query
    action, appointment_id = query.data.split('_')

    if action == "accept" or action == "reject":
        status = 'accepted' if action == 'accept' else 'rejected'
        status_ru = 'принята' if status == 'accepted' else 'отклонена' 

        update_appointment_status(appointment_id, status)

        conn = get_db_connection()
        appointment = conn.execute('SELECT * FROM appointments WHERE id = ?', (appointment_id,)).fetchone()
        conn.close()

        if appointment:
            chat_id = appointment['chat_id']
            time = appointment['time']
            await query.answer()
            await query.edit_message_text(f"Заявка {status_ru}! Действие завершено.")

            try:
                await context.bot.send_message(
                    chat_id,
                    f"Ваша заявка на встречу на {time} была {status_ru}."  
                )
            except Exception as e:
                print(f"Ошибка отправки уведомления пользователю: {e}")
        else:
            await query.answer("Заявка не найдена.")


async def main():
    create_table()

    # Асинхронная задача для логгера
    asyncio.create_task(log_task())

    TOKEN = os.getenv("BOT_TOKEN")
    app = ApplicationBuilder().token(TOKEN).build()

    # Регистрация обработчиков
    app.add_handler(CommandHandler('start', start))
    app.add_handler(CommandHandler('book', book))
    app.add_handler(CommandHandler('view_requests', view_requests))
    app.add_handler(CommandHandler('upcoming_requests', upcoming_requests))
    app.add_handler(CallbackQueryHandler(date_handler, pattern='^date_'))
    app.add_handler(CallbackQueryHandler(time_handler, pattern="^time_"))
    app.add_handler(CallbackQueryHandler(reason_handler, pattern="^reason_"))
    app.add_handler(MessageHandler(filters.TEXT, message_handler))
    app.add_handler(CallbackQueryHandler(appointment_action, pattern="^(accept|reject)_"))

    # Запуск бота
    print("Бот запущен!")
    await app.run_polling()

if __name__ == '__main__':
    # Запуск основного события без `asyncio.run` (если цикл уже запущен)
    asyncio.run(main())


if __name__ == '__main__':
    asyncio.run(main())
