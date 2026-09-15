#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""采集 Tushare 每日指标（含总市值），写入 storage/stock/data.sqlite。默认最近 1 个交易日。"""

from __future__ import annotations

import argparse
import sqlite3
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import tushare as ts

REPO_ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = REPO_ROOT / ".env"
DB_PATH = REPO_ROOT / "storage" / "stock" / "data.sqlite"

DEFAULT_DAYS = 1
CALL_INTERVAL_SEC = 0.4
MAX_RETRIES = 5
RETRY_BACKOFF_SEC = 2.0
PAGE_SIZE = 6000
DAILY_BASIC_FIELDS = (
    "ts_code,trade_date,close,turnover_rate,turnover_rate_f,volume_ratio,"
    "pe,pe_ttm,pb,ps,ps_ttm,dv_ratio,dv_ttm,"
    "total_share,float_share,free_share,total_mv,circ_mv"
)

TABLE_SPECS = {
    "daily_basic": {
        "pk": ("ts_code", "trade_date"),
        "columns": [
            ("ts_code", "TEXT NOT NULL"),
            ("trade_date", "TEXT NOT NULL"),
            ("close", "REAL"),
            ("turnover_rate", "REAL"),
            ("turnover_rate_f", "REAL"),
            ("volume_ratio", "REAL"),
            ("pe", "REAL"),
            ("pe_ttm", "REAL"),
            ("pb", "REAL"),
            ("ps", "REAL"),
            ("ps_ttm", "REAL"),
            ("dv_ratio", "REAL"),
            ("dv_ttm", "REAL"),
            ("total_share", "REAL"),
            ("float_share", "REAL"),
            ("free_share", "REAL"),
            ("total_mv", "REAL"),
            ("circ_mv", "REAL"),
            ("updated_at", "TEXT NOT NULL"),
        ],
        "indexes": [
            ("idx_daily_basic_trade_date", ("trade_date",)),
            ("idx_daily_basic_ts_code", ("ts_code",)),
        ],
    },
}

RATE_LIMIT_MARKERS = ("每分钟", "频率", "freq", "limit", "太多", "访问次数")
PERMISSION_MARKERS = ("积分", "权限", "没有访问", "无权限", "permission")


def log(message: str) -> None:
    print(message, flush=True)


def load_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip("'").strip('"')
        if key:
            values[key] = value
    return values


def to_ymd(value: object) -> str | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    text = str(value).strip().replace("-", "")
    if len(text) < 8 or not text[:8].isdigit():
        return None
    return f"{text[:4]}-{text[4:6]}-{text[6:8]}"


def to_py(value: object):
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    if hasattr(value, "item"):
        value = value.item()
    return value


def is_rate_limit(error: BaseException) -> bool:
    text = str(error)
    return any(marker in text for marker in RATE_LIMIT_MARKERS)


def is_permission_error(error: BaseException) -> bool:
    text = str(error)
    return any(marker in text for marker in PERMISSION_MARKERS)


def load_token() -> str:
    env = load_env(ENV_PATH)
    token = env.get("TUSHARE_TOKEN") or ts.get_token()
    if not token:
        raise SystemExit(f"未找到 TUSHARE_TOKEN，请在 {ENV_PATH} 中配置")
    return token


def init_db(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    for table, spec in TABLE_SPECS.items():
        col_sql = ", ".join(f"{name} {decl}" for name, decl in spec["columns"])
        pk_sql = ", ".join(spec["pk"])
        conn.execute(
            f"CREATE TABLE IF NOT EXISTS {table} ({col_sql}, PRIMARY KEY ({pk_sql}))"
        )
        for index_name, index_cols in spec["indexes"]:
            cols = ", ".join(index_cols)
            conn.execute(f"CREATE INDEX IF NOT EXISTS {index_name} ON {table} ({cols})")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS import_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            api_name TEXT NOT NULL,
            start_date TEXT NOT NULL,
            end_date TEXT NOT NULL,
            rows_saved INTEGER NOT NULL,
            status TEXT NOT NULL,
            message TEXT,
            started_at TEXT NOT NULL,
            finished_at TEXT NOT NULL
        )
        """
    )
    conn.commit()
    return conn


def upsert_dataframe(conn: sqlite3.Connection, table: str, df: pd.DataFrame) -> int:
    if df is None or df.empty:
        return 0
    spec = TABLE_SPECS[table]
    col_names = [name for name, _ in spec["columns"]]
    work = df.copy()
    if "trade_date" in work.columns:
        work["trade_date"] = work["trade_date"].map(to_ymd)
    for name in col_names:
        if name == "updated_at":
            continue
        if name not in work.columns:
            work[name] = None
    work["updated_at"] = datetime.now().isoformat(timespec="seconds")
    work = work.drop_duplicates(subset=list(spec["pk"]), keep="last")
    records = []
    for row in work[col_names].itertuples(index=False, name=None):
        records.append(tuple(to_py(value) for value in row))
    placeholders = ",".join("?" for _ in col_names)
    insert_cols = ",".join(col_names)
    pk_sql = ",".join(spec["pk"])
    update_sql = ",".join(
        f"{name}=excluded.{name}" for name in col_names if name not in spec["pk"]
    )
    sql = (
        f"INSERT INTO {table} ({insert_cols}) VALUES ({placeholders}) "
        f"ON CONFLICT ({pk_sql}) DO UPDATE SET {update_sql}"
    )
    conn.executemany(sql, records)
    return len(records)


def write_import_log(
    conn: sqlite3.Connection,
    api_name: str,
    start_date: str,
    end_date: str,
    rows_saved: int,
    status: str,
    message: str,
    started_at: str,
) -> None:
    conn.execute(
        """
        INSERT INTO import_log (
            api_name, start_date, end_date, rows_saved, status, message, started_at, finished_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            api_name,
            to_ymd(start_date) or start_date,
            to_ymd(end_date) or end_date,
            rows_saved,
            status,
            message,
            started_at,
            datetime.now().isoformat(timespec="seconds"),
        ),
    )
    conn.commit()


def call_api(pro, method_name: str, **kwargs) -> pd.DataFrame:
    last_error: BaseException | None = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            time.sleep(CALL_INTERVAL_SEC)
            data = pro.query(method_name, **kwargs)
            if data is None:
                return pd.DataFrame()
            return data
        except Exception as exc:  # noqa: BLE001 — Tushare 错误类型不统一
            last_error = exc
            if is_permission_error(exc):
                raise
            if is_rate_limit(exc) or "timeout" in str(exc).lower():
                wait = RETRY_BACKOFF_SEC * attempt
                log(f"  限频/超时，{wait:.1f}s 后重试 {method_name} ({attempt}/{MAX_RETRIES}): {exc}")
                time.sleep(wait)
                continue
            raise
    raise last_error if last_error else RuntimeError(f"{method_name} 调用失败")


def fetch_pages(pro, api_name: str, **kwargs) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    offset = 0
    while True:
        page_kwargs = dict(kwargs)
        if offset:
            page_kwargs["offset"] = offset
            page_kwargs["limit"] = PAGE_SIZE
        page = call_api(pro, api_name, **page_kwargs)
        if page is None or page.empty:
            break
        frames.append(page)
        if len(page) < PAGE_SIZE:
            break
        offset += len(page)
        if offset > PAGE_SIZE * 8:
            log(f"  警告：{api_name} 分页超过安全上限，已停在 offset={offset}")
            break
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


def fetch_daily_basic(
    pro,
    conn: sqlite3.Connection,
    trade_dates: list[str],
) -> tuple[int, str, str]:
    rows = 0
    errors: list[str] = []
    permission_hit = False
    for trade_date in trade_dates:
        if permission_hit:
            break
        try:
            df = fetch_pages(
                pro,
                "daily_basic",
                trade_date=trade_date,
                fields=DAILY_BASIC_FIELDS,
            )
            saved = upsert_dataframe(conn, "daily_basic", df)
            conn.commit()
            rows += saved
            log(f"  daily_basic {trade_date}: {saved} 行")
        except Exception as exc:  # noqa: BLE001
            if is_permission_error(exc):
                permission_hit = True
                errors.append(str(exc))
                log(f"  daily_basic 权限不足，跳过后续日期: {exc}")
                break
            errors.append(f"{trade_date}: {exc}")
            log(f"  daily_basic {trade_date} 失败: {exc}")
    if permission_hit and rows == 0:
        status = "failed"
    elif permission_hit or errors:
        status = "partial" if rows else "failed"
    else:
        status = "ok"
    message = "; ".join(errors)
    return rows, status, message


def list_trade_dates(pro, start_date: str, end_date: str) -> list[str]:
    cal = call_api(
        pro,
        "trade_cal",
        exchange="SSE",
        start_date=start_date,
        end_date=end_date,
        is_open="1",
    )
    if cal is None or cal.empty:
        return []
    dates = cal["cal_date"].astype(str).str.replace("-", "", regex=False).tolist()
    dates.sort()
    return dates


def dates_from_daily(conn: sqlite3.Connection, limit: int) -> list[str]:
    rows = conn.execute(
        "SELECT DISTINCT trade_date FROM daily ORDER BY trade_date DESC LIMIT ?",
        (limit,),
    ).fetchall()
    dates = []
    for (trade_date,) in reversed(rows):
        compact = str(trade_date).replace("-", "")
        if len(compact) == 8 and compact.isdigit():
            dates.append(compact)
    return dates


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="采集 Tushare 每日指标（含总市值）到本地 SQLite")
    parser.add_argument(
        "--days",
        type=int,
        default=DEFAULT_DAYS,
        help=f"采集最近几个交易日，默认 {DEFAULT_DAYS}",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    days = args.days
    if days <= 0:
        log("--days 必须为正整数")
        return 1
    token = load_token()
    pro = ts.pro_api(token)
    conn = init_db(DB_PATH)
    log(f"数据库：{DB_PATH}")

    try:
        trade_dates = dates_from_daily(conn, days)
        if not trade_dates:
            end = datetime.now().date()
            start = end - timedelta(days=max(days * 3, 14))
            trade_dates = list_trade_dates(
                pro,
                start.strftime("%Y%m%d"),
                end.strftime("%Y%m%d"),
            )[-days:]
        if not trade_dates:
            log("没有可采集的交易日，退出")
            return 1
        log(f"交易日 {len(trade_dates)} 个：{trade_dates[0]} ~ {trade_dates[-1]}")

        started_at = datetime.now().isoformat(timespec="seconds")
        log("\n开始 daily_basic (按交易日)")
        rows, status, message = fetch_daily_basic(pro, conn, trade_dates)
        write_import_log(
            conn,
            api_name="daily_basic",
            start_date=trade_dates[0],
            end_date=trade_dates[-1],
            rows_saved=rows,
            status=status,
            message=message,
            started_at=started_at,
        )
        log(f"完成 daily_basic: {status}, {rows} 行")
        if status == "failed":
            return 1
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
