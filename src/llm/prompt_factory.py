import re
import logging
from typing import Dict, List, Optional
from datetime import datetime

logger = logging.getLogger(__name__)

class PromptFactory:
    """Фабрика промптов для разных типов запросов"""
    
    def __init__(self, schema_info: Dict = None):
        self.schema_info = schema_info or {}
        self.query_templates = self._load_query_templates()
        
    def _load_query_templates(self) -> Dict[str, Dict]:
        """Загрузка шаблонов запросов"""
        return {
            'count': {
                'description': 'Подсчет количества записей',
                'examples': [
                    ("Сколько всего видео?", "SELECT COUNT(*) FROM videos;"),
                    ("Количество видео у креатора", "SELECT COUNT(*) FROM videos WHERE creator_id = '{ID}';"),
                    ("Сколько снимков за дату?", "SELECT COUNT(*) FROM video_snapshots WHERE DATE(created_at) = '{DATE}';")
                ],
                'placeholders': ['{ID}', '{DATE}', '{YEAR}', '{MONTH}']
            },
            'sum': {
                'description': 'Суммирование значений',
                'examples': [
                    ("Сумма просмотров", "SELECT SUM(views_count) FROM videos;"),
                    ("Суммарный прирост просмотров", "SELECT SUM(delta_views_count) FROM video_snapshots WHERE DATE(created_at) = '{DATE}';"),
                    ("Общее количество лайков", "SELECT SUM(likes_count) FROM videos;")
                ],
                'placeholders': ['{DATE}', '{ID}']
            },
            'average': {
                'description': 'Среднее значение',
                'examples': [
                    ("Среднее количество просмотров", "SELECT AVG(views_count) FROM videos;"),
                    ("Средний прирост за день", "SELECT AVG(delta_views_count) FROM video_snapshots WHERE DATE(created_at) = '{DATE}';")
                ],
                'placeholders': ['{DATE}']
            },
            'filter': {
                'description': 'Фильтрация записей',
                'examples': [
                    ("Видео с просмотрами больше N", "SELECT * FROM videos WHERE views_count > {NUMBER};"),
                    ("Снимки за период", "SELECT * FROM video_snapshots WHERE created_at BETWEEN '{DATE1}' AND '{DATE2}';"),
                    ("Видео креатора", "SELECT * FROM videos WHERE creator_id = '{ID}';")
                ],
                'placeholders': ['{NUMBER}', '{DATE1}', '{DATE2}', '{ID}']
            },
            'group': {
                'description': 'Группировка данных',
                'examples': [
                    ("Статистика по дням", "SELECT DATE(created_at), COUNT(*) FROM video_snapshots GROUP BY DATE(created_at) ORDER BY DATE(created_at);"),
                    ("Просмотры по креаторам", "SELECT creator_id, SUM(views_count) FROM videos GROUP BY creator_id;")
                ],
                'placeholders': []
            },
            'join': {
                'description': 'Объединение таблиц',
                'examples': [
                    ("Прирост просмотров по креаторам", "SELECT v.creator_id, SUM(vs.delta_views_count) FROM video_snapshots vs JOIN videos v ON vs.video_id = v.id GROUP BY v.creator_id;"),
                    ("Статистика видео с данными креаторов", "SELECT v.*, c.name FROM videos v JOIN creators c ON v.creator_id = c.id;")
                ],
                'placeholders': []
            }
        }
    
    def detect_query_type(self, user_query: str) -> str:
        """Определение типа запроса"""
        query_lower = user_query.lower()
        
        if any(word in query_lower for word in ['сколько', 'количество', 'число', 'count']):
            return 'count'
        elif any(word in query_lower for word in ['сумма', 'суммарн', 'итого', 'общ', 'sum']):
            return 'sum'
        elif any(word in query_lower for word in ['средн', 'avg', 'average']):
            return 'average'
        elif any(word in query_lower for word in ['групп', 'group', 'по дням', 'по месяцам']):
            return 'group'
        elif any(word in query_lower for word in ['прирост', 'изменен', 'delta', 'разниц']):
            return 'join'  # Часто требует JOIN
        elif any(word in query_lower for word in ['где', 'фильтр', 'условие', 'where']):
            return 'filter'
        else:
            return 'filter'  # По умолчанию
    
    def create_schema_prompt(self, detailed: bool = False) -> str:
        """Создание промпта со схемой БД"""
        if not self.schema_info:
            return ""
        
        prompt_parts = ["## ДОСТУПНЫЕ ТАБЛИЦЫ И ПОЛЯ:"]
        
        for table_name, table_info in self.schema_info.get('tables', {}).items():
            russian_name = self.schema_info.get('aliases', {}).get(table_name, table_name)
            
            prompt_parts.append(f"\n### {table_name} ({russian_name}):")
            
            for column_name, column_info in table_info.get('columns', {}).items():
                column_key = f"{table_name}.{column_name}"
                russian_alias = self.schema_info.get('aliases', {}).get(column_key, column_name)
                
                prompt_parts.append(f"- {column_name} ({column_info}) - {russian_alias}")
        
        # Добавляем связи если есть
        if detailed and self.schema_info.get('relationships'):
            prompt_parts.append("\n## СВЯЗИ МЕЖДУ ТАБЛИЦАМИ:")
            for rel in self.schema_info.get('relationships', []):
                prompt_parts.append(f"- {rel['from_table']}.{rel['from_column']} → {rel['to_table']}.{rel['to_column']}")
        
        return "\n".join(prompt_parts)
    
    def create_enhanced_prompt(self, user_query: str, query_type: str = None, 
                              include_examples: bool = True) -> str:
        """Создание улучшенного промпта"""
        
        if query_type is None:
            query_type = self.detect_query_type(user_query)
        
        template = self.query_templates.get(query_type, self.query_templates['filter'])
        
        prompt_parts = []
        
        # 1. Инструкция
        prompt_parts.append("""Ты — SQL-ассистент. Преобразуй русский вопрос в SQL запрос для PostgreSQL.

ПРАВИЛА:
1. Возвращай ТОЛЬКО SQL код
2. Используй {ПЛЕЙСХОЛДЕРЫ} для параметров
3. Всегда добавляй точку с запятой в конце
4. Для дат используй формат 'ГГГГ-ММ-ДД'
5. Для ID используй одинарные кавычки
""")
        
        # 2. Схема если есть
        if self.schema_info:
            schema_prompt = self.create_schema_prompt(detailed=False)
            prompt_parts.append(f"\n{schema_prompt}")
        
        # 3. Примеры этого типа запроса
        if include_examples:
            prompt_parts.append(f"\n## ПРИМЕРЫ ЗАПРОСОВ ТИПА '{template['description']}':")
            
            for example_query, example_sql in template['examples']:
                prompt_parts.append(f"\nВопрос: {example_query}")
                prompt_parts.append(f"SQL: {example_sql}")
        
        # 4. Плейсхолдеры
        if template['placeholders']:
            prompt_parts.append(f"\n## ИСПОЛЬЗУЙ ЭТИ ПЛЕЙСХОЛДЕРЫ:")
            for placeholder in template['placeholders']:
                prompt_parts.append(f"- {placeholder}")
        
        # 5. Сам запрос
        prompt_parts.append(f"\n## ТВОЙ ВОПРОС:")
        prompt_parts.append(f"Вопрос: {user_query}")
        prompt_parts.append("SQL:")
        
        return "\n".join(prompt_parts)
    
    def extract_parameters(self, user_query: str, sql_template: str) -> Dict[str, str]:
        """Извлечение параметров из запроса для заполнения шаблона"""
        params = {}
        
        # Ищем даты
        date_match = re.search(r'(\d{1,2})\s+(\w+)\s+(\d{4})', user_query, re.IGNORECASE)
        if date_match:
            day, month_ru, year = date_match.groups()
            month_map = {
                'января': 1, 'февраля': 2, 'марта': 3, 'апреля': 4,
                'мая': 5, 'июня': 6, 'июля': 7, 'августа': 8,
                'сентября': 9, 'октября': 10, 'ноября': 11, 'декабря': 12,
            }
            month_num = month_map.get(month_ru.lower(), 1)
            params['{DATE}'] = f"'{year}-{month_num:02d}-{int(day):02d}'"
        
        # Ищем диапазон дат
        date_range_match = re.search(r'с\s+(\d{1,2})\s+(\w+)\s+(\d{4})\s+по\s+(\d{1,2})\s+(\w+)\s+(\d{4})', user_query, re.IGNORECASE)
        if date_range_match:
            day1, month1_ru, year1, day2, month2_ru, year2 = date_range_match.groups()
            month_map = {
                'января': 1, 'февраля': 2, 'марта': 3, 'апреля': 4,
                'мая': 5, 'июня': 6, 'июля': 7, 'августа': 8,
                'сентября': 9, 'октября': 10, 'ноября': 11, 'декабря': 12,
            }
            month1_num = month_map.get(month1_ru.lower(), 1)
            month2_num = month_map.get(month2_ru.lower(), 1)
            
            params['{DATE1}'] = f"'{year1}-{month1_num:02d}-{int(day1):02d}'"
            params['{DATE2}'] = f"'{year2}-{month2_num:02d}-{int(day2):02d}'"
        
        # Ищем числа
        numbers = re.findall(r'\b(\d+)\b', user_query)
        if numbers:
            params['{NUMBER}'] = numbers[0]
            for i, num in enumerate(numbers, 1):
                params[f'{{NUMBER{i}}}'] = num
        
        # Ищем ID
        id_patterns = [
            r'[a-f0-9]{32}',
            r'креатор[ауе]?\s+([a-f0-9]{32})',
            r'id\s+([a-f0-9]{32})'
        ]
        
        for pattern in id_patterns:
            id_match = re.search(pattern, user_query, re.IGNORECASE)
            if id_match:
                params['{ID}'] = f"'{id_match.group(0)}'"
                break
        
        return params
    
    def fill_template(self, sql_template: str, params: Dict[str, str]) -> str:
        """Заполнение шаблона параметрами"""
        sql = sql_template
        
        for placeholder, value in params.items():
            if placeholder in sql:
                sql = sql.replace(placeholder, value)
        
        return sql
    
    def generate_fallback_sql(self, user_query: str) -> str:
        """Генерация fallback SQL на основе типа запроса"""
        query_type = self.detect_query_type(user_query)
        
        fallback_templates = {
            'count': "SELECT COUNT(*) FROM videos;",
            'sum': "SELECT SUM(views_count) FROM videos;",
            'average': "SELECT AVG(views_count) FROM videos;",
            'filter': "SELECT * FROM videos LIMIT 10;",
            'group': "SELECT DATE(created_at), COUNT(*) FROM video_snapshots GROUP BY DATE(created_at) LIMIT 10;",
            'join': "SELECT v.*, vs.delta_views_count FROM videos v JOIN video_snapshots vs ON v.id = vs.video_id LIMIT 10;"
        }
        
        return fallback_templates.get(query_type, "SELECT * FROM videos LIMIT 10;")