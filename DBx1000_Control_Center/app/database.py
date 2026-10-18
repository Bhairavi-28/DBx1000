import sqlite3
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = APP_DIR / "data"
DB_PATH = DATA_DIR / "experiments.db"

DATA_DIR.mkdir(parents=True, exist_ok=True)