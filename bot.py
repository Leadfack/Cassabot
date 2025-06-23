import os
import logging
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import (
    Updater,
    CommandHandler,
    MessageHandler,
    Filters,
    ConversationHandler,
    CallbackContext
)
from pyairtable import Table

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Состояния разговора
MENU, CASH_FLOW_SELECT_PAGE, CASH_FLOW_SELECT_SHIFT, CASH_FLOW_SELECT_TYPE, CASH_FLOW_ENTER_AMOUNT = range(5)

# Подключение к Airtable
AIRTABLE_API_KEY = os.getenv('AIRTABLE_API_KEY')
AIRTABLE_BASE_ID = os.getenv('AIRTABLE_BASE_ID')

operators_table = Table(AIRTABLE_API_KEY, AIRTABLE_BASE_ID, 'Operators')
cash_table = Table(AIRTABLE_API_KEY, AIRTABLE_BASE_ID, 'Cash')
schedule_table = Table(AIRTABLE_API_KEY, AIRTABLE_BASE_ID, 'Schedule')

def create_main_keyboard():
    """Создает основную клавиатуру"""
    keyboard = [
        [KeyboardButton("💰 Записать кассу")],
        [KeyboardButton("📅 График")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def start(update: Update, context: CallbackContext) -> int:
    """Начало разговора"""
    user_id = str(update.effective_user.id)
    
    try:
        # Ищем оператора по TG ID
        operators = operators_table.all()
        operator = None
        
        for op in operators:
            if op['fields'].get('TG ID') == user_id:
                operator = op
                break
        
        if operator:
            # Сохраняем данные оператора
            context.user_data['operator_id'] = operator['fields'].get('ID')
            context.user_data['operator_name'] = operator['fields'].get('Name')
            
            # Получаем страницы оператора
            pages = {}
            if 'Страница' in operator['fields']:
                for page_id in operator['fields']['Страница']:
                    page = cash_table.get(page_id)
                    if page and 'Name' in page['fields']:
                        pages[page['fields']['Name']] = page_id
            
            context.user_data['page_names'] = pages
            
            update.message.reply_text(
                f"👋 Привет, {operator['fields'].get('Name')}!\nВыберите действие:",
                reply_markup=create_main_keyboard()
            )
            return MENU
        else:
            update.message.reply_text(
                "❌ Извините, но я вас не узнаю. Обратитесь к менеджеру для регистрации в системе."
            )
            return ConversationHandler.END
            
    except Exception as e:
        logger.error(f"Error in start handler: {str(e)}")
        update.message.reply_text(
            "❌ Произошла ошибка при запуске бота. Попробуйте позже или обратитесь к менеджеру."
        )
        return ConversationHandler.END

def handle_menu(update: Update, context: CallbackContext) -> int:
    """Обработчик главного меню"""
    text = update.message.text

    if text == "💰 Записать кассу":
        pages = context.user_data.get('page_names', {})
        if not pages:
            update.message.reply_text(
                "❌ У вас нет доступных страниц. Обратитесь к менеджеру.",
                reply_markup=create_main_keyboard()
            )
            return MENU

        keyboard = [[KeyboardButton(page_name)] for page_name in pages.keys()]
        keyboard.append([KeyboardButton("⬅️ Назад")])
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        
        update.message.reply_text(
            "📋 Выберите страницу:",
            reply_markup=reply_markup
        )
        return CASH_FLOW_SELECT_PAGE

    elif text == "📅 График":
        keyboard = [
            [KeyboardButton("🏖️ Выходной"), KeyboardButton("🔄 Замена")],
            [KeyboardButton("⬅️ Назад")]
        ]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        
        update.message.reply_text(
            "📅 Выберите статус:",
            reply_markup=reply_markup
        )
        return MENU

    else:
        update.message.reply_text(
            "⚠️ Пожалуйста, используйте кнопки меню",
            reply_markup=create_main_keyboard()
        )
        return MENU

def handle_cash_flow_page(update: Update, context: CallbackContext) -> int:
    """Обработчик выбора страницы"""
    text = update.message.text
    
    if text == "⬅️ Назад":
        update.message.reply_text(
            "👉 Выберите действие:",
            reply_markup=create_main_keyboard()
        )
        return MENU
    
    pages = context.user_data.get('page_names', {})
    if text not in pages:
        update.message.reply_text(
            "⚠️ Пожалуйста, выберите страницу из списка",
            reply_markup=ReplyKeyboardMarkup([[page] for page in pages.keys()], resize_keyboard=True)
        )
        return CASH_FLOW_SELECT_PAGE
    
    context.user_data['selected_page'] = pages[text]
    context.user_data['selected_page_name'] = text
    
    keyboard = [
        [KeyboardButton("🌅 Утро"), KeyboardButton("☀️ День"), KeyboardButton("🌙 Вечер")],
        [KeyboardButton("⬅️ Назад")]
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    
    update.message.reply_text(
        "⏰ Выберите смену:",
        reply_markup=reply_markup
    )
    return CASH_FLOW_SELECT_SHIFT

def handle_cash_flow_shift(update: Update, context: CallbackContext) -> int:
    """Обработчик выбора смены"""
    text = update.message.text.replace('🌅 ', '').replace('☀️ ', '').replace('🌙 ', '')
    
    if text == "⬅️ Назад":
        pages = context.user_data.get('page_names', {})
        keyboard = [[KeyboardButton(page_name)] for page_name in pages.keys()]
        keyboard.append([KeyboardButton("⬅️ Назад")])
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        
        update.message.reply_text(
            "📋 Выберите страницу:",
            reply_markup=reply_markup
        )
        return CASH_FLOW_SELECT_PAGE
    
    if text not in ['Утро', 'День', 'Вечер']:
        update.message.reply_text(
            "⚠️ Пожалуйста, выберите смену из списка",
            reply_markup=ReplyKeyboardMarkup([
                [KeyboardButton("🌅 Утро"), KeyboardButton("☀️ День"), KeyboardButton("🌙 Вечер")],
                [KeyboardButton("⬅️ Назад")]
            ], resize_keyboard=True)
        )
        return CASH_FLOW_SELECT_SHIFT
    
    context.user_data['selected_shift'] = text
    
    keyboard = [
        [KeyboardButton("💵 Касса"), KeyboardButton("✈️ Долет"), KeyboardButton("↩️ Возврат")],
        [KeyboardButton("⬅️ Назад")]
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    
    update.message.reply_text(
        "📝 Выберите тип операции:",
        reply_markup=reply_markup
    )
    return CASH_FLOW_SELECT_TYPE

def handle_cash_flow_type(update: Update, context: CallbackContext) -> int:
    """Обработчик выбора типа операции"""
    text = update.message.text.replace('💵 ', '').replace('✈️ ', '').replace('↩️ ', '')
    
    if text == "⬅️ Назад":
        keyboard = [
            [KeyboardButton("🌅 Утро"), KeyboardButton("☀️ День"), KeyboardButton("🌙 Вечер")],
            [KeyboardButton("⬅️ Назад")]
        ]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        
        update.message.reply_text(
            "⏰ Выберите смену:",
            reply_markup=reply_markup
        )
        return CASH_FLOW_SELECT_SHIFT
    
    if text not in ['Касса', 'Долет', 'Возврат']:
        update.message.reply_text(
            "⚠️ Пожалуйста, выберите тип операции из списка",
            reply_markup=ReplyKeyboardMarkup([
                [KeyboardButton("💵 Касса"), KeyboardButton("✈️ Долет"), KeyboardButton("↩️ Возврат")],
                [KeyboardButton("⬅️ Назад")]
            ], resize_keyboard=True)
        )
        return CASH_FLOW_SELECT_TYPE
    
    context.user_data['selected_type'] = text
    
    keyboard = [[KeyboardButton("❌ Отмена")]]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    
    update.message.reply_text(
        "💰 Введите сумму:",
        reply_markup=reply_markup
    )
    return CASH_FLOW_ENTER_AMOUNT

def handle_cash_flow_amount(update: Update, context: CallbackContext) -> int:
    """Обработчик ввода суммы"""
    text = update.message.text
    
    if text == "❌ Отмена":
        update.message.reply_text(
            "🚫 Операция отменена",
            reply_markup=create_main_keyboard()
        )
        return MENU
    
    try:
        amount = float(text)
        if amount <= 0:
            raise ValueError("Сумма должна быть положительной")
        
        # Создаем запись в таблице
        record = {
            'Page': [context.user_data['selected_page']],
            'Operator': [context.user_data['operator_id']],
            'Shift': context.user_data['selected_shift'],
            'Type': context.user_data['selected_type'],
            'Amount': amount
        }
        
        cash_table.create(record)
        
        update.message.reply_text(
            f"✅ Запись успешно создана!\n\n"
            f"📄 Страница: {context.user_data['selected_page_name']}\n"
            f"⏰ Смена: {context.user_data['selected_shift']}\n"
            f"📝 Тип: {context.user_data['selected_type']}\n"
            f"💰 Сумма: {amount}",
            reply_markup=create_main_keyboard()
        )
        return MENU
        
    except ValueError as e:
        update.message.reply_text(
            "⚠️ Пожалуйста, введите корректную сумму (положительное число)",
            reply_markup=ReplyKeyboardMarkup([[KeyboardButton("❌ Отмена")]], resize_keyboard=True)
        )
        return CASH_FLOW_ENTER_AMOUNT

def help_command(update: Update, context: CallbackContext) -> None:
    """Отправляет сообщение с помощью при команде /help"""
    help_text = """
Доступные команды:
/start - Начать работу с ботом
/help - Показать это сообщение помощи

Функции бота:
1. 💰 Касса - учет движения денежных средств
2. 📅 График - управление расписанием работы
"""
    update.message.reply_text(help_text)

def main():
    """Основная функция"""
    try:
        updater = Updater(os.getenv('TELEGRAM_TOKEN'))
        dispatcher = updater.dispatcher

        # Добавляем обработчики
        dispatcher.add_handler(CommandHandler('help', help_command))
        
        # Добавляем обработчики состояний
        conv_handler = ConversationHandler(
            entry_points=[CommandHandler('start', start)],
            states={
                MENU: [MessageHandler(Filters.text & ~Filters.command, handle_menu)],
                CASH_FLOW_SELECT_PAGE: [MessageHandler(Filters.text & ~Filters.command, handle_cash_flow_page)],
                CASH_FLOW_SELECT_SHIFT: [MessageHandler(Filters.text & ~Filters.command, handle_cash_flow_shift)],
                CASH_FLOW_SELECT_TYPE: [MessageHandler(Filters.text & ~Filters.command, handle_cash_flow_type)],
                CASH_FLOW_ENTER_AMOUNT: [MessageHandler(Filters.text & ~Filters.command, handle_cash_flow_amount)],
            },
            fallbacks=[CommandHandler('help', help_command)],
        )
        dispatcher.add_handler(conv_handler)

        # Запускаем бота
        updater.start_polling()
        updater.idle()
    except Exception as e:
        logger.error(f"Критическая ошибка: {e}")

if __name__ == '__main__':
    main() 