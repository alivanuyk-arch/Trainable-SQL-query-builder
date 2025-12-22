import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, MessageHandler, filters

logger = logging.getLogger(__name__)

async def handle_correction(update: Update, context: ContextTypes.DEFAULT_TYPE, bot_instance):
    """Обработка исправленного SQL от пользователя"""
    user_id = update.effective_user.id
    
    if user_id not in bot_instance.sessions:
        return
    
    session = bot_instance.sessions[user_id]
    
    if not session.waiting_for_correction:
        return
    
    user_sql = update.message.text.strip()
    
    # Проверяем на команду отмены
    if user_sql.lower() in ['/cancel', 'отмена', 'cancel']:
        session.waiting_for_correction = False
        await update.message.reply_text("❌ Редактирование отменено")
        return
    
    # Проверяем, что это похоже на SQL
    if not (user_sql.upper().startswith('SELECT') or user_sql.upper().startswith('WITH')):
        await update.message.reply_text(
            "⚠️ Это не похоже на SQL запрос. SQL должен начинаться с SELECT или WITH.\n"
            "Попробуйте еще раз или отправьте /cancel для отмены."
        )
        return
    
    # Сохраняем исправление
    session.waiting_for_correction = False
    session.current_sql = user_sql
    
    # Учимся на исправлении
    await bot_instance.constructor.learn_from_correction(
        original_query=session.current_query,
        llm_sql=session.current_sql,  # Здесь должна быть оригинальная версия LLM
        corrected_sql=user_sql,
        user_feedback="manual_correction"
    )
    
    bot_instance.stats['corrections'] += 1
    
    # Спрашиваем подтверждение
    keyboard = [
        [
            InlineKeyboardButton("✅ Выполнить исправленный", callback_data="confirm_yes"),
            InlineKeyboardButton("↩️ Вернуться к исходному", callback_data="revert_original")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        f"✅ Исправление сохранено для обучения!\n\n"
        f"```sql\n{user_sql}\n```\n\n"
        f"Выберите действие:",
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )

async def handle_rephrasing(update: Update, context: ContextTypes.DEFAULT_TYPE, bot_instance):
    """Обработка перефразированного вопроса"""
    user_id = update.effective_user.id
    
    if user_id not in bot_instance.sessions:
        return
    
    session = bot_instance.sessions[user_id]
    
    # Обрабатываем как обычный запрос
    await bot_instance.handle_message(update, context)