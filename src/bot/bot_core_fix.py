"""
Автоматический рефакторинг bot_core.py
"""
import os
from pathlib import Path

def create_structure():
    """Создает структуру проекта"""
    base = Path("src/bot")
    
    # Создаем папки
    folders = ["handlers", "utils", "templates"]
    for folder in folders:
        (base / folder).mkdir(exist_ok=True)
        (base / folder / "__init__.py").touch()
    
    # Создаем файлы
    files = [
        "sessions.py",
        "keyboards.py", 
        "formatters.py",
        "database.py",
        "schemas.py",
        "handlers/commands.py",
        "handlers/messages.py",
        "handlers/callbacks.py",
        "handlers/corrections.py",
        "utils/logger.py",
        "utils/validators.py",
        "utils/decorators.py"
    ]
    
    for file in files:
        (base / file).parent.mkdir(exist_ok=True, parents=True)
        (base / file).touch()
    
    print("✅ Структура создана")
    print("\n📁 Новая структура:")
    for root, dirs, files in os.walk(base):
        level = root.replace(str(base), '').count(os.sep)
        indent = ' ' * 2 * level
        print(f'{indent}{os.path.basename(root)}/')
        subindent = ' ' * 2 * (level + 1)
        for file in files:
            if file.endswith('.py'):
                print(f'{subindent}{file}')

if __name__ == "__main__":
    create_structure()
    print("\n🎯 Дальше:")
    print("1. Перенесите UserSession в sessions.py")
    print("2. Разделите handlers по файлам")
    print("3. Создайте core.py с основной логикой")