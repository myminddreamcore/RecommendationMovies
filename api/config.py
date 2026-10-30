
import os
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
except ImportError:
    pass

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+psycopg2://postgres:postgres@localhost:5432/movies_db")
# Как часто (сек) можно пересобирать рекомендательную модель после новых оценок
REFRESH_SECONDS = int(os.getenv("REFRESH_SECONDS", "300"))
