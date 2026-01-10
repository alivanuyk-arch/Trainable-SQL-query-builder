import aiohttp
import re
import json
import logging
from typing import Optional, Dict, Any, List
from dataclasses import dataclass
import asyncio
from src.llm.prompt_factory import PromptFactory

logger = logging.getLogger(__name__)

@dataclass
class LLMResult:
    sql: str
    confidence: float
    is_safe: bool
    source: str
    metadata: Dict[str, Any]
    raw_response: Optional[str] = None

class LLMClient:
    """Универсальный клиент для работы с LLM"""
    
    def __init__(self, config):
        self.config = config
        self.model = config.OLLAMA_MODEL
        self.base_url = config.OLLAMA_BASE_URL
        self.provider = config.LLM_PROVIDER

        # Статистика
        self.stats = {
            'total_requests': 0,
            'successful_requests': 0,
            'failed_requests': 0,
            'total_tokens': 0,
            'avg_response_time': 0
        }

        # Критическое исправление: создаем сессию ЗДЕСЬ
        import aiohttp
        self.session = aiohttp.ClientSession()
        logger.info(f"HTTP-сессия для {self.provider} создана.")

        # Инициализация prompt factory
        self.prompt_factory = PromptFactory()

        self.logger = logging.getLogger(__name__)
        self.logger.info(f"LLMClient initialized for {self.provider}: {self.model}")

    async def initialize(self):
        """Инициализация клиента"""
        self.session = aiohttp.ClientSession()
        logger.info(f"LLM Client initialized with {self.provider}: {self.model}")
    
    async def close(self):
        """Закрытие клиента"""
        if self.session:
            await self.session.close()
            self.session = None
    
    async def generate_sql(self, user_query: str, schema_prompt: str = None, 
                          context: Dict = None) -> Optional[LLMResult]:
        """Генерация SQL из пользовательского запроса"""
        
        self.stats['total_requests'] += 1
        start_time = asyncio.get_event_loop().time()
        
        try:
            if self.provider == 'ollama':
                result = await self._call_ollama(user_query, schema_prompt, context)
            elif self.provider == 'openai':
                result = await self._call_openai(user_query, schema_prompt, context)
            else:
                logger.error(f"Unknown LLM provider: {self.provider}")
                return None
            
            end_time = asyncio.get_event_loop().time()
            response_time = end_time - start_time
            
            # Обновляем статистику
            self.stats['successful_requests'] += 1
            self.stats['avg_response_time'] = (
                (self.stats['avg_response_time'] * (self.stats['successful_requests'] - 1) + response_time) 
                / self.stats['successful_requests']
            )
            
            return result
            
        except Exception as e:
            self.stats['failed_requests'] += 1
            logger.error(f"LLM generation error: {e}", exc_info=True)
            return None
    
    async def _call_ollama(self, user_query: str, schema_prompt: str, context: Dict) -> Optional[LLMResult]:
        """Вызов Ollama API"""
        
        # Строим промпт
        prompt = self._build_prompt(user_query, schema_prompt, context)
        
        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": 0.1,
                "num_predict": 1000,
                "top_p": 0.9,
                "stop": ["[/INST]", "```", "Question:"]
            },
            "system": "You are a helpful SQL assistant. Return ONLY SQL code, no explanations."
        }
        
        try:
            async with self.session.post(
                f"{self.base_url}/api/generate",
                json=payload,
                timeout=45
            ) as response:
                
                if response.status == 200:
                    data = await response.json()
                    raw_response = data.get('response', '')
                    
                    # Извлекаем SQL
                    sql = self._extract_sql(raw_response)
                    
                    if sql:
                        # Валидация безопасности
                        is_safe = self._validate_sql_safety(sql)
                        
                        # Расчет уверенности
                        confidence = self._calculate_confidence(sql, raw_response)
                        
                        return LLMResult(
                            sql=sql,
                            confidence=confidence,
                            is_safe=is_safe,
                            source='ollama',
                            metadata={
                                'model': self.model,
                                'response_time': data.get('total_duration', 0) / 1_000_000_000,
                                'prompt_tokens': data.get('prompt_eval_count', 0),
                                'completion_tokens': data.get('eval_count', 0)
                            },
                            raw_response=raw_response
                        )
                    else:
                        logger.error("Failed to extract SQL from response")
                        return None
                        
                else:
                    error_text = await response.text()
                    logger.error(f"Ollama API error: {response.status} - {error_text}")
                    return None
                    
        except asyncio.TimeoutError:
            logger.error("Ollama request timeout")
            return None
        except Exception as e:
            logger.error(f"Ollama call exception: {e}")
            return None
    
    async def _call_openai(self, user_query: str, schema_prompt: str, context: Dict) -> Optional[LLMResult]:
        """Вызов OpenAI API"""
        try:
            import openai
        except ImportError:
            logger.error("OpenAI library not installed")
            return None
        
        # Строим сообщения
        messages = self._build_openai_messages(user_query, schema_prompt, context)
        
        try:
            client = openai.AsyncOpenAI(api_key=self.config.OPENAI_API_KEY)
            
            response = await client.chat.completions.create(
                model=self.config.OPENAI_MODEL,
                messages=messages,
                temperature=0.1,
                max_tokens=1000,
                stop=["```", "Question:"]
            )
            
            raw_response = response.choices[0].message.content
            
            # Извлекаем SQL
            sql = self._extract_sql(raw_response)
            
            if sql:
                is_safe = self._validate_sql_safety(sql)
                confidence = self._calculate_confidence(sql, raw_response)
                
                return LLMResult(
                    sql=sql,
                    confidence=confidence,
                    is_safe=is_safe,
                    source='openai',
                    metadata={
                        'model': response.model,
                        'response_time': response.usage.total_tokens / 1000,  # Примерное время
                        'prompt_tokens': response.usage.prompt_tokens,
                        'completion_tokens': response.usage.completion_tokens
                    },
                    raw_response=raw_response
                )
            else:
                logger.error("Failed to extract SQL from OpenAI response")
                return None
                
        except Exception as e:
            logger.error(f"OpenAI API error: {e}")
            return None
    
    def _build_prompt(self, user_query: str, schema_prompt: str, context: Dict) -> str:
        """Построение промпта для LLM"""
        
        prompt_parts = []
        
        # 1. Системный промпт
        prompt_parts.append("""<s>[INST] <<SYS>>
You are a professional SQL translator. Your task is to convert Russian natural language questions into correct PostgreSQL SQL queries.

IMPORTANT RULES:
1. Return ONLY SQL code, no explanations
2. Use proper JOINs when needed
3. Handle dates correctly (use DATE() for date comparisons)
4. Use parameterized queries style with {PLACEHOLDERS}
5. Always include a semicolon at the end

EXAMPLE PLACEHOLDERS:
- {ID} for identifiers
- {DATE} for dates
- {NUMBER} for numbers
- {YEAR} for years
- {MONTH} for months

FORMAT: Just SQL, nothing else.
<</SYS>>""")
        
        # 2. Схема БД если есть
        if schema_prompt:
            prompt_parts.append(f"\n## DATABASE SCHEMA:\n\n{schema_prompt}")
        
        # 3. Контекст если есть
        if context and context.get('previous_corrections'):
            prompt_parts.append("\n## PREVIOUS CORRECTIONS (learn from these):")
            for correction in context['previous_corrections'][:3]:
                prompt_parts.append(f"\nUser: {correction.get('query', '')}")
                prompt_parts.append(f"Wrong SQL: {correction.get('wrong_sql', '')}")
                prompt_parts.append(f"Correct SQL: {correction.get('correct_sql', '')}")
        
        # 4. Примеры
        prompt_parts.append("""
## EXAMPLES:

Question: Сколько всего видео в системе?
SQL: SELECT COUNT(*) FROM videos;

Question: Видео креатора с id abc123
SQL: SELECT * FROM videos WHERE creator_id = '{ID}';

Question: Статистика за ноябрь 2025 года
SQL: SELECT * FROM videos WHERE EXTRACT(YEAR FROM video_created_at) = {YEAR} AND EXTRACT(MONTH FROM video_created_at) = {MONTH};

Question: Сумма просмотров всех видео
SQL: SELECT SUM(views_count) FROM videos;

Question: Прирост просмотров 28 ноября 2025
SQL: SELECT SUM(delta_views_count) FROM video_snapshots WHERE DATE(created_at) = '{DATE}';
""")
        
        # 5. Сам запрос
        prompt_parts.append(f"""
## YOUR TASK:
Convert this Russian question to PostgreSQL SQL:

Question: {user_query}
SQL: [/INST]""")
        
        return "\n".join(prompt_parts)
    
    def _build_openai_messages(self, user_query: str, schema_prompt: str, context: Dict) -> List[Dict]:
        """Построение сообщений для OpenAI"""
        
        messages = [
            {
                "role": "system",
                "content": """You are a professional SQL translator. Convert Russian questions to PostgreSQL SQL.
                
Rules:
1. Return ONLY SQL code
2. Use {PLACEHOLDERS} for parameters
3. Always end with semicolon
4. Use proper JOINs when needed"""
            }
        ]
        
        if schema_prompt:
            messages.append({
                "role": "user",
                "content": f"Database schema:\n\n{schema_prompt}\n\nNow convert this question: {user_query}"
            })
        else:
            messages.append({
                "role": "user",
                "content": user_query
            })
        
        return messages
    
    def _extract_sql(self, response: str) -> Optional[str]:
        """Извлечение SQL из ответа LLM"""
        if not response:
            return None
        
        # Очищаем ответ
        response = response.strip()
        
        # Убираем markdown
        response = re.sub(r'```(?:sql)?', '', response)
        response = re.sub(r'`', '', response)
        
        # Ищем SQL
        sql_match = re.search(r'(SELECT .*?)(?:;|$)', response, re.IGNORECASE | re.DOTALL)
        
        if sql_match:
            sql = sql_match.group(1).strip()
            
            # Добавляем точку с запятой если нет
            if not sql.endswith(';'):
                sql += ';'
            
            # Нормализуем пробелы
            sql = re.sub(r'\s+', ' ', sql)
            
            # Заменяем русские даты
            sql = self._replace_russian_dates(sql)
            
            return sql
        
        return None
    
    def _replace_russian_dates(self, sql: str) -> str:
        """Замена русских дат в SQL"""
        month_map = {
            'января': 1, 'февраля': 2, 'марта': 3, 'апреля': 4,
            'мая': 5, 'июня': 6, 'июля': 7, 'августа': 8,
            'сентября': 9, 'октября': 10, 'ноября': 11, 'декабря': 12,
        }
        
        # Паттерн: "28 ноября 2025"
        def replace_date(match):
            day = match.group(1)
            month_ru = match.group(2)
            year = match.group(3)
            month_num = month_map.get(month_ru.lower(), 1)
            return f"'{year}-{month_num:02d}-{int(day):02d}'"
        
        pattern = r"(\d{1,2})\s+(\w+)\s+(\d{4})"
        sql = re.sub(pattern, replace_date, sql, flags=re.IGNORECASE)
        
        return sql
    
    def _validate_sql_safety(self, sql: str) -> bool:
        """Валидация безопасности SQL"""
        if not sql:
            return False
        
        sql_upper = sql.upper()
        
        # Запрещенные команды
        dangerous = [
            "DROP ", "DELETE ", "UPDATE ", "INSERT ", 
            "ALTER ", "TRUNCATE ", "CREATE ", "GRANT ",
            "REVOKE ", "EXECUTE ", "DECLARE ", "CURSOR ",
            "BEGIN ", "COMMIT ", "ROLLBACK "
        ]
        
        for cmd in dangerous:
            if cmd in sql_upper:
                logger.warning(f"Dangerous SQL command detected: {cmd}")
                return False
        
        # Должен начинаться с SELECT
        if not sql_upper.startswith("SELECT"):
            logger.warning("SQL doesn't start with SELECT")
            return False
        
        return True
    
    def _calculate_confidence(self, sql: str, raw_response: str) -> float:
        """Расчет уверенности в ответе LLM"""
        confidence = 0.5  # Базовая уверенность
        
        # Проверяем наличие ключевых слов
        required_keywords = ['SELECT', 'FROM']
        has_required = all(keyword in sql.upper() for keyword in required_keywords)
        
        if has_required:
            confidence += 0.2
        
        # Проверяем длину SQL (слишком короткий может быть неправильным)
        if 20 < len(sql) < 500:
            confidence += 0.1
        
        # Проверяем наличие правильных конструкций
        if 'WHERE' in sql.upper():
            confidence += 0.1
        
        # Проверяем наличие плейсхолдеров (хороший признак)
        if '{' in sql and '}' in sql:
            confidence += 0.1
        
        # Ограничиваем максимальную уверенность
        return min(0.95, confidence)
    
    def get_stats(self) -> Dict:
        """Получение статистики использования LLM"""
        return self.stats.copy()