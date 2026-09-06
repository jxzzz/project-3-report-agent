import sqlite3
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = PROJECT_ROOT / "support.db"


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only = ON;")
    return conn


def schema_text() -> str:
    conn = get_connection()
    try:
        rows = conn.execute(
            """
            SELECT sql FROM sqlite_master
            WHERE type = 'table' AND name NOT LIKE 'sqlite_%'
            ORDER BY name
            """
        ).fetchall()
        return "\n\n".join(row["sql"] for row in rows)
    finally:
        conn.close()


def execute_select(sql: str, params: tuple = ()) -> dict:
    statement = sql.strip()

    if not statement.upper().startswith("SELECT"):
        return {"error": "只允许 SELECT 查询"}

    if ";" in statement:
        return {"error": "只允许单条 SQL，不能包含分号"}

    conn = get_connection()
    try:
        cursor = conn.execute(statement, params)
        rows = [dict(row) for row in cursor.fetchall()]
        columns = (
            [item[0] for item in cursor.description]
            if cursor.description
            else []
        )

        return {
            "sql": statement,
            "columns": columns,
            "row_count": len(rows),
            "rows": rows,
        }
    except sqlite3.Error as exc:
        return {"error": f"SQL 执行失败：{exc}"}
    finally:
        conn.close()