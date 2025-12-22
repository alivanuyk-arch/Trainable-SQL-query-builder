import sys
import logging
from pathlib import Path
from typing import Dict, Any, Optional
from dataclasses import dataclass
from datetime import datetime
import json

# КРИТИЧЕСКИ ВАЖНО: Добавляем корень проекта в путь
current_dir = Path(__file__).parent.parent.parent  # Поднимаемся на 3 уровня вверх
sys.path.insert(0, str(current_dir))

print(f"[DEBUG bot_core] Текущий файл: {__file__}")
print(f"[DEBUG bot_core] Добавлен путь: {current_dir}")

try:
    from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
    from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters
    from telegram.constants import ParseMode
    print("[DEBUG bot_core] Telegram модули загружены")
except ImportError as e:
    print(f"[DEBUG bot_core] Ошибка загрузки Telegram: {e}")
    raise

# Импортируем наши модули с обработкой ошибок
try:
    from src.constructor.core import QueryConstructor
    print("[DEBUG bot_core] QueryConstructor загружен")
except ImportError as e:
    print(f"[DEBUG bot_core] Ошибка QueryConstructor: {e}")
    # Пробуем альтернативный путь
    try:
        from constructor.core import QueryConstructor
        print("[DEBUG bot_core] QueryConstructor загружен через альтернативный путь")
    except ImportError:
        print("[DEBUG bot_core] Создаю заглушку QueryConstructor")
        # Заглушка для теста
        class QueryConstructor:
            def __init__(self, *args, **kwargs):
                print("[DEBUG] Создан QueryConstructor-заглушка")
                pass
            async def initialize_with_schema(self, *args):
                pass
            async def process_query(self, query, user_id=None):
                return {"sql": "SELECT 1 as test;", "source": "test"}
            async def learn_from_correction(self, *args):
                pass
            async def learn_from_success(self, *args):
                pass
            def save_all_data(self):
                pass
            def get_stats(self):
                return type('obj', (object,), {
                    'total_patterns': 0,
                    'exact_hits': 0,
                    'pattern_hits': 0,
                    'llm_calls': 0,
                    'corrections': 0,
                    'learning_rate': 0.0
                })()

try:
    from src.llm.client import LLMClient
    print("[DEBUG bot_core] LLMClient загружен")
except ImportError as e:
    print(f"[DEBUG bot_core] Ошибка LLMClient: {e}")
    # Заглушка
    class LLMClient:
        def __init__(self, *args, **kwargs):
            pass
        async def initialize(self):
            pass
        async def close(self):
            pass
        def get_stats(self):
            return {}

try:
    from src.database.manager import DatabaseManager
    print("[DEBUG bot_core] DatabaseManager загружен")
except ImportError as e:
    print(f"[DEBUG bot_core] Ошибка DatabaseManager: {e}")
    # Заглушка
    class DatabaseManager:
        def __init__(self, *args, **kwargs):
            pass
        async def connect(self):
            pass
        async def disconnect(self):
            pass
        async def execute_query(self, sql, params=None):
            return [{"test": 1, "message": "Test data from stub"}]

try:
    from src.constructor.schema_detector import AutoSchemaDetector
    print("[DEBUG bot_core] AutoSchemaDetector загружен")
except ImportError as e:
    print(f"[DEBUG bot_core] Ошибка AutoSchemaDetector: {e}")
    # Заглушка
    class AutoSchemaDetector:
        def __init__(self, *args, **kwargs):
            pass
        async def detect_schema(self):
            return {"tables": {}, "aliases": {}}
        def generate_schema_prompt(self):
            return ""

try:
    from src.utils.logger import setup_logging
    print("[DEBUG bot_core] setup_logging загружен")
except ImportError as e:
    print(f"[DEBUG bot_core] Ошибка setup_logging: {e}")
    import logging
    def setup_logging(name, log_dir=None):
        logger = logging.getLogger(name)
        logger.setLevel(logging.INFO)
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
        logger.addHandler(handler)
        return logger

try:
    from src.utils.cost_tracker import CostTracker
    print("[DEBUG bot_core] CostTracker загружен")
except ImportError as e:
    print(f"[DEBUG bot_core] Ошибка CostTracker: {e}")
    # Заглушка
    class CostTracker:
        def __init__(self, *args, **kwargs):
            pass
        def track_request(self, *args, **kwargs):
            pass
        def get_stats(self):
            return {}

print("[DEBUG bot_core] Все импорты обработаны")
logger = logging.getLogger(__name__)

@dataclass
class UserSession:
    """Сессия пользователя"""
    user_id: int
    current_query: Optional[str] = None
    current_sql: Optional[str] = None
    waiting_for_correction: bool = False
    correction_step: int = 0
    last_interaction: datetime = None
    query_history: list = None
    preferred_format: str = "table"
    
    def __post_init__(self):
        if self.query_history is None:
            self.query_history = []
        if self.last_interaction is None:
            self.last_interaction = datetime.now()

class SQLBot:
    """Основной класс Telegram бота для SQL конструктора"""
    
    def __init__(self, config):
        self.config = config
        self.application = None
        self.sessions: Dict[int, UserSession] = {}
        
        # Инициализация компонентов
        self.db_manager = DatabaseManager(config.DATABASE_URL)
        self.llm_client = LLMClient(config) if config.LLM_ENABLED else None
        self.constructor = QueryConstructor(self.llm_client, self.db_manager, config)
        self.cost_tracker = CostTracker()
        
        # Схема БД
        self.schema = None
        self.schema_prompt = None
        
        # Состояния
        self.stats = {
            'total_users': 0,
            'total_queries': 0,
            'successful_queries': 0,
            'corrections': 0,
            'avg_response_time': 0
        }
    
    async def initialize(self):
        """Инициализация бота"""
        logger.info("Initializing SQL Bot...")
        
        # Инициализация Telegram бота
        self.application = Application.builder().token(self.config.TELEGRAM_TOKEN).build()
        
        # Регистрация обработчиков
        self._register_handlers()
        
        # Инициализация БД
        await self.db_manager.connect()
        
        # Загрузка/определение схемы
        await self._initialize_schema()
        
        # Инициализация LLM если включена
        if self.llm_client:
            await self.llm_client.initialize()
        
        # Инициализация конструктора
        await self.constructor.initialize_with_schema(self.schema)
        
        logger.info("SQL Bot initialized successfully")
    
    async def _initialize_schema(self):
        """Инициализация схемы БД"""
        if self.config.ENABLE_AUTO_SCHEMA_DETECTION:
            # Автоматическое определение схемы
            detector = AutoSchemaDetector(self.db_manager)
            self.schema = await detector.detect_schema()
            self.schema_prompt = detector.generate_schema_prompt()
            logger.info(f"Auto-detected schema: {len(self.schema.get('tables', {}))} tables")
        else:
            # Использование предопределенной схемы
            from src.database.schema_loader import SchemaLoader
            loader = SchemaLoader(self.config.DATA_DIR)
            self.schema = await loader.load_from_json(self.config.JSON_DATA_FILE)
            self.schema_prompt = self._generate_simple_schema_prompt()
            logger.info(f"Loaded schema from JSON")
    
    def _generate_simple_schema_prompt(self) -> str:
        """Генерация простого промпта схемы"""
        if not self.schema:
            return ""
        
        prompt = "Available tables and fields:\n\n"
        
        for table_name, table_info in self.schema.get('tables', {}).items():
            prompt += f"{table_name}:\n"
            for column_name, column_type in table_info.get('columns', {}).items():
                prompt += f"  - {column_name} ({column_type})\n"
            prompt += "\n"
        
        return prompt
    
    def _register_handlers(self):
        """Регистрация обработчиков"""
        # Команды
        self.application.add_handler(CommandHandler("start", self.start_command))
        self.application.add_handler(CommandHandler("help", self.help_command))
        self.application.add_handler(CommandHandler("stats", self.stats_command))
        self.application.add_handler(CommandHandler("schema", self.schema_command))
        self.application.add_handler(CommandHandler("clear", self.clear_command))
        self.application.add_handler(CommandHandler("format", self.format_command))
        
        # Сообщения
        self.application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_message))
        
        # Callback queries (кнопки)
        self.application.add_handler(CallbackQueryHandler(self.handle_callback))
        
        # Ошибки
        self.application.add_error_handler(self.error_handler)
    
    async def start(self):
        """Запуск бота"""
        await self.application.run_polling(allowed_updates=Update.ALL_TYPES)
    
    async def stop(self):
        """Остановка бота"""
        # Сохранение данных
        self.constructor.save_all_data()
        
        # Закрытие соединений
        if self.llm_client:
            await self.llm_client.close()
        await self.db_manager.disconnect()
        
        logger.info("SQL Bot stopped")
    
    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработка команды /start"""
        user = update.effective_user
        user_id = user.id
        
        # Создаем или обновляем сессию
        if user_id not in self.sessions:
            self.sessions[user_id] = UserSession(user_id=user_id)
            self.stats['total_users'] += 1
        
        welcome_message = f"""
👋 Привет, {user.first_name}!

Я — умный конструктор SQL запросов. Просто опишите на русском языке, какую информацию хотите получить из базы данных.

Примеры запросов:
• "Сколько всего видео в системе?"
• "Статистика за ноябрь 2025 года"
• "Прирост просмотров 28 ноября"
• "Сумма просмотров у креатора abc123"

Используйте /help для списка команд
Используйте /schema для просмотра структуры базы данных
"""
        
        await update.message.reply_text(welcome_message)
    
    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработка команды /help"""
        help_text = """
📚 **Доступные команды:**

/start - Начало работы
/help - Эта справка
/schema - Показать структуру базы данных
/stats - Статистика использования
/clear - Очистить историю запросов
/format - Изменить формат вывода (table/json)

💡 **Как пользоваться:**
1. Просто напишите вопрос на русском языке
2. Бот предложит SQL запрос
3. Выберите вариант:
   ✅ Да, всё верно - выполнить запрос
   ✏️ Нет, исправить - править SQL вручную
   🔄 Перефразируй - переформулировать вопрос

🎯 **Примеры запросов:**
• "Видео креатора с id abc123"
• "Сумма просмотров за ноябрь"
• "Средний прирост просмотров в день"
• "Топ 10 видео по просмотрам"
"""
        
        await update.message.reply_text(help_text, parse_mode=ParseMode.MARKDOWN)
    
    async def schema_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработка команды /schema"""
        if not self.schema:
            await update.message.reply_text("❌ Схема базы данных не загружена")
            return
        
        schema_text = "📊 **Структура базы данных:**\n\n"
        
        for table_name, table_info in self.schema.get('tables', {}).items():
            russian_name = self.schema.get('aliases', {}).get(table_name, table_name)
            schema_text += f"**{table_name}** ({russian_name}):\n"
            
            for column_name, column_info in table_info.get('columns', {}).items():
                column_key = f"{table_name}.{column_name}"
                russian_alias = self.schema.get('aliases', {}).get(column_key, column_name)
                schema_text += f"  • `{column_name}` - {russian_alias}\n"
            
            schema_text += "\n"
        
        # Обрезаем если слишком длинное
        if len(schema_text) > 4000:
            schema_text = schema_text[:4000] + "\n\n... (полную схему смотрите в БД)"
        
        await update.message.reply_text(schema_text, parse_mode=ParseMode.MARKDOWN)
    
    async def stats_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработка команды /stats"""
        user_id = update.effective_user.id
        
        # Статистика конструктора
        const_stats = self.constructor.get_stats()
        
        # Статистика LLM если есть
        llm_stats = self.llm_client.get_stats() if self.llm_client else {}
        
        stats_text = f"""
📈 **Статистика системы:**

**Общая:**
• Пользователей: {self.stats['total_users']}
• Запросов: {self.stats['total_queries']}
• Успешных: {self.stats['successful_queries']}
• Исправлений: {self.stats['corrections']}

**Конструктор:**
• Паттернов: {const_stats.total_patterns}
• Попаданий в кэш: {const_stats.exact_hits}
• Попаданий в паттерны: {const_stats.pattern_hits}
• Обращений к LLM: {const_stats.llm_calls}
• Коэффициент обучения: {const_stats.learning_rate:.2%}
"""
        
        if llm_stats:
            stats_text += f"""
**LLM ({self.config.LLM_PROVIDER}):**
• Всего запросов: {llm_stats.get('total_requests', 0)}
• Успешных: {llm_stats.get('successful_requests', 0)}
• Среднее время: {llm_stats.get('avg_response_time', 0):.2f} сек
"""
        
        await update.message.reply_text(stats_text, parse_mode=ParseMode.MARKDOWN)
    
    async def clear_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработка команды /clear"""
        user_id = update.effective_user.id
        
        if user_id in self.sessions:
            self.sessions[user_id].query_history = []
        
        await update.message.reply_text("✅ История запросов очищена")
    
    async def format_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработка команды /format"""
        user_id = update.effective_user.id
        
        keyboard = [
            [
                InlineKeyboardButton("📊 Таблица", callback_data="format_table"),
                InlineKeyboardButton("📝 JSON", callback_data="format_json")
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            "Выберите формат вывода результатов:",
            reply_markup=reply_markup
        )
    
    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработка текстовых сообщений (запросов)"""
        user_query = update.message.text.strip()
        user_id = update.effective_user.id
        
        logger.info(f"User {user_id}: '{user_query}'")
        
        # Проверяем сессию
        if user_id not in self.sessions:
            self.sessions[user_id] = UserSession(user_id=user_id)
            self.stats['total_users'] += 1
        
        session = self.sessions[user_id]
        session.current_query = user_query
        session.last_interaction = datetime.now()
        
        # Добавляем в историю
        session.query_history.append({
            'query': user_query,
            'timestamp': datetime.now().isoformat()
        })
        
        # Показываем "печатает"
        await update.message.chat.send_action(action="typing")
        
        try:
            # Обрабатываем запрос
            result = await self.constructor.process_query(user_query, str(user_id))
            
            if not result:
                await update.message.reply_text("❌ Не удалось сгенерировать SQL запрос")
                return
            
            session.current_sql = result['sql']
            self.stats['total_queries'] += 1
            
            # Форматируем SQL для отображения
            formatted_sql = self._format_sql_for_display(result['sql'])
            
            # Создаем сообщение с источником
            source_emoji = {
                'exact_cache': '💾',
                'pattern': '🔍',
                'llm': '🤖',
                'fallback': '⚡'
            }.get(result.get('source', 'llm'), '🤖')
            
            source_text = {
                'exact_cache': 'из кэша',
                'pattern': 'по паттерну',
                'llm': 'сгенерирован ИИ',
                'fallback': 'упрощенный запрос'
            }.get(result.get('source', 'llm'), 'сгенерирован ИИ')
            
            message = f"{source_emoji} **Нашел так** ({source_text}):\n\n"
            message += f"```sql\n{formatted_sql}\n```\n\n"
            
            if result.get('confidence') and result['confidence'] < 0.7:
                message += "⚠️ *Низкая уверенность в результате*\n\n"
            
            # Добавляем кнопки
            keyboard = [
                [
                    InlineKeyboardButton("✅ Да, всё верно", callback_data="confirm_yes"),
                    InlineKeyboardButton("✏️ Нет, исправить", callback_data="correct_no")
                ],
                [
                    InlineKeyboardButton("🔄 Перефразируй вопрос", callback_data="rephrase")
                ]
            ]
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await update.message.reply_text(
                message,
                reply_markup=reply_markup,
                parse_mode=ParseMode.MARKDOWN
            )
            
        except Exception as e:
            logger.error(f"Error processing query: {e}")
            await update.message.reply_text(
                f"❌ Ошибка при обработке запроса: {str(e)}"
            )
    
    async def handle_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработка callback кнопок"""
        query = update.callback_query
        await query.answer()
        
        user_id = update.effective_user.id
        
        if user_id not in self.sessions:
            return
        
        session = self.sessions[user_id]
        
        # Удаляем предыдущее сообщение с кнопками
        try:
            await query.delete_message()
        except:
            pass
        
        if query.data == "confirm_yes":
            # Подтверждение запроса - выполняем
            await self._execute_and_show_results(query, session)
            
        elif query.data == "correct_no":
            # Запрос на исправление
            session.waiting_for_correction = True
            session.correction_step = 1
            
            await query.message.reply_text(
                f"✏️ **Редактируйте SQL запрос:**\n\n"
                f"```sql\n{session.current_sql}\n```\n\n"
                f"Пришлите исправленную версию. Для отмены отправьте /cancel",
                parse_mode=ParseMode.MARKDOWN
            )
            
        elif query.data == "rephrase":
            # Перефразирование вопроса
            await query.message.reply_text(
                "🔄 Перефразируйте ваш вопрос более детально.\n\n"
                "Пример:\n"
                "• Вместо 'Статистика за ноябрь' → 'Статистика за ноябрь 2025 года'\n"
                "• Вместо 'Видео креатора' → 'Все видео креатора с id abc123'\n\n"
                "Пришлите уточненный вопрос:"
            )
            
        elif query.data.startswith("format_"):
            # Изменение формата вывода
            format_type = query.data.replace("format_", "")
            session.preferred_format = format_type
            
            format_name = {"table": "таблицу", "json": "JSON"}[format_type]
            await query.message.reply_text(f"✅ Формат вывода изменен на {format_name}")
    
    async def _execute_and_show_results(self, query, session: UserSession):
        """Выполнение SQL и показ результатов"""
        await query.message.reply_text("⚡ Выполняю запрос...")
        
        try:
            # Выполняем SQL
            results = await self.db_manager.execute_query(session.current_sql)
            
            self.stats['successful_queries'] += 1
            
            # Сохраняем успешный пример для обучения
            await self.constructor.learn_from_success(
                session.current_query, 
                session.current_sql
            )
            
            # Показываем результаты
            if not results:
                await query.message.reply_text("📭 Запрос выполнен успешно, но данных не найдено")
                return
            
            # Форматируем результаты
            if session.preferred_format == "table":
                formatted = self._format_results_as_table(results)
            else:
                formatted = self._format_results_as_json(results)
            
            # Отправляем результаты (частично если слишком много)
            if len(formatted) > 4000:
                await query.message.reply_text(
                    f"📊 **Найдено записей:** {len(results)}\n\n"
                    f"Показаны первые 5 записей:\n\n{formatted[:2000]}...\n\n"
                    f"Для полного результата измените запрос или формат вывода"
                )
            else:
                await query.message.reply_text(
                    f"📊 **Найдено записей:** {len(results)}\n\n{formatted}",
                    parse_mode=ParseMode.MARKDOWN if session.preferred_format == "table" else None
                )
                
        except Exception as e:
            logger.error(f"Query execution error: {e}")
            await query.message.reply_text(
                f"❌ **Ошибка выполнения запроса:**\n\n"
                f"```\n{str(e)}\n```\n\n"
                f"Попробуйте исправить SQL запрос или перефразируйте вопрос",
                parse_mode=ParseMode.MARKDOWN
            )
    
    def _format_sql_for_display(self, sql: str) -> str:
        """Форматирование SQL для красивого отображения"""
        # Простое форматирование ключевых слов
        keywords = ['SELECT', 'FROM', 'WHERE', 'JOIN', 'LEFT JOIN', 'INNER JOIN', 
                   'GROUP BY', 'ORDER BY', 'HAVING', 'LIMIT', 'OFFSET', 'AND', 'OR']
        
        formatted = sql
        
        for keyword in keywords:
            formatted = formatted.replace(keyword, f"\n{keyword}")
            formatted = formatted.replace(keyword.lower(), f"\n{keyword}")
        
        # Убираем лишние пустые строки
        lines = [line.strip() for line in formatted.split('\n') if line.strip()]
        formatted = '\n'.join(lines)
        
        return formatted
    
    def _format_results_as_table(self, results: list) -> str:
        """Форматирование результатов как таблицы"""
        if not results:
            return "Нет данных"
        
        # Берем первые 10 записей для отображения
        display_results = results[:10]
        
        # Определяем заголовки
        headers = list(display_results[0].keys())
        
        # Формируем таблицу
        table_lines = []
        
        # Заголовки
        header_line = "| " + " | ".join(headers) + " |"
        separator = "|-" + "-|-".join(["-" * len(h) for h in headers]) + "-|"
        
        table_lines.append(header_line)
        table_lines.append(separator)
        
        # Данные
        for row in display_results:
            row_values = []
            for header in headers:
                value = row.get(header, "")
                # Обрезаем длинные значения
                if isinstance(value, str) and len(value) > 20:
                    value = value[:17] + "..."
                row_values.append(str(value))
            
            row_line = "| " + " | ".join(row_values) + " |"
            table_lines.append(row_line)
        
        formatted_table = "\n".join(table_lines)
        
        if len(results) > 10:
            formatted_table += f"\n\n... и еще {len(results) - 10} записей"
        
        return formatted_table
    
    def _format_results_as_json(self, results: list) -> str:
        """Форматирование результатов как JSON"""
        # Берем первые 5 записей для отображения
        display_results = results[:5]
        
        formatted = json.dumps(display_results, ensure_ascii=False, indent=2)
        
        if len(results) > 5:
            formatted += f"\n\n... и еще {len(results) - 5} записей"
        
        return formatted
    
    async def error_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик ошибок"""
        logger.error(f"Update {update} caused error {context.error}")
        
        if update and update.effective_message:
            await update.effective_message.reply_text(
                "❌ Произошла ошибка. Попробуйте еще раз или обратитесь к администратору."
            )