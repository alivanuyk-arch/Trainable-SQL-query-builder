import re
import json
import logging
from typing import Dict, List, Optional, Tuple, Set
from dataclasses import dataclass
from datetime import datetime
from collections import defaultdict
import hashlib

logger = logging.getLogger(__name__)

@dataclass
class LearningExample:
    query: str
    sql: str
    correction_type: str  # 'full', 'partial', 'optimization'
    confidence: float
    timestamp: str

class PatternLearner:
    """Система обучения паттернам на основе исправлений"""
    
    def __init__(self, storage_path):
        self.storage_path = storage_path
        self.examples: List[LearningExample] = []
        self.pattern_clusters = defaultdict(list)
        self.learned_rules: Dict[str, Dict] = {}
        
        self._load_examples()
    
    def _load_examples(self):
        """Загрузка примеров обучения"""
        examples_file = self.storage_path / "learning_examples.json"
        
        if examples_file.exists():
            try:
                with open(examples_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    
                for item in data.get('examples', []):
                    example = LearningExample(
                        query=item['query'],
                        sql=item['sql'],
                        correction_type=item.get('correction_type', 'full'),
                        confidence=item.get('confidence', 1.0),
                        timestamp=item.get('timestamp', datetime.now().isoformat())
                    )
                    self.examples.append(example)
                    
                logger.info(f"Loaded {len(self.examples)} learning examples")
            except Exception as e:
                logger.error(f"Error loading examples: {e}")
    
    def add_example(self, original_query: str, llm_sql: str, corrected_sql: str, 
                   correction_type: str = 'full'):
        """Добавление нового примера для обучения"""
        
        # Анализируем разницу
        diff = self._analyze_correction(llm_sql, corrected_sql)
        
        # Создаем пример
        example = LearningExample(
            query=original_query,
            sql=corrected_sql,
            correction_type=correction_type,
            confidence=self._calculate_confidence(diff),
            timestamp=datetime.now().isoformat()
        )
        
        self.examples.append(example)
        self._cluster_example(example)
        self._extract_rules(example, diff)
        self._save_examples()
        
        logger.info(f"Added learning example: {original_query[:50]}...")
    
    def _analyze_correction(self, llm_sql: str, corrected_sql: str) -> Dict:
        """Анализ исправления для извлечения правил"""
        
        diff = {
            'structural_changes': [],
            'parameter_changes': [],
            'optimizations': [],
            'error_types': []
        }
        
        # Нормализуем SQL для сравнения
        llm_normalized = self._normalize_sql(llm_sql)
        corrected_normalized = self._normalize_sql(corrected_sql)
        
        # 1. Структурные изменения (JOIN, GROUP BY, etc.)
        structural_keywords = ['JOIN', 'GROUP BY', 'ORDER BY', 'HAVING', 'LIMIT', 'OFFSET']
        
        for keyword in structural_keywords:
            llm_has = keyword in llm_normalized
            corrected_has = keyword in corrected_normalized
            
            if llm_has != corrected_has:
                diff['structural_changes'].append({
                    'keyword': keyword,
                    'llm_has': llm_has,
                    'corrected_has': corrected_has
                })
        
        # 2. Изменения параметров (WHERE условия)
        llm_conditions = self._extract_conditions(llm_sql)
        corrected_conditions = self._extract_conditions(corrected_sql)
        
        # Находим добавленные/удаленные условия
        added = [c for c in corrected_conditions if c not in llm_conditions]
        removed = [c for c in llm_conditions if c not in corrected_conditions]
        
        if added:
            diff['parameter_changes'].append({'type': 'added', 'conditions': added})
        if removed:
            diff['parameter_changes'].append({'type': 'removed', 'conditions': removed})
        
        # 3. Оптимизации
        if len(corrected_sql) < len(llm_sql) * 0.8:  # На 20% короче
            diff['optimizations'].append({
                'type': 'shorter',
                'llm_length': len(llm_sql),
                'corrected_length': len(corrected_sql),
                'reduction': (len(llm_sql) - len(corrected_sql)) / len(llm_sql)
            })
        
        return diff
    
    def _normalize_sql(self, sql: str) -> str:
        """Нормализация SQL для сравнения"""
        if not sql:
            return ""
        
        # Приводим к верхнему регистру ключевые слова
        normalized = sql.upper()
        
        # Удаляем лишние пробелы и переносы
        normalized = re.sub(r'\s+', ' ', normalized)
        
        # Удаляем значения параметров
        normalized = re.sub(r"'\d{4}-\d{2}-\d{2}'", "'{DATE}'", normalized)
        normalized = re.sub(r"'\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}'", "'{TIMESTAMP}'", normalized)
        normalized = re.sub(r"'\w{32}'", "'{ID}'", normalized)
        normalized = re.sub(r"'\w{8}-\w{4}-\w{4}-\w{4}-\w{12}'", "'{UUID}'", normalized)
        normalized = re.sub(r'\b\d+\b', '{NUMBER}', normalized)
        
        return normalized
    
    def _extract_conditions(self, sql: str) -> List[str]:
        """Извлечение условий WHERE"""
        conditions = []
        
        # Ищем WHERE часть
        where_match = re.search(r'WHERE\s+(.+?)(?:\s+(?:GROUP BY|ORDER BY|LIMIT|$))', sql, re.IGNORECASE | re.DOTALL)
        
        if where_match:
            where_clause = where_match.group(1)
            
            # Разбиваем на отдельные условия (AND/OR)
            and_parts = re.split(r'\s+AND\s+', where_clause, flags=re.IGNORECASE)
            
            for part in and_parts:
                or_parts = re.split(r'\s+OR\s+', part, flags=re.IGNORECASE)
                conditions.extend([p.strip() for p in or_parts])
        
        return conditions
    
    def _calculate_confidence(self, diff: Dict) -> float:
        """Расчет уверенности в примере"""
        confidence = 1.0
        
        # Штрафуем за множественные структурные изменения
        structural_changes = len(diff.get('structural_changes', []))
        if structural_changes > 2:
            confidence *= 0.7
        
        # Штрафуем за удаление условий (возможно LLM было право)
        for change in diff.get('parameter_changes', []):
            if change['type'] == 'removed' and len(change['conditions']) > 0:
                confidence *= 0.8
        
        return max(0.1, confidence)  # Минимум 10% уверенности
    
    def _cluster_example(self, example: LearningExample):
        """Кластеризация примеров"""
        # Извлекаем ключевые слова из запроса
        keywords = self._extract_keywords(example.query)
        
        if keywords:
            cluster_key = "_".join(sorted(keywords)[:3])  # Используем 3 ключевых слова
            self.pattern_clusters[cluster_key].append(example)
    
    def _extract_keywords(self, query: str) -> Set[str]:
        """Извлечение ключевых слов из запроса"""
        stop_words = {'и', 'в', 'с', 'по', 'за', 'у', 'о', 'от', 'для', 'на', 'из'}
        
        words = re.findall(r'\b\w+\b', query.lower())
        keywords = set()
        
        for word in words:
            if word in stop_words:
                continue
            if len(word) < 3:
                continue
            if word.isdigit():
                continue
            
            keywords.add(word)
        
        return keywords
    
    def _extract_rules(self, example: LearningExample, diff: Dict):
        """Извлечение правил из исправления"""
        
        for change in diff.get('structural_changes', []):
            if not change['llm_has'] and change['corrected_has']:
                # LLM пропустил важную конструкцию
                rule_key = f"add_{change['keyword'].replace(' ', '_').lower()}"
                
                if rule_key not in self.learned_rules:
                    self.learned_rules[rule_key] = {
                        'type': 'structural_add',
                        'keyword': change['keyword'],
                        'triggers': self._extract_keywords(example.query),
                        'confidence': example.confidence,
                        'examples': 1,
                        'last_used': example.timestamp
                    }
                else:
                    self.learned_rules[rule_key]['examples'] += 1
                    self.learned_rules[rule_key]['confidence'] = max(
                        self.learned_rules[rule_key]['confidence'],
                        example.confidence
                    )
                    self.learned_rules[rule_key]['last_used'] = example.timestamp
        
        for change in diff.get('parameter_changes', []):
            for condition in change.get('conditions', []):
                # Извлекаем паттерн условия
                condition_pattern = self._patternize_condition(condition)
                
                if change['type'] == 'added':
                    rule_key = f"require_{hashlib.md5(condition_pattern.encode()).hexdigest()[:8]}"
                    
                    if rule_key not in self.learned_rules:
                        self.learned_rules[rule_key] = {
                            'type': 'condition_required',
                            'pattern': condition_pattern,
                            'triggers': self._extract_keywords(example.query),
                            'confidence': example.confidence,
                            'examples': 1,
                            'last_used': example.timestamp
                        }
    
    def _patternize_condition(self, condition: str) -> str:
        """Преобразование условия в паттерн"""
        pattern = condition
        
        # Заменяем значения на типы
        pattern = re.sub(r"'\d{4}-\d{2}-\d{2}'", "'{DATE}'", pattern)
        pattern = re.sub(r"'\w{32}'", "'{ID}'", pattern)
        pattern = re.sub(r'\b\d+\b', '{NUMBER}', pattern)
        
        return pattern
    
    def apply_rules_to_query(self, user_query: str, llm_sql: str) -> str:
        """Применение выученных правил к SQL запросу"""
        improved_sql = llm_sql
        
        query_keywords = self._extract_keywords(user_query)
        
        for rule_key, rule in self.learned_rules.items():
            # Проверяем триггеры правила
            rule_triggers = set(rule.get('triggers', []))
            if rule_triggers and rule_triggers.intersection(query_keywords):
                
                if rule['type'] == 'structural_add':
                    keyword = rule['keyword']
                    
                    # Проверяем, нет ли уже этой конструкции
                    if keyword not in improved_sql.upper():
                        # Добавляем конструкцию в нужное место
                        improved_sql = self._add_structural_element(improved_sql, keyword, rule)
                
                elif rule['type'] == 'condition_required':
                    condition_pattern = rule['pattern']
                    
                    # Проверяем, нет ли похожего условия
                    if not self._has_similar_condition(improved_sql, condition_pattern):
                        improved_sql = self._add_condition(improved_sql, condition_pattern)
        
        return improved_sql if improved_sql != llm_sql else llm_sql
    
    def _add_structural_element(self, sql: str, element: str, rule: Dict) -> str:
        """Добавление структурного элемента в SQL"""
        # Простая реализация - в реальности нужен более сложный анализ
        if element == 'GROUP BY' and 'GROUP BY' not in sql.upper():
            # Находим SELECT и добавляем GROUP BY
            select_match = re.search(r'SELECT\s+(.+?)\s+FROM', sql, re.IGNORECASE | re.DOTALL)
            if select_match:
                select_clause = select_match.group(1)
                # Берем первое поле для группировки
                first_field = select_clause.split(',')[0].strip()
                if 'COUNT' not in first_field.upper() and 'SUM' not in first_field.upper():
                    sql = sql.rstrip(';') + f" GROUP BY {first_field};"
        
        return sql
    
    def _has_similar_condition(self, sql: str, pattern: str) -> bool:
        """Проверка наличия похожего условия"""
        conditions = self._extract_conditions(sql)
        
        for condition in conditions:
            condition_pattern = self._patternize_condition(condition)
            if condition_pattern == pattern:
                return True
        
        return False
    
    def _add_condition(self, sql: str, pattern: str) -> str:
        """Добавление условия в WHERE"""
        if 'WHERE' not in sql.upper():
            # Добавляем WHERE
            where_pos = sql.upper().find('FROM') + 4
            sql = sql[:where_pos] + ' WHERE ' + pattern + sql[where_pos:]
        else:
            # Добавляем AND
            sql = sql.rstrip(';') + ' AND ' + pattern + ';'
        
        return sql
    
    def _save_examples(self):
        """Сохранение примеров обучения"""
        try:
            data = {
                'examples': [
                    {
                        'query': ex.query,
                        'sql': ex.sql,
                        'correction_type': ex.correction_type,
                        'confidence': ex.confidence,
                        'timestamp': ex.timestamp
                    }
                    for ex in self.examples[-100:]  # Храним последние 100 примеров
                ],
                'total_examples': len(self.examples),
                'updated_at': datetime.now().isoformat()
            }
            
            examples_file = self.storage_path / "learning_examples.json"
            with open(examples_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
                
        except Exception as e:
            logger.error(f"Error saving examples: {e}")
    
    def get_learning_stats(self) -> Dict:
        """Получение статистики обучения"""
        return {
            'total_examples': len(self.examples),
            'total_clusters': len(self.pattern_clusters),
            'total_rules': len(self.learned_rules),
            'active_rules': sum(1 for r in self.learned_rules.values() 
                              if r.get('examples', 0) >= 3),
            'avg_confidence': sum(ex.confidence for ex in self.examples) / len(self.examples) 
                            if self.examples else 0
        }
    
    def optimize_rules(self):
        """Оптимизация правил - удаление устаревших"""
        rules_to_remove = []
        
        for rule_key, rule in self.learned_rules.items():
            last_used = datetime.fromisoformat(rule.get('last_used', '2000-01-01'))
            days_since_use = (datetime.now() - last_used).days
            
            if days_since_use > 60 or rule.get('examples', 0) < 2:
                rules_to_remove.append(rule_key)
        
        for rule_key in rules_to_remove:
            del self.learned_rules[rule_key]
        
        if rules_to_remove:
            logger.info(f"Removed {len(rules_to_remove)} outdated rules")