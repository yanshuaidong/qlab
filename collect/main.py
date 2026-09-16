#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""采集 Tushare 资金流向，写入本地 SQLite。默认近 365 个自然日。"""

from __future__ import annotations

import argparse
import sqlite3
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import tushare as ts

_COLLECT_DIR = Path(__file__).resolve().parent
if str(_COLLECT_DIR) not in sys.path:
    sys.path.insert(0, str(_COLLECT_DIR))
from moneyflow_rates import ensure_rate_columns, refresh_moneyflow_rates

REPO_ROOT = _COLLECT_DIR.parent
ENV_PATH = REPO_ROOT / ".env"
DB_PATH = REPO_ROOT / "storage" / "stock" / "tushare_moneyflow" / "data.sqlite"

DEFAULT_DAYS = 365
CALL_INTERVAL_SEC = 0.4
MAX_RETRIES = 5
RETRY_BACKOFF_SEC = 2.0

# Tushare 入参 YYYYMMDD；入库 YYYY-MM-DD。
TABLE_SPECS = {
    "moneyflow": {
        "pk": ("ts_code", "trade_date"),
        "columns": [
            ("ts_code", "TEXT NOT NULL"),
            ("trade_date", "TEXT NOT NULL"),
            ("buy_sm_vol", "INTEGER"),
            ("buy_sm_amount", "REAL"),
            ("sell_sm_vol", "INTEGER"),
            ("sell_sm_amount", "REAL"),
            ("buy_md_vol", "INTEGER"),
            ("buy_md_amount", "REAL"),
            ("sell_md_vol", "INTEGER"),
            ("sell_md_amount", "REAL"),
            ("buy_lg_vol", "INTEGER"),
            ("buy_lg_amount", "REAL"),
            ("sell_lg_vol", "INTEGER"),
            ("sell_lg_amount", "REAL"),
            ("buy_elg_vol", "INTEGER"),
            ("buy_elg_amount", "REAL"),
            ("sell_elg_vol", "INTEGER"),
            ("sell_elg_amount", "REAL"),
            ("net_mf_vol", "INTEGER"),
            ("net_mf_amount", "REAL"),
            ("updated_at", "TEXT NOT NULL"),
        ],
        "indexes": [
            ("idx_moneyflow_trade_date", ("trade_date",)),
            ("idx_moneyflow_ts_code", ("ts_code",)),
        ],
    },
    "moneyflow_dc": {
        "pk": ("ts_code", "trade_date"),
        "columns": [
            ("ts_code", "TEXT NOT NULL"),
            ("trade_date", "TEXT NOT NULL"),
            ("name", "TEXT"),
            ("pct_change", "REAL"),
            ("close", "REAL"),
            ("net_amount", "REAL"),
            ("net_amount_rate", "REAL"),
            ("buy_elg_amount", "REAL"),
            ("buy_elg_amount_rate", "REAL"),
            ("buy_lg_amount", "REAL"),
            ("buy_lg_amount_rate", "REAL"),
            ("buy_md_amount", "REAL"),
            ("buy_md_amount_rate", "REAL"),
            ("buy_sm_amount", "REAL"),
            ("buy_sm_amount_rate", "REAL"),
            ("updated_at", "TEXT NOT NULL"),
        ],
        "indexes": [
            ("idx_moneyflow_dc_trade_date", ("trade_date",)),
            ("idx_moneyflow_dc_ts_code", ("ts_code",)),
        ],
    },
    "moneyflow_ths": {
        "pk": ("ts_code", "trade_date"),
        "columns": [
            ("ts_code", "TEXT NOT NULL"),
            ("trade_date", "TEXT NOT NULL"),
            ("name", "TEXT"),
            ("pct_change", "REAL"),
            ("latest", "REAL"),
            ("net_amount", "REAL"),
            ("net_d5_amount", "REAL"),
            ("buy_lg_amount", "REAL"),
            ("buy_lg_amount_rate", "REAL"),
            ("buy_md_amount", "REAL"),
            ("buy_md_amount_rate", "REAL"),
            ("buy_sm_amount", "REAL"),
            ("buy_sm_amount_rate", "REAL"),
            ("updated_at", "TEXT NOT NULL"),
        ],
        "indexes": [
            ("idx_moneyflow_ths_trade_date", ("trade_date",)),
            ("idx_moneyflow_ths_ts_code", ("ts_code",)),
        ],
    },
    "moneyflow_mkt_dc": {
        "pk": ("trade_date",),
        "columns": [
            ("trade_date", "TEXT NOT NULL"),
            ("close_sh", "REAL"),
            ("pct_change_sh", "REAL"),
            ("close_sz", "REAL"),
            ("pct_change_sz", "REAL"),
            ("net_amount", "REAL"),
            ("net_amount_rate", "REAL"),
            ("buy_elg_amount", "REAL"),
            ("buy_elg_amount_rate", "REAL"),
            ("buy_lg_amount", "REAL"),
            ("buy_lg_amount_rate", "REAL"),
            ("buy_md_amount", "REAL"),
            ("buy_md_amount_rate", "REAL"),
            ("buy_sm_amount", "REAL"),
            ("buy_sm_amount_rate", "REAL"),
            ("updated_at", "TEXT NOT NULL"),
        ],
        "indexes": [],
    },
    "moneyflow_ind_dc": {
        "pk": ("ts_code", "trade_date", "content_type"),
        "columns": [
            ("ts_code", "TEXT NOT NULL"),
            ("trade_date", "TEXT NOT NULL"),
            ("content_type", "TEXT NOT NULL"),
            ("name", "TEXT"),
            ("pct_change", "REAL"),
            ("close", "REAL"),
            ("net_amount", "REAL"),
            ("net_amount_rate", "REAL"),
            ("buy_elg_amount", "REAL"),
            ("buy_elg_amount_rate", "REAL"),
            ("buy_lg_amount", "REAL"),
            ("buy_lg_amount_rate", "REAL"),
            ("buy_md_amount", "REAL"),
            ("buy_md_amount_rate", "REAL"),
            ("buy_sm_amount", "REAL"),
            ("buy_sm_amount_rate", "REAL"),
            ("buy_sm_amount_stock", "TEXT"),
            ("rank", "INTEGER"),
            ("updated_at", "TEXT NOT NULL"),
        ],
        "indexes": [
            ("idx_moneyflow_ind_dc_trade_date", ("trade_date",)),
            ("idx_moneyflow_ind_dc_type_date", ("content_type", "trade_date")),
        ],
    },
    "moneyflow_ind_ths": {
        "pk": ("ts_code", "trade_date"),
        "columns": [
            ("ts_code", "TEXT NOT NULL"),
            ("trade_date", "TEXT NOT NULL"),
            ("industry", "TEXT"),
            ("lead_stock", "TEXT"),
            ("close", "REAL"),
            ("pct_change", "REAL"),
            ("company_num", "INTEGER"),
            ("pct_change_stock", "REAL"),
            ("close_price", "REAL"),
            ("net_buy_amount", "REAL"),
            ("net_sell_amount", "REAL"),
            ("net_amount", "REAL"),
            ("updated_at", "TEXT NOT NULL"),
        ],
        "indexes": [
            ("idx_moneyflow_ind_ths_trade_date", ("trade_date",)),
        ],
    },
    "moneyflow_cnt_ths": {
        "pk": ("ts_code", "trade_date"),
        "columns": [
            ("ts_code", "TEXT NOT NULL"),
            ("trade_date", "TEXT NOT NULL"),
            ("name", "TEXT"),
            ("lead_stock", "TEXT"),
            ("close_price", "REAL"),
            ("pct_change", "REAL"),
            ("industry_index", "REAL"),
            ("company_num", "INTEGER"),
            ("pct_change_stock", "REAL"),
            ("net_buy_amount", "REAL"),
            ("net_sell_amount", "REAL"),
            ("net_amount", "REAL"),
            ("updated_at", "TEXT NOT NULL"),
        ],
        "indexes": [
            ("idx_moneyflow_cnt_ths_trade_date", ("trade_date",)),
        ],
    },
    "moneyflow_hsgt": {
        "pk": ("trade_date",),
        "columns": [
            ("trade_date", "TEXT NOT NULL"),
            ("ggt_ss", "REAL"),
            ("ggt_sz", "REAL"),
            ("hgt", "REAL"),
            ("sgt", "REAL"),
            ("north_money", "REAL"),
            ("south_money", "REAL"),
            ("updated_at", "TEXT NOT NULL"),
        ],
        "indexes": [],
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
    ensure_rate_columns(conn)
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
    if table == "moneyflow_ind_dc" and "content_type" in work.columns:
        work["content_type"] = work["content_type"].fillna("").astype(str)
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


PAGE_SIZE = 6000
API_PAGE_SIZE = {
    "moneyflow_hsgt": 300,
    "moneyflow_mkt_dc": 3000,
    "moneyflow_ind_dc": 5000,
    "moneyflow_ind_ths": 5000,
    "moneyflow_cnt_ths": 5000,
}


def fetch_pages(pro, api_name: str, **kwargs) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    offset = 0
    page_size = API_PAGE_SIZE.get(api_name, PAGE_SIZE)
    while True:
        page_kwargs = dict(kwargs)
        if offset:
            page_kwargs["offset"] = offset
            page_kwargs["limit"] = page_size
        page = call_api(pro, api_name, **page_kwargs)
        if page is None or page.empty:
            break
        frames.append(page)
        if len(page) < page_size:
            break
        offset += len(page)
        if offset > page_size * 8:
            log(f"  警告：{api_name} 分页超过安全上限，已停在 offset={offset}")
            break
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


class PermissionDenied(Exception):
    """当前积分不足以调用该接口。"""


def fetch_daily(
    pro,
    conn: sqlite3.Connection,
    api_name: str,
    trade_dates: list[str],
    extra_kwargs: dict | None = None,
    content_types: list[str] | None = None,
) -> tuple[int, str, str]:
    rows = 0
    errors: list[str] = []
    extra_kwargs = extra_kwargs or {}
    loops = content_types or [None]
    permission_hit = False
    for trade_date in trade_dates:
        if permission_hit:
            break
        for content_type in loops:
            kwargs = dict(extra_kwargs)
            kwargs["trade_date"] = trade_date
            label = trade_date
            if content_type:
                kwargs["content_type"] = content_type
                label = f"{trade_date}/{content_type}"
            try:
                df = fetch_pages(pro, api_name, **kwargs)
                if content_type:
                    if "content_type" not in df.columns or df.empty:
                        df = df.copy()
                        df["content_type"] = content_type
                    else:
                        df = df.copy()
                        df["content_type"] = df["content_type"].replace("", pd.NA)
                        df["content_type"] = df["content_type"].fillna(content_type)
                saved = upsert_dataframe(conn, api_name, df)
                conn.commit()
                if api_name == "moneyflow" and saved:
                    ymd = to_ymd(trade_date) or str(trade_date)
                    refresh_moneyflow_rates(conn, start_date=ymd, end_date=ymd)
                    conn.commit()
                rows += saved
                log(f"  {api_name} {label}: {saved} 行")
            except Exception as exc:  # noqa: BLE001
                if is_permission_error(exc):
                    permission_hit = True
                    errors.append(str(exc))
                    log(f"  {api_name} 权限不足，跳过后续日期: {exc}")
                    break
                errors.append(f"{label}: {exc}")
                log(f"  {api_name} {label} 失败: {exc}")
    if permission_hit and rows == 0:
        status = "failed"
    elif permission_hit or errors:
        status = "partial" if rows else "failed"
    else:
        status = "ok"
    message = "; ".join(errors)
    return rows, status, message


def fetch_range(
    pro,
    conn: sqlite3.Connection,
    api_name: str,
    start_date: str,
    end_date: str,
) -> tuple[int, str, str]:
    try:
        df = fetch_pages(pro, api_name, start_date=start_date, end_date=end_date)
        saved = upsert_dataframe(conn, api_name, df)
        conn.commit()
        log(f"  {api_name} {start_date}~{end_date}: {saved} 行")
        return saved, "ok", ""
    except Exception as exc:  # noqa: BLE001
        status = "failed"
        log(f"  {api_name} 失败: {exc}")
        return 0, status, str(exc)


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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="采集 Tushare 资金流向到本地 SQLite")
    parser.add_argument(
        "--days",
        type=int,
        default=DEFAULT_DAYS,
        help=f"自然日窗口，默认 {DEFAULT_DAYS}",
    )
    parser.add_argument(
        "apis",
        nargs="*",
        help="只跑这些接口，例如 moneyflow_dc；默认跑全部",
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
    end = datetime.now().date()
    start = end - timedelta(days=days)
    start_date = start.strftime("%Y%m%d")
    end_date = end.strftime("%Y%m%d")

    log(f"采集区间：{start_date} ~ {end_date}（近 {days} 个自然日）")
    log(f"数据库：{DB_PATH}")
    conn = init_db(DB_PATH)

    try:
        trade_dates = list_trade_dates(pro, start_date, end_date)
        if not trade_dates:
            log("交易日历为空，退出")
            return 1
        log(f"开市日 {len(trade_dates)} 个：{trade_dates[0]} ~ {trade_dates[-1]}")

        jobs = [
            ("moneyflow", "daily"),
            ("moneyflow_dc", "daily"),
            ("moneyflow_ths", "daily"),
            ("moneyflow_mkt_dc", "range"),
            ("moneyflow_ind_dc", "daily_types"),
            ("moneyflow_ind_ths", "daily"),
            ("moneyflow_cnt_ths", "daily"),
            ("moneyflow_hsgt", "range"),
        ]
        only = {item.strip() for item in args.apis if item.strip()}
        if only:
            jobs = [job for job in jobs if job[0] in only]
            if not jobs:
                log(f"没有匹配的接口：{sorted(only)}")
                return 1
        summary: list[tuple[str, int, str]] = []
        for api_name, mode in jobs:
            started_at = datetime.now().isoformat(timespec="seconds")
            log(f"\n开始 {api_name} ({mode})")
            if mode == "daily":
                rows, status, message = fetch_daily(pro, conn, api_name, trade_dates)
            elif mode == "daily_types":
                rows, status, message = fetch_daily(
                    pro,
                    conn,
                    api_name,
                    trade_dates,
                    content_types=["行业", "概念", "地域"],
                )
            else:
                rows, status, message = fetch_range(
                    pro, conn, api_name, start_date, end_date
                )
            write_import_log(
                conn,
                api_name=api_name,
                start_date=start_date,
                end_date=end_date,
                rows_saved=rows,
                status=status,
                message=message,
                started_at=started_at,
            )
            summary.append((api_name, rows, status))
            log(f"完成 {api_name}: {status}, {rows} 行")

        log("\n==== 汇总 ====")
        failed = 0
        for api_name, rows, status in summary:
            log(f"{api_name:20s} {status:8s} {rows:>8d} 行")
            if status == "failed":
                failed += 1
        if failed == len(summary):
            return 1
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
