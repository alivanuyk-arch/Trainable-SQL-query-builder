"""
Простой запуск бота
"""
import logging
from config import config

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def main():
    print("=" * 60)
    print("🚀 Запуск Trainable SQL Query Builder")
    print("=" * 60)
    
    try:
        from src.bot.bot_core import run_bot
        
        logger.info(f"Запуск бота с токеном: ***{config.TELEGRAM_TOKEN[-5:]}")
        run_bot(config.TELEGRAM_TOKEN)  # Синхронный вызов
        
    except KeyboardInterrupt:
        print("\n✅ Бот остановлен пользователем")
    except Exception as e:
        print(f"\n❌ Ошибка запуска бота: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()  # Без asyncio.run()