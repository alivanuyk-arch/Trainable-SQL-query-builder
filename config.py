import os
from pathlib import Path
from dotenv import load_dotenv

# Загрузка .env
env_path = Path(__file__).parent / '.env'
if env_path.exists():
    load_dotenv(env_path)

class Config:
    # Telegram
    TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
    
    # Database
    DB_HOST = os.getenv("DB_HOST", "localhost")
    DB_PORT = os.getenv("DB_PORT", "5432")
    DB_NAME = os.getenv("DB_NAME", "video_analytics")
    DB_USER = os.getenv("DB_USER", "postgres")
    DB_PASSWORD = os.getenv("DB_PASSWORD", "postgres")
    
    # LLM
    LLM_ENABLED = os.getenv("LLM_ENABLED", "true").lower() == "true"
    LLM_PROVIDER = os.getenv("LLM_PROVIDER", "ollama")  # ollama, openai
    OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "mistral:7b-instruct")
    OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
    OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-3.5-turbo")
    
    # Paths
    PROJECT_ROOT = Path(__file__).parent
    DATA_DIR = PROJECT_ROOT / "data"
    STORAGE_DIR = PROJECT_ROOT / "storage"
    
    # Files
    JSON_DATA_FILE = DATA_DIR / "videos.json"
    CACHE_FILE = STORAGE_DIR / "query_cache.json"
    PATTERNS_FILE = STORAGE_DIR / "learned_patterns.json"
    CORRECTIONS_FILE = STORAGE_DIR / "corrections_log.json"
    
    # Settings
    ENABLE_AUTO_SCHEMA_DETECTION = True
    ENABLE_SELF_LEARNING = True
    CACHE_TTL_HOURS = 24
    
    @property
    def DATABASE_URL(self):
        return f"postgresql://{self.DB_USER}:{self.DB_PASSWORD}@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"

config = Config()

# Создаем директории если их нет
config.DATA_DIR.mkdir(exist_ok=True)
config.STORAGE_DIR.mkdir(exist_ok=True)