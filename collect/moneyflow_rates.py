#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""给 moneyflow 补算净流入占比：净额(万元) × 1000 / daily.amount(千元)。"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB_PATH = REPO_ROOT / "storage" / "stock" / "data.sqlite"
SAMPLE_DATE = "2025-12-11"

RATE_COLUMNS = (
    "net_mf_amount_rate",
    "buy_elg_amount_rate",
    "buy_lg_amount_rate",
    "buy_md_amount_rate",
    "buy_sm_amount_rate",
)


def log(message: str) -> None:
    print(message, flush=True)


def to_ymd(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip().replace("-", "")
    if len(text) < 8 or not text[:8].isdigit():
        return None
    return f"{text[:4]}-{text[4:6]}-{text[6:8]}"


def ensure_rate_columns(conn: sqlite3.Connection) -> list[str]:
    existing = {
        row[1] for row in conn.execute("PRAGMA table_info(moneyflow)").fetchall()
    }
    added: list[str] = []
    for name in RATE_COLUMNS:
        if name in existing:
            continue
        conn.execute(f"ALTER TABLE moneyflow ADD COLUMN {name} REAL")
        added.append(name)
    return added


def refresh_moneyflow_rates(
    conn: sqlite3.Connection,
    start_date: str | None = None,
    end_date: str | None = None,
) -> int:
    start = to_ymd(start_date)
    end = to_ymd(end_date)
    clauses = ["m.ts_code = d.ts_code", "m.trade_date = d.trade_date"]
    params: list[str] = []
    if start:
        clauses.append("m.trade_date >= ?")
        params.append(start)
    if end:
        clauses.append("m.trade_date <= ?")
        params.append(end)
    where_sql = " AND ".join(clauses)
    sql = f"""
        UPDATE moneyflow AS m
        SET
            net_mf_amount_rate = CASE
                WHEN d.amount IS NULL OR d.amount = 0 THEN NULL
                ELSE ROUND(m.net_mf_amount * 1000.0 / d.amount, 2)
            END,
            buy_elg_amount_rate = CASE
                WHEN d.amount IS NULL OR d.amount = 0 THEN NULL
                ELSE ROUND(
                    (COALESCE(m.buy_elg_amount, 0) - COALESCE(m.sell_elg_amount, 0))
                    * 1000.0 / d.amount,
                    2
                )
            END,
            buy_lg_amount_rate = CASE
                WHEN d.amount IS NULL OR d.amount = 0 THEN NULL
                ELSE ROUND(
                    (COALESCE(m.buy_lg_amount, 0) - COALESCE(m.sell_lg_amount, 0))
                    * 1000.0 / d.amount,
                    2
                )
            END,
            buy_md_amount_rate = CASE
                WHEN d.amount IS NULL OR d.amount = 0 THEN NULL
                ELSE ROUND(
                    (COALESCE(m.buy_md_amount, 0) - COALESCE(m.sell_md_amount, 0))
                    * 1000.0 / d.amount,
                    2
                )
            END,
            buy_sm_amount_rate = CASE
                WHEN d.amount IS NULL OR d.amount = 0 THEN NULL
                ELSE ROUND(
                    (COALESCE(m.buy_sm_amount, 0) - COALESCE(m.sell_sm_amount, 0))
                    * 1000.0 / d.amount,
                    2
                )
            END
        FROM daily AS d
        WHERE {where_sql}
    """
    cursor = conn.execute(sql, params)
    return cursor.rowcount if cursor.rowcount is not None else 0


def summarize_rates(conn: sqlite3.Connection) -> dict[str, int]:
    row = conn.execute(
        """
        SELECT
            COUNT(*) AS mf_rows,
            SUM(CASE WHEN m.net_mf_amount_rate IS NOT NULL THEN 1 ELSE 0 END) AS filled,
            SUM(
                CASE
                    WHEN d.ts_code IS NULL OR d.amount IS NULL OR d.amount = 0 THEN 1
                    ELSE 0
                END
            ) AS skipped
        FROM moneyflow m
        LEFT JOIN daily d
          ON d.ts_code = m.ts_code AND d.trade_date = m.trade_date
        """
    ).fetchone()
    return {
        "mf_rows": int(row[0] or 0),
        "filled": int(row[1] or 0),
        "skipped": int(row[2] or 0),
    }


def print_sample(conn: sqlite3.Connection, sample_date: str) -> None:
    date = to_ymd(sample_date) or sample_date
    dc = conn.execute(
        """
        SELECT dc.ts_code, dc.name, dc.buy_elg_amount, dc.buy_elg_amount_rate,
               d.amount AS daily_amount
        FROM moneyflow_dc dc
        LEFT JOIN daily d
          ON d.ts_code = dc.ts_code AND d.trade_date = dc.trade_date
        WHERE dc.trade_date = ?
          AND dc.buy_elg_amount_rate IS NOT NULL
          AND dc.buy_elg_amount_rate != 0
        ORDER BY ABS(dc.buy_elg_amount_rate - 28.16), ABS(dc.buy_elg_amount - 114300)
        LIMIT 1
        """,
        (date,),
    ).fetchone()
    if not dc:
        log(f"样例：{date} 没有东财资金流，跳过对照")
        return

    ts_code, name, dc_elg, dc_rate, daily_amount = dc
    turnover_wan = (daily_amount / 10.0) if daily_amount else None
    implied_wan = (dc_elg / dc_rate * 100.0) if dc_rate else None
    log(
        f"东财对照 {date} {ts_code} {name}："
        f"超大单净流入 {dc_elg:.2f} 万元，占比 {dc_rate:.2f}%，"
        f"隐含成交额 {implied_wan:.2f} 万元"
        if implied_wan is not None
        else f"东财对照 {date} {ts_code} {name}：超大单净流入 {dc_elg} 万元，占比 {dc_rate}"
    )
    if turnover_wan is not None:
        log(f"  daily.amount/10 = {turnover_wan:.2f} 万元（千元字段 / 10）")

    l2 = conn.execute(
        """
        SELECT
            net_mf_amount,
            net_mf_amount_rate,
            (COALESCE(buy_elg_amount, 0) - COALESCE(sell_elg_amount, 0)) AS elg_net,
            buy_elg_amount_rate
        FROM moneyflow
        WHERE ts_code = ? AND trade_date = ?
        """,
        (ts_code, date),
    ).fetchone()
    if not l2:
        log("  同日同股没有 L2 moneyflow")
        return
    net_amt, net_rate, elg_net, elg_rate = l2
    log(
        f"  L2 净流入 {net_amt} 万元 / {net_rate}%，"
        f"超大单净流入 {elg_net} 万元 / {elg_rate}%"
    )
    if daily_amount and net_amt is not None and net_rate is not None:
        expect = round(net_amt * 1000.0 / daily_amount, 2)
        log(f"  抽查 net_mf_amount_rate：库内 {net_rate}，重算 {expect}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="回填 moneyflow 净流入占比")
    parser.add_argument(
        "--db",
        default=str(DEFAULT_DB_PATH),
        help="SQLite 路径，默认 storage/stock/data.sqlite",
    )
    parser.add_argument("--start-date", help="起始交易日 YYYY-MM-DD 或 YYYYMMDD")
    parser.add_argument("--end-date", help="结束交易日 YYYY-MM-DD 或 YYYYMMDD")
    parser.add_argument(
        "--sample-date",
        default=SAMPLE_DATE,
        help=f"对照样例日期，默认 {SAMPLE_DATE}",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    db_path = Path(args.db)
    if not db_path.is_file():
        log(f"数据库不存在: {db_path}")
        return 1

    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    try:
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        missing = {"moneyflow", "daily"} - tables
        if missing:
            log(f"缺少表: {', '.join(sorted(missing))}。当前库: {db_path}")
            return 1

        added = ensure_rate_columns(conn)
        if added:
            log(f"新增列: {', '.join(added)}")
        else:
            log("占比列已存在")

        updated = refresh_moneyflow_rates(conn, args.start_date, args.end_date)
        conn.commit()
        log(f"回填 {updated} 行")

        stats = summarize_rates(conn)
        log(
            f"moneyflow {stats['mf_rows']} 行，已填占比 {stats['filled']}，"
            f"无成交额跳过 {stats['skipped']}"
        )
        print_sample(conn, args.sample_date)
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
