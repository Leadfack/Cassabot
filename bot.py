import logging
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters, ConversationHandler
import os
from dotenv import load_dotenv
from pyairtable import Table
from typing import Dict, List, Optional

# Загрузка переменных окружения
load_dotenv()

# Airtable config (production values)
AIRTABLE_API_KEY = os.environ["AIRTABLE_API_KEY"]
BASE_ID = os.environ["BASE_ID"]
OPERATORS_TABLE_ID = os.environ["OPERATORS_TABLE_ID"]
CASH_TABLE_ID = os.environ["CASH_TABLE_ID"]
SCHEDULE_TABLE_ID = os.environ["SCHEDULE_TABLE_ID"]

# Telegram Bot Token
TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Conversation states
CHOOSING_ACTION, CHOOSING_PAGE, CHOOSING_TYPE, ENTERING_AMOUNT, CHOOSING_SHIFT, ENTERING_DATE = range(6)
SCHEDULE_CHOOSING_DATE, SCHEDULE_CHOOSING_SHIFT = range(2)

OPERATION_TYPES = ['Касса', 'Долет', 'Возврат']

# --- Airtable helpers ---
def get_operator_record(tg_id: str):
    table = Table(AIRTABLE_API_KEY, BASE_ID, OPERATORS_TABLE_ID)
    records = table.all(formula=f"{{TG ID}} = '{tg_id}'")
    return records[0] if records else None

def get_operator_pages_and_manager(tg_id: str):
    rec = get_operator_record(tg_id)
    if rec:
        pages = rec['fields'].get('Страница', [])
        manager = rec['fields'].get('managerName', '')
        name = rec['fields'].get('Name', '')
        return pages, manager, name
    return [], '', ''

def get_schedule_row(operator_name: str, page: str):
    table = Table(AIRTABLE_API_KEY, BASE_ID, SCHEDULE_TABLE_ID)
    formula = f"AND({{Имя}} = '{operator_name}', {{Страница}} = '{page}')"
    records = table.all(formula=formula)
    return records[0] if records else None

def update_schedule_day(record_id: str, day: int, shift: str):
    table = Table(AIRTABLE_API_KEY, BASE_ID, SCHEDULE_TABLE_ID)
    field_name = str(day)
    table.update(record_id, {field_name: shift})

def add_cash_record(operator_name, manager, page, amount, shift, date, type_):
    table = Table(AIRTABLE_API_KEY, BASE_ID, CASH_TABLE_ID)
    table.create({
        "Name": operator_name,
        "Менеджер": manager,
        "Страница": page,
        "Касса": amount,
        "Смена": shift,
        "Date": date,
        "Тип": type_
    })

# --- Bot logic ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.effective_user
    pages, manager, name = get_operator_pages_and_manager(str(user.id))
    if not pages:
        await update.message.reply_text('У вас нет доступа к боту. Обратитесь к администратору.')
        return ConversationHandler.END
    context.user_data['pages'] = pages
    context.user_data['manager'] = manager
    context.user_data['operator_name'] = name
    keyboard = [
        [KeyboardButton("📝 Записать кассу"), KeyboardButton("📅 График смен")],
        [KeyboardButton("❓ Помощь")]
    ]
    await update.message.reply_text(
        f'Привет, {name}! Выберите действие:',
        reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    )
    return CHOOSING_ACTION

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        '1. "Записать кассу" — только по своим страницам\n'
        '2. "График смен" — только по своим страницам\n'
        '3. Все данные пишутся в Airtable автоматически\n'
        'Если возникли вопросы — обратитесь к менеджеру.'
    )

async def handle_action(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text
    if text == "📝 Записать кассу":
        keyboard = [[InlineKeyboardButton(page, callback_data=f'page_{page}')] for page in context.user_data['pages']]
        keyboard.append([InlineKeyboardButton("Отмена", callback_data='cancel')])
        await update.message.reply_text('Выберите страницу:', reply_markup=InlineKeyboardMarkup(keyboard))
        return CHOOSING_PAGE
    elif text == "📅 График смен":
        keyboard = [[InlineKeyboardButton(page, callback_data=f'schedule_page_{page}')] for page in context.user_data['pages']]
        keyboard.append([InlineKeyboardButton("Отмена", callback_data='cancel')])
        await update.message.reply_text('Выберите страницу для графика:', reply_markup=InlineKeyboardMarkup(keyboard))
        return SCHEDULE_CHOOSING_DATE
    elif text == "❓ Помощь":
        await help_command(update, context)
        return CHOOSING_ACTION
    return CHOOSING_ACTION

async def handle_page_selection(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    if query.data == 'cancel':
        await query.edit_message_text('Операция отменена.')
        return CHOOSING_ACTION
    page = query.data.replace('page_', '')
    context.user_data['selected_page'] = page
    keyboard = [[InlineKeyboardButton(t, callback_data=f'type_{t}')] for t in OPERATION_TYPES]
    keyboard.append([InlineKeyboardButton("Отмена", callback_data='cancel')])
    await query.edit_message_text(f'Страница: {page}\nВыберите тип:', reply_markup=InlineKeyboardMarkup(keyboard))
    return CHOOSING_TYPE

async def handle_type_selection(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    if query.data == 'cancel':
        await query.edit_message_text('Операция отменена.')
        return CHOOSING_ACTION
    type_ = query.data.replace('type_', '')
    context.user_data['selected_type'] = type_
    await query.edit_message_text(f'Тип: {type_}\nВведите сумму:')
    return ENTERING_AMOUNT

async def handle_amount(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        amount = float(update.message.text.replace(',', '.'))
        context.user_data['amount'] = amount
        keyboard = [[InlineKeyboardButton(shift, callback_data=f'shift_{shift}') for shift in ["08-16", "00-08", "12-18", "16-00", "18-00", "06-12"]]]
        keyboard.append([InlineKeyboardButton("Отмена", callback_data='cancel')])
        await update.message.reply_text('Выберите смену:', reply_markup=InlineKeyboardMarkup(keyboard))
        return CHOOSING_SHIFT
    except ValueError:
        await update.message.reply_text('Введите корректную сумму (например: 1000 или 1000.50)')
        return ENTERING_AMOUNT

async def handle_shift_selection(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    if query.data == 'cancel':
        await query.edit_message_text('Операция отменена.')
        return CHOOSING_ACTION
    shift = query.data.replace('shift_', '')
    context.user_data['selected_shift'] = shift
    await query.edit_message_text('Введите число месяца (например: 16):')
    return ENTERING_DATE

async def handle_date(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        day = int(update.message.text)
        if not (1 <= day <= 31):
            raise ValueError
        now = datetime.now()
        date_str = f"{day}.{now.month}.{now.year}"
        add_cash_record(
            context.user_data['operator_name'],
            context.user_data['manager'],
            context.user_data['selected_page'],
            context.user_data['amount'],
            context.user_data['selected_shift'],
            date_str,
            context.user_data['selected_type']
        )
        await update.message.reply_text('✅ Запись кассы добавлена!')
        context.user_data.clear()
        return CHOOSING_ACTION
    except ValueError:
        await update.message.reply_text('Введите корректное число (1-31)')
        return ENTERING_DATE

# --- SCHEDULE ---
async def handle_schedule_page(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    if query.data == 'cancel':
        await query.edit_message_text('Операция отменена.')
        return CHOOSING_ACTION
    page = query.data.replace('schedule_page_', '')
    context.user_data['schedule_page'] = page
    # Календарь на 7 дней вперёд
    today = datetime.now()
    keyboard = [[InlineKeyboardButton(str(today.day + i), callback_data=f'schedule_day_{today.day + i}')]
               for i in range(7)]
    keyboard.append([InlineKeyboardButton("Отмена", callback_data='cancel')])
    await query.edit_message_text('Выберите день:', reply_markup=InlineKeyboardMarkup(keyboard))
    return SCHEDULE_CHOOSING_SHIFT

async def handle_schedule_day(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    if query.data == 'cancel':
        await query.edit_message_text('Операция отменена.')
        return CHOOSING_ACTION
    day = int(query.data.replace('schedule_day_', ''))
    context.user_data['schedule_day'] = day
    # Список смен
    shifts = ["08-16", "00-08", "12-18", "16-00", "18-00", "06-12", "Выходной"]
    keyboard = [[InlineKeyboardButton(shift, callback_data=f'schedule_shift_{shift}') for shift in shifts]]
    keyboard.append([InlineKeyboardButton("Отмена", callback_data='cancel')])
    await query.edit_message_text('Выберите смену:', reply_markup=InlineKeyboardMarkup(keyboard))
    return SCHEDULE_CHOOSING_DATE

async def handle_schedule_shift(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    if query.data == 'cancel':
        await query.edit_message_text('Операция отменена.')
        return CHOOSING_ACTION
    shift = query.data.replace('schedule_shift_', '')
    operator_name = context.user_data['operator_name']
    page = context.user_data['schedule_page']
    day = context.user_data['schedule_day']
    row = get_schedule_row(operator_name, page)
    if row:
        update_schedule_day(row['id'], day, shift)
        await query.edit_message_text(f'✅ График обновлён: {page}, {day} число — {shift}')
    else:
        await query.edit_message_text('❌ Не найдена строка графика для этой страницы.')
    context.user_data.clear()
    return CHOOSING_ACTION

# --- MAIN ---
def main() -> None:
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('start', start)],
        states={
            CHOOSING_ACTION: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_action)],
            CHOOSING_PAGE: [CallbackQueryHandler(handle_page_selection)],
            CHOOSING_TYPE: [CallbackQueryHandler(handle_type_selection)],
            ENTERING_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_amount)],
            CHOOSING_SHIFT: [CallbackQueryHandler(handle_shift_selection)],
            ENTERING_DATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_date)],
            SCHEDULE_CHOOSING_DATE: [CallbackQueryHandler(handle_schedule_page), CallbackQueryHandler(handle_schedule_shift)],
            SCHEDULE_CHOOSING_SHIFT: [CallbackQueryHandler(handle_schedule_day)],
        },
        fallbacks=[CommandHandler('start', start)]
    )
    application.add_handler(conv_handler)
    application.add_handler(CommandHandler('help', help_command))
    application.run_polling()

if __name__ == '__main__':
    main() 