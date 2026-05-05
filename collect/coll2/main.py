from __future__ import annotations

import argparse
import sqlite3
import time
from datetime import datetime
from pathlib import Path
from typing import Iterable

import akshare as ak
import pandas as pd


DEFAULT_DB_PATH = Path(__file__).resolve().parent / "data" / "qlab_coll2_stock.sqlite"
DEFAULT_STOCK_TABLE = "stock_basic_info"
FUND_FLOW_TABLE = "stock_individual_fund_flow"
FUND_FLOW_LOG_TABLE = "stock_individual_fund_flow_import_log"
SOURCE_NAME = "akshare.stock_individual_fund_flow"


EXCHANGE_TO_MARKET = {
    "SSE": "sh",
    "SH": "sh",
    "SHSE": "sh",
    "SZSE": "sz",
    "SZ": "sz",
    "BSE": "bj",
    "BJ": "bj",
    "BJSE": "bj",
}


COLUMN_MAP = {
    "日期": "trade_date",
    "收盘价": "close",
    "涨跌幅": "pct_change",
    "主力净流入-净额": "main_net_inflow_amount",
    "主力净流入-净占比": "main_net_inflow_ratio",
    "超大单净流入-净额": "super_large_net_inflow_amount",
    "超大单净流入-净占比": "super_large_net_inflow_ratio",
    "大单净流入-净额": "large_net_inflow_amount",
    "大单净流入-净占比": "large_net_inflow_ratio",
    "中单净流入-净额": "medium_net_inflow_amount",
    "中单净流入-净占比": "medium_net_inflow_ratio",
    "小单净流入-净额": "small_net_inflow_amount",
    "小单净流入-净占比": "small_net_inflow_ratio",
}


FUND_FLOW_COLUMNS = [
    "exchange",
    "code",
    "name",
    "market",
    "trade_date",
    "close",
    "pct_change",
    "main_net_inflow_amount",
    "main_net_inflow_ratio",
    "super_large_net_inflow_amount",
    "super_large_net_inflow_ratio",
    "large_net_inflow_amount",
    "large_net_inflow_ratio",
    "medium_net_inflow_amount",
    "medium_net_inflow_ratio",
    "small_net_inflow_amount",
    "small_net_inflow_ratio",
    "source",
    "updated_at",
]


def quote_identifier(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def clean_text(value: object) -> str | None:
    if pd.isna(value):
        return None
    text = str(value).strip()
    return text or None


def parse_date(value: object) -> str | None:
    if pd.isna(value):
        return None
    parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        text = str(value).strip()
        return text or None
    return parsed.strftime("%Y-%m-%d")


def parse_float(value: object) -> float | None:
    if pd.isna(value):
        return None
    text = str(value).strip().replace(",", "")
    if not text or text in {"-", "--", "None", "nan"}:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def create_fund_flow_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {FUND_FLOW_TABLE} (
            exchange TEXT NOT NULL,
            code TEXT NOT NULL,
            name TEXT,
            market TEXT NOT NULL,
            trade_date TEXT NOT NULL,
            close REAL,
            pct_change REAL,
            main_net_inflow_amount REAL,
            main_net_inflow_ratio REAL,
            super_large_net_inflow_amount REAL,
            super_large_net_inflow_ratio REAL,
            large_net_inflow_amount REAL,
            large_net_inflow_ratio REAL,
            medium_net_inflow_amount REAL,
            medium_net_inflow_ratio REAL,
            small_net_inflow_amount REAL,
            small_net_inflow_ratio REAL,
            source TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (exchange, code, trade_date)
        )
        """
    )
    conn.execute(
        f"""
        CREATE INDEX IF NOT EXISTS idx_{FUND_FLOW_TABLE}_code_date
        ON {FUND_FLOW_TABLE} (code, trade_date)
        """
    )


def create_fund_flow_log_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {FUND_FLOW_LOG_TABLE} (
            exchange TEXT NOT NULL,
            code TEXT NOT NULL,
            name TEXT,
            market TEXT NOT NULL,
            rows_saved INTEGER NOT NULL,
            status TEXT NOT NULL,
            message TEXT,
            started_at TEXT NOT NULL,
            finished_at TEXT NOT NULL,
            PRIMARY KEY (exchange, code)
        )
        """
    )


def load_stock_list(
    conn: sqlite3.Connection,
    stock_table: str,
    exchanges: Iterable[str],
    security_types: Iterable[str],
    limit: int | None,
) -> list[dict[str, str]]:
    table_exists = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (stock_table,),
    ).fetchone()
    if not table_exists:
        raise ValueError(f"股票池表不存在: {stock_table}")

    exchange_values = [item.strip().upper() for item in exchanges if item.strip()]
    security_type_values = [item.strip() for item in security_types if item.strip()]

    conditions: list[str] = []
    params: list[object] = []
    if exchange_values:
        conditions.append(
            f"exchange IN ({','.join('?' for _ in exchange_values)})"
        )
        params.extend(exchange_values)
    if security_type_values:
        conditions.append(
            f"security_type IN ({','.join('?' for _ in security_type_values)})"
        )
        params.extend(security_type_values)

    where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    limit_clause = "LIMIT ?" if limit is not None else ""
    if limit is not None:
        params.append(limit)

    table_sql = quote_identifier(stock_table)
    sql = f"""
        SELECT exchange, code, name
        FROM {table_sql}
        {where_clause}
        ORDER BY exchange, code
        {limit_clause}
    """
    rows = conn.execute(sql, params).fetchall()
    stocks: list[dict[str, str]] = []
    for exchange, code, name in rows:
        market = EXCHANGE_TO_MARKET.get(str(exchange).upper())
        if not market:
            continue
        stocks.append(
            {
                "exchange": str(exchange).upper(),
                "code": str(code).zfill(6),
                "name": clean_text(name) or "",
                "market": market,
            }
        )
    return stocks


def normalize_fund_flow(df: pd.DataFrame, stock: dict[str, str]) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=FUND_FLOW_COLUMNS)

    missing_columns = [col for col in COLUMN_MAP if col not in df.columns]
    if missing_columns:
        raise ValueError(f"接口返回缺少字段: {', '.join(missing_columns)}")

    now = datetime.now().isoformat(timespec="seconds")
    normalized = df.rename(columns=COLUMN_MAP)
    out = pd.DataFrame(
        {
            "exchange": stock["exchange"],
            "code": stock["code"],
            "name": stock["name"],
            "market": stock["market"],
            "trade_date": normalized["trade_date"].map(parse_date),
            "close": normalized["close"].map(parse_float),
            "pct_change": normalized["pct_change"].map(parse_float),
            "main_net_inflow_amount": normalized["main_net_inflow_amount"].map(parse_float),
            "main_net_inflow_ratio": normalized["main_net_inflow_ratio"].map(parse_float),
            "super_large_net_inflow_amount": normalized[
                "super_large_net_inflow_amount"
            ].map(parse_float),
            "super_large_net_inflow_ratio": normalized[
                "super_large_net_inflow_ratio"
            ].map(parse_float),
            "large_net_inflow_amount": normalized["large_net_inflow_amount"].map(parse_float),
            "large_net_inflow_ratio": normalized["large_net_inflow_ratio"].map(parse_float),
            "medium_net_inflow_amount": normalized[
                "medium_net_inflow_amount"
            ].map(parse_float),
            "medium_net_inflow_ratio": normalized[
                "medium_net_inflow_ratio"
            ].map(parse_float),
            "small_net_inflow_amount": normalized["small_net_inflow_amount"].map(parse_float),
            "small_net_inflow_ratio": normalized["small_net_inflow_ratio"].map(parse_float),
            "source": SOURCE_NAME,
            "updated_at": now,
        }
    )
    out = out[out["trade_date"].notna()].copy()
    return out[FUND_FLOW_COLUMNS]


def fetch_fund_flow(stock: dict[str, str]) -> pd.DataFrame:
    raw = ak.stock_individual_fund_flow(
        stock=stock["code"],
        market=stock["market"],
    )
    return normalize_fund_flow(raw, stock)


def upsert_fund_flow_rows(
    conn: sqlite3.Connection,
    rows: Iterable[dict[str, object]],
) -> int:
    rows = list(rows)
    if not rows:
        return 0

    columns_sql = ", ".join(quote_identifier(col) for col in FUND_FLOW_COLUMNS)
    placeholders = ", ".join("?" for _ in FUND_FLOW_COLUMNS)
    update_sql = ", ".join(
        f"{quote_identifier(col)} = excluded.{quote_identifier(col)}"
        for col in FUND_FLOW_COLUMNS
        if col not in {"exchange", "code", "trade_date"}
    )
    sql = f"""
        INSERT INTO {FUND_FLOW_TABLE} ({columns_sql})
        VALUES ({placeholders})
        ON CONFLICT(exchange, code, trade_date) DO UPDATE SET
            {update_sql}
    """
    values = [tuple(row.get(col) for col in FUND_FLOW_COLUMNS) for row in rows]
    conn.executemany(sql, values)
    return len(rows)


def upsert_fund_flow_log(
    conn: sqlite3.Connection,
    stock: dict[str, str],
    rows_saved: int,
    status: str,
    message: str | None,
    started_at: str,
) -> None:
    finished_at = datetime.now().isoformat(timespec="seconds")
    conn.execute(
        f"""
        INSERT INTO {FUND_FLOW_LOG_TABLE} (
            exchange, code, name, market, rows_saved, status, message,
            started_at, finished_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(exchange, code) DO UPDATE SET
            name = excluded.name,
            market = excluded.market,
            rows_saved = excluded.rows_saved,
            status = excluded.status,
            message = excluded.message,
            started_at = excluded.started_at,
            finished_at = excluded.finished_at
        """,
        (
            stock["exchange"],
            stock["code"],
            stock["name"],
            stock["market"],
            rows_saved,
            status,
            message,
            started_at,
            finished_at,
        ),
    )


def comma_values(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def save_individual_fund_flow(
    db_path: Path,
    stock_table: str,
    exchanges: Iterable[str],
    security_types: Iterable[str],
    limit: int | None,
    sleep_seconds: float,
    skip_ok: bool,
) -> None:
    with sqlite3.connect(db_path) as conn:
        create_fund_flow_table(conn)
        create_fund_flow_log_table(conn)
        stocks = load_stock_list(
            conn,
            stock_table=stock_table,
            exchanges=exchanges,
            security_types=security_types,
            limit=limit,
        )
        if skip_ok:
            finished = {
                (row[0], row[1])
                for row in conn.execute(
                    f"SELECT exchange, code FROM {FUND_FLOW_LOG_TABLE} WHERE status = 'ok'"
                )
            }
            stocks = [
                stock
                for stock in stocks
                if (stock["exchange"], stock["code"]) not in finished
            ]

        total = len(stocks)
        if skip_ok:
            print(
                f"待拉取 {total} 只（{db_path}；已跳过 {FUND_FLOW_LOG_TABLE} 中 status=ok）"
            )
        else:
            print(f"待拉取 {total} 只（{db_path}；--no-skip 全量重拉）")

        for index, stock in enumerate(stocks, start=1):
            started_at = datetime.now().isoformat(timespec="seconds")
            try:
                df = fetch_fund_flow(stock)
                rows_saved = upsert_fund_flow_rows(
                    conn,
                    df.to_dict(orient="records"),
                )
                upsert_fund_flow_log(
                    conn,
                    stock=stock,
                    rows_saved=rows_saved,
                    status="ok",
                    message=None,
                    started_at=started_at,
                )
                conn.commit()
                print(
                    f"[{index}/{total}] {stock['code']} {stock['name']}: "
                    f"{rows_saved} 行"
                )
            except Exception as exc:
                conn.rollback()
                upsert_fund_flow_log(
                    conn,
                    stock=stock,
                    rows_saved=0,
                    status="failed",
                    message=str(exc),
                    started_at=started_at,
                )
                conn.commit()
                print(
                    f"[{index}/{total}] {stock['code']} {stock['name']}: "
                    f"失败 - {exc}"
                )
                print("遇错即停；未处理后续股票。")
                raise SystemExit(1)

            if sleep_seconds > 0 and index < total:
                time.sleep(sleep_seconds)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "使用 akshare.stock_individual_fund_flow 拉取东方财富个股日级资金流向，"
            "写入 SQLite（默认跳过 {log} 中 status=ok 的股票）。".format(
                log=FUND_FLOW_LOG_TABLE
            )
        )
    )
    parser.add_argument(
        "--db",
        type=Path,
        default=DEFAULT_DB_PATH,
        help=f"SQLite 路径。默认: {DEFAULT_DB_PATH}",
    )
    parser.add_argument(
        "--stock-table",
        default=DEFAULT_STOCK_TABLE,
        help=f"股票池表。默认: {DEFAULT_STOCK_TABLE}",
    )
    parser.add_argument(
        "--exchanges",
        default="SSE,SZSE,BSE",
        help="逗号分隔的 exchange 过滤。",
    )
    parser.add_argument(
        "--security-types",
        default="A股",
        help="逗号分隔的 security_type 过滤。",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="仅处理前 N 只（调试用）。",
    )
    parser.add_argument(
        "--sleep",
        type=float,
        default=1.0,
        help="每只股票请求之间的休眠秒数。",
    )
    parser.add_argument(
        "--no-skip",
        action="store_true",
        help="不跳过已成功的股票（全量重拉并覆盖最近窗口数据）。",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    save_individual_fund_flow(
        db_path=args.db,
        stock_table=args.stock_table,
        exchanges=comma_values(args.exchanges),
        security_types=comma_values(args.security_types),
        limit=args.limit,
        sleep_seconds=args.sleep,
        skip_ok=not args.no_skip,
    )


if __name__ == "__main__":
    main()
