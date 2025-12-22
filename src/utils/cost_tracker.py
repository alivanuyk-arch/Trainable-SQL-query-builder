import json
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional
import logging

logger = logging.getLogger(__name__)

class CostTracker:
    """Трекер стоимости LLM запросов"""
    
    def __init__(self, storage_path: Path = None):
        self.storage_path = storage_path
        self.costs: Dict[str, float] = {
            'total': 0.0,
            'today': 0.0,
            'monthly': 0.0
        }
        self.usage_stats: Dict = {
            'total_requests': 0,
            'total_tokens': 0,
            'avg_tokens_per_request': 0,
            'requests_today': 0
        }
        
        self._load_data()
    
    def _load_data(self):
        """Загрузка данных о стоимости"""
        if not self.storage_path:
            return
        
        cost_file = self.storage_path / "cost_tracking.json"
        
        if cost_file.exists():
            try:
                with open(cost_file, 'r') as f:
                    data = json.load(f)
                
                self.costs = data.get('costs', self.costs)
                self.usage_stats = data.get('usage_stats', self.usage_stats)
                
                # Сбрасываем дневную статистику если новый день
                last_update = data.get('last_update')
                if last_update:
                    last_date = datetime.fromisoformat(last_update).date()
                    if last_date < datetime.now().date():
                        self.costs['today'] = 0.0
                        self.usage_stats['requests_today'] = 0
                        
            except Exception as e:
                logger.error(f"Error loading cost data: {e}")
    
    def track_request(self, provider: str, model: str, prompt_tokens: int, 
                     completion_tokens: int, estimated_cost: float = None):
        """Трекинг запроса к LLM"""
        self.usage_stats['total_requests'] += 1
        self.usage_stats['requests_today'] += 1
        
        total_tokens = prompt_tokens + completion_tokens
        self.usage_stats['total_tokens'] += total_tokens
        
        # Обновляем среднее
        avg = self.usage_stats['avg_tokens_per_request']
        new_avg = (avg * (self.usage_stats['total_requests'] - 1) + total_tokens) / self.usage_stats['total_requests']
        self.usage_stats['avg_tokens_per_request'] = new_avg
        
        # Расчет стоимости если не предоставлена
        if estimated_cost is None:
            estimated_cost = self._estimate_cost(provider, model, prompt_tokens, completion_tokens)
        
        self.costs['total'] += estimated_cost
        self.costs['today'] += estimated_cost
        self.costs['monthly'] += estimated_cost
        
        # Сохраняем
        self._save_data()
        
        logger.info(f"Tracked LLM request: {provider}:{model}, tokens: {total_tokens}, cost: ${estimated_cost:.6f}")
    
    def _estimate_cost(self, provider: str, model: str, prompt_tokens: int, 
                      completion_tokens: int) -> float:
        """Оценка стоимости запроса"""
        # Цены на 1000 токенов (примерные)
        pricing = {
            'openai': {
                'gpt-3.5-turbo': {'input': 0.0015, 'output': 0.002},
                'gpt-4': {'input': 0.03, 'output': 0.06},
                'gpt-4-turbo': {'input': 0.01, 'output': 0.03},
            },
            'ollama': {
                'default': {'input': 0.0, 'output': 0.0}  # Бесплатно
            }
        }
        
        provider_pricing = pricing.get(provider, pricing['ollama'])
        model_pricing = provider_pricing.get(model, provider_pricing.get('default', {'input': 0.0, 'output': 0.0}))
        
        input_cost = (prompt_tokens / 1000) * model_pricing['input']
        output_cost = (completion_tokens / 1000) * model_pricing['output']
        
        return input_cost + output_cost
    
    def _save_data(self):
        """Сохранение данных о стоимости"""
        if not self.storage_path:
            return
        
        try:
            data = {
                'costs': self.costs,
                'usage_stats': self.usage_stats,
                'last_update': datetime.now().isoformat()
            }
            
            cost_file = self.storage_path / "cost_tracking.json"
            with open(cost_file, 'w') as f:
                json.dump(data, f, indent=2)
                
        except Exception as e:
            logger.error(f"Error saving cost data: {e}")
    
    def get_stats(self) -> Dict:
        """Получение статистики"""
        return {
            'total_cost': round(self.costs['total'], 6),
            'cost_today': round(self.costs['today'], 6),
            'cost_monthly': round(self.costs['monthly'], 6),
            'total_requests': self.usage_stats['total_requests'],
            'requests_today': self.usage_stats['requests_today'],
            'total_tokens': self.usage_stats['total_tokens'],
            'avg_tokens_per_request': round(self.usage_stats['avg_tokens_per_request'], 1)
        }
    
    def reset_daily(self):
        """Сброс дневной статистики"""
        self.costs['today'] = 0.0
        self.usage_stats['requests_today'] = 0
        self._save_data()
    
    def reset_monthly(self):
        """Сброс месячной статистики"""
        self.costs['monthly'] = 0.0
        self._save_data()