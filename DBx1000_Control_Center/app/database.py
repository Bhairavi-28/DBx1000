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

def save_experiment(row):
    initialise_database()

    with get_connection() as connection:
        connection.execute("""
            INSERT OR REPLACE INTO experiments (
                run_id, timestamp, workload, algorithm,
                index_type, thread_count, status,
                exit_code, git_commit
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            row["run_id"],
            row["timestamp_utc"],
            row["workload"],
            row["cc_alg"],
            row["index_struct"],
            int(row["threads"]),
            row["status"],
            row["exit_code"],
            row["git_commit"],
        ))

        connection.execute("""
            INSERT INTO metrics (
                run_id, transaction_count, abort_count,
                runtime_seconds, throughput,
                cpu_percent, memory_mb
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            row["run_id"],
            row["completed_txns"],
            row["aborts"],
            row["reported_runtime_seconds"],
            row["throughput_txn_s"],
            row["cpu_percent_mean"],
            row["rss_mb_peak"],
        ))


def run_query(sql):
    sql = sql.strip()
    if not sql:
        raise ValueError("Enter a SQL query.")

    
    sql = sql.rstrip(";").strip()
    if ";" in sql:
        raise ValueError("Execute one query at a time.")
    initialise_database()
    with get_connection() as connection:
        # SQLite itself enforces read-only query behaviour.
        def authorise(action, arg1, arg2, database_name, trigger_name):
            allowed_actions = {
                sqlite3.SQLITE_SELECT,
                sqlite3.SQLITE_READ,
                sqlite3.SQLITE_FUNCTION,
                sqlite3.SQLITE_RECURSIVE,
            }
            if action in allowed_actions:
                return sqlite3.SQLITE_OK
            return sqlite3.SQLITE_DENY

        connection.set_authorizer(authorise)
        cursor = connection.execute(sql)

        if cursor.description is None:
            raise ValueError("The query did not return a result set.")
        return [dict(row) for row in cursor.fetchall()]