#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""采集近一年的 ST 列表和 ST 变更记录，写入 storage/stock/data.sqlite。"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

if __package__:
    from .daily import call_api, is_permission_error, load_token, log, to_py, to_ymd, write_import_log
else:
    from daily import call_api, is_permission_error, load_token, log, to_py, to_ymd, write_import_log

import tushare as ts

DB_PATH = Path(__file__).resolve().parent.parent / "storage" / "stock" / "data.sqlite"
PAGE_SIZE = 1000
STOCK_ST_FIELDS = ("ts_code", "name", "trade_date", "type", "type_name")
ST_FIELDS = ("ts_code", "name", "pub_date", "imp_date", "st_type", "st_reason", "st_explain")
ST_DATE_FIELDS = ("pub_date", "imp_date")


def q(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def compact_date(value: str) -> str:
    return datetime.strptime(value.replace("-", ""), "%Y%m%d").strftime("%Y%m%d")


def calendar_days(start_date: str, end_date: str) -> list[str]:
    day = datetime.strptime(start_date, "%Y%m%d").date()
    last = datetime.strptime(end_date, "%Y%m%d").date()
    days = []
    while day <= last:
        days.append(day.strftime("%Y%m%d"))
        day += timedelta(days=1)
    return days


def init_db(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=60)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS stock_st (
            ts_code TEXT NOT NULL,
            trade_date TEXT NOT NULL,
            name TEXT,
            type TEXT,
            type_name TEXT,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (ts_code, trade_date)
        );
        CREATE INDEX IF NOT EXISTS idx_stock_st_trade_date ON stock_st (trade_date);

        CREATE TABLE IF NOT EXISTS st (
            ts_code TEXT NOT NULL,
            name TEXT,
            pub_date TEXT NOT NULL,
            imp_date TEXT NOT NULL,
            st_type TEXT NOT NULL,
            st_reason TEXT,
            st_explain TEXT,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (ts_code, pub_date, imp_date, st_type)
        );
        CREATE INDEX IF NOT EXISTS idx_st_ts_code ON st (ts_code);
        CREATE INDEX IF NOT EXISTS idx_st_imp_date ON st (imp_date);

        CREATE TABLE IF NOT EXISTS stock_st_slice (
            api_name TEXT NOT NULL,
            slice_key TEXT NOT NULL,
            rows INTEGER NOT NULL,
            status TEXT NOT NULL,
            finished_at TEXT NOT NULL,
            PRIMARY KEY (api_name, slice_key)
        );

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
        );
        """
    )
    return conn


def load_done(conn: sqlite3.Connection, api_name: str) -> set[str]:
    return {
        row[0]
        for row in conn.execute(
            "SELECT slice_key FROM stock_st_slice WHERE api_name=? AND status='ok'",
            (api_name,),
        )
    }


def mark_slice(conn: sqlite3.Connection, api_name: str, slice_key: str, rows: int, status: str) -> None:
    conn.execute(
        """
        INSERT INTO stock_st_slice (api_name, slice_key, rows, status, finished_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT (api_name, slice_key) DO UPDATE SET
            rows=excluded.rows,
            status=excluded.status,
            finished_at=excluded.finished_at
        """,
        (api_name, slice_key, rows, status, datetime.now().isoformat(timespec="seconds")),
    )


def _records(df: pd.DataFrame, columns: tuple[str, ...], date_columns: tuple[str, ...]) -> list[tuple]:
    work = df.loc[:, list(columns)].copy()
    for column in date_columns:
        work[column] = work[column].map(to_ymd)
    updated_at = datetime.now().isoformat(timespec="seconds")
    records = []
    for row in work.itertuples(index=False, name=None):
        values = [to_py(value) for value in row]
        records.append((*values, updated_at))
    return records


def fetch_pages(pro, api_name: str, fields: tuple[str, ...], expect_field: str, expect_day: str, **params) -> pd.DataFrame:
    """按日分页取完才返回。空表表示当天没有记录。"""
    frames = []
    offset = 0
    fingerprints = set()
    compact = compact_date(expect_day)
    while True:
        page = call_api(
            pro,
            api_name,
            fields=",".join(fields),
            limit=PAGE_SIZE,
            offset=offset,
            **params,
        )
        if page is None or page.empty:
            break
        if len(page) > PAGE_SIZE:
            raise ValueError("接口返回超过分页大小，拒绝写入")
        missing = set(fields) - set(page.columns)
        if missing:
            raise ValueError(f"接口缺少字段：{sorted(missing)}")
        page = page.loc[:, list(fields)].copy()
        got = page[expect_field].map(lambda value: compact_date(str(value)) if to_py(value) else "")
        if not got.eq(compact).all():
            raise ValueError(f"接口返回了 {expect_day} 以外的 {expect_field}")
        fingerprint = tuple(pd.util.hash_pandas_object(page, index=False).tolist())
        if fingerprint in fingerprints:
            raise ValueError(f"检测到重复分页 offset={offset}")
        fingerprints.add(fingerprint)
        frames.append(page)
        if len(page) < PAGE_SIZE:
            break
        offset += len(page)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=list(fields))


def replace_stock_st_day(conn: sqlite3.Connection, trade_date: str, df: pd.DataFrame) -> int:
    """开市日的 ST 名单整日替换。空响应不覆盖已有名单。"""
    ymd = to_ymd(compact_date(trade_date))
    columns = STOCK_ST_FIELDS
    if df is None or df.empty:
        exists = conn.execute("SELECT 1 FROM stock_st WHERE trade_date=? LIMIT 1", (ymd,)).fetchone()
        if exists:
            raise ValueError("接口返回空名单但库内该日已有记录，保留原数据")
        return 0
    missing = set(columns) - set(df.columns)
    if missing:
        raise ValueError(f"缺少字段：{sorted(missing)}")
    work = df.loc[:, list(columns)].copy()
    if work["ts_code"].map(lambda value: not str(to_py(value) or "").strip()).any():
        raise ValueError("ST 名单缺少股票代码")
    dates = work["trade_date"].map(lambda value: to_ymd(value) if to_py(value) else None)
    if not dates.eq(ymd).all():
        raise ValueError("名单日期与请求日期不一致")
    work = work.drop_duplicates(subset=["ts_code", "trade_date"], keep="last")
    records = _records(work, columns, ("trade_date",))
    quoted = ",".join(q(name) for name in (*columns, "updated_at"))
    placeholders = ",".join("?" for _ in (*columns, "updated_at"))
    with conn:
        conn.execute("DELETE FROM stock_st WHERE trade_date=?", (ymd,))
        conn.executemany(
            f"INSERT INTO stock_st ({quoted}) VALUES ({placeholders})",
            records,
        )
    return len(records)


def upsert_st_rows(conn: sqlite3.Connection, df: pd.DataFrame) -> int:
    if df is None or df.empty:
        return 0
    missing = set(ST_FIELDS) - set(df.columns)
    if missing:
        raise ValueError(f"缺少字段：{sorted(missing)}")
    work = df.loc[:, list(ST_FIELDS)].copy()
    for column in ("ts_code", *ST_DATE_FIELDS, "st_type"):
        if work[column].map(lambda value: not str(to_py(value) or "").strip()).any():
            raise ValueError(f"ST 变更记录缺少 {column}")
    for column in ST_DATE_FIELDS:
        work[column] = work[column].map(to_ymd)
    work = work.drop_duplicates(subset=["ts_code", "pub_date", "imp_date", "st_type"], keep="last")
    records = _records(work, ST_FIELDS, ())
    columns = (*ST_FIELDS, "updated_at")
    quoted = ",".join(q(name) for name in columns)
    placeholders = ",".join("?" for _ in columns)
    updates = ",".join(
        f"{q(name)}=excluded.{q(name)}"
        for name in columns
        if name not in ("ts_code", "pub_date", "imp_date", "st_type")
    )
    sql = (
        f"INSERT INTO st ({quoted}) VALUES ({placeholders}) "
        f"ON CONFLICT (ts_code, pub_date, imp_date, st_type) DO UPDATE SET {updates}"
    )
    with conn:
        conn.executemany(sql, records)
    return len(records)


def collect_stock_st(pro, conn: sqlite3.Connection, trade_dates: list[str]) -> tuple[int, str, str]:
    done = load_done(conn, "stock_st")
    rows = 0
    errors = []
    skipped = 0
    for trade_date in trade_dates:
        if trade_date in done:
            skipped += 1
            continue
        try:
            saved = replace_stock_st_day(
                conn,
                trade_date,
                fetch_pages(pro, "stock_st", STOCK_ST_FIELDS, "trade_date", trade_date, trade_date=trade_date),
            )
            if saved == 0:
                raise ValueError("开市日 ST 名单为空，不记为完成")
            with conn:
                mark_slice(conn, "stock_st", trade_date, saved, "ok")
            rows += saved
            log(f"  stock_st {trade_date}: {saved} 行")
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{trade_date}: {exc}")
            log(f"  stock_st {trade_date} 失败: {exc}")
            if is_permission_error(exc):
                break
    if skipped:
        log(f"  stock_st 跳过已完成 {skipped} 天")
    status = ("partial" if rows or skipped else "failed") if errors else "ok"
    return rows, status, "; ".join(errors)


def collect_st(pro, conn: sqlite3.Connection, days: list[str]) -> tuple[int, str, str]:
    done = load_done(conn, "st")
    rows = 0
    errors = []
    skipped = 0
    for field in ("imp_date", "pub_date"):
        for day in days:
            key = f"{field}:{day}"
            if key in done:
                skipped += 1
                continue
            try:
                saved = upsert_st_rows(
                    conn,
                    fetch_pages(pro, "st", ST_FIELDS, field, day, **{field: day}),
                )
                with conn:
                    mark_slice(conn, "st", key, saved, "ok")
                rows += saved
                if saved:
                    log(f"  st {field} {day}: {saved} 行")
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{key}: {exc}")
                log(f"  st {key} 失败: {exc}")
                if is_permission_error(exc):
                    break
        else:
            continue
        break
    if skipped:
        log(f"  st 跳过已完成 {skipped} 个日期切片")
    status = ("partial" if rows or skipped else "failed") if errors else "ok"
    return rows, status, "; ".join(errors)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="采集 ST 列表和 ST 变更到 storage/stock/data.sqlite")
    parser.add_argument("--days", type=int, default=365, help="自然日回溯窗口，默认 365")
    parser.add_argument("--start-date", help="开始日期 YYYY-MM-DD 或 YYYYMMDD")
    parser.add_argument("--end-date", help="结束日期，默认今天")
    return parser.parse_args(argv)


def resolve_window(args: argparse.Namespace) -> tuple[str, str]:
    if args.days <= 0:
        raise ValueError("--days 必须为正整数")
    end = datetime.strptime(compact_date(args.end_date), "%Y%m%d").date() if args.end_date else datetime.now().date()
    start = datetime.strptime(compact_date(args.start_date), "%Y%m%d").date() if args.start_date else end - timedelta(days=args.days)
    if start > end or end > datetime.now().date():
        raise ValueError("需满足开始日期 <= 结束日期 <= 今天")
    return start.strftime("%Y%m%d"), end.strftime("%Y%m%d")


def main(argv: list[str] | None = None) -> int:
    try:
        args = parse_args(argv)
        start_date, end_date = resolve_window(args)
    except (ValueError, argparse.ArgumentError) as exc:
        log(str(exc))
        return 1
    token = load_token()
    pro = ts.pro_api(token)
    conn = init_db(DB_PATH)
    log(f"采集区间：{start_date} ~ {end_date}；数据库：{DB_PATH}")
    exit_code = 0
    try:
        cal = call_api(pro, "trade_cal", exchange="SSE", start_date=start_date, end_date=end_date, is_open="1")
        if cal is None or cal.empty:
            raise ValueError("交易日历为空")
        trade_dates = sorted({compact_date(str(day)) for day in cal["cal_date"]})
        if any(day < start_date or day > end_date for day in trade_dates):
            raise ValueError("交易日历超出请求范围")
        log(f"开市日 {len(trade_dates)} 个：{trade_dates[0]} ~ {trade_dates[-1]}")
        for api_name, runner, units in (
            ("stock_st", lambda: collect_stock_st(pro, conn, trade_dates), "行"),
            ("st", lambda: collect_st(pro, conn, calendar_days(start_date, end_date)), "行"),
        ):
            started_at = datetime.now().isoformat(timespec="seconds")
            log(f"\n开始 {api_name}")
            try:
                rows, status, message = runner()
            except Exception as exc:  # noqa: BLE001
                rows, status, message = 0, "failed", str(exc)
                log(f"  {api_name} 失败: {exc}")
            write_import_log(conn, api_name, start_date, end_date, rows, status, message, started_at)
            log(f"完成 {api_name}: {status}, {rows} {units}")
            if status != "ok":
                exit_code = 1
    except Exception as exc:  # noqa: BLE001
        log(f"采集失败：{exc}")
        exit_code = 1
    finally:
        conn.close()
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
