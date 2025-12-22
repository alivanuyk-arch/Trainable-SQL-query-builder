import json
import logging
from typing import Dict, List, Any
from pathlib import Path

logger = logging.getLogger(__name__)

class SchemaLoader:
    """Загрузчик и анализатор схемы данных"""
    
    def __init__(self, data_path: Path):
        self.data_path = data_path
        self.schema = {}
    
    async def load_from_json(self, json_file: Path = None) -> Dict:
        """Загрузка схемы из JSON файла"""
        if json_file is None:
            json_file = self.data_path
        
        if not json_file.exists():
            logger.warning(f"JSON file not found: {json_file}")
            return {}
        
        try:
            with open(json_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            if isinstance(data, list) and len(data) > 0:
                # Анализируем первый элемент массива
                self.schema = self._analyze_structure(data[0])
                self._add_statistics(data)
            
            logger.info(f"Schema loaded from {json_file}")
            return self.schema
            
        except Exception as e:
            logger.error(f"Error loading JSON schema: {e}")
            return {}
    
    def _analyze_structure(self, item: Dict) -> Dict:
        """Анализ структуры одного элемента"""
        schema = {}
        
        for key, value in item.items():
            field_info = {
                'type': self._guess_type(value),
                'nullable': value is None,
                'sample': str(value)[:50] if value else None
            }
            
            # Особые случаи
            if key.endswith('_id'):
                field_info['is_id'] = True
            elif key.endswith('_at') or key.endswith('_date'):
                field_info['is_timestamp'] = True
            elif key.endswith('_count'):
                field_info['is_counter'] = True
            
            schema[key] = field_info
        
        return schema
    
    def _guess_type(self, value: Any) -> str:
        """Определение типа данных"""
        if value is None:
            return 'unknown'
        elif isinstance(value, str):
            # Проверяем на UUID
            if len(value) == 36 and '-' in value:
                return 'uuid'
            # Проверяем на timestamp строку
            if '202' in value and ('T' in value or '-' in value):
                return 'timestamp'
            return 'text'
        elif isinstance(value, bool):
            return 'boolean'
        elif isinstance(value, int):
            return 'integer'
        elif isinstance(value, float):
            return 'float'
        elif isinstance(value, dict):
            return 'json'
        elif isinstance(value, list):
            return 'array'
        else:
            return 'unknown'
    
    def _add_statistics(self, data: List[Dict]) -> None:
        """Добавление статистики в схему"""
        if not data:
            return
        
        # Собираем уникальные значения для каждого поля
        for field in self.schema.keys():
            values = [item.get(field) for item in data if field in item]
            unique_values = set(values)
            
            if 'stats' not in self.schema[field]:
                self.schema[field]['stats'] = {}
            
            self.schema[field]['stats'].update({
                'count': len(values),
                'unique_count': len(unique_values),
                'sample_values': list(unique_values)[:5]
            })
    
    def generate_russian_aliases(self) -> Dict[str, str]:
        """Генерация русских алиасов для полей"""
        aliases = {}
        mapping = {
            # Общие суффиксы
            '_id': 'идентификатор',
            '_at': 'дата и время',
            '_date': 'дата',
            '_count': 'количество',
            '_name': 'название',
            '_type': 'тип',
            
            # Конкретные поля
            'video': 'видео',
            'creator': 'креатор',
            'views': 'просмотры',
            'likes': 'лайки',
            'comments': 'комментарии',
            'reports': 'репорты',
            'created': 'создан',
            'updated': 'обновлен',
            'delta': 'изменение',
        }
        
        for field in self.schema.keys():
            russian_name = field
            for eng, rus in mapping.items():
                if field.endswith(eng):
                    base = field.replace(eng, '')
                    if base in mapping:
                        russian_name = f"{mapping[base]} {rus}"
                    else:
                        russian_name = rus
                    break
                elif field.startswith(eng):
                    suffix = field.replace(eng, '')
                    if suffix in mapping:
                        russian_name = f"{rus} {mapping[suffix]}"
                    else:
                        russian_name = f"{rus} {suffix}"
                    break
            
            aliases[field] = russian_name
        
        return aliases
    
    def save_schema(self, output_path: Path) -> None:
        """Сохранение схемы в файл"""
        schema_data = {
            'schema': self.schema,
            'aliases': self.generate_russian_aliases(),
            'generated_at': str(datetime.now())
        }
        
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(schema_data, f, ensure_ascii=False, indent=2)
        
        logger.info(f"Schema saved to {output_path}")