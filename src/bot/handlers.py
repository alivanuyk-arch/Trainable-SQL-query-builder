"""
Обработчики - создают конструктор при первом запросе
"""
import logging
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes
from telegram.constants import ParseMode

logger = logging.getLogger(__name__)

# ==================== КОНСТРУКТОР ====================

_constructor = None

def get_constructor():
    """Создает конструктор один раз при первом вызове"""
    global _constructor
    if _constructor is None:
        try:
            from config import config
            from src.constructor.core import QueryConstructor
            from src.database.manager import DatabaseManager
            from src.llm.client import LLMClient
            
            logger.info("🧠 Создание конструктора...")
            
            # 1. Менеджер БД
            db_manager = DatabaseManager(config.DATABASE_URL)
            logger.debug("✅ DatabaseManager создан")
            
            # 2. LLM клиент
            llm_client = None
            if config.LLM_ENABLED:
                llm_client = LLMClient(config)
                logger.debug(f"✅ LLMClient создан ({config.LLM_PROVIDER})")
            else:
                logger.debug("⚠️  LLM отключен")
            
            # 3. Сам конструктор
            _constructor = QueryConstructor(llm_client, db_manager, config)
            logger.info("✅ Конструктор создан и готов к работе")
            
        except Exception as e:
            logger.error(f"❌ Ошибка создания конструктора: {e}")
            import traceback
            traceback.print_exc()
            _constructor = False  # Помечаем как неудачу
    
    return _constructor if _constructor not in (None, False) else None

# ==================== ОБРАБОТЧИКИ ====================

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик /start"""
    welcome_text = (
        "🤖 **Trainable SQL Query Builder**\n\n"
        "Я конвертирую ваши запросы на русском языке в SQL.\n\n"
        "📝 **Как пользоваться:**\n"
        "1. Просто напишите вопрос\n"
        "2. Я сгенерирую SQL запрос\n"
        "3. Вы можете его подтвердить или исправить\n"
        "4. Система обучается на ваших исправлениях!\n\n"
        "🔧 **Доступные команды:**\n"
        "/start - это сообщение\n"
        "/stats - статистика использования\n"
        "/help - справка"
    )
    await update.message.reply_text(welcome_text, parse_mode=ParseMode.MARKDOWN)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик /help"""
    help_text = (
        "💡 **Примеры запросов:**\n\n"
        "• 'Сколько всего видео?'\n"
        "• 'Статистика за ноябрь 2025'\n"
        "• 'Прирост просмотров 28 ноября'\n"
        "• 'Топ 10 видео по просмотрам'\n\n"
        "🔄 **После генерации SQL:**\n"
        "✅ - выполнить запрос\n"
        "✏️ - исправить SQL вручную\n"
        "🔄 - перефразировать вопрос\n\n"
        "🧠 **Система самообучается** на ваших исправлениях!"
    )
    await update.message.reply_text(help_text, parse_mode=ParseMode.MARKDOWN)

async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик /stats"""
    constructor = get_constructor()
    
    if not constructor:
        await update.message.reply_text("❌ Статистика недоступна (конструктор не создан)")
        return
    
    # Получаем статистику из конструктора
    stats = constructor.stats if hasattr(constructor, 'stats') else {}
    total = stats.get('total_queries', 0)
    llm_calls = stats.get('llm_calls', 0)
    corrections = stats.get('corrections', 0)
    
    if total > 0:
        llm_percent = int((llm_calls / total) * 100)
    else:
        llm_percent = 0
    
    stats_text = (
        f"📊 **Статистика системы**\n\n"
        f"• Всего запросов: `{total}`\n"
        f"• Обращений к LLM: `{llm_calls}` ({llm_percent}%)\n"
        f"• Исправлений: `{corrections}`\n\n"
        f"_Чем меньше % LLM, тем эффективнее обучение_"
    )
    
    await update.message.reply_text(stats_text, parse_mode=ParseMode.MARKDOWN)

async def handle_user_query(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка вопроса пользователя"""

    # ПЕРВОЕ: проверка режима редактирования
    if context.user_data.get('waiting_for_correction'):
        logger.info("📝 В режиме редактирования, перенаправляю в handle_sql_correction")
        await handle_sql_correction(update, context)
        return

    try:
        user_question = update.message.text.strip()
        user_id = update.effective_user.id
        
        logger.info(f"User {user_id} query: {user_question[:100]}...")
        
        if not user_question:
            await update.message.reply_text("Пожалуйста, введите ваш вопрос.")
            return
        
        # Показываем что обрабатываем
        await update.message.reply_text(
            f"🔍 _Обрабатываю: {user_question}_", 
            parse_mode=ParseMode.MARKDOWN
        )
        
        # Получаем конструктор (создастся при первом вызове)
        constructor = get_constructor()
        
        if not constructor:
            await update.message.reply_text(
                "❌ Конструктор SQL не доступен\n"
                "Проверьте настройки базы данных и LLM"
            )
            return
        
        # Используем новый метод конструктора
        if hasattr(constructor, 'process_and_execute_query'):
            result = await constructor.process_and_execute_query(user_question, user_id)
        else:
            # Запасной вариант если метода нет
            result = await constructor.process_query(user_question, user_id)
        
        # Проверяем результат
        if not result.get('success', True):
            error_msg = result.get('error', 'Неизвестная ошибка')
            await update.message.reply_text(f"❌ Ошибка: {error_msg}")
            return
        
        sql = result.get('sql', '')
        source = result.get('source', 'unknown')
        
        if not sql:
            await update.message.reply_text("❌ Не удалось сгенерировать SQL запрос")
            return
        
        # Сохраняем для возможных исправлений
        context.user_data['last_question'] = user_question
        context.user_data['last_sql'] = sql
        context.user_data['last_source'] = source
        context.user_data['last_result'] = result
        
        # Формируем ответ
        source_emoji = {
            'cache': '🔄',
            'pattern': '📚',
            'llm': '🤖',
            'test': '🧪'
        }.get(source, '❓')
        
        source_text = {
            'cache': 'из кэша',
            'pattern': 'по шаблону', 
            'llm': 'от LLM',
            'test': 'тестовый'
        }.get(source, 'неизвестно')
        
        # Проверяем выполнение SQL
        execution = result.get('execution', {})
        execution_success = execution.get('success', False)
        execution_results = execution.get('results', [])
        
        # Создаем кнопки
        keyboard = []
        
        if execution_success:
            keyboard.append([
                InlineKeyboardButton("✅ Подтвердить", callback_data="confirm_success"),
                InlineKeyboardButton("✏️ Исправить SQL", callback_data="edit_sql")
            ])
        else:
            keyboard.append([
                InlineKeyboardButton("✏️ Исправить SQL", callback_data="edit_sql")
            ])
        
        if source == 'llm':
            keyboard.append([
                InlineKeyboardButton("🔄 Перефразировать вопрос", callback_data="rephrase")
            ])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        # Формируем сообщение
        message_parts = []
        message_parts.append(f"{source_emoji} **Сгенерирован SQL** ({source_text}):")
        message_parts.append(f"```sql\n{sql}\n```")
        
        # Добавляем результаты если есть
        if execution_success and execution_results:
            row_count = len(execution_results)
            if row_count == 1:
                # Показываем первую запись
                first_result = execution_results[0]
                if isinstance(first_result, dict):
                    # Форматируем красиво
                    formatted = []
                    for key, value in first_result.items():
                        formatted.append(f"  {key}: {value}")
                    message_parts.append("📊 **Результат:**")
                    message_parts.append("\n".join(formatted))
                else:
                    message_parts.append(f"📊 **Результат:** {first_result}")
            else:
                message_parts.append(f"📊 **Найдено записей:** {row_count}")
        
        response = "\n\n".join(message_parts)
        
        # Отправляем
        await update.message.reply_text(
            response,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=reply_markup
        )
        
    except Exception as e:
        logger.error(f"Error in handle_user_query: {e}", exc_info=True)
        await update.message.reply_text(
            f"❌ **Произошла ошибка**\n\n"
            f"Попробуйте:\n"
            f"• Переформулировать вопрос\n"
            f"• Использовать /help для примеров"
            )

async def handle_sql_correction(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка исправленного SQL от пользователя"""
    try:
        corrected_sql = update.message.text.strip()
        user_id = update.effective_user.id
        
        logger.info(f"🔧 Получено исправление SQL от {user_id}: {corrected_sql[:100]}...")
        
        # Проверяем режим редактирования
        if not context.user_data.get('waiting_for_correction'):
            logger.warning("Не в режиме редактирования, игнорируем")
            return
        
        # Получаем сохраненные данные
        question = context.user_data.get('last_question')
        original_sql = context.user_data.get('last_sql')
        
        if not question or not original_sql:
            await update.message.reply_text("❌ Ошибка: данные вопроса не найдены")
            context.user_data.clear()
            return
        
        # Отключаем режим редактирования
        context.user_data['waiting_for_correction'] = False
        
        # Проверяем команду отмены
        if corrected_sql.lower() in ['/cancel', 'отмена', 'cancel']:
            await update.message.reply_text("❌ Редактирование отменено")
            context.user_data.clear()
            return
        
        # Проверяем что это похоже на SQL
        if not (corrected_sql.upper().startswith('SELECT') or 
                corrected_sql.upper().startswith('WITH')):
            await update.message.reply_text(
                "⚠️ Это не похоже на SQL запрос.\n"
                "SQL должен начинаться с SELECT или WITH.\n"
                "Попробуйте еще раз или отправьте /cancel"
            )
            context.user_data['waiting_for_correction'] = True
            return
        
        # Получаем конструктор
        constructor = get_constructor()
        if not constructor:
            await update.message.reply_text("❌ Конструктор не доступен")
            return
        
        # Обрабатываем исправление через конструктор
        logger.info(f"📤 Отправляю исправление в конструктор...")
        result = await constructor.process_correction(
            question=question,
            original_sql=original_sql,
            corrected_sql=corrected_sql,
            user_id=user_id
        )
        
        logger.info(f"📥 Результат исправления: {result}")
        
        # Показываем результат
        await update.message.reply_text(
            f"✅ **Исправление применено!**\n\n"
            f"**Исправленный SQL:**\n"
            f"```sql\n{corrected_sql}\n```\n\n"
            f"**Результат выполнения:** {result}\n\n"
            f"Система запомнила это исправление.",
            parse_mode=ParseMode.MARKDOWN
        )
        
        # Очищаем состояние
        context.user_data.clear()
        
    except Exception as e:
        logger.error(f"Ошибка обработки исправления: {e}")
        await update.message.reply_text(f"❌ Ошибка обработки исправления: {str(e)}")
        context.user_data.clear()


async def handle_callback_query(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик кнопок"""
    query = update.callback_query
    await query.answer()
    
    data = query.data
    
    if data == "confirm_success":
        await handle_confirm_success(query, context)
    elif data == "edit_sql":
        await handle_edit_sql(query, context)
    elif data == "rephrase":
        await handle_rephrase(query, context)
    else:
        await query.message.reply_text("❌ Неизвестное действие")

async def handle_confirm_success(query, context):
    """Кнопка '✅ Подтвердить'"""
    constructor = get_constructor()
    
    if not constructor:
        await query.edit_message_text("❌ Конструктор не доступен")
        return
    
    # Получаем сохраненные данные
    question = context.user_data.get('last_question')
    sql = context.user_data.get('last_sql')
    
    if not question or not sql:
        await query.edit_message_text("❌ Данные не найдены")
        return
    
    try:
        # Сохраняем как успешный паттерн
        if hasattr(constructor, 'learn_from_success'):
            await constructor.learn_from_success(question, sql)
        
        await query.edit_message_text(
            "✅ **Запрос подтвержден!** Система запомнила этот паттерн.",
            parse_mode=ParseMode.MARKDOWN
        )
        
    except Exception as e:
        await query.edit_message_text(f"❌ Ошибка сохранения: {str(e)}")

async def handle_edit_sql(query, context):
    """Кнопка '✏️ Исправить SQL'"""
    context.user_data['waiting_for_correction'] = True
    
    await query.edit_message_text(
        "✏️ **Режим редактирования**\n\n"
        "Пришлите исправленный SQL запрос.\n"
        "Используйте /cancel для отмены.",
        parse_mode=ParseMode.MARKDOWN
    )

async def handle_rephrase(query, context):
    """Кнопка '🔄 Перефразировать вопрос'"""
    await query.edit_message_text(
        "🔄 **Перефразирование**\n\n"
        "Пришлите перефразированный вопрос.",
        parse_mode=ParseMode.MARKDOWN
    )