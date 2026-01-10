import re
import json
import hashlib
import logging
from typing import Dict, List, Set, Optional, Any, Tuple
from pathlib import Path
from datetime import datetime
from dataclasses import dataclass, asdict
from collections import defaultdict

logger = logging.getLogger(__name__)

@dataclass
class ConstructorStats:
    """Статистика конструктора"""
    total_patterns: int
    exact_hits: int
    pattern_hits: int
    llm_calls: int
    corrections: int
    learning_rate: float

class QueryConstructor:
    """Самообучающийся конструктор SQL запросов"""
    
    def __init__(self, llm_client=None, db_manager=None, config=None):
        self.llm = llm_client
        self.db = db_manager
        self.config = config
        
        # Структуры данных
        self.exact_cache: Dict[str, str] = {}
        self.patterns: Dict[str, Dict] = {}
        self.word_index: Dict[str, Set[str]] = defaultdict(set)
        self.corrections_log: List[Dict] = []
        
        # Конфигурация
        self.stop_words = {'и', 'в', 'с', 'по', 'за', 'у', 'о', 'от', 'есть', 'всего', 'x', 'id', 'для', 'на'}
        
        # Статистика
        self.stats = {
            'total_queries': 0,
            'exact_hits': 0,
            'pattern_hits': 0,
            'llm_calls': 0,
            'corrections': 0,
            'auto_learned': 0
        }
        
        # Схема БД
        self.schema = {}
        self.schema_aliases = {}
        
        # Пути к файлам
        self.cache_file = config.CACHE_FILE
        self.patterns_file = config.PATTERNS_FILE
        self.corrections_file = config.CORRECTIONS_FILE
        
        # Загрузка сохранённых данных
        self._load_data()
        
        logger.info(f"Конструктор инициализирован. Паттернов: {len(self.patterns)}")
    
    async def initialize_with_schema(self, schema: Dict):
        """Инициализация со схемой БД"""
        self.schema = schema.get('schema', {})
        self.schema_aliases = schema.get('aliases', {})
        
        # Предзагрузка базовых паттернов на основе схемы
        await self._preload_basic_patterns()
        
        logger.info(f"Конструктор инициализирован со схемой: {len(self.schema)} таблиц")
    
    async def _preload_basic_patterns(self):
        """Предзагрузка базовых паттернов на основе схемы"""
        basic_patterns = [
            # Подсчет всех записей
            ("Сколько всего записей в таблице?", 
             "SELECT COUNT(*) FROM {table}"),
            
            # Подсчет по условию
            ("Сколько записей где поле равно значению?", 
             "SELECT COUNT(*) FROM {table} WHERE {field} = {value}"),
            
            # Сумма значений
            ("Сумма значений в поле", 
             "SELECT SUM({field}) FROM {table}"),
            
            # Среднее значение
            ("Среднее значение поля", 
             "SELECT AVG({field}) FROM {table}"),
            
            # Группировка по дате
            ("Статистика по дням", 
             "SELECT DATE({date_field}), COUNT(*) FROM {table} GROUP BY DATE({date_field}) ORDER BY DATE({date_field})"),
        ]
        
        for query_template, sql_template in basic_patterns:
            words = self._extract_words(query_template)
            pattern_key = self._make_pattern_key(words)
            
            if pattern_key not in self.patterns:
                self.patterns[pattern_key] = {
                    'words': list(words),
                    'template': sql_template,
                    'count': 0,
                    'examples': [],
                    'source': 'schema_preload',
                    'created_at': datetime.now().isoformat()
                }
    
    async def process_query(self, user_query: str, user_id: str = None) -> Dict:
        """Основной метод обработки запроса"""
        self.stats['total_queries'] += 1
        
        logger.info(f"Processing query: '{user_query}'")
        
        # 1. Проверяем точный кэш
        if user_query in self.exact_cache:
            logger.info(f"Exact cache hit for: '{user_query}'")
            self.stats['exact_hits'] += 1
            return {
                'sql': self.exact_cache[user_query],
                'source': 'exact_cache',
                'needs_validation': False
            }
        
        # 2. Ищем похожий паттерн
        words = self._extract_words(user_query)
        pattern = self._find_pattern(words)
        
        if pattern:
            logger.info(f"Pattern hit for: '{user_query}'")
            self.stats['pattern_hits'] += 1
            sql = self._fill_template(pattern['template'], user_query)
            pattern['count'] += 1
            
            # Если шаблон заполнен - сохраняем в кэш
            if '{' not in sql:
                self.exact_cache[user_query] = sql
                self._save_cache()
            
            return {
                'sql': sql,
                'source': 'pattern',
                'needs_validation': True,
                'pattern_id': list(self.patterns.keys())[list(self.patterns.values()).index(pattern)]
            }
        
        # 3. Используем LLM если доступна
        if self.llm and self.config.LLM_ENABLED:
            logger.info(f"Using LLM for: '{user_query}'")
            self.stats['llm_calls'] += 1
            
            sql_result = await self.llm.generate_sql(user_query, self.schema)
            
            if sql_result and sql_result.get('sql'):
                sql = sql_result['sql']
                
                return {
                    'sql': sql,
                    'source': 'llm',
                    'needs_validation': True,
                    'confidence': sql_result.get('confidence', 0.5),
                    'llm_metadata': sql_result.get('metadata', {})
                }
        
        # 4. Fallback - простой запрос
        logger.warning(f"Fallback for query: '{user_query}'")
        fallback_sql = self._generate_fallback_sql(user_query)
        
        return {
            'sql': fallback_sql,
            'source': 'fallback',
            'needs_validation': True,
            'warning': 'Could not generate optimal SQL'
        }
    
    async def process_and_execute_query(self, query_text: str, user_id: int = None):
        """
        Полный цикл: вопрос → SQL → выполнение → результаты
        """
        # 1. Генерируем SQL (используем существующий process_query)
        result = await self.process_query(query_text, user_id)
        
        # 2. Если SQL сгенерирован успешно - выполняем
        if result.get('sql'):
            try:
                sql = result['sql']
                execution_results = await self.db_manager.execute_query(sql)
                
                # Добавляем результаты выполнения в ответ
                result['execution'] = {
                    'success': True,
                    'results': execution_results,
                    'row_count': len(execution_results) if execution_results else 0
                }
                
            except Exception as e:
                # Ошибка выполнения SQL
                result['execution'] = {
                    'success': False,
                    'error': str(e),
                    'results': [],
                    'row_count': 0
                }
        
        return result
    
    async def learn_from_correction(self, original_query: str, 
                                  llm_sql: str, 
                                  corrected_sql: str,
                                  user_feedback: str = None):
        """Обучение на исправлении пользователя"""
        self.stats['corrections'] += 1
        
        # Логируем исправление
        correction_record = {
            'original_query': original_query,
            'llm_sql': llm_sql,
            'corrected_sql': corrected_sql,
            'user_feedback': user_feedback,
            'timestamp': datetime.now().isoformat(),
            'diff': self._compute_sql_diff(llm_sql, corrected_sql)
        }
        
        self.corrections_log.append(correction_record)
        self._save_corrections()
        
        # Извлекаем паттерн из оригинального запроса
        words = self._extract_words(original_query)
        
        # Создаем обобщенный SQL шаблон
        generalized_sql = self._generalize_sql(corrected_sql)
        
        # Сохраняем новый паттерн
        self._learn_from_example(original_query, generalized_sql, words, 'correction')
        
        # Сохраняем точный кэш
        self.exact_cache[original_query] = corrected_sql
        self._save_cache()
        
        logger.info(f"Learned from correction. Patterns: {len(self.patterns)}")
    
    async def learn_from_success(self, user_query: str, sql: str):
        """Обучение на успешном запросе"""
        words = self._extract_words(user_query)
        
        # Сохраняем в точный кэш
        self.exact_cache[user_query] = sql
        self._save_cache()
        
        # Создаем паттерн если его нет
        pattern = self._find_pattern(words)
        if not pattern:
            generalized_sql = self._generalize_sql(sql)
            self._learn_from_example(user_query, generalized_sql, words, 'success')
        
        self.stats['auto_learned'] += 1
        
        logger.info(f"Learned from success. Cache size: {len(self.exact_cache)}")
    
    def _extract_words(self, query: str) -> Set[str]:
        """Извлекаем нормализованные слова"""
        query_lower = query.lower()
        
        # Заменяем знаки препинания на пробелы
        for char in '?.,!;:()[]{}"\'«»':
            query_lower = query_lower.replace(char, ' ')
        
        # Сохраняем специальные идентификаторы
        query_lower = re.sub(r'[a-f0-9]{32}', ' IDCREATOR ', query_lower)
        query_lower = re.sub(r'[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}', ' IDVIDEO ', query_lower)
        
        # Удаляем даты
        query_lower = re.sub(r'\d{4}-\d{2}-\d{2}', ' ', query_lower)
        query_lower = re.sub(r'\d{1,2}\s+\w+\s+\d{4}', ' ', query_lower)
        
        # Удаляем простые числа
        query_lower = re.sub(r'\b\d{1,4}\b', ' ', query_lower)
        
        # Разбиваем на слова и фильтруем
        words = query_lower.split()
        filtered = set()
        
        for word in words:
            if word in self.stop_words:
                continue
            if len(word) < 2:
                continue
            filtered.add(word)
        
        return filtered
    
    def _find_pattern(self, words: Set[str]) -> Optional[Dict]:
        """Ищет похожий паттерн"""
        if not words:
            return None
        
        best_pattern = None
        best_score = 0
        
        for pattern_hash, pattern in self.patterns.items():
            pattern_words = set(pattern['words'])
            
            # Вычисляем пересечение
            common = words.intersection(pattern_words)
            
            if not common:
                continue
            
            # Оценка схожести
            coverage = len(common) / len(pattern_words)
            recall = len(common) / len(words) if words else 0
            
            # Комбинированная оценка
            score = (coverage * 0.6) + (recall * 0.4)
            
            if score > best_score and score > 0.5:
                best_score = score
                best_pattern = pattern
        
        return best_pattern
    
    def _fill_template(self, template: str, query: str) -> str:
        """Заполняет шаблон параметрами"""
        sql = template
        
        # Извлекаем параметры из запроса
        params = self._extract_parameters(query)
        
        # Заменяем плейсхолдеры
        for placeholder, value in params.items():
            if placeholder in sql:
                sql = sql.replace(placeholder, str(value))
        
        return sql
    
    def _extract_parameters(self, query: str) -> Dict[str, Any]:
        """Извлечение параметров из запроса"""
        params = {}
        query_lower = query.lower()
        
        # Месяцы
        month_map = {
            'января': 1, 'февраля': 2, 'марта': 3, 'апреля': 4,
            'мая': 5, 'июня': 6, 'июля': 7, 'августа': 8,
            'сентября': 9, 'октября': 10, 'ноября': 11, 'декабря': 12,
        }
        
        # Ищем даты
        date_patterns = [
            (r'(\d{1,2})\s+(\w+)\s+(\d{4})', lambda m: f"'{m.group(3)}-{month_map.get(m.group(2).lower(), '01'):02d}-{int(m.group(1)):02d}'"),
            (r'(\d{4}-\d{2}-\d{2})', lambda m: f"'{m.group(1)}'"),
        ]
        
        for pattern, converter in date_patterns:
            match = re.search(pattern, query_lower)
            if match:
                params['{DATE}'] = converter(match)
                break
        
        # Ищем числа
        numbers = re.findall(r'\b(\d+)\b', query)
        if numbers:
            params['{NUMBER}'] = numbers[0]
            for i, num in enumerate(numbers, 1):
                params[f'{{NUMBER{i}}}'] = num
        
        # Ищем ID
        id_patterns = [
            (r'[a-f0-9]{32}', '{ID}'),
            (r'креатор[ауе]?\s+([a-f0-9]{32})', '{CREATOR_ID}'),
            (r'видео\s+([a-f0-9\-]{36})', '{VIDEO_ID}'),
        ]
        
        for pattern, placeholder in id_patterns:
            match = re.search(pattern, query_lower)
            if match:
                params[placeholder] = f"'{match.group(0)}'"
                break
        
        return params
    
    def _generate_fallback_sql(self, query: str) -> str:
        """Генерация fallback SQL запроса"""
        # Пытаемся понять, что хочет пользователь
        query_lower = query.lower()
        
        if any(word in query_lower for word in ['сколько', 'количество', 'число']):
            # Подсчет
            if 'видео' in query_lower:
                return "SELECT COUNT(*) FROM videos"
            elif 'снимк' in query_lower or 'снапшот' in query_lower:
                return "SELECT COUNT(*) FROM video_snapshots"
            else:
                return "SELECT COUNT(*) FROM videos"
        
        elif any(word in query_lower for word in ['сумма', 'суммарн', 'итого']):
            # Сумма
            if 'просмотр' in query_lower:
                return "SELECT SUM(views_count) FROM videos"
            elif 'лайк' in query_lower:
                return "SELECT SUM(likes_count) FROM videos"
            elif 'комментар' in query_lower:
                return "SELECT SUM(comments_count) FROM videos"
        
        # Дефолтный запрос
        return "SELECT * FROM videos LIMIT 10"
    
    def _generalize_sql(self, sql: str) -> str:
        """Создаёт шаблон из конкретного SQL"""
        template = sql
        
        # Заменяем конкретные значения на плейсхолдеры
        template = re.sub(r"'[^']*'", "'{VALUE}'", template)  # Строки
        template = re.sub(r'\b\d+\b', '{NUMBER}', template)    # Числа
        
        # Сохраняем специальные конструкции
        template = re.sub(r"'\d{4}-\d{2}-\d{2}'", "'{DATE}'", template)
        template = re.sub(r"'\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}'", "'{TIMESTAMP}'", template)
        
        return template
    
    def _compute_sql_diff(self, sql1: str, sql2: str) -> Dict:
        """Вычисление различий между SQL запросами"""
        # Простая реализация - можно улучшить
        return {
            'same_structure': sql1.strip().lower() == sql2.strip().lower(),
            'length_diff': len(sql2) - len(sql1),
            'tables_changed': len(set(re.findall(r'FROM\s+(\w+)', sql2, re.IGNORECASE)) - 
                                 set(re.findall(r'FROM\s+(\w+)', sql1, re.IGNORECASE)))
        }
    
    def _learn_from_example(self, query: str, sql: str, words: Set[str], source: str = 'manual'):
        """Сохраняет новый паттерн"""
        if not words:
            return
        
        pattern_key = self._make_pattern_key(words)
        
        if pattern_key in self.patterns:
            # Увеличиваем счетчик использования
            self.patterns[pattern_key]['count'] += 1
            self.patterns[pattern_key]['examples'].append(query)
            self.patterns[pattern_key]['last_used'] = datetime.now().isoformat()
        else:
            # Создаем новый паттерн
            self.patterns[pattern_key] = {
                'words': list(words),
                'template': sql,
                'count': 1,
                'examples': [query],
                'source': source,
                'created_at': datetime.now().isoformat(),
                'last_used': datetime.now().isoformat()
            }
            
            # Индексируем слова
            for word in words:
                self.word_index[word].add(pattern_key)
    
    def _make_pattern_key(self, words: Set[str]) -> str:
        """Создаёт ключ паттерна"""
        sorted_words = sorted(words)
        key_str = " ".join(sorted_words)
        return hashlib.md5(key_str.encode()).hexdigest()[:16]
    
    def _load_data(self):
        """Загрузка сохранённых данных"""
        try:
            if self.cache_file.exists():
                with open(self.cache_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.exact_cache = data.get('exact_cache', {})
            
            if self.patterns_file.exists():
                with open(self.patterns_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    patterns_data = data.get('patterns', {})
                    
                    self.patterns.clear()
                    self.word_index.clear()
                    
                    for pattern_key, pattern in patterns_data.items():
                        self.patterns[pattern_key] = pattern
                        for word in pattern.get('words', []):
                            self.word_index[word].add(pattern_key)
            
            if self.corrections_file.exists():
                with open(self.corrections_file, 'r', encoding='utf-8') as f:
                    self.corrections_log = json.load(f)
                    
        except Exception as e:
            logger.error(f"Ошибка загрузки данных: {e}")
    
    def _save_cache(self):
        """Сохраняет кэш"""
        try:
            data = {
                'exact_cache': self.exact_cache,
                'updated_at': datetime.now().isoformat(),
                'total_queries': self.stats['total_queries'],
                'cache_size': len(self.exact_cache)
            }
            
            with open(self.cache_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"Ошибка сохранения кэша: {e}")
    
    def _save_patterns(self):
        """Сохраняет паттерны"""
        try:
            data = {
                'patterns': self.patterns,
                'updated_at': datetime.now().isoformat(),
                'total_patterns': len(self.patterns),
                'stats': self.stats
            }
            
            with open(self.patterns_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"Ошибка сохранения паттернов: {e}")
    
    def _save_corrections(self):
        """Сохраняет исправления"""
        try:
            data = {
                'corrections': self.corrections_log[-100:],  # Последние 100 исправлений
                'total_corrections': len(self.corrections_log),
                'updated_at': datetime.now().isoformat()
            }
            
            with open(self.corrections_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"Ошибка сохранения исправлений: {e}")
    
    def save_all_data(self):
        """Сохраняет все данные"""
        self._save_cache()
        self._save_patterns()
        self._save_corrections()
        logger.info(f"Data saved. Patterns: {len(self.patterns)}, Cache: {len(self.exact_cache)}")
    
    def get_stats(self) -> ConstructorStats:
        """Возвращает статистику"""
        learning_rate = 0
        if self.stats['total_queries'] > 0:
            learning_rate = (self.stats['exact_hits'] + self.stats['pattern_hits']) / self.stats['total_queries']
        
        return ConstructorStats(
            total_patterns=len(self.patterns),
            exact_hits=self.stats['exact_hits'],
            pattern_hits=self.stats['pattern_hits'],
            llm_calls=self.stats['llm_calls'],
            corrections=self.stats['corrections'],
            learning_rate=learning_rate
        )
    
    def clear_cache(self):
        """Очищает кэш"""
        self.exact_cache = {}
        self._save_cache()
        logger.info("Кэш очищен")
    
    def optimize_patterns(self):
        """Оптимизация паттернов - удаление неиспользуемых"""
        patterns_to_remove = []
        
        for pattern_key, pattern in self.patterns.items():
            # Удаляем паттерны, которые не использовались давно и имеют мало примеров
            last_used = datetime.fromisoformat(pattern.get('last_used', '2000-01-01'))
            days_since_use = (datetime.now() - last_used).days
            
            if days_since_use > 30 and pattern['count'] < 3:
                patterns_to_remove.append(pattern_key)
        
        for pattern_key in patterns_to_remove:
            del self.patterns[pattern_key]
        
        if patterns_to_remove:
            logger.info(f"Removed {len(patterns_to_remove)} unused patterns")
            self._save_patterns()

    async def process_correction(self, question: str, original_sql: str, 
                           corrected_sql: str, user_id: int = None) -> str:
        """
        Обработка исправления SQL от пользователя
        Возвращает результат выполнения исправленного SQL
        """
        try:
            self.logger.info(f"Обработка исправления от user_id={user_id}")
            
            # 1. Выполняем исправленный SQL
            result = ""
            if hasattr(self, 'db') and self.db:
                try:
                    result_data = await self.db.execute_query(corrected_sql)
                    if isinstance(result_data, list):
                        result = f"Найдено {len(result_data)} записей"
                    else:
                        result = str(result_data)
                except Exception as db_error:
                    result = f"Ошибка выполнения SQL: {str(db_error)}"
            else:
                result = "✅ SQL принят (тестовый режим)"
            
            # 2. Если SQL был изменён - учимся
            if original_sql.strip() != corrected_sql.strip():
                self.stats['corrections'] += 1
                self.logger.info(f"SQL изменён, исправлений: {self.stats['corrections']}")
                
                # Сохраняем в лог исправлений
                self.corrections_log.append({
                    'timestamp': datetime.now().isoformat(),
                    'user_id': user_id,
                    'question': question,
                    'original_sql': original_sql,
                    'corrected_sql': corrected_sql,
                    'result': result
                })
                
                # Извлекаем правило из исправления
                if hasattr(self, '_learn_from_correction'):
                    success = await self._learn_from_correction(question, original_sql, corrected_sql)
                    if success:
                        self.logger.info("Правило успешно извлечено")
            
            # 3. Сохраняем исправленную версию в кэш
            self.exact_cache[question] = corrected_sql
            
            # 4. Обновляем статистику
            self.stats['total_queries'] += 1
            
            # 5. Сохраняем все данные
            self._save_cache()
            self._save_corrections_log()
            if hasattr(self, '_save_patterns'):
                self._save_patterns()
            
            self.logger.info(f"Исправление обработано: {original_sql[:30]}... → {corrected_sql[:30]}...")
            return result
            
        except Exception as e:
            self.logger.error(f"Ошибка обработки исправления: {e}")
            return f"Ошибка обработки: {str(e)}"