#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""采集最近 365 个自然日的大宗交易，逐笔保存到本地 SQLite。"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import requests

# 同时支持 python collect/block_trade.py 与 python -m collect.block_trade。
if __package__:
    from .daily import call_api, is_permission_error, load_token, log, to_py, write_import_log
else:
    from daily import call_api, is_permission_error, load_token, log, to_py, write_import_log

DB_PATH = Path(__file__).resolve().parent.parent / "storage" / "stock" / "data.sqlite"
PAGE_SIZE = 1000
FIELDS = ("ts_code", "trade_date", "price", "vol", "amount", "buyer", "seller")


class TushareClient:
    """使用官方 HTTPS JSON 接口，HTTP 错误不能当作无成交数据。"""

    def __init__(self, token: str):
        self.token = token

    def query(self, api_name: str, fields: str = "", **params) -> pd.DataFrame:
        response = requests.post(
            "https://api.tushare.pro",
            json={"api_name": api_name, "token": self.token, "params": params, "fields": fields},
            timeout=30,
        )
        response.raise_for_status()
        result = response.json()
        if result["code"] != 0:
            raise RuntimeError(result.get("msg") or "Tushare 接口调用失败")
        data = result["data"]
        return pd.DataFrame(data["items"], columns=data["fields"])


def compact_date(value: str) -> str:
    return datetime.strptime(value.replace("-", ""), "%Y%m%d").strftime("%Y%m%d")


def init_db(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS block_trade (
            trade_date TEXT NOT NULL,
            record_no INTEGER NOT NULL,
            ts_code TEXT NOT NULL,
            price REAL,
            vol REAL,
            amount REAL,
            buyer TEXT,
            seller TEXT,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (trade_date, record_no)
        );
        CREATE INDEX IF NOT EXISTS idx_block_trade_ts_code_trade_date
            ON block_trade (ts_code, trade_date);
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
    """)
    return conn


def fetch_day(pro, trade_date: str) -> pd.DataFrame:
    """一日所有分页取完后才返回；不按股票或全字段去重。"""
    frames = []
    offset = 0
    fingerprints = set()
    while True:
        page = call_api(
            pro, "block_trade", trade_date=trade_date,
            fields=",".join(FIELDS), limit=PAGE_SIZE, offset=offset,
        )
        if page.empty:
            break
        if len(page) > PAGE_SIZE:
            raise ValueError("接口返回超过分页大小，拒绝写入疑似分页异常的数据")
        missing = set(FIELDS) - set(page.columns)
        if missing:
            raise ValueError(f"接口缺少字段：{sorted(missing)}")
        page = page.loc[:, list(FIELDS)].copy()
        page["trade_date"] = page["trade_date"].map(compact_date)
        if not page["trade_date"].eq(trade_date).all():
            raise ValueError(f"接口返回了 {trade_date} 以外的日期")
        # 若服务端忽略 offset，拒绝将重复整页无限追加。页内相同成交仍保留。
        fingerprint = tuple(pd.util.hash_pandas_object(page, index=False).tolist())
        if fingerprint in fingerprints:
            raise ValueError(f"检测到重复分页 offset={offset}，当日不写入")
        fingerprints.add(fingerprint)
        frames.append(page)
        if len(page) < PAGE_SIZE:
            break
        offset += len(page)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=FIELDS)


def replace_day(conn: sqlite3.Connection, trade_date: str, df: pd.DataFrame) -> int:
    """按日原子替换；本地序号不是交易所成交编号，相同明细也逐笔保留。"""
    compact = compact_date(trade_date)
    ymd = datetime.strptime(compact, "%Y%m%d").strftime("%Y-%m-%d")
    records = []
    if not df.empty:
        missing = set(FIELDS) - set(df.columns)
        if missing:
            raise ValueError(f"缺少字段：{sorted(missing)}")
        work = df.loc[:, list(FIELDS)].copy()
        if not work["trade_date"].map(compact_date).eq(compact).all():
            raise ValueError("成交日期与请求日期不一致")
        if work["ts_code"].isna().any() or work["ts_code"].astype(str).str.strip().eq("").any():
            raise ValueError("成交记录缺少股票代码")
        for col in ("price", "vol", "amount"):
            work[col] = pd.to_numeric(work[col], errors="raise")
        work = work.sort_values(list(FIELDS), kind="stable", na_position="last")
        updated_at = datetime.now().isoformat(timespec="seconds")
        for number, row in enumerate(work.itertuples(index=False, name=None), 1):
            code, _, price, vol, amount, buyer, seller = map(to_py, row)
            records.append((ymd, number, code, price, vol, amount, buyer, seller, updated_at))
    elif conn.execute("SELECT 1 FROM block_trade WHERE trade_date=? LIMIT 1", (ymd,)).fetchone():
        raise ValueError("接口返回空数据但库内该日已有记录，保留原数据并报告失败")
    with conn:
        conn.execute("DELETE FROM block_trade WHERE trade_date=?", (ymd,))
        conn.executemany(
            """INSERT INTO block_trade
               (trade_date,record_no,ts_code,price,vol,amount,buyer,seller,updated_at)
               VALUES (?,?,?,?,?,?,?,?,?)""", records,
        )
    return len(records)


def collect(pro, conn: sqlite3.Connection, trade_dates: list[str]) -> tuple[int, str, str]:
    rows = 0
    errors = []
    for trade_date in trade_dates:
        try:
            saved = replace_day(conn, trade_date, fetch_day(pro, trade_date))
            rows += saved
            log(f"  block_trade {trade_date}: {saved} 行")
        except Exception as exc:
            errors.append(f"{trade_date}: {exc}")
            log(f"  block_trade {trade_date} 失败: {exc}")
            if is_permission_error(exc):
                break
    status = ("partial" if rows else "failed") if errors else "ok"
    return rows, status, "; ".join(errors)


def main() -> int:
    parser = argparse.ArgumentParser(description="采集大宗交易到 storage/stock/data.sqlite")
    parser.add_argument("--days", type=int, default=365, help="自然日回溯窗口，默认 365")
    parser.add_argument("--start-date", help="开始日期 YYYY-MM-DD 或 YYYYMMDD")
    parser.add_argument("--end-date", help="结束日期，默认今天")
    args = parser.parse_args()
    if args.days <= 0:
        parser.error("--days 必须为正整数")
    try:
        end = datetime.strptime(compact_date(args.end_date), "%Y%m%d").date() if args.end_date else datetime.now().date()
        start = datetime.strptime(compact_date(args.start_date), "%Y%m%d").date() if args.start_date else end - timedelta(days=args.days)
    except ValueError as exc:
        parser.error(str(exc))
    if start > end or end > datetime.now().date():
        parser.error("需满足开始日期 <= 结束日期 <= 今天")
    start_date, end_date = start.strftime("%Y%m%d"), end.strftime("%Y%m%d")
    pro = TushareClient(load_token())
    conn = init_db(DB_PATH)
    started_at = datetime.now().isoformat(timespec="seconds")
    log(f"采集区间：{start_date} ~ {end_date}；数据库：{DB_PATH}")
    rows, status, message = 0, "failed", ""
    try:
        cal = call_api(pro, "trade_cal", exchange="SSE", start_date=start_date, end_date=end_date, is_open="1")
        if cal.empty:
            raise ValueError("交易日历为空，无法确认采集日期")
        dates = sorted({compact_date(day) for day in cal["cal_date"]})
        if any(day < start_date or day > end_date for day in dates):
            raise ValueError("交易日历超出请求范围")
        log(f"开市日 {len(dates)} 个：{dates[0]} ~ {dates[-1]}")
        rows, status, message = collect(pro, conn, dates)
    except Exception as exc:
        message = str(exc)
        log(f"采集失败：{exc}")
    finally:
        write_import_log(conn, "block_trade", start_date, end_date, rows, status, message, started_at)
        conn.close()
    log(f"完成 block_trade: {status}, {rows} 行")
    return 0 if status == "ok" else 1


if __name__ == "__main__":
    sys.exit(main())
