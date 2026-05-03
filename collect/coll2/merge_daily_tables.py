from __future__ import annotations

import argparse
import sqlite3
import time
from pathlib import Path


DEFAULT_DB_PATH = Path(__file__).with_name("data") / "stock.sqlite"
TARGET_TABLE = "stock_daily"


def quote_identifier(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def create_stock_daily_table(conn: sqlite3.Connection, target_table: str) -> None:
    conn.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {quote_identifier(target_table)} (
            exchange TEXT NOT NULL,
            stock_code TEXT NOT NULL,
            stock_name TEXT,
            trade_date TEXT NOT NULL,
            open REAL,
            close REAL,
            high REAL,
            low REAL,
            volume INTEGER,
            amount REAL,
            amplitude REAL,
            pct_change REAL,
            change_amount REAL,
            turnover_rate REAL,
            adjust TEXT NOT NULL,
            source TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (exchange, stock_code, adjust, trade_date)
        )
        """
    )


def create_stock_daily_indexes(conn: sqlite3.Connection, target_table: str) -> None:
    conn.execute(
        f"""
        CREATE INDEX IF NOT EXISTS idx_{target_table}_trade_date
        ON {quote_identifier(target_table)} (trade_date)
        """
    )
    conn.execute(
        f"""
        CREATE INDEX IF NOT EXISTS idx_{target_table}_code_date
        ON {quote_identifier(target_table)} (stock_code, trade_date)
        """
    )
    conn.execute(
        f"""
        CREATE INDEX IF NOT EXISTS idx_{target_table}_exchange_code_date
        ON {quote_identifier(target_table)} (exchange, stock_code, trade_date)
        """
    )


def table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    row = conn.execute(
        """
        SELECT 1
        FROM sqlite_master
        WHERE type = 'table' AND name = ?
        """,
        (table_name,),
    ).fetchone()
    return row is not None


def table_row_count(conn: sqlite3.Connection, table_name: str) -> int:
    return int(
        conn.execute(f"SELECT COUNT(*) FROM {quote_identifier(table_name)}").fetchone()[0]
    )


def list_source_tables(conn: sqlite3.Connection, target_table: str) -> list[str]:
    rows = conn.execute(
        """
        SELECT name
        FROM sqlite_master
        WHERE type = 'table'
          AND name LIKE 'daily_%'
          AND name <> ?
        ORDER BY name
        """,
        (target_table,),
    ).fetchall()
    return [str(row[0]) for row in rows]


def drop_existing_target(conn: sqlite3.Connection, target_table: str) -> None:
    conn.execute(f"DROP TABLE IF EXISTS {quote_identifier(target_table)}")


def merge_one_table(conn: sqlite3.Connection, source_table: str, target_table: str) -> int:
    before = table_row_count(conn, target_table)
    conn.execute(
        f"""
        INSERT INTO {quote_identifier(target_table)} (
            exchange, stock_code, stock_name, trade_date, open, close, high, low,
            volume, amount, amplitude, pct_change, change_amount, turnover_rate,
            adjust, source, updated_at
        )
        SELECT
            exchange, stock_code, stock_name, trade_date, open, close, high, low,
            volume, amount, amplitude, pct_change, change_amount, turnover_rate,
            adjust, source, updated_at
        FROM {quote_identifier(source_table)}
        WHERE 1 = 1
        ON CONFLICT(exchange, stock_code, adjust, trade_date) DO UPDATE SET
            stock_name = excluded.stock_name,
            open = excluded.open,
            close = excluded.close,
            high = excluded.high,
            low = excluded.low,
            volume = excluded.volume,
            amount = excluded.amount,
            amplitude = excluded.amplitude,
            pct_change = excluded.pct_change,
            change_amount = excluded.change_amount,
            turnover_rate = excluded.turnover_rate,
            source = excluded.source,
            updated_at = excluded.updated_at
        """
    )
    after = table_row_count(conn, target_table)
    return after - before


def sum_source_rows(conn: sqlite3.Connection, source_tables: list[str]) -> int:
    total = 0
    for index, table_name in enumerate(source_tables, start=1):
        total += table_row_count(conn, table_name)
        if index % 500 == 0:
            print(f"[count] {index}/{len(source_tables)} tables, rows={total}", flush=True)
    return total


def drop_source_tables(conn: sqlite3.Connection, source_tables: list[str]) -> None:
    for index, table_name in enumerate(source_tables, start=1):
        conn.execute(f"DROP TABLE {quote_identifier(table_name)}")
        if index % 500 == 0:
            print(f"[drop] {index}/{len(source_tables)} tables dropped", flush=True)


def migrate(
    db_path: Path,
    target_table: str,
    replace_target: bool,
    drop_sources: bool,
    vacuum: bool,
) -> None:
    if not db_path.is_file():
        raise FileNotFoundError(f"Database not found: {db_path}")

    started = time.perf_counter()
    with sqlite3.connect(db_path) as conn:
        conn.execute("PRAGMA foreign_keys = OFF")
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = NORMAL")

        if table_exists(conn, target_table):
            existing_rows = table_row_count(conn, target_table)
            if existing_rows and not replace_target:
                raise RuntimeError(
                    f"{target_table} already exists with {existing_rows} rows. "
                    "Use --replace-target to rebuild it."
                )
            if replace_target:
                print(f"[prepare] drop existing {target_table}", flush=True)
                drop_existing_target(conn, target_table)

        source_tables = list_source_tables(conn, target_table)
        if not source_tables:
            print("[done] no daily_* source tables found", flush=True)
            return

        print(f"[prepare] source tables: {len(source_tables)}", flush=True)
        create_stock_daily_table(conn, target_table)
        conn.commit()

        source_total = sum_source_rows(conn, source_tables)
        print(f"[merge] source rows: {source_total}", flush=True)

        conn.execute("BEGIN")
        merged_new_rows = 0
        for index, table_name in enumerate(source_tables, start=1):
            merged_new_rows += merge_one_table(conn, table_name, target_table)
            if index % 500 == 0:
                print(
                    f"[merge] {index}/{len(source_tables)} tables, "
                    f"new rows={merged_new_rows}",
                    flush=True,
                )

        target_rows = table_row_count(conn, target_table)
        if target_rows != source_total:
            conn.rollback()
            raise RuntimeError(
                f"Validation failed: {target_table} rows={target_rows}, "
                f"source rows={source_total}. Nothing was dropped."
            )

        print(f"[validate] {target_table} rows={target_rows}", flush=True)
        create_stock_daily_indexes(conn, target_table)

        if drop_sources:
            drop_source_tables(conn, source_tables)
            print(f"[drop] all {len(source_tables)} source tables dropped", flush=True)

        conn.commit()

        if vacuum:
            print("[vacuum] rebuilding database file; this can take a while", flush=True)
            conn.execute("VACUUM")

    elapsed = time.perf_counter() - started
    print(f"[done] elapsed={elapsed:.1f}s db={db_path}", flush=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Merge per-stock daily_* SQLite tables into one stock_daily table."
    )
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument("--target-table", default=TARGET_TABLE)
    parser.add_argument(
        "--replace-target",
        action="store_true",
        help="Drop and rebuild the target table if it already exists.",
    )
    parser.add_argument(
        "--keep-source-tables",
        action="store_true",
        help="Merge and validate, but do not drop the old daily_* tables.",
    )
    parser.add_argument(
        "--vacuum",
        action="store_true",
        help="Compact the database after dropping source tables.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    migrate(
        db_path=args.db,
        target_table=args.target_table,
        replace_target=args.replace_target,
        drop_sources=not args.keep_source_tables,
        vacuum=args.vacuum,
    )


if __name__ == "__main__":
    main()
