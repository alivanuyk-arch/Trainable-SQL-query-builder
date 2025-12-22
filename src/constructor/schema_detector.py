import logging
from typing import Dict, List, Any
from dataclasses import dataclass, asdict 
from datetime import datetime

logger = logging.getLogger(__name__)

@dataclass
class TableInfo:
    name: str
    columns: Dict[str, str]  # column_name -> data_type
    primary_key: List[str]
    foreign_keys: List[Dict]
    estimated_rows: int = 0

class AutoSchemaDetector:
    """Автоматическое определение схемы БД"""
    
    def __init__(self, db_manager):
        self.db = db_manager
        self.tables: Dict[str, TableInfo] = {}
        self.relationships = []
        self.russian_aliases = {}
        
    async def detect_schema(self) -> Dict:
        """Основной метод определения схемы"""
        logger.info("Starting auto schema detection...")
        
        # 1. Получаем список таблиц
        tables = await self._get_tables()
        
        # 2. Для каждой таблицы получаем колонки
        for table in tables:
            table_info = await self._analyze_table(table)
            self.tables[table] = table_info
        
        # 3. Определяем связи между таблицами
        self.relationships = await self._find_relationships()
        
        # 4. Генерируем русские алиасы
        self.russian_aliases = self._generate_russian_aliases()
        
        # 5. Формируем полную схему
        schema = {
            'tables': {name: asdict(info) for name, info in self.tables.items()},
            'relationships': self.relationships,
            'aliases': self.russian_aliases,
            'detected_at': datetime.now().isoformat()
        }
        
        logger.info(f"Schema detected: {len(self.tables)} tables")
        return schema
    
    async def _get_tables(self) -> List[str]:
        """Получение списка таблиц"""
        query = """
            SELECT table_name 
            FROM information_schema.tables 
            WHERE table_schema = 'public'
            AND table_type = 'BASE TABLE'
            ORDER BY table_name
        """
        
        try:
            rows = await self.db.execute_query(query)
            return [row['table_name'] for row in rows]
        except Exception as e:
            logger.error(f"Error getting tables: {e}")
            return []
    
    async def _analyze_table(self, table_name: str) -> TableInfo:
        """Анализ структуры таблицы"""
        # Получаем колонки
        columns_query = """
            SELECT column_name, data_type, is_nullable,
                   column_default, character_maximum_length
            FROM information_schema.columns
            WHERE table_name = $1
            ORDER BY ordinal_position
        """
        
        columns_rows = await self.db.execute_query(columns_query, [table_name])
        columns = {row['column_name']: row['data_type'] for row in columns_rows}
        
        # Получаем первичный ключ
        pk_query = """
            SELECT kcu.column_name
            FROM information_schema.table_constraints tc
            JOIN information_schema.key_column_usage kcu
              ON tc.constraint_name = kcu.constraint_name
            WHERE tc.table_name = $1
              AND tc.constraint_type = 'PRIMARY KEY'
        """
        
        pk_rows = await self.db.execute_query(pk_query, [table_name])
        primary_key = [row['column_name'] for row in pk_rows]
        
        # Получаем внешние ключи
        fk_query = """
            SELECT
                kcu.column_name as fk_column,
                ccu.table_name as referenced_table,
                ccu.column_name as referenced_column
            FROM information_schema.table_constraints tc
            JOIN information_schema.key_column_usage kcu
              ON tc.constraint_name = kcu.constraint_name
            JOIN information_schema.constraint_column_usage ccu
              ON ccu.constraint_name = tc.constraint_name
            WHERE tc.table_name = $1
              AND tc.constraint_type = 'FOREIGN KEY'
        """
        
        fk_rows = await self.db.execute_query(fk_query, [table_name])
        foreign_keys = [dict(row) for row in fk_rows]
        
        # Оцениваем количество строк
        try:
            count_query = f"SELECT COUNT(*) as cnt FROM {table_name}"
            count_result = await self.db.execute_scalar(count_query)
            estimated_rows = count_result or 0
        except:
            estimated_rows = 0
        
        return TableInfo(
            name=table_name,
            columns=columns,
            primary_key=primary_key,
            foreign_keys=foreign_keys,
            estimated_rows=estimated_rows
        )
    
    async def _find_relationships(self) -> List[Dict]:
        """Поиск связей между таблицами"""
        relationships = []
        
        for table_name, table_info in self.tables.items():
            for fk in table_info.foreign_keys:
                relationships.append({
                    'from_table': table_name,
                    'from_column': fk['fk_column'],
                    'to_table': fk['referenced_table'],
                    'to_column': fk['referenced_column'],
                    'type': 'foreign_key'
                })
        
        # Дополнительно ищем потенциальные связи по именам колонок
        for table_name, table_info in self.tables.items():
            for column_name in table_info.columns:
                if column_name.endswith('_id'):
                    # Пробуем найти таблицу без префикса _id
                    potential_table = column_name[:-3]
                    if potential_table in self.tables:
                        relationships.append({
                            'from_table': table_name,
                            'from_column': column_name,
                            'to_table': potential_table,
                            'to_column': 'id',
                            'type': 'potential',
                            'confidence': 0.7
                        })
        
        return relationships
    
    def _generate_russian_aliases(self) -> Dict[str, str]:
        """Генерация русских названий"""
        aliases = {}
        
        # Словарь для таблиц
        table_translations = {
            'videos': 'видео',
            'video_snapshots': 'снимки_статистики_видео',
            'creators': 'креаторы',
            'users': 'пользователи',
            'statistics': 'статистика',
            'reports': 'отчеты',
        }
        
        # Словарь для полей
        field_translations = {
            'id': 'идентификатор',
            'created_at': 'дата_создания',
            'updated_at': 'дата_обновления',
            'views_count': 'количество_просмотров',
            'likes_count': 'количество_лайков',
            'comments_count': 'количество_комментариев',
            'video_id': 'идентификатор_видео',
            'creator_id': 'идентификатор_креатора',
            'delta_views_count': 'изменение_просмотров',
            'delta_likes_count': 'изменение_лайков',
            'delta_comments_count': 'изменение_комментариев',
            'video_created_at': 'дата_создания_видео',
        }
        
        # Генерируем алиасы для таблиц
        for table_name in self.tables:
            if table_name in table_translations:
                aliases[table_name] = table_translations[table_name]
            else:
                # Автоматическая транслитерация
                aliases[table_name] = table_name.replace('_', '_')
        
        # Генерируем алиасы для полей
        for table_name, table_info in self.tables.items():
            for column_name in table_info.columns:
                key = f"{table_name}.{column_name}"
                
                if column_name in field_translations:
                    aliases[key] = field_translations[column_name]
                elif column_name.endswith('_count'):
                    base = column_name.replace('_count', '')
                    aliases[key] = f"количество_{base}"
                elif column_name.endswith('_at'):
                    aliases[key] = 'дата_и_время'
                elif column_name.endswith('_id'):
                    base = column_name.replace('_id', '')
                    aliases[key] = f"идентификатор_{base}"
                else:
                    aliases[key] = column_name.replace('_', '_')
        
        return aliases
    
    def generate_schema_prompt(self) -> str:
        """Генерация промпта со схемой для LLM"""
        prompt = "## СХЕМА БАЗЫ ДАННЫХ:\n\n"
        
        for table_name, table_info in self.tables.items():
            prompt += f"### ТАБЛИЦА: {table_name} ({self.russian_aliases.get(table_name, table_name)})\n"
            prompt += "Поля:\n"
            
            for column_name, data_type in table_info.columns.items():
                alias_key = f"{table_name}.{column_name}"
                alias = self.russian_aliases.get(alias_key, column_name)
                nullable = "NULL" if "YES" in str(table_info.columns.get(column_name, "")).upper() else "NOT NULL"
                prompt += f"- {column_name} ({data_type}) {nullable} - {alias}\n"
            
            if table_info.primary_key:
                prompt += f"Первичный ключ: {', '.join(table_info.primary_key)}\n"
            
            if table_info.foreign_keys:
                prompt += "Внешние ключи:\n"
                for fk in table_info.foreign_keys:
                    prompt += f"  → {fk['fk_column']} → {fk['referenced_table']}.{fk['referenced_column']}\n"
            
            prompt += f"Примерное количество строк: {table_info.estimated_rows:,}\n\n"
        
        if self.relationships:
            prompt += "## СВЯЗИ МЕЖДУ ТАБЛИЦАМИ:\n"
            for rel in self.relationships:
                prompt += f"- {rel['from_table']}.{rel['from_column']} → {rel['to_table']}.{rel['to_column']}\n"
        
        return prompt