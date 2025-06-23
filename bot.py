import os
import asyncio
import logging
from datetime import datetime
from dotenv import load_dotenv
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import (
    Updater,
    CommandHandler,
    MessageHandler,
    Filters,
    ConversationHandler,
    CallbackContext,
    CallbackQueryHandler
)
from pyairtable import Api, Base, Table

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Загрузка переменных окружения
load_dotenv()

# Константы для состояний разговора
(MENU, CASH_FLOW_SELECT_PAGE, CASH_FLOW_SELECT_SHIFT, CASH_FLOW_SELECT_TYPE, 
 CASH_FLOW_ENTER_AMOUNT, CASH_FLOW_ENTER_DATE, SCHEDULE_SELECT_DATE, 
 SCHEDULE_SELECT_SHIFT) = range(8)

# Константы для Airtable
AIRTABLE_API_KEY = os.getenv('AIRTABLE_API_KEY')
BASE_ID = "appPLEgqFVgDw0mmi"  # ID вашей базы Managers
OPERATORS_TABLE = "Операторы"
CASH_TABLE = "Касса"
SCHEDULE_TABLE = "График"

# Константы для смен
SHIFTS = ["00-08", "08-16", "16-00", "00-06", "06-12", "18-00"]

# Инициализация Airtable
airtable = Api(AIRTABLE_API_KEY)
base = Base(airtable, BASE_ID)
operators_table = base.table(OPERATORS_TABLE)
cash_table = base.table(CASH_TABLE)
schedule_table = base.table(SCHEDULE_TABLE)

def create_main_keyboard():
    """Создает основную клавиатуру"""
    keyboard = [
        [KeyboardButton("💰 Записать кассу")],
        [KeyboardButton("📅 График")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def create_navigation_keyboard(include_back=True, include_main_menu=True):
    """Создает клавиатуру с кнопками навигации"""
    keyboard = []
    if include_back:
        keyboard.append([KeyboardButton("⬅️ Назад")])
    if include_main_menu:
        keyboard.append([KeyboardButton("🏠 В главное меню")])
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

async def start(update: Update, context: CallbackContext):
    """Обработчик команды /start"""
    # Получаем информацию о пользователе
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
            logger.info(f"Found operator: {operator}")
            # Сохраняем данные оператора
            context.user_data['operator_id'] = operator['fields'].get('ID')
            context.user_data['operator_name'] = operator['fields'].get('Name')
            context.user_data['manager'] = operator['fields'].get('Менеджер', [None])[0] if operator['fields'].get('Менеджер') else None
            
            # Получаем страницы оператора
            pages = {}
            if 'Страница' in operator['fields']:
                for page_id in operator['fields']['Страница']:
                    try:
                        page = cash_table.get(page_id)
                        if page and 'Name' in page['fields']:
                            pages[page['fields']['Name']] = page_id
                    except Exception as e:
                        logger.error(f"Error fetching page {page_id}: {str(e)}")
            
            context.user_data['page_names'] = pages
            logger.info(f"Saved operator data: {context.user_data}")
            
            # Создаем основную клавиатуру
            await update.message.reply_text(
                "Выберите действие:",
                reply_markup=create_main_keyboard()
            )
            return MENU
        else:
            logger.warning(f"Operator not found for TG ID: {user_id}")
            await update.message.reply_text(
                "Извините, но я вас не узнаю. Обратитесь к менеджеру для регистрации в системе."
            )
            return ConversationHandler.END
            
    except Exception as e:
        logger.error(f"Error in start handler: {str(e)}")
        await update.message.reply_text(
            "Произошла ошибка при запуске бота. Попробуйте позже или обратитесь к менеджеру."
        )
        return ConversationHandler.END

async def handle_menu(update: Update, context: CallbackContext):
    """Обработчик главного меню"""
    text = update.message.text
    logger.info(f"Menu selection: {text}")

    if text == "💰 Записать кассу":
        # Получаем страницы оператора
        try:
            # Получаем ID страниц из данных оператора
            operator_id = context.user_data.get('operator_id')
            if not operator_id:
                logger.error("Operator ID not found in context")
                await update.message.reply_text(
                    "Ошибка: не найден ID оператора. Попробуйте перезапустить бота командой /start",
                    reply_markup=create_main_keyboard()
                )
                return MENU

            # Получаем оператора из таблицы
            operators = operators_table.all(formula=f"{{ID}}='{operator_id}'")
            if not operators:
                logger.error(f"Operator not found with ID: {operator_id}")
                await update.message.reply_text(
                    "Ошибка: не найден оператор. Обратитесь к менеджеру.",
                    reply_markup=create_main_keyboard()
                )
                return MENU

            operator = operators[0]
            pages = {}
            
            if 'Страница' in operator['fields']:
                for page_id in operator['fields']['Страница']:
                    try:
                        page = cash_table.get(page_id)
                        if page and 'Name' in page['fields']:
                            pages[page['fields']['Name']] = page_id
                    except Exception as e:
                        logger.error(f"Error fetching page {page_id}: {str(e)}")

            if not pages:
                logger.error("No pages found for operator")
                await update.message.reply_text(
                    "У вас нет доступных страниц. Обратитесь к менеджеру.",
                    reply_markup=create_main_keyboard()
                )
                return MENU

            # Сохраняем страницы в контекст
            context.user_data['page_names'] = pages
            logger.info(f"Available pages: {pages}")

            # Создаем клавиатуру со страницами
            keyboard = [[KeyboardButton(page_name)] for page_name in pages.keys()]
            keyboard.extend([
                [KeyboardButton("⬅️ Назад")],
                [KeyboardButton("🏠 В главное меню")]
            ])
            reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

            await update.message.reply_text(
                "Выберите страницу:",
                reply_markup=reply_markup
            )
            return CASH_FLOW_SELECT_PAGE

        except Exception as e:
            logger.error(f"Error in cash flow menu: {str(e)}")
            await update.message.reply_text(
                "Произошла ошибка. Попробуйте позже или обратитесь к менеджеру.",
                reply_markup=create_main_keyboard()
            )
            return MENU

    elif text == "📅 График":
        # Создаем клавиатуру с кнопками навигации
        keyboard = [
            [KeyboardButton("⬅️ Назад")],
            [KeyboardButton("🏠 В главное меню")]
        ]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        
        await update.message.reply_text(
            "Введите число месяца (1-31):",
            reply_markup=reply_markup
        )
        return SCHEDULE_SELECT_DATE

    else:
        await update.message.reply_text(
            "Выберите действие из меню:",
            reply_markup=create_main_keyboard()
        )
        return MENU

async def handle_cash_flow_page(update: Update, context: CallbackContext):
    """Обработчик выбора страницы для записи кассы"""
    text = update.message.text
    
    if text == "⬅️ Назад" or text == "🏠 В главное меню":
        return await handle_navigation(update, context)
    
    context.user_data['selected_page'] = text
    
    # Создаем клавиатуру с выбором смены
    keyboard = [[KeyboardButton(shift)] for shift in SHIFTS]
    keyboard.extend([
        [KeyboardButton("⬅️ Назад")],
        [KeyboardButton("🏠 В главное меню")]
    ])
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    
    await update.message.reply_text(
        "Выберите смену:",
        reply_markup=reply_markup
    )
    return CASH_FLOW_SELECT_SHIFT

async def handle_cash_flow_shift(update: Update, context: CallbackContext):
    """Обработчик выбора смены"""
    text = update.message.text
    
    if text == "⬅️ Назад" or text == "🏠 В главное меню":
        return await handle_navigation(update, context)
    
    # Сохраняем выбранную смену
    context.user_data['selected_shift'] = text
    
    # Создаем клавиатуру для выбора типа операции
    keyboard = [
        [KeyboardButton("Касса")],
        [KeyboardButton("Долет")],
        [KeyboardButton("Возврат")],
        [KeyboardButton("⬅️ Назад")],
        [KeyboardButton("🏠 В главное меню")]
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    
    await update.message.reply_text(
        "Выберите тип операции:",
        reply_markup=reply_markup
    )
    return CASH_FLOW_SELECT_TYPE

async def handle_cash_flow_type(update: Update, context: CallbackContext):
    """Обработчик выбора типа операции"""
    text = update.message.text
    
    if text == "⬅️ Назад" or text == "🏠 В главное меню":
        return await handle_navigation(update, context)
    
    # Проверяем тип операции
    valid_types = ["Касса", "Долет", "Возврат"]
    
    if text not in valid_types:
        await update.message.reply_text(
            "Пожалуйста, выберите тип операции из предложенных вариантов.",
            reply_markup=ReplyKeyboardMarkup([
                [KeyboardButton("Касса")],
                [KeyboardButton("Долет")],
                [KeyboardButton("Возврат")],
                [KeyboardButton("⬅️ Назад")],
                [KeyboardButton("🏠 В главное меню")]
            ], resize_keyboard=True)
        )
        return CASH_FLOW_SELECT_TYPE
    
    # Сохраняем тип операции
    context.user_data['operation_type'] = text
    
    # Создаем клавиатуру для ввода суммы
    keyboard = [
        [KeyboardButton("⬅️ Назад")],
        [KeyboardButton("🏠 В главное меню")]
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    
    await update.message.reply_text(
        "Введите сумму:",
        reply_markup=reply_markup
    )
    return CASH_FLOW_ENTER_AMOUNT

async def handle_cash_flow_amount(update: Update, context: CallbackContext):
    """Обработчик ввода суммы"""
    text = update.message.text
    
    if text == "⬅️ Назад" or text == "🏠 В главное меню":
        return await handle_navigation(update, context)
    
    try:
        amount = float(text)
        context.user_data['amount'] = amount
        
        # Создаем клавиатуру с кнопкой "Сегодня" и навигацией
        keyboard = [
            [KeyboardButton("📅 Сегодня")],
            [KeyboardButton("⬅️ Назад")],
            [KeyboardButton("🏠 В главное меню")]
        ]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        
        await update.message.reply_text(
            "Введите дату в формате ДД.ММ.ГГГГ или нажмите 'Сегодня':",
            reply_markup=reply_markup
        )
        return CASH_FLOW_ENTER_DATE
    except ValueError:
        await update.message.reply_text(
            "Пожалуйста, введите корректное число."
        )
        return CASH_FLOW_ENTER_AMOUNT

async def handle_cash_flow_date(update: Update, context: CallbackContext):
    """Обработчик ввода даты"""
    text = update.message.text
    
    if text == "⬅️ Назад" or text == "🏠 В главное меню":
        return await handle_navigation(update, context)
    
    try:
        # Получаем дату
        if text == "📅 Сегодня":
            date = datetime.now().strftime("%Y-%m-%d")
        else:
            try:
                # Преобразуем дату из формата ДД.ММ.ГГГГ в ГГГГ-ММ-ДД
                parsed_date = datetime.strptime(text, "%d.%m.%Y")
                date = parsed_date.strftime("%Y-%m-%d")
            except ValueError:
                await update.message.reply_text(
                    "Пожалуйста, введите дату в формате ДД.ММ.ГГГГ или нажмите 'Сегодня'",
                    reply_markup=ReplyKeyboardMarkup([
                        [KeyboardButton("📅 Сегодня")],
                        [KeyboardButton("⬅️ Назад")],
                        [KeyboardButton("🏠 В главное меню")]
                    ], resize_keyboard=True)
                )
                return CASH_FLOW_ENTER_DATE
        
        # Получаем все необходимые данные из контекста
        operator_id = context.user_data.get('operator_id')
        operator_name = context.user_data.get('operator_name')
        page_name = context.user_data.get('selected_page')
        page_id = context.user_data.get('page_names', {}).get(page_name)
        shift = context.user_data.get('selected_shift')
        operation_type = context.user_data.get('operation_type')
        display_operation_type = context.user_data.get('display_operation_type')
        amount = float(context.user_data.get('amount', 0))

        logger.info(f"Context data before creating record:")
        logger.info(f"operator_id: {operator_id}")
        logger.info(f"operator_name: {operator_name}")
        logger.info(f"page_name: {page_name}")
        logger.info(f"page_id: {page_id}")
        logger.info(f"shift: {shift}")
        logger.info(f"operation_type: {operation_type}")
        logger.info(f"display_operation_type: {display_operation_type}")
        logger.info(f"amount: {amount}")
        logger.info(f"date: {date}")
        
        # Проверяем наличие всех необходимых данных
        if not all([operator_id, operator_name, page_id, shift, operation_type, amount, date]):
            missing_fields = []
            if not operator_id: missing_fields.append("ID оператора")
            if not operator_name: missing_fields.append("Имя оператора")
            if not page_id: missing_fields.append("ID страницы")
            if not shift: missing_fields.append("Смена")
            if not operation_type: missing_fields.append("Тип операции")
            if not amount: missing_fields.append("Сумма")
            if not date: missing_fields.append("Дата")
            
            logger.error(f"Missing required fields: {', '.join(missing_fields)}")
            await update.message.reply_text(
                f"Не удалось создать запись. Отсутствуют необходимые данные: {', '.join(missing_fields)}. Начните заново.",
                reply_markup=create_main_keyboard()
            )
            return MENU
        
        # Создаем запись в Airtable
        record = {
            "ID": str(operator_id),
            "Name": operator_name,
            "Касса": amount,
            "Страница": [page_id],
            "Смена": shift,
            "Date": date,
            "Тип": operation_type,
            "Менеджер": [context.user_data['manager']] if context.user_data.get('manager') else None
        }
        
        logger.info(f"Creating record with data: {record}")
        
        try:
            # Создаем запись
            result = cash_table.create(record)
            logger.info(f"Record created successfully: {result}")
            
            # Отправляем сообщение об успехе
            await update.message.reply_text(
                f"✅ Запись успешно создана!\n\n"
                f"📄 Страница: {page_name}\n"
                f"⏰ Смена: {shift}\n"
                f"📝 Тип: {operation_type}\n"
                f"💵 Сумма: {amount}\n"
                f"📅 Дата: {text}",
                reply_markup=create_main_keyboard()
            )
            return MENU
        except Exception as e:
            logger.error(f"Error creating record in Airtable: {str(e)}")
            await update.message.reply_text(
                "Не удалось создать запись в базе данных. Пожалуйста, попробуйте еще раз или обратитесь к менеджеру.",
                reply_markup=create_main_keyboard()
            )
            return MENU
            
    except Exception as e:
        logger.error(f"Error in handle_cash_flow_date: {str(e)}")
        await update.message.reply_text(
            "Произошла ошибка при обработке даты. Пожалуйста, попробуйте еще раз.",
            reply_markup=create_main_keyboard()
        )
        return MENU

async def handle_schedule_date(update: Update, context: CallbackContext):
    """Обработчик выбора даты для графика"""
    text = update.message.text
    
    if text == "⬅️ Назад" or text == "🏠 В главное меню":
        return await handle_navigation(update, context)
    
    try:
        day = int(text)
        if 1 <= day <= 31:
            context.user_data['selected_date'] = day
            
            # Создаем клавиатуру с вариантами статуса и навигацией
            keyboard = [
                [KeyboardButton("🏖️ Выходной")],
                [KeyboardButton("🔄 Замена")],
                [KeyboardButton("⬅️ Назад")],
                [KeyboardButton("🏠 В главное меню")]
            ]
            reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
            
            await update.message.reply_text(
                f"Выберите статус для {day} числа:",
                reply_markup=reply_markup
            )
            return SCHEDULE_SELECT_SHIFT
        else:
            await update.message.reply_text(
                "Пожалуйста, введите число от 1 до 31",
                reply_markup=ReplyKeyboardMarkup([
                    [KeyboardButton("⬅️ Назад")],
                    [KeyboardButton("🏠 В главное меню")]
                ], resize_keyboard=True)
            )
            return SCHEDULE_SELECT_DATE
    except ValueError:
        await update.message.reply_text(
            "Пожалуйста, введите корректное число от 1 до 31",
            reply_markup=ReplyKeyboardMarkup([
                [KeyboardButton("⬅️ Назад")],
                [KeyboardButton("🏠 В главное меню")]
            ], resize_keyboard=True)
        )
        return SCHEDULE_SELECT_DATE

async def handle_schedule_shift(update: Update, context: CallbackContext):
    """Обработчик выбора статуса для графика"""
    text = update.message.text
    
    if text == "⬅️ Назад" or text == "🏠 В главное меню":
        return await handle_navigation(update, context)
    
    text = text.replace("🏖️ ", "").replace("🔄 ", "")
    
    operator_id = context.user_data['operator_id']
    day = context.user_data['selected_date']
    
    # Находим запись в графике для данного оператора
    schedule_records = schedule_table.all(
        formula=f"{{ID}}='{operator_id}'"
    )
    
    if schedule_records:
        record = schedule_records[0]
        # Обновляем поле с номером дня
        schedule_table.update(record['id'], {
            str(day): text
        })
        
        await update.message.reply_text(
            f"✅ График успешно обновлен!\n📅 День {day}: установлен статус '{text}'",
            reply_markup=create_main_keyboard()
        )
    else:
        await update.message.reply_text(
            "❌ Не удалось найти вашу запись в графике. Обратитесь к менеджеру.",
            reply_markup=create_main_keyboard()
        )
    
    return MENU

async def handle_navigation(update: Update, context: CallbackContext):
    """Обработчик навигации (Назад/В главное меню)"""
    text = update.message.text
    
    if text == "🏠 В главное меню":
        await update.message.reply_text(
            "Выберите действие:",
            reply_markup=create_main_keyboard()
        )
        return MENU
    elif text == "⬅️ Назад":
        # Определяем текущее состояние и возвращаемся на шаг назад
        current_state = context.user_data.get('state', MENU)
        if current_state == CASH_FLOW_ENTER_DATE:
            return await handle_cash_flow_type(update, context)
        elif current_state == CASH_FLOW_ENTER_AMOUNT:
            return await handle_cash_flow_shift(update, context)
        elif current_state == CASH_FLOW_SELECT_TYPE:
            return await handle_cash_flow_page(update, context)
        elif current_state == CASH_FLOW_SELECT_SHIFT:
            return await handle_menu(update, context)
        elif current_state == CASH_FLOW_SELECT_PAGE:
            return await handle_menu(update, context)
        elif current_state == SCHEDULE_SELECT_SHIFT:
            return await handle_schedule_date(update, context)
        elif current_state == SCHEDULE_SELECT_DATE:
            return await handle_menu(update, context)
    
    return MENU

def help_command(update: Update, context: CallbackContext) -> None:
    """Отправляет сообщение с помощью при команде /help"""
    help_text = """
Доступные команды:
/start - Начать работу с ботом
/help - Показать это сообщение помощи

Функции бота:
1. Касса - учет движения денежных средств
2. График - управление расписанием работы
"""
    update.message.reply_text(help_text)

def main():
    updater = Updater(os.getenv('TELEGRAM_TOKEN'))
    dispatcher = updater.dispatcher

    # Добавляем обработчики
    dispatcher.add_handler(CommandHandler('start', start))
    dispatcher.add_handler(CommandHandler('help', help_command))
    
    # Добавляем обработчики состояний
    conv_handler = ConversationHandler(
        entry_points=[MessageHandler(Filters.text & ~Filters.command, handle_menu)],
        states={
            CASH_FLOW_SELECT_PAGE: [MessageHandler(Filters.text & ~Filters.command, handle_cash_flow_page)],
            CASH_FLOW_SELECT_SHIFT: [MessageHandler(Filters.text & ~Filters.command, handle_cash_flow_shift)],
            CASH_FLOW_SELECT_TYPE: [MessageHandler(Filters.text & ~Filters.command, handle_cash_flow_type)],
            CASH_FLOW_ENTER_AMOUNT: [MessageHandler(Filters.text & ~Filters.command, handle_cash_flow_amount)],
            CASH_FLOW_ENTER_DATE: [MessageHandler(Filters.text & ~Filters.command, handle_cash_flow_date)],
            SCHEDULE_SELECT_DATE: [MessageHandler(Filters.text & ~Filters.command, handle_schedule_date)],
            SCHEDULE_SELECT_SHIFT: [MessageHandler(Filters.text & ~Filters.command, handle_schedule_shift)],
        },
        fallbacks=[],
    )
    dispatcher.add_handler(conv_handler)

    # Запускаем бота
    updater.start_polling()
    updater.idle()

if __name__ == '__main__':
    main() 