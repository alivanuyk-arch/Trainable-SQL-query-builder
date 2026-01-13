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
        
        constructor = get_constructor()

        if not constructor:
            await update.message.reply_text(
                "❌ Конструктор SQL не доступен\n"
                "Проверьте настройки базы данных и LLM"
            )
            return

        # Используем конструктор (только для получения SQL)
        if hasattr(constructor, 'process_query'):
            result = await constructor.process_query(user_question, user_id)
        else:
            await update.message.reply_text("❌ Конструктор не поддерживает process_query")
            return

        logger.info(f"Constructor result keys: {list(result.keys())}")
        logger.info(f"Constructor has llm: {hasattr(constructor, 'llm')}")

        # ========== КРИТИЧЕСКИЙ БЛОК: ЕСЛИ НУЖЕН LLM ==========
        if result.get('needs_llm'):
            logger.info(f"🔄 Constructor says needs LLM for: '{user_question}'")
            
            # Берем LLM клиент из конструктора
            llm_client = getattr(constructor, 'llm', None)
            
            if llm_client:
                logger.info("✅ LLM client available, calling...")
                
                try:
                    # Простой промпт со схемой
                    schema_prompt = """
                    Available tables:
                    - videos (id, title, views_count, likes_count, comments_count, created_at, video_created_at)
                    - video_snapshots (id, video_id, delta_views_count, delta_likes_count, delta_comments_count, created_at)
                    - creators (id, name, channel_url)
                    """
                    
                    # Вызываем LLM
                    await update.message.reply_text(
                        "🤖 Обращаюсь к AI для генерации SQL...",
                        parse_mode=ParseMode.MARKDOWN
                    )
                    
                    llm_result = await llm_client.generate_sql(user_question, schema_prompt)
                    
                    if llm_result and llm_result.sql:
                        # Заменяем fallback на LLM результат
                        result['sql'] = llm_result.sql
                        result['source'] = 'llm'
                        result['success'] = True
                        result['confidence'] = getattr(llm_result, 'confidence', 0.8)
                        result['is_safe'] = getattr(llm_result, 'is_safe', True)
                        
                        logger.info(f"✅ LLM generated SQL: {llm_result.sql}")
                        
                        # Сохраняем в конструктор для будущего
                        if hasattr(constructor, 'learn_new_pattern'):
                            await constructor.learn_new_pattern(user_question, llm_result.sql)
                            logger.info(f"💾 Saved to constructor patterns")
                            
                    else:
                        logger.warning("LLM returned no SQL, keeping fallback")
                        result['source'] = 'fallback'
                        result['success'] = True
                        
                except Exception as e:
                    logger.error(f"❌ LLM call failed: {e}", exc_info=True)
                    result['source'] = 'fallback'
                    result['success'] = True
                    result['error'] = f"LLM error: {str(e)}"
            else:
                logger.warning("No LLM client in constructor, using fallback")
                result['source'] = 'fallback'
                result['success'] = True

        # ========== ПРОВЕРКА РЕЗУЛЬТАТА ==========
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
            'fallback': '⚠️',
            'test': '🧪'
        }.get(source, '❓')
        
        source_text = {
            'cache': 'из кэша',
            'pattern': 'по шаблону', 
            'llm': 'от AI',
            'fallback': 'базовый',
            'test': 'тестовый'
        }.get(source, 'неизвестно')
        
        # Проверяем выполнение SQL (если есть db_manager)
        execution = {'success': False, 'results': []}
        
        # Если есть DatabaseManager, выполняем SQL
        if hasattr(constructor, 'db') and constructor.db and sql.upper().startswith('SELECT'):
            try:
                execution_results = await constructor.db.execute_query(sql)
                execution = {
                    'success': True,
                    'results': execution_results,
                    'row_count': len(execution_results) if execution_results else 0
                }
                logger.info(f"✅ SQL executed, rows: {execution['row_count']}")
            except Exception as e:
                execution = {'success': False, 'error': str(e), 'results': []}
                logger.warning(f"❌ SQL execution failed: {e}")
        
        result['execution'] = execution
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
        elif not execution_success and execution.get('error'):
            message_parts.append(f"⚠️ **Ошибка выполнения:** {execution['error']}")
        
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
        original_sql = context.user_data.get('original_sql_for_edit', context.user_data.get('last_sql'))
        source = context.user_data.get('last_source', 'unknown')
        
        if not question or not original_sql:
            await update.message.reply_text("❌ Ошибка: данные вопроса не найдены")
            context.user_data.clear()
            return
        
        # Отключаем режим редактирования
        context.user_data['waiting_for_correction'] = False
        
        # Проверяем команду отмены
        if corrected_sql.lower() in ['/cancel', 'отмена', 'cancel']:
            await update.message.reply_text("❌ Редактирование отменено")
            context.user_data.pop('original_sql_for_edit', None)
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
        
        # Если SQL был изменен - учимся на исправлении
        if original_sql.strip() != corrected_sql.strip():
            logger.info(f"🔧 SQL изменен, сохраняем исправление...")
            
            # Сохраняем исправление в конструктор
            if hasattr(constructor, 'learn_from_correction'):
                await constructor.learn_from_correction(
                    question=question,
                    llm_sql=original_sql,
                    corrected_sql=corrected_sql,
                    user_feedback="исправлено пользователем"
                )
                logger.info(f"💾 Исправление сохранено в конструктор")
            
            # Обновляем последний SQL
            context.user_data['last_sql'] = corrected_sql
            
            # Выполняем исправленный SQL
            execution_result = ""
            if hasattr(constructor, 'db') and constructor.db:
                try:
                    db_result = await constructor.db.execute_query(corrected_sql)
                    if isinstance(db_result, list):
                        execution_result = f"Найдено {len(db_result)} записей"
                    else:
                        execution_result = str(db_result)
                except Exception as db_error:
                    execution_result = f"Ошибка выполнения: {str(db_error)}"
            else:
                execution_result = "✅ SQL принят"
            
            # Показываем результат
            await update.message.reply_text(
                f"✅ **Исправление применено!**\n\n"
                f"**Исправленный SQL:**\n"
                f"```sql\n{corrected_sql}\n```\n\n"
                f"**Результат:** {execution_result}\n\n"
                f"Система запомнила это исправление.",
                parse_mode=ParseMode.MARKDOWN
            )
            
        else:
            # SQL не изменился
            await update.message.reply_text(
                "⚠️ **SQL не изменен**\n\n"
                "Вы отправили тот же самый запрос.",
                parse_mode=ParseMode.MARKDOWN
            )
        
        # Очищаем временные данные
        context.user_data.pop('original_sql_for_edit', None)
        
    except Exception as e:
        logger.error(f"Ошибка обработки исправления: {e}")
        await update.message.reply_text(f"❌ Ошибка обработки исправления: {str(e)}")
        context.user_data.clear()


async def handle_callback_query(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик кнопок с обучением системы"""
    query = update.callback_query
    await query.answer()
    
    data = query.data
    logger.info(f"Callback query: {data}")
    
    try:
        if data == "confirm_success":
            # ✅ Пользователь подтвердил, что SQL правильный
            await handle_confirm_success(query, context)
            
        elif data == "edit_sql":
            # ✏️ Пользователь хочет исправить SQL
            await handle_edit_sql(query, context)
            
        elif data == "rephrase":
            # 🔄 Пользователь хочет перефразировать вопрос
            await handle_rephrase(query, context)
            
        elif data == "save_correction":
            # 💾 Пользователь отправил исправленный SQL
            await handle_save_correction(query, context)
            
        elif data == "cancel_correction":
            # ❌ Отмена редактирования
            context.user_data.pop('waiting_for_correction', None)
            await query.edit_message_text("❌ Редактирование отменено")
            
        else:
            logger.warning(f"Unknown callback data: {data}")
            await query.message.reply_text("❌ Неизвестное действие")
            
    except Exception as e:
        logger.error(f"Error in callback handler: {e}", exc_info=True)
        await query.message.reply_text(f"❌ Ошибка: {str(e)}")


async def handle_confirm_success(query, context):
    """✅ Кнопка 'Подтвердить' - система учится на успешном запросе"""
    constructor = get_constructor()
    
    if not constructor:
        await query.edit_message_text("❌ Конструктор не доступен")
        return
    
    # Получаем сохраненные данные
    question = context.user_data.get('last_question')
    sql = context.user_data.get('last_sql')
    source = context.user_data.get('last_source', 'unknown')
    
    if not question or not sql:
        await query.edit_message_text("❌ Данные не найдены")
        return
    
    try:
        # 1. Сохраняем в конструктор как успешный паттерн
        if hasattr(constructor, 'learn_from_success'):
            await constructor.learn_from_success(question, sql)
            logger.info(f"✅ Learned from success: '{question[:50]}...'")
        
        # 2. Если это был LLM ответ - дополнительно сохраняем
        if source == 'llm':
            if hasattr(constructor, 'learn_new_pattern'):
                await constructor.learn_new_pattern(question, sql)
                logger.info(f"💾 Saved LLM pattern to constructor")
        
        # 3. Обновляем статистику
        if hasattr(constructor, 'stats'):
            constructor.stats['confirmed_patterns'] = constructor.stats.get('confirmed_patterns', 0) + 1
        
        await query.edit_message_text(
            "✅ **Запрос подтвержден!**\n\n"
            f"• Паттерн сохранен для будущих запросов\n"
            f"• При следующем запросе ответ будет мгновенным\n"
            f"• Система стала умнее на 1 шаблон 😊",
            parse_mode=ParseMode.MARKDOWN
        )
        
    except Exception as e:
        logger.error(f"Error confirming: {e}")
        await query.edit_message_text(f"❌ Ошибка сохранения: {str(e)}")


async def handle_edit_sql(query, context):
    """✏️ Кнопка 'Исправить SQL'"""
    try:
        # Получаем сохраненные данные
        original_sql = context.user_data.get('last_sql', '')
        question = context.user_data.get('last_question', '')
        source = context.user_data.get('last_source', 'unknown')
        
        if not original_sql:
            await query.edit_message_text("❌ Не найден SQL для редактирования")
            return
        
        logger.info(f"Starting SQL edit for: '{question[:50]}...'")
        
        # Активируем режим редактирования
        context.user_data['waiting_for_correction'] = True
        
        # Сохраняем оригинальный SQL отдельно
        context.user_data['original_sql_for_edit'] = original_sql
        
        await query.edit_message_text(
            "✏️ **Режим редактирования SQL**\n\n"
            f"**Вопрос:** {question}\n\n"
            f"**Текущий SQL:**\n"
            f"```sql\n{original_sql}\n```\n\n"
            "**Отправьте исправленный SQL запрос.**\n"
            "Используйте /cancel для отмены.\n\n"
            f"_Источник: {source}_",
            parse_mode=ParseMode.MARKDOWN
        )
        
    except Exception as e:
        logger.error(f"Error in handle_edit_sql: {e}")
        await query.edit_message_text(f"❌ Ошибка: {str(e)}")

async def handle_rephrase(query, context):
    """Кнопка '🔄 Перефразировать вопрос'"""
    await query.edit_message_text(
        "🔄 **Перефразирование**\n\n"
        "Пришлите перефразированный вопрос.",
        parse_mode=ParseMode.MARKDOWN
    )
    async def add_correction_to_prompt(user_query: str, 
                                  wrong_llm_sql: str, 
                                  correct_user_sql: str, 
                                  user_id: int) -> bool:
        """
        Добавляет правило из исправления LLM в промпт.
        Возвращает True если успешно, False если ошибка.
        """
    try:
        # 1. Проверяем доступность prompt_factory
        if not hasattr(constructor, 'prompt_factory'):
            logger.error("❌ Constructor has no prompt_factory")
            return False
            
        if not constructor.prompt_factory:
            logger.error("❌ prompt_factory is None")
            return False
        
        # 2. Анализируем ошибку
        error_type = analyze_error_type(wrong_llm_sql, correct_user_sql)
        
        # 3. Создаём правило
        rule = create_prompt_rule(
            user_query=user_query,
            wrong_sql=wrong_llm_sql,
            correct_sql=correct_user_sql,
            error_type=error_type
        )
        
        # 4. Добавляем в фабрику промптов
        await constructor.prompt_factory.add_correction_rule(rule)
        
        # 5. Логируем успех
        logger.info(f"✅ Added correction rule to prompt. User {user_id}, error: {error_type}")
        
        # 6. Обновляем промпт в конструкторе (если нужно)
        if hasattr(constructor, 'update_schema_prompt'):
            new_prompt = constructor.prompt_factory.get_full_prompt()
            await constructor.update_schema_prompt(new_prompt)
        
        return True
        
    except Exception as e:
        logger.error(f"❌ Failed to add correction to prompt: {e}")
        return False
    
def analyze_error_type(wrong_sql: str, correct_sql: str) -> str:
    """Определяет тип ошибки LLM"""
    wrong_upper = wrong_sql.upper()
    correct_upper = correct_sql.upper()
    
    if "COUNT(*)" in wrong_upper and "SUM(" in correct_upper:
        return "WRONG_AGGREGATION"
    elif "JOIN" not in wrong_upper and "JOIN" in correct_upper:
        return "MISSING_JOIN"
    elif "WHERE" not in wrong_upper and "WHERE" in correct_upper:
        return "MISSING_FILTER"
    elif "EXTRACT" not in wrong_upper and "EXTRACT" in correct_upper:
        return "DATE_FORMAT_ERROR"
    else:
        return "LOGIC_ERROR"

def create_prompt_rule(user_query: str, wrong_sql: str, 
                       correct_sql: str, error_type: str) -> str:
    """Создаёт текстовое правило для промпта"""
    keywords = extract_keywords(user_query)
    
    return f"""
# ERROR CORRECTION #{hash(user_query) % 1000:03d}
# When user asks: "{keywords}"
# LLM mistake: {error_type}
# Wrong SQL: {wrong_sql[:120]}...
# Correct SQL: {correct_sql[:120]}...
# Rule: {generate_rule_text(error_type, wrong_sql, correct_sql)}
"""