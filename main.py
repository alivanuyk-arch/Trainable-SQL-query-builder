import asyncio
import sys
import os
from pathlib import Path

# КРИТИЧЕСКИ ВАЖНО для Windows
current_dir = Path(__file__).parent

# Добавляем ВСЕ возможные пути
sys.path.insert(0, str(current_dir))
sys.path.insert(0, str(current_dir / "src"))

print("="*60)
print("🔧 НАСТРОЙКА ПУТЕЙ PYTHON")
print("="*60)
print(f"Текущая директория: {current_dir}")
print(f"Python пути:")
for i, p in enumerate(sys.path[:5]):
    print(f"  {i+1}. {p}")

# Проверяем структуру
print(f"\n📁 СТРУКТУРА ПРОЕКТА:")
check_paths = [
    ("src/", current_dir / "src"),
    ("src/bot/", current_dir / "src" / "bot"),
    ("src/bot/bot_core.py", current_dir / "src" / "bot" / "bot_core.py"),
    ("src/bot/__init__.py", current_dir / "src" / "bot" / "__init__.py"),
]

for name, path in check_paths:
    if path.exists():
        print(f"  ✅ {name}")
    else:
        print(f"  ❌ {name} - не найден по пути: {path}")

print("\n🔄 ПОПЫТКА ИМПОРТА...")

# Пробуем несколько способов импорта
try:
    # Способ 1: Обычный импорт
    print("1. Обычный импорт: from src.bot.bot_core import SQLBot")
    from src.bot.bot_core import SQLBot
    print("   ✅ Успешно!")
except ImportError as e:
    print(f"   ❌ Ошибка: {e}")
    
    try:
        # Способ 2: Прямой импорт из src
        print("\n2. Прямой импорт: from bot.bot_core import SQLBot")
        # Временно добавляем src в путь
        import sys
        sys.path.insert(0, str(current_dir / "src"))
        from bot.bot_core import SQLBot
        print("   ✅ Успешно!")
    except ImportError as e2:
        print(f"   ❌ Ошибка: {e2}")
        
        try:
            # Способ 3: Абсолютный импорт
            print("\n3. Абсолютный импорт")
            import importlib.util
            
            spec = importlib.util.spec_from_file_location(
                "bot_core", 
                str(current_dir / "src" / "bot" / "bot_core.py")
            )
            bot_core_module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(bot_core_module)
            SQLBot = bot_core_module.SQLBot
            print("   ✅ Успешно через importlib!")
        except Exception as e3:
            print(f"   ❌ Ошибка: {e3}")
            print("\n⚠️  КРИТИЧЕСКАЯ ОШИБКА - файл bot_core.py не может быть загружен")
            sys.exit(1)

# Аналогично для других модулей
try:
    from src.utils.logger import setup_logging
    print("✅ logger импортирован")
except ImportError:
    # Создаем простой logger
    import logging
    def setup_logging(name, log_dir=None):
        logger = logging.getLogger(name)
        logger.setLevel(logging.INFO)
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
        logger.addHandler(handler)
        return logger
    print("⚠️  Использую упрощенный logger")

try:
    import config
    print("✅ config импортирован")
except ImportError:
    print("❌ config не найден, создаю минимальный...")
    
    # Минимальный config
    import os
    from pathlib import Path
    
    class Config:
        TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
        LLM_ENABLED = True
        LLM_PROVIDER = "ollama"
        OLLAMA_MODEL = "mistral"
        OLLAMA_BASE_URL = "http://localhost:11434"
        PROJECT_ROOT = Path(__file__).parent
        STORAGE_DIR = PROJECT_ROOT / "storage"
        STORAGE_DIR.mkdir(exist_ok=True)
        DATABASE_URL = "sqlite:///./test.db"
        
        @property
        def CACHE_FILE(self):
            return self.STORAGE_DIR / "cache.json"
        
        @property
        def PATTERNS_FILE(self):
            return self.STORAGE_DIR / "patterns.json"
    
    class config:
        config = Config()
    
    print("✅ config создан")

logger = setup_logging(__name__, config.config.STORAGE_DIR)

print("\n" + "="*60)
print("🚀 ЗАПУСК БОТА")
print("="*60)

class Application:
    def __init__(self):
        self.bot = None
    
    async def start(self):
        try:
            print("🤖 Создаю экземпляр бота...")
            self.bot = SQLBot(config.config)
            
            print("🔄 Инициализирую бота...")
            await self.bot.initialize()
            
            print("✅ Бот инициализирован!")
            print("🎉 Запускаю поллинг...")
            
            await self.bot.start()
            
        except Exception as e:
            print(f"❌ Ошибка запуска: {e}")
            import traceback
            traceback.print_exc()
    
    async def stop(self):
        if self.bot:
            await self.bot.stop()
        print("👋 Бот остановлен")

async def main():
    app = Application()
    try:
        await app.start()
    except KeyboardInterrupt:
        print("\n🛑 Остановлено пользователем")
    finally:
        await app.stop()

if __name__ == "__main__":
    # Для Python 3.13+ используем uvloop если доступен
    try:
        import uvloop
        uvloop.install()
        print("✅ Используется uvloop для лучшей производительности")
    except ImportError:
        print("⚠️  uvloop не установлен, используем стандартный asyncio")
    
    # Запуск приложения
    asyncio.run(main())