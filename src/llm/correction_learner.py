import json
import re
import logging
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, asdict
from datetime import datetime
from collections import defaultdict
import difflib

logger = logging.getLogger(__name__)

@dataclass
class CorrectionRecord:
    original_query: str
    llm_sql: str
    corrected_sql: str
    user_feedback: Optional[str]
    timestamp: str
    correction_type: str
    confidence: float
    learned_pattern: Optional[str] = None

class CorrectionLearner:
    """Система обучения на исправлениях пользователей"""
    
    def __init__(self, storage_path):
        self.storage_path = storage_path
        self.corrections: List[CorrectionRecord] = []
        self.patterns: Dict[str, Dict] = {}
        self.feedback_analysis: Dict[str, Dict] = {}
        
        self._load_data()
        
        # Статистика
        self.stats = {
            'total_corrections': len(self.corrections),
            'patterns_learned': 0,
            'success_rate': 0.0,
            'common_mistakes': defaultdict(int)
        }
    
    def _load_data(self):
        """Загрузка данных об исправлениях"""
        corrections_file = self.storage_path / "corrections_learned.json"
        
        if corrections_file.exists():
            try:
                with open(corrections_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                
                self.corrections = [
                    CorrectionRecord(**record) for record in data.get('corrections', [])
                ]
                self.patterns = data.get('patterns', {})
                self.feedback_analysis = data.get('feedback_analysis', {})
                
                logger.info(f"Loaded {len(self.corrections)} corrections")
            except Exception as e:
                logger.error(f"Error loading corrections: {e}")
    
    def add_correction(self, original_query: str, llm_sql: str, 
                      corrected_sql: str, user_feedback: str = None):
        """Добавление нового исправления"""
        
        # Анализируем тип исправления
        correction_type = self._analyze_correction_type(llm_sql, corrected_sql)
        
        # Создаем запись
        record = CorrectionRecord(
            original_query=original_query,
            llm_sql=llm_sql,
            corrected_sql=corrected_sql,
            user_feedback=user_feedback,
            timestamp=datetime.now().isoformat(),
            correction_type=correction_type,
            confidence=self._calculate_confidence(llm_sql, corrected_sql)
        )
        
        self.corrections.append(record)
        self.stats['total_corrections'] += 1
        
        # Анализируем и учимся
        self._analyze_correction(record)
        self._extract_pattern(record)
        self._update_feedback_analysis(user_feedback)
        
        # Сохраняем
        self._save_data()
        
        logger.info(f"Added correction: {correction_type} for '{original_query[:50]}...'")
    
    def _analyze_correction_type(self, llm_sql: str, corrected_sql: str) -> str:
        """Анализ типа исправления"""
        llm_norm = self._normalize_sql(llm_sql)
        corrected_norm = self._normalize_sql(corrected_sql)
        
        if llm_norm == corrected_norm:
            return "formatting"
        
        # Проверяем структурные изменения
        structural_keywords = ['JOIN', 'GROUP BY', 'ORDER BY', 'HAVING']
        
        for keyword in structural_keywords:
            llm_has = keyword in llm_norm
            corrected_has = keyword in corrected_norm
            
            if llm_has != corrected_has:
                return f"structural_{keyword.lower().replace(' ', '_')}"
        
        # Проверяем условия WHERE
        llm_where = self._extract_where_conditions(llm_sql)
        corrected_where = self._extract_where_conditions(corrected_sql)
        
        if llm_where != corrected_where:
            if len(corrected_where) > len(llm_where):
                return "where_addition"
            else:
                return "where_correction"
        
        # Проверяем поля SELECT
        llm_select = self._extract_select_fields(llm_sql)
        corrected_select = self._extract_select_fields(corrected_sql)
        
        if llm_select != corrected_select:
            return "select_fields"
        
        # Проверяем агрегацию
        aggregate_functions = ['COUNT', 'SUM', 'AVG', 'MAX', 'MIN']
        for func in aggregate_functions:
            if (func in corrected_norm) != (func in llm_norm):
                return "aggregation"
        
        return "other"
    
    def _normalize_sql(self, sql: str) -> str:
        """Нормализация SQL для сравнения"""
        if not sql:
            return ""
        
        # Приводим к верхнему регистру
        normalized = sql.upper()
        
        # Удаляем лишние пробелы
        normalized = re.sub(r'\s+', ' ', normalized)
        
        # Удаляем значения
        normalized = re.sub(r"'\d{4}-\d{2}-\d{2}'", "'{DATE}'", normalized)
        normalized = re.sub(r'\b\d+\b', '{NUMBER}', normalized)
        normalized = re.sub(r"'\w{32}'", "'{ID}'", normalized)
        
        return normalized
    
    def _extract_where_conditions(self, sql: str) -> List[str]:
        """Извлечение условий WHERE"""
        conditions = []
        
        where_match = re.search(r'WHERE\s+(.+?)(?:\s+(?:GROUP BY|ORDER BY|LIMIT|$))', 
                               sql, re.IGNORECASE | re.DOTALL)
        
        if where_match:
            where_clause = where_match.group(1)
            # Разбиваем на отдельные условия
            parts = re.split(r'\s+AND\s+|\s+OR\s+', where_clause, flags=re.IGNORECASE)
            conditions = [part.strip() for part in parts]
        
        return conditions
    
    def _extract_select_fields(self, sql: str) -> List[str]:
        """Извлечение полей SELECT"""
        fields = []
        
        select_match = re.search(r'SELECT\s+(.+?)\s+FROM', sql, re.IGNORECASE | re.DOTALL)
        
        if select_match:
            select_clause = select_match.group(1)
            # Разбиваем на отдельные поля
            parts = select_clause.split(',')
            fields = [part.strip() for part in parts]
        
        return fields
    
    def _calculate_confidence(self, llm_sql: str, corrected_sql: str) -> float:
        """Расчет уверенности в исправлении"""
        # Используем difflib для сравнения строк
        similarity = difflib.SequenceMatcher(
            None, 
            self._normalize_sql(llm_sql), 
            self._normalize_sql(corrected_sql)
        ).ratio()
        
        # Чем меньше схожесть, тем больше уверенность в необходимости исправления
        confidence = 1.0 - similarity
        
        return max(0.1, min(1.0, confidence))
    
    def _analyze_correction(self, record: CorrectionRecord):
        """Анализ исправления для обучения"""
        
        # Анализируем разницу
        diff = self._compute_sql_diff(record.llm_sql, record.corrected_sql)
        
        # Определяем тип ошибки
        error_type = self._identify_error_type(diff)
        
        if error_type:
            self.stats['common_mistakes'][error_type] += 1
        
        # Обновляем статистику успешности
        if record.correction_type in ['formatting', 'other']:
            # Мелкие исправления не считаются серьезными ошибками
            self.stats['success_rate'] = min(1.0, self.stats['success_rate'] + 0.01)
        else:
            # Серьезные исправления
            self.stats['success_rate'] = max(0.0, self.stats['success_rate'] - 0.05)
    
    def _compute_sql_diff(self, sql1: str, sql2: str) -> Dict:
        """Вычисление различий между SQL запросами"""
        diff = {
            'tables_added': [],
            'tables_removed': [],
            'conditions_added': [],
            'conditions_removed': [],
            'fields_changed': [],
            'aggregation_changed': False
        }
        
        # Извлекаем таблицы
        tables1 = set(re.findall(r'FROM\s+(\w+)', sql1, re.IGNORECASE))
        tables2 = set(re.findall(r'FROM\s+(\w+)', sql2, re.IGNORECASE))
        
        diff['tables_added'] = list(tables2 - tables1)
        diff['tables_removed'] = list(tables1 - tables2)
        
        # Извлекаем условия
        conditions1 = self._extract_where_conditions(sql1)
        conditions2 = self._extract_where_conditions(sql2)
        
        diff['conditions_added'] = [c for c in conditions2 if c not in conditions1]
        diff['conditions_removed'] = [c for c in conditions1 if c not in conditions2]
        
        # Извлекаем поля
        fields1 = self._extract_select_fields(sql1)
        fields2 = self._extract_select_fields(sql2)
        
        if fields1 != fields2:
            diff['fields_changed'] = list(set(fields2) - set(fields1))
        
        # Проверяем агрегацию
        agg_funcs = ['COUNT', 'SUM', 'AVG', 'MAX', 'MIN']
        has_agg1 = any(func in sql1.upper() for func in agg_funcs)
        has_agg2 = any(func in sql2.upper() for func in agg_funcs)
        
        diff['aggregation_changed'] = has_agg1 != has_agg2
        
        return diff
    
    def _identify_error_type(self, diff: Dict) -> Optional[str]:
        """Определение типа ошибки"""
        if diff['tables_added'] or diff['tables_removed']:
            return "missing_join"
        
        if diff['conditions_added']:
            if any('EXTRACT' in cond.upper() for cond in diff['conditions_added']):
                return "missing_date_extract"
            if any('YEAR' in cond.upper() for cond in diff['conditions_added']):
                return "missing_year"
            return "missing_condition"
        
        if diff['conditions_removed']:
            return "unnecessary_condition"
        
        if diff['fields_changed']:
            return "wrong_fields"
        
        if diff['aggregation_changed']:
            return "aggregation_error"
        
        return None
    
    def _extract_pattern(self, record: CorrectionRecord):
        """Извлечение паттерна из исправления"""
        
        # Извлекаем ключевые слова из запроса
        keywords = self._extract_query_keywords(record.original_query)
        
        if not keywords:
            return
        
        # Создаем шаблон SQL
        sql_template = self._create_sql_template(record.corrected_sql)
        
        # Создаем паттерн
        pattern_key = "_".join(sorted(keywords)[:3]) + "_" + record.correction_type
        
        self.patterns[pattern_key] = {
            'keywords': keywords,
            'sql_template': sql_template,
            'correction_type': record.correction_type,
            'example_query': record.original_query,
            'confidence': record.confidence,
            'created_at': record.timestamp,
            'usage_count': 1
        }
        
        record.learned_pattern = pattern_key
        self.stats['patterns_learned'] += 1
    
    def _extract_query_keywords(self, query: str) -> List[str]:
        """Извлечение ключевых слов из запроса"""
        stop_words = {'и', 'в', 'с', 'по', 'за', 'у', 'о', 'от', 'для', 'на', 'из'}
        
        words = re.findall(r'\b\w+\b', query.lower())
        keywords = []
        
        for word in words:
            if word in stop_words:
                continue
            if len(word) < 3:
                continue
            if word.isdigit():
                continue
            
            keywords.append(word)
        
        return keywords[:5]  # Берем первые 5 ключевых слов
    
    def _create_sql_template(self, sql: str) -> str:
        """Создание шаблона SQL из конкретного запроса"""
        template = sql
        
        # Заменяем конкретные значения на плейсхолдеры
        template = re.sub(r"'\d{4}-\d{2}-\d{2}'", "'{DATE}'", template)
        template = re.sub(r"'\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}'", "'{TIMESTAMP}'", template)
        template = re.sub(r"'\w{32}'", "'{ID}'", template)
        template = re.sub(r"'\w{8}-\w{4}-\w{4}-\w{4}-\w{12}'", "'{UUID}'", template)
        template = re.sub(r'\b\d+\b', '{NUMBER}', template)
        
        # Заменяем конкретные имена таблиц на плейсхолдеры если нужно
        common_tables = ['videos', 'video_snapshots', 'creators']
        for table in common_tables:
            if table in template:
                template = template.replace(table, '{TABLE}')
                break
        
        return template
    
    def _update_feedback_analysis(self, feedback: Optional[str]):
        """Анализ и обновление фидбека"""
        if not feedback:
            return
        
        # Простой анализ текста фидбека
        feedback_lower = feedback.lower()
        
        if any(word in feedback_lower for word in ['неправильно', 'ошибка', 'неверно']):
            key = 'negative_correction'
        elif any(word in feedback_lower for word in ['правильно', 'верно', 'так', 'да']):
            key = 'positive_confirmation'
        elif any(word in feedback_lower for word in ['уточни', 'дополни', 'добавь']):
            key = 'clarification_needed'
        else:
            key = 'general_feedback'
        
        if key not in self.feedback_analysis:
            self.feedback_analysis[key] = {
                'count': 1,
                'examples': [feedback],
                'last_seen': datetime.now().isoformat()
            }
        else:
            self.feedback_analysis[key]['count'] += 1
            self.feedback_analysis[key]['examples'].append(feedback)
            self.feedback_analysis[key]['last_seen'] = datetime.now().isoformat()
    
    def find_similar_pattern(self, user_query: str) -> Optional[Dict]:
        """Поиск похожего паттерна для пользовательского запроса"""
        query_keywords = set(self._extract_query_keywords(user_query))
        
        best_pattern = None
        best_score = 0
        
        for pattern_key, pattern in self.patterns.items():
            pattern_keywords = set(pattern.get('keywords', []))
            
            if not pattern_keywords:
                continue
            
            # Вычисляем схожесть по ключевым словам
            common = query_keywords.intersection(pattern_keywords)
            if not common:
                continue
            
            coverage = len(common) / len(pattern_keywords)
            recall = len(common) / len(query_keywords) if query_keywords else 0
            
            score = (coverage * 0.6) + (recall * 0.4)
            
            if score > best_score and score > 0.3:
                best_score = score
                best_pattern = pattern
        
        return best_pattern
    
    def apply_learned_patterns(self, user_query: str, llm_sql: str) -> str:
        """Применение выученных паттернов к SQL"""
        pattern = self.find_similar_pattern(user_query)
        
        if not pattern:
            return llm_sql
        
        # Увеличиваем счетчик использования
        pattern['usage_count'] += 1
        
        # Применяем паттерн если уверенность высокая
        if pattern['confidence'] > 0.7:
            sql_template = pattern['sql_template']
            
            # Заполняем шаблон параметрами из запроса
            params = self._extract_parameters(user_query)
            filled_sql = self._fill_template(sql_template, params)
            
            return filled_sql
        
        return llm_sql
    
    def _extract_parameters(self, query: str) -> Dict[str, str]:
        """Извлечение параметров из запроса"""
        params = {}
        
        # Ищем даты
        date_match = re.search(r'(\d{1,2})\s+(\w+)\s+(\d{4})', query, re.IGNORECASE)
        if date_match:
            day, month_ru, year = date_match.groups()
            month_map = {
                'января': 1, 'февраля': 2, 'марта': 3, 'апреля': 4,
                'мая': 5, 'июня': 6, 'июля': 7, 'августа': 8,
                'сентября': 9, 'октября': 10, 'ноября': 11, 'декабря': 12,
            }
            month_num = month_map.get(month_ru.lower(), 1)
            params['{DATE}'] = f"'{year}-{month_num:02d}-{int(day):02d}'"
            params['{YEAR}'] = year
            params['{MONTH}'] = str(month_num)
        
        # Ищем числа
        numbers = re.findall(r'\b(\d+)\b', query)
        if numbers:
            params['{NUMBER}'] = numbers[0]
        
        return params
    
    def _fill_template(self, template: str, params: Dict[str, str]) -> str:
        """Заполнение шаблона параметрами"""
        sql = template
        
        for placeholder, value in params.items():
            if placeholder in sql:
                sql = sql.replace(placeholder, value)
        
        return sql
    
    def _save_data(self):
        """Сохранение данных об исправлениях"""
        try:
            data = {
                'corrections': [asdict(record) for record in self.corrections[-100:]],
                'patterns': self.patterns,
                'feedback_analysis': self.feedback_analysis,
                'stats': self.stats,
                'updated_at': datetime.now().isoformat()
            }
            
            corrections_file = self.storage_path / "corrections_learned.json"
            with open(corrections_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
                
        except Exception as e:
            logger.error(f"Error saving corrections: {e}")
    
    def get_stats(self) -> Dict:
        """Получение статистики обучения"""
        return {
            'total_corrections': self.stats['total_corrections'],
            'patterns_learned': self.stats['patterns_learned'],
            'success_rate': round(self.stats['success_rate'], 2),
            'common_mistakes': dict(self.stats['common_mistakes']),
            'feedback_types': {k: v['count'] for k, v in self.feedback_analysis.items()}
        }