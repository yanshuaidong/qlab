from __future__ import annotations

import argparse
import sqlite3
from datetime import datetime
from pathlib import Path


DEFAULT_DB_PATH = Path(__file__).with_name("data") / "stock.sqlite"
DEFAULT_OUTPUT_TABLE = "stock_limit_up_candidates_120"


def quote_identifier(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def build_limit_up_candidates(
    db_path: Path,
    output_table: str,
    recent_days: int,
    window_index: int,
    window_size: int,
    min_pct: float,
    max_pct: float,
    adjust: str,
) -> int:
    now = datetime.now().isoformat(timespec="seconds")
    table_sql = quote_identifier(output_table)
    if window_index < 1:
        raise ValueError("--window-index must be >= 1")
    if window_size < 1:
        raise ValueError("--window-size must be >= 1")
    window_start_rank = (window_index - 1) * window_size + 1
    window_end_rank = window_index * window_size
    if window_end_rank > recent_days:
        raise ValueError("--window-index * --window-size must be <= --recent-days")

    with sqlite3.connect(db_path) as conn:
        conn.execute(f"DROP TABLE IF EXISTS {table_sql}")
        conn.execute(
            f"""
            CREATE TABLE {table_sql} (
                exchange TEXT NOT NULL,
                code TEXT NOT NULL,
                name TEXT,
                board TEXT,
                security_type TEXT,
                limit_up_count_120 INTEGER NOT NULL,
                first_limit_up_date TEXT NOT NULL,
                last_limit_up_date TEXT NOT NULL,
                max_pct_change REAL NOT NULL,
                min_pct_change REAL NOT NULL,
                hit_dates TEXT NOT NULL,
                recent_days INTEGER NOT NULL,
                window_index INTEGER NOT NULL,
                window_size INTEGER NOT NULL,
                window_start_rank INTEGER NOT NULL,
                window_end_rank INTEGER NOT NULL,
                min_pct REAL NOT NULL,
                max_pct REAL NOT NULL,
                adjust TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (exchange, code)
            )
            """
        )
        conn.execute(
            f"""
            INSERT INTO {table_sql} (
                exchange,
                code,
                name,
                board,
                security_type,
                limit_up_count_120,
                first_limit_up_date,
                last_limit_up_date,
                max_pct_change,
                min_pct_change,
                hit_dates,
                recent_days,
                window_index,
                window_size,
                window_start_rank,
                window_end_rank,
                min_pct,
                max_pct,
                adjust,
                updated_at
            )
            WITH daily_with_calc AS (
                SELECT
                    d.exchange,
                    d.stock_code AS code,
                    d.stock_name AS name,
                    d.trade_date,
                    d.close,
                    d.pct_change,
                    d.adjust,
                    LAG(d.close) OVER (
                        PARTITION BY d.exchange, d.stock_code, d.adjust
                        ORDER BY d.trade_date
                    ) AS prev_close,
                    ROW_NUMBER() OVER (
                        PARTITION BY d.exchange, d.stock_code, d.adjust
                        ORDER BY d.trade_date DESC
                    ) AS recent_rank
                FROM stock_daily d
                WHERE d.adjust = ?
            ),
            scored AS (
                SELECT
                    exchange,
                    code,
                    name,
                    trade_date,
                    close,
                    prev_close,
                    pct_change,
                    CASE
                        WHEN pct_change IS NOT NULL THEN pct_change
                        WHEN prev_close IS NOT NULL AND prev_close != 0
                            THEN ROUND((close - prev_close) * 100.0 / prev_close, 4)
                        ELSE NULL
                    END AS effective_pct_change,
                    CASE
                        WHEN pct_change IS NOT NULL THEN 'pct_change'
                        WHEN prev_close IS NOT NULL AND prev_close != 0 THEN 'calculated'
                        ELSE 'missing'
                    END AS pct_change_source,
                    recent_rank
                FROM daily_with_calc
                WHERE recent_rank BETWEEN ? AND ?
            ),
            hits AS (
                SELECT *
                FROM scored
                WHERE effective_pct_change BETWEEN ? AND ?
            )
            SELECT
                h.exchange,
                h.code,
                COALESCE(MAX(sbi.name), MAX(h.name), '') AS name,
                MAX(sbi.board) AS board,
                MAX(sbi.security_type) AS security_type,
                COUNT(*) AS limit_up_count_120,
                MIN(h.trade_date) AS first_limit_up_date,
                MAX(h.trade_date) AS last_limit_up_date,
                ROUND(MAX(h.effective_pct_change), 4) AS max_pct_change,
                ROUND(MIN(h.effective_pct_change), 4) AS min_pct_change,
                GROUP_CONCAT(
                    h.trade_date || ':' || ROUND(h.effective_pct_change, 2),
                    ','
                ) AS hit_dates,
                ? AS recent_days,
                ? AS window_index,
                ? AS window_size,
                ? AS window_start_rank,
                ? AS window_end_rank,
                ? AS min_pct,
                ? AS max_pct,
                ? AS adjust,
                ? AS updated_at
            FROM hits h
            LEFT JOIN stock_basic_info sbi
                ON sbi.exchange = h.exchange
               AND sbi.code = h.code
            GROUP BY h.exchange, h.code
            ORDER BY last_limit_up_date DESC, limit_up_count_120 DESC, h.exchange, h.code
            """,
            (
                adjust,
                window_start_rank,
                window_end_rank,
                min_pct,
                max_pct,
                recent_days,
                window_index,
                window_size,
                window_start_rank,
                window_end_rank,
                min_pct,
                max_pct,
                adjust,
                now,
            ),
        )
        conn.execute(
            f"""
            CREATE INDEX idx_{output_table}_last_limit_up_date
            ON {table_sql} (last_limit_up_date)
            """
        )
        count = conn.execute(f"SELECT COUNT(*) FROM {table_sql}").fetchone()[0]
        conn.commit()
        return int(count)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build a local stock pool that had near-10% limit-up moves in recent daily rows."
    )
    parser.add_argument(
        "--db",
        type=Path,
        default=DEFAULT_DB_PATH,
        help=f"SQLite database path. Default: {DEFAULT_DB_PATH}",
    )
    parser.add_argument(
        "--output-table",
        default=DEFAULT_OUTPUT_TABLE,
        help=f"Output table name. Default: {DEFAULT_OUTPUT_TABLE}",
    )
    parser.add_argument(
        "--recent-days",
        type=int,
        default=120,
        help="Latest N daily rows per stock to scan.",
    )
    parser.add_argument(
        "--window-index",
        type=int,
        default=3,
        help=(
            "Which window to scan after splitting recent rows by --window-size. "
            "Default 3 means ranks 61..90 when --window-size is 30."
        ),
    )
    parser.add_argument(
        "--window-size",
        type=int,
        default=30,
        help="Trading rows per split window. Default: 30.",
    )
    parser.add_argument(
        "--min-pct",
        type=float,
        default=9.9,
        help="Minimum effective pct_change counted as limit-up.",
    )
    parser.add_argument(
        "--max-pct",
        type=float,
        default=10.1,
        help="Maximum effective pct_change counted as limit-up.",
    )
    parser.add_argument(
        "--adjust",
        default="",
        help="stock_daily.adjust value to scan. Default: empty string.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    count = build_limit_up_candidates(
        db_path=args.db,
        output_table=args.output_table,
        recent_days=args.recent_days,
        window_index=args.window_index,
        window_size=args.window_size,
        min_pct=args.min_pct,
        max_pct=args.max_pct,
        adjust=args.adjust,
    )
    print(
        f"Built {args.output_table} with {count} stocks "
        f"from {args.db} "
        f"(window {args.window_index} x {args.window_size}, "
        f"{args.min_pct}..{args.max_pct}%)."
    )


if __name__ == "__main__":
    main()
