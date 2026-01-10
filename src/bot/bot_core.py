"""
Только Telegram API - старая версия для Python 3.13
"""
import logging
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters

logger = logging.getLogger(__name__)

def run_bot(token: str):
    """Запуск Telegram бота (синхронная обертка)"""
    app = Application.builder().token(token).build()
    
    from src.bot import handlers
    
    app.add_handler(CommandHandler("start", handlers.start_command))
    app.add_handler(CommandHandler("help", handlers.help_command))
    app.add_handler(CommandHandler("stats", handlers.stats_command))
    app.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND,
        handlers.handle_user_query
    ))
    app.add_handler(CallbackQueryHandler(handlers.handle_callback_query))
    
    logger.info("🚀 Запуск polling...")
    app.run_polling()  # Синхронный вызов