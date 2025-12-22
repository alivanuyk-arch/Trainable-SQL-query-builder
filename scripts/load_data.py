#!/usr/bin/env python3
"""
Загрузка данных из JSON в PostgreSQL
"""
import sys
import os
import json
import asyncio
import asyncpg
import uuid
from pathlib import Path
from datetime import datetime

# Добавляем путь к проекту
sys.path.append(str(Path(__file__).parent.parent))

# Импортируем конфиг из .env
from dotenv import load_dotenv

# Загружаем .env
env_path = Path(__file__).parent.parent / '.env'
load_dotenv(env_path)

# Параметры подключения из .env
DB_CONFIG = {
    'host': os.getenv('DB_HOST', 'localhost'),
    'port': os.getenv('DB_PORT', '5432'),
    'user': os.getenv('DB_USER', 'postgres'),
    'password': os.getenv('DB_PASSWORD', 'postgres123'),
    'database': os.getenv('DB_NAME', 'video_analytics')
}

def parse_datetime(date_str):
    """Парсит строку даты в datetime"""
    if not date_str:
        return None
    
    # Убираем Z и приводим к стандартному формату
    date_str = date_str.replace('Z', '+00:00')
    
    try:
        return datetime.fromisoformat(date_str)
    except ValueError:
        # Пробуем другие форматы
        try:
            return datetime.strptime(date_str, '%Y-%m-%d %H:%M:%S')
        except ValueError:
            return datetime.strptime(date_str, '%Y-%m-%d')

async def load_json_data(json_filepath: str):
    """Загружает данные из JSON в базу"""
    
    # Проверяем файл
    json_path = Path(json_filepath)
    if not json_path.exists():
        print(f"❌ Файл {json_path} не найден!")
        return
    
    print(f"📂 Загрузка данных из {json_path}")
    
    try:
        # Подключаемся к БД
        conn = await asyncpg.connect(**DB_CONFIG)
        print(f"✅ Подключено к базе {DB_CONFIG['database']}")
        
        # Читаем JSON
        with open(json_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        # Поддерживаем две структуры
        if isinstance(data, dict) and "videos" in data:
            videos_list = data["videos"]
            print(f"📁 Найдено {len(videos_list)} видео в ключе 'videos'")
        elif isinstance(data, list):
            videos_list = data
            print(f"📁 Найдено {len(videos_list)} видео в списке")
        else:
            print("❌ Неизвестный формат JSON")
            return
        
        if not videos_list:
            print("⚠️ Нет данных для загрузки")
            return
        
        video_records = []
        snapshot_records = []
        
        # Обрабатываем видео
        for video in videos_list:
            # ID видео
            try:
                video_id = uuid.UUID(video['id']) if 'id' in video else uuid.uuid4()
            except (ValueError, KeyError):
                video_id = uuid.uuid4()
            
            # Даты
            video_created_at = parse_datetime(video.get('video_created_at'))
            created_at = parse_datetime(video.get('created_at')) or datetime.now()
            updated_at = parse_datetime(video.get('updated_at')) or datetime.now()
            
            # Собираем запись видео
            video_records.append((
                str(video_id),
                video.get('creator_id', 'unknown'),
                video_created_at,
                video.get('views_count', 0),
                video.get('likes_count', 0),
                video.get('comments_count', 0),
                video.get('reports_count', 0),
                created_at,
                updated_at
            ))
            
            # Обрабатываем снапшоты если есть
            for snapshot in video.get('snapshots', []):
                snapshot_id = snapshot.get('id', str(uuid.uuid4()))
                snapshot_created_at = parse_datetime(snapshot.get('created_at')) or datetime.now()
                snapshot_updated_at = parse_datetime(snapshot.get('updated_at')) or datetime.now()
                
                snapshot_records.append((
                    str(snapshot_id),
                    str(video_id),
                    snapshot.get('views_count', 0),
                    snapshot.get('likes_count', 0),
                    snapshot.get('comments_count', 0),
                    snapshot.get('reports_count', 0),
                    snapshot.get('delta_views_count', 0),
                    snapshot.get('delta_likes_count', 0),
                    snapshot.get('delta_comments_count', 0),
                    snapshot.get('delta_reports_count', 0),
                    snapshot_created_at,
                    snapshot_updated_at
                ))
        
        print(f"📊 Подготовлено {len(video_records)} видео")
        print(f"📈 Подготовлено {len(snapshot_records)} снапшотов")
        
        # SQL запросы
        video_insert_sql = """
        INSERT INTO videos 
        (id, creator_id, video_created_at, views_count, likes_count, 
         comments_count, reports_count, created_at, updated_at)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
        ON CONFLICT (id) DO NOTHING
        """
        
        snapshot_insert_sql = """
        INSERT INTO video_snapshots 
        (id, video_id, views_count, likes_count, comments_count, reports_count,
         delta_views_count, delta_likes_count, delta_comments_count, delta_reports_count,
         created_at, updated_at)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)
        ON CONFLICT (id) DO NOTHING
        """
        
        # Вставка видео
        print("\n📥 Загружаю видео в БД...")
        batch_size = 100
        total_videos = 0
        
        for i in range(0, len(video_records), batch_size):
            batch = video_records[i:i + batch_size]
            await conn.executemany(video_insert_sql, batch)
            total_videos += len(batch)
            print(f"  Видео: {min(i + batch_size, len(video_records))}/{len(video_records)}")
        
        # Вставка снапшотов
        print("\n📥 Загружаю снапшоты в БД...")
        total_snapshots = 0
        
        for i in range(0, len(snapshot_records), batch_size):
            batch = snapshot_records[i:i + batch_size]
            await conn.executemany(snapshot_insert_sql, batch)
            total_snapshots += len(batch)
            print(f"  Снапшоты: {min(i + batch_size, len(snapshot_records))}/{len(snapshot_records)}")
        
        print(f"\n✅ Загрузка завершена!")
        print(f"📊 Видео загружено: {total_videos}")
        print(f"📈 Снапшотов загружено: {total_snapshots}")
        
        # Проверяем
        videos_count = await conn.fetchval("SELECT COUNT(*) FROM videos")
        snapshots_count = await conn.fetchval("SELECT COUNT(*) FROM video_snapshots")
        
        print(f"🔍 Проверка: в базе {videos_count} видео и {snapshots_count} снапшотов")
        
        await conn.close()
        
    except Exception as e:
        print(f"❌ Ошибка загрузки: {e}")
        import traceback
        traceback.print_exc()

async def load_test_data():
    """Загружает тестовые данные если нет JSON"""
    print("📝 Создаю тестовые данные...")
    
    try:
        conn = await asyncpg.connect(**DB_CONFIG)
        
        # Тестовое видео
        await conn.execute("""
            INSERT INTO videos 
            (id, creator_id, video_created_at, views_count, likes_count, comments_count)
            VALUES 
            ('550e8400-e29b-41d4-a716-446655440000', 'creator_123', '2025-11-01 10:00:00', 15000, 450, 120),
            ('550e8400-e29b-41d4-a716-446655440001', 'creator_456', '2025-11-15 14:30:00', 89000, 3200, 890)
            ON CONFLICT (id) DO NOTHING
        """)
        
        # Тестовые снапшоты
        await conn.execute("""
            INSERT INTO video_snapshots 
            (id, video_id, views_count, likes_count, comments_count, delta_views_count, created_at)
            VALUES 
            ('550e8400-e29b-41d4-a716-446655440010', '550e8400-e29b-41d4-a716-446655440000', 15000, 450, 120, 500, '2025-11-01 12:00:00'),
            ('550e8400-e29b-41d4-a716-446655440011', '550e8400-e29b-41d4-a716-446655440001', 89000, 3200, 890, 2500, '2025-11-15 16:00:00')
            ON CONFLICT (id) DO NOTHING
        """)
        
        print("✅ Тестовые данные созданы")
        await conn.close()
        
    except Exception as e:
        print(f"❌ Ошибка: {e}")

async def main():
    """Основная функция"""
    print("="*60)
    print("📤 ЗАГРУЗКА ДАННЫХ В POSTGRESQL")
    print("="*60)
    
    if len(sys.argv) == 2:
        # Загрузка из JSON файла
        json_file = sys.argv[1]
        await load_json_data(json_file)
    else:
        # Создание тестовых данных
        print("ℹ️  Использование: python scripts/load_data.py <путь_к_json>")
        print("📝 Или создаю тестовые данные...")
        
        answer = input("Создать тестовые данные? (y/n): ").lower()
        if answer == 'y':
            await load_test_data()
        else:
            print("❌ Не указан файл JSON")

if __name__ == "__main__":
    asyncio.run(main())