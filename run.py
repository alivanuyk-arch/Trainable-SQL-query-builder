import sys
import asyncio
from pathlib import Path

# КРИТИЧЕСКИ ВАЖНО для Python 3.13
import nest_asyncio
nest_asyncio.apply()
print("✅ Применен nest_asyncio для Python 3.13")

# Добавляем пути
current_dir = Path(__file__).parent
sys.path.insert(0, str(current_dir))
sys.path.insert(0, str(current_dir / "src"))

print("="*60)
print("🚀 ЗАПУСК SQL QUERY BUILDER (Python 3.13 Fix)")
print("="*60)

async def main():
    try:
        # Импортируем модули
        from src.bot.bot_core import SQLBot
        import config
        
        print("🤖 Создаю бота...")
        bot = SQLBot(config.config)
        
        print("🔄 Инициализирую...")
        await bot.initialize()
        
        print("✅ Бот готов!")
        print("📱 Откройте Telegram и найдите вашего бота")
        print("💬 Напишите /start для начала")
        print("="*60)
        
        # Запускаем бота напрямую
        from telegram.ext import Application
        app = bot.application
        
        # Запускаем поллинг с правильными параметрами
        await app.run_polling(
            allowed_updates=None,
            drop_pending_updates=True,
            close_loop=False  # ВАЖНО: не закрывать loop!
        )
        
    except KeyboardInterrupt:
        print("\n🛑 Остановлено пользователем")
    except Exception as e:
        print(f"\n❌ Ошибка: {e}")
        import traceback
        traceback.print_exc()
    finally:
        print("\n👋 Завершение работы")

if __name__ == "__main__":
    # Просто запускаем
    asyncio.run(main())