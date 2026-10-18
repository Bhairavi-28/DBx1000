import sqlite3
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = APP_DIR / "data"
DB_PATH = DATA_DIR / "experiments.db"

DATA_DIR.mkdir(parents=True, exist_ok=True)

def get_connection():
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def initialise_database():
    with get_connection() as connection:
        connection.executescript("""
            CREATE TABLE IF NOT EXISTS experiments (
                run_id TEXT PRIMARY KEY,
                timestamp TEXT NOT NULL,
                workload TEXT,
                algorithm TEXT,
                index_type TEXT,
                thread_count INTEGER NOT NULL,
                status TEXT NOT NULL,
                exit_code INTEGER,
                git_commit TEXT
            );

            CREATE TABLE IF NOT EXISTS metrics (
                metric_id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL,
                transaction_count INTEGER,
                abort_count INTEGER,
                runtime_seconds REAL,
                throughput REAL,
                cpu_percent REAL,
                memory_mb REAL,
                FOREIGN KEY (run_id)
                    REFERENCES experiments(run_id)
                    ON DELETE CASCADE
            );
        """)