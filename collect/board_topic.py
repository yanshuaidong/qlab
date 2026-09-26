#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""采集 Tushare 打板专题数据，写入 storage/stock/data.sqlite。默认近 365 个自然日。"""

from __future__ import annotations

import argparse
import itertools
import json
import sqlite3
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import requests

if __package__:
    from .block_trade import TushareClient
    from .daily import is_permission_error, is_rate_limit, load_token, log, to_py, to_ymd, write_import_log
else:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from block_trade import TushareClient
    from daily import is_permission_error, is_rate_limit, load_token, log, to_py, to_ymd, write_import_log

REPO_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = REPO_ROOT / "storage" / "stock" / "data.sqlite"

DEFAULT_DAYS = 365
DEFAULT_INTERVAL = 0.15
MEMBER_INTERVAL = 0.3
FAST_INTERVAL = 0.12
CODE_WORKERS = 4
MAX_RETRIES = 5
RETRY_BACKOFF_SEC = 2.0
MAX_PAGES = 500
THS_INDEX_CAP = 5000
THS_INDEX_TYPES = ("N", "I", "R", "S", "ST", "TH", "BB")
THS_INDEX_EXCHANGES = ("A", "HK", "US")

DAILY_KINDS = {"daily", "daily_replace"}


class BoardClient(TushareClient):
    """官方 HTTPS 接口。空数据不是权限错误，HTTP 错误也不能当成 0 行。"""

    def query(self, api_name: str, fields: str = "", **params) -> pd.DataFrame:
        response = requests.post(
            "https://api.tushare.pro",
            json={"api_name": api_name, "token": self.token, "params": params, "fields": fields},
            timeout=60,
        )
        response.raise_for_status()
        result = response.json()
        if result.get("code") != 0:
            raise RuntimeError(result.get("msg") or "Tushare 接口调用失败")
        data = result.get("data") or {}
        items = data.get("items") or []
        columns = data.get("fields") or []
        if not items:
            return pd.DataFrame(columns=columns)
        return pd.DataFrame(items, columns=columns)


def q(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def text_cols(*names: str) -> list[tuple[str, str]]:
    return [(name, "TEXT") for name in names]


def real_cols(*names: str) -> list[tuple[str, str]]:
    return [(name, "REAL") for name in names]


def int_cols(*names: str) -> list[tuple[str, str]]:
    return [(name, "INTEGER") for name in names]


def _spec(
    *,
    kind: str,
    pk: tuple[str, ...],
    columns: list[tuple[str, str]],
    api_fields: tuple[str, ...],
    page_size: int = 2000,
    paginate: bool = True,
    interval: float = DEFAULT_INTERVAL,
    rename: dict[str, str] | None = None,
    variants: list[dict] | None = None,
    const: dict | None = None,
    fills: dict[str, str] | None = None,
    dates: tuple[str, ...] = ("trade_date",),
    required: tuple[str, ...] | None = None,
    workers: int = 1,
) -> dict:
    return {
        "kind": kind,
        "pk": pk,
        "columns": columns,
        "api_fields": api_fields,
        "page_size": page_size,
        "paginate": paginate,
        "interval": interval,
        "rename": rename or {},
        "variants": variants or [],
        "const": const or {},
        "fills": fills or {},
        "dates": dates,
        "required": required,
        "workers": workers,
    }


def _updated(columns: list[tuple[str, str]]) -> list[tuple[str, str]]:
    return [*columns, ("updated_at", "TEXT NOT NULL")]


SPECS: dict[str, dict] = {
    "hm_list": _spec(
        kind="snapshot",
        pk=("name",),
        columns=_updated([*text_cols("name", "intro", "orgs")]),
        api_fields=("name", "desc", "orgs"),
        page_size=1000,
        rename={"desc": "intro"},
        dates=(),
    ),
    "ths_index": _spec(
        kind="ths_index",
        pk=("ts_code",),
        columns=_updated([*text_cols("ts_code", "name", "exchange", "list_date", "type"), *int_cols("count")]),
        api_fields=("ts_code", "name", "count", "exchange", "list_date", "type"),
        paginate=False,
        dates=("list_date",),
    ),
    "ths_member": _spec(
        kind="per_code",
        pk=("ts_code", "con_code"),
        columns=_updated([
            *text_cols("ts_code", "con_code", "con_name", "in_date", "out_date", "is_new"),
            *real_cols("weight"),
        ]),
        api_fields=("ts_code", "con_code", "con_name", "weight", "in_date", "out_date", "is_new"),
        page_size=5000,
        interval=MEMBER_INTERVAL,
        dates=("in_date", "out_date"),
        workers=CODE_WORKERS,
    ),
    "ths_daily": _spec(
        kind="code_range",
        pk=("trade_date", "ts_code"),
        columns=_updated([
            *text_cols("ts_code", "trade_date"),
            *real_cols(
                "close", "open", "high", "low", "pre_close", "avg_price", "change",
                "pct_change", "vol", "turnover_rate", "total_mv", "float_mv",
            ),
        ]),
        api_fields=(
            "ts_code", "trade_date", "close", "open", "high", "low", "pre_close", "avg_price",
            "change", "pct_change", "vol", "turnover_rate", "total_mv", "float_mv",
        ),
        page_size=3000,
        workers=CODE_WORKERS,
    ),
    "limit_list_d": _spec(
        kind="daily",
        pk=("trade_date", "ts_code", "limit_flag"),
        columns=_updated([
            *text_cols("trade_date", "ts_code", "industry", "name", "first_time", "last_time", "up_stat", "limit_flag"),
            *real_cols("close", "pct_chg", "amount", "limit_amount", "float_mv", "total_mv", "turnover_ratio", "fd_amount"),
            *int_cols("open_times", "limit_times"),
        ]),
        api_fields=(
            "trade_date", "ts_code", "industry", "name", "close", "pct_chg", "amount", "limit_amount",
            "float_mv", "total_mv", "turnover_ratio", "fd_amount", "first_time", "last_time",
            "open_times", "up_stat", "limit_times", "limit",
        ),
        page_size=2500,
        interval=FAST_INTERVAL,
        rename={"limit": "limit_flag"},
        variants=[{"param": "limit_type", "values": ["U", "D", "Z"]}],
        fills={"limit_flag": "limit_type"},
    ),
    "limit_list_ths": _spec(
        kind="daily",
        pk=("trade_date", "ts_code", "limit_type"),
        columns=_updated([
            *text_cols(
                "trade_date", "ts_code", "name", "lu_desc", "limit_type", "tag", "status",
                "first_lu_time", "last_lu_time", "first_ld_time", "last_ld_time", "market_type",
            ),
            *real_cols(
                "price", "pct_chg", "limit_order", "limit_amount", "turnover_rate", "free_float",
                "lu_limit_order", "limit_up_suc_rate", "turnover", "rise_rate", "sum_float",
            ),
            *int_cols("open_num"),
        ]),
        api_fields=(
            "trade_date", "ts_code", "name", "price", "pct_chg", "open_num", "lu_desc", "limit_type",
            "tag", "status", "first_lu_time", "last_lu_time", "first_ld_time", "last_ld_time",
            "limit_order", "limit_amount", "turnover_rate", "free_float", "lu_limit_order",
            "limit_up_suc_rate", "turnover", "rise_rate", "sum_float", "market_type",
        ),
        page_size=4000,
        interval=FAST_INTERVAL,
        variants=[{"param": "limit_type", "values": ["涨停池", "连扳池", "冲刺涨停", "炸板池", "跌停池"]}],
        fills={"limit_type": "limit_type"},
    ),
    "limit_step": _spec(
        kind="daily",
        pk=("trade_date", "ts_code"),
        columns=_updated([*text_cols("ts_code", "name", "trade_date", "nums")]),
        api_fields=("ts_code", "name", "trade_date", "nums"),
        page_size=2000,
        interval=FAST_INTERVAL,
    ),
    "limit_cpt_list": _spec(
        kind="daily",
        pk=("trade_date", "ts_code"),
        columns=_updated([
            *text_cols("ts_code", "name", "trade_date", "up_stat", "rank"),
            *int_cols("days", "cons_nums", "up_nums"),
            *real_cols("pct_chg"),
        ]),
        api_fields=("ts_code", "name", "trade_date", "days", "up_stat", "cons_nums", "up_nums", "pct_chg", "rank"),
        page_size=2000,
        interval=FAST_INTERVAL,
    ),
    "kpl_list": _spec(
        kind="daily",
        pk=("trade_date", "ts_code", "tag"),
        columns=_updated([
            *text_cols("ts_code", "name", "trade_date", "lu_time", "ld_time", "open_time", "last_time", "lu_desc", "tag", "theme", "status"),
            *real_cols(
                "net_change", "bid_amount", "bid_change", "bid_turnover", "lu_bid_vol", "pct_chg",
                "bid_pct_chg", "rt_pct_chg", "limit_order", "amount", "turnover_rate", "free_float",
                "lu_limit_order",
            ),
        ]),
        api_fields=(
            "ts_code", "name", "trade_date", "lu_time", "ld_time", "open_time", "last_time", "lu_desc",
            "tag", "theme", "net_change", "bid_amount", "status", "bid_change", "bid_turnover",
            "lu_bid_vol", "pct_chg", "bid_pct_chg", "rt_pct_chg", "limit_order", "amount",
            "turnover_rate", "free_float", "lu_limit_order",
        ),
        page_size=8000,
        interval=FAST_INTERVAL,
        variants=[{"param": "tag", "values": ["涨停", "炸板", "跌停", "自然涨停", "竞价"]}],
        fills={"tag": "tag"},
    ),
    "kpl_concept_cons": _spec(
        kind="daily",
        pk=("trade_date", "ts_code", "con_code"),
        columns=_updated([
            *text_cols("ts_code", "name", "con_name", "con_code", "trade_date", "intro"),
            *int_cols("hot_num"),
        ]),
        api_fields=("ts_code", "name", "con_name", "con_code", "trade_date", "desc", "hot_num"),
        page_size=3000,
        rename={"desc": "intro"},
    ),
    "top_list": _spec(
        kind="daily_replace",
        pk=("trade_date", "record_no"),
        columns=_updated([
            ("trade_date", "TEXT"),
            ("record_no", "INTEGER"),
            *text_cols("ts_code", "name", "reason"),
            *real_cols(
                "close", "pct_change", "turnover_rate", "amount", "l_sell", "l_buy", "l_amount",
                "net_amount", "net_rate", "amount_rate", "float_values",
            ),
        ]),
        api_fields=(
            "trade_date", "ts_code", "name", "close", "pct_change", "turnover_rate", "amount",
            "l_sell", "l_buy", "l_amount", "net_amount", "net_rate", "amount_rate", "float_values", "reason",
        ),
        page_size=10000,
        required=("trade_date", "ts_code"),
    ),
    "top_inst": _spec(
        kind="daily_replace",
        pk=("trade_date", "record_no"),
        columns=_updated([
            ("trade_date", "TEXT"),
            ("record_no", "INTEGER"),
            *text_cols("ts_code", "exalter", "side", "reason"),
            *real_cols("buy", "buy_rate", "sell", "sell_rate", "net_buy"),
        ]),
        api_fields=("trade_date", "ts_code", "exalter", "side", "buy", "buy_rate", "sell", "sell_rate", "net_buy", "reason"),
        page_size=10000,
        required=("trade_date", "ts_code"),
    ),
    "hm_detail": _spec(
        kind="daily_replace",
        pk=("trade_date", "record_no"),
        columns=_updated([
            ("trade_date", "TEXT"),
            ("record_no", "INTEGER"),
            *text_cols("ts_code", "ts_name", "hm_name", "hm_orgs", "tag"),
            *real_cols("buy_amount", "sell_amount", "net_amount"),
        ]),
        api_fields=(
            "trade_date", "ts_code", "ts_name", "buy_amount", "sell_amount", "net_amount",
            "hm_name", "hm_orgs", "tag",
        ),
        page_size=2000,
        required=("trade_date", "ts_code"),
    ),
    "ths_hot": _spec(
        kind="daily",
        pk=("trade_date", "market", "data_type", "ts_code", "rank_time"),
        columns=_updated([
            *text_cols("trade_date", "market", "data_type", "ts_code", "ts_name", "concept", "rank_reason", "rank_time"),
            *int_cols("rank"),
            *real_cols("pct_change", "current_price", "hot"),
        ]),
        api_fields=(
            "trade_date", "data_type", "ts_code", "ts_name", "rank", "pct_change", "current_price",
            "concept", "rank_reason", "hot", "rank_time",
        ),
        page_size=2000,
        variants=[{"param": "market", "values": ["热股", "ETF", "可转债", "行业板块", "概念板块", "期货", "港股", "热基", "美股"]}],
        const={"is_new": "N"},
        fills={"market": "market", "data_type": "market"},
    ),
    "dc_hot": _spec(
        kind="daily",
        pk=("trade_date", "market", "hot_type", "ts_code", "rank_time"),
        columns=_updated([
            *text_cols("trade_date", "market", "hot_type", "data_type", "ts_code", "ts_name", "rank_time"),
            *int_cols("rank"),
            *real_cols("pct_change", "current_price"),
        ]),
        api_fields=("trade_date", "data_type", "ts_code", "ts_name", "rank", "pct_change", "current_price", "rank_time"),
        page_size=2000,
        variants=[
            {"param": "market", "values": ["A股市场", "ETF基金", "港股市场", "美股市场"]},
            {"param": "hot_type", "values": ["人气榜", "飙升榜"]},
        ],
        const={"is_new": "N"},
        fills={"market": "market", "hot_type": "hot_type"},
    ),
    "dc_index": _spec(
        kind="daily",
        pk=("trade_date", "ts_code"),
        columns=_updated([
            *text_cols("ts_code", "trade_date", "name", "leading", "leading_code", "idx_type", "level"),
            *real_cols("pct_change", "leading_pct", "total_mv", "turnover_rate"),
            *int_cols("up_num", "down_num"),
        ]),
        api_fields=(
            "ts_code", "trade_date", "name", "leading", "leading_code", "pct_change", "leading_pct",
            "total_mv", "turnover_rate", "up_num", "down_num", "idx_type", "level",
        ),
        page_size=5000,
        variants=[{"param": "idx_type", "values": ["行业板块", "概念板块", "地域板块"]}],
        fills={"idx_type": "idx_type"},
    ),
    "dc_daily": _spec(
        kind="daily",
        pk=("trade_date", "ts_code"),
        columns=_updated([
            *text_cols("ts_code", "trade_date", "category"),
            *real_cols("close", "open", "high", "low", "change", "pct_change", "vol", "amount", "swing", "turnover_rate"),
        ]),
        api_fields=(
            "ts_code", "trade_date", "close", "open", "high", "low", "change", "pct_change",
            "vol", "amount", "swing", "turnover_rate", "category",
        ),
        page_size=2000,
    ),
    "dc_member": _spec(
        kind="daily",
        pk=("trade_date", "ts_code", "con_code"),
        columns=_updated([*text_cols("trade_date", "ts_code", "con_code", "name")]),
        api_fields=("trade_date", "ts_code", "con_code", "name"),
        page_size=5000,
    ),
    "tdx_index": _spec(
        kind="daily",
        pk=("trade_date", "ts_code"),
        columns=_updated([
            *text_cols("ts_code", "trade_date", "name", "idx_type"),
            *int_cols("idx_count"),
            *real_cols("total_share", "float_share", "total_mv", "float_mv"),
        ]),
        api_fields=("ts_code", "trade_date", "name", "idx_type", "idx_count", "total_share", "float_share", "total_mv", "float_mv"),
        page_size=1000,
        variants=[{"param": "idx_type", "values": ["概念板块", "行业板块", "风格板块", "地区板块"]}],
        fills={"idx_type": "idx_type"},
    ),
    "tdx_daily": _spec(
        kind="daily",
        pk=("trade_date", "ts_code"),
        columns=_updated([
            *text_cols("ts_code", "trade_date", "rise", "pe", "pb"),
            *real_cols(
                "close", "open", "high", "low", "pre_close", "change", "pct_change", "vol", "amount",
                "vol_ratio", "turnover_rate", "swing", "pct_3d", "pct_5d", "pct_10d", "pct_20d", "pct_60d",
                "mtd", "ytd", "pct_1y", "float_mv", "ab_total_mv", "float_share", "total_share",
                "bm_buy_net", "bm_buy_ratio", "bm_net", "bm_ratio",
            ),
            *int_cols("up_num", "down_num", "limit_up_num", "limit_down_num", "lu_days"),
        ]),
        api_fields=(
            "ts_code", "trade_date", "close", "open", "high", "low", "pre_close", "change", "pct_change",
            "vol", "amount", "rise", "vol_ratio", "turnover_rate", "swing", "up_num", "down_num",
            "limit_up_num", "limit_down_num", "lu_days", "3day", "5day", "10day", "20day", "60day",
            "mtd", "ytd", "1year", "pe", "pb", "float_mv", "ab_total_mv", "float_share", "total_share",
            "bm_buy_net", "bm_buy_ratio", "bm_net", "bm_ratio",
        ),
        page_size=3000,
        rename={"3day": "pct_3d", "5day": "pct_5d", "10day": "pct_10d", "20day": "pct_20d", "60day": "pct_60d", "1year": "pct_1y"},
    ),
    "tdx_member": _spec(
        kind="daily",
        pk=("trade_date", "ts_code", "con_code"),
        columns=_updated([*text_cols("ts_code", "trade_date", "con_code", "con_name")]),
        api_fields=("ts_code", "trade_date", "con_code", "con_name"),
        page_size=3000,
    ),
    "stk_auction": _spec(
        kind="daily",
        pk=("trade_date", "ts_code"),
        columns=_updated([
            *text_cols("ts_code", "trade_date"),
            *real_cols("vol", "price", "amount", "pre_close", "turnover_rate", "volume_ratio", "float_share"),
        ]),
        api_fields=("ts_code", "trade_date", "vol", "price", "amount", "pre_close", "turnover_rate", "volume_ratio", "float_share"),
        page_size=8000,
    ),
}

API_ORDER = (
    "hm_list", "ths_index", "ths_member", "ths_daily",
    "limit_list_d", "limit_list_ths", "limit_step", "limit_cpt_list", "kpl_list",
    "top_list", "top_inst", "hm_detail", "ths_hot", "dc_hot",
    "dc_index", "dc_daily", "dc_member", "tdx_index", "tdx_daily", "tdx_member",
    "kpl_concept_cons", "stk_auction",
)


def validate_specs() -> None:
    if set(SPECS) != set(API_ORDER):
        raise RuntimeError("API_ORDER 与 SPECS 不一致")
    for name, spec in SPECS.items():
        columns = [column for column, _ in spec["columns"]]
        if len(columns) != len(set(columns)):
            raise RuntimeError(f"{name} 列名重复")
        missing_pk = [column for column in spec["pk"] if column not in columns]
        if missing_pk or columns[-1] != "updated_at":
            raise RuntimeError(f"{name} 主键或 updated_at 不正确")
        produced = (set(spec["api_fields"]) - set(spec["rename"])) | set(spec["rename"].values()) | set(spec["fills"])
        required_cols = set(columns) - {"updated_at", "record_no"}
        if required_cols - produced:
            raise RuntimeError(f"{name} 缺少列来源：{sorted(required_cols - produced)}")


validate_specs()


def compact_date(value: object) -> str:
    text = str(value).strip().replace("-", "")
    if len(text) < 8 or not text[:8].isdigit():
        raise ValueError(f"无法解析日期：{value}")
    return text[:8]


def to_store(value: object):
    if isinstance(value, (list, dict)):
        return json.dumps(value, ensure_ascii=False)
    return to_py(value)


def init_db(path: Path) -> sqlite3.Connection:
    if str(path) != ":memory:":
        path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=60)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA busy_timeout=120000")
    for table, spec in SPECS.items():
        pk = set(spec["pk"])
        parts = []
        for name, decl in spec["columns"]:
            if name in pk and "NOT NULL" not in decl:
                decl = f"{decl} NOT NULL"
            parts.append(f"{q(name)} {decl}")
        pk_sql = ", ".join(q(column) for column in spec["pk"])
        conn.execute(f"CREATE TABLE IF NOT EXISTS {q(table)} ({', '.join(parts)}, PRIMARY KEY ({pk_sql}))")
        for column in ("trade_date", "ts_code", "con_code"):
            if any(name == column for name, _ in spec["columns"]):
                conn.execute(
                    f"CREATE INDEX IF NOT EXISTS idx_{table}_{column} ON {q(table)} ({q(column)})"
                )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS board_topic_slice (
            api_name TEXT NOT NULL,
            slice_key TEXT NOT NULL,
            rows INTEGER NOT NULL,
            status TEXT NOT NULL,
            finished_at TEXT NOT NULL,
            PRIMARY KEY (api_name, slice_key)
        )
        """
    )
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


_RATE_LOCK = threading.Lock()
_NEXT_SLOT: dict[str, float] = {}
_THREAD_DB = threading.local()


def reserve_slot(api_name: str, interval: float) -> None:
    """按接口限制相邻请求的发起间隔。请求本身花掉的时间计入额度，不再额外空等。"""
    if interval <= 0:
        return
    while True:
        with _RATE_LOCK:
            now = time.monotonic()
            slot = _NEXT_SLOT.get(api_name, 0.0)
            if slot <= now:
                _NEXT_SLOT[api_name] = now + interval
                return
            delay = slot - now
            _NEXT_SLOT[api_name] = slot + interval
        time.sleep(delay)


def call_api(pro, api_name: str, *, interval: float, fields: str, **params) -> pd.DataFrame:
    last_error: BaseException | None = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            reserve_slot(api_name, interval)
            data = pro.query(api_name, fields=fields, **params)
            if data is None:
                return pd.DataFrame()
            return data
        except Exception as exc:  # noqa: BLE001 — Tushare 错误类型不统一
            last_error = exc
            if is_permission_error(exc):
                raise
            retry = is_rate_limit(exc) or "timeout" in str(exc).lower()
            if isinstance(exc, requests.HTTPError):
                status = exc.response.status_code if exc.response is not None else 0
                retry = status >= 500 or status == 429
            elif isinstance(exc, requests.RequestException):
                retry = True
            if not retry or attempt == MAX_RETRIES:
                raise
            wait = RETRY_BACKOFF_SEC * attempt
            log(f"  限频/网络错误，{wait:.1f}s 后重试 {api_name} ({attempt}/{MAX_RETRIES}): {exc}")
            time.sleep(wait)
    raise last_error if last_error else RuntimeError(f"{api_name} 调用失败")


def page_fingerprint(page: pd.DataFrame):
    try:
        hashed = pd.util.hash_pandas_object(page, index=False)
    except TypeError:
        hashed = pd.util.hash_pandas_object(page.astype(str), index=False)
    return tuple(hashed.tolist())


def fetch_pages(pro, api_name: str, *, page_size: int, interval: float, fields: str, **params) -> pd.DataFrame:
    frames = []
    offset = 0
    seen = set()
    pages = 0
    while True:
        if pages >= MAX_PAGES:
            raise ValueError(f"{api_name} 分页超过安全上限，拒绝写入疑似截断的数据")
        page = call_api(
            pro, api_name, interval=interval, fields=fields,
            limit=page_size, offset=offset, **params,
        )
        pages += 1
        if page is None or page.empty:
            break
        if len(page) > page_size:
            raise ValueError(f"{api_name} 返回超过分页大小，拒绝写入")
        fingerprint = page_fingerprint(page)
        if fingerprint in seen:
            raise ValueError(f"{api_name} 检测到重复分页 offset={offset}，拒绝写入")
        seen.add(fingerprint)
        frames.append(page)
        if len(page) < page_size:
            break
        offset += len(page)
        log(f"  {api_name} 继续分页 offset={offset}")
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


def variant_combos(spec: dict):
    dims = spec["variants"]
    if not dims:
        yield {}, ""
        return
    keys = [item["param"] for item in dims]
    values = [item["values"] for item in dims]
    for combo in itertools.product(*values):
        yield dict(zip(keys, combo)), "|".join(combo)


def _blank(series: pd.Series) -> pd.Series:
    return series.isna() | series.map(lambda value: str(value).strip() == "" or str(value) == "None")


def prepare_frame(df: pd.DataFrame, spec: dict, fills: dict | None = None, expect_date: str | None = None, date_range: tuple[str, str] | None = None) -> pd.DataFrame:
    work = df.copy()
    if spec["rename"]:
        work = work.rename(columns=spec["rename"])
    for column, value in (fills or {}).items():
        if column not in work.columns:
            work[column] = value
        else:
            missing = _blank(work[column])
            work.loc[missing, column] = value
    for name, _ in spec["columns"]:
        if name in ("record_no", "updated_at"):
            continue
        if name not in work.columns:
            work[name] = None
    for date_col in spec["dates"]:
        if date_col in work.columns:
            work[date_col] = work[date_col].map(to_ymd)
    for name, decl in spec["columns"]:
        if name not in work.columns or name in ("record_no", "updated_at"):
            continue
        if decl.startswith("REAL") or decl.startswith("INTEGER"):
            work[name] = pd.to_numeric(work[name], errors="coerce")
    if expect_date is not None and not work.empty:
        if "trade_date" not in work.columns or work["trade_date"].isna().any() or not work["trade_date"].eq(expect_date).all():
            raise ValueError(f"接口返回了 {expect_date} 以外的日期")
    if date_range is not None and not work.empty:
        start, end = date_range
        dates = work["trade_date"]
        if dates.isna().any() or dates.lt(start).any() or dates.gt(end).any():
            raise ValueError("行情日期超出请求区间")
    return work


def _required(spec: dict) -> tuple[str, ...]:
    if spec["required"] is not None:
        return spec["required"]
    return tuple(column for column in spec["pk"] if column != "record_no")


def _check_required(work: pd.DataFrame, spec: dict, table: str) -> None:
    for column in _required(spec):
        if column not in work.columns or _blank(work[column]).any():
            raise ValueError(f"{table} 缺少必填字段 {column}")


def _records(work: pd.DataFrame, spec: dict, with_record_no: bool) -> list[tuple]:
    columns = [name for name, _ in spec["columns"]]
    data_columns = [name for name in columns if name != "record_no"]
    stamped = work.copy()
    stamped["updated_at"] = datetime.now().isoformat(timespec="seconds")
    if with_record_no:
        sort_cols = [name for name in data_columns if name != "updated_at"]
        stamped = stamped.sort_values(sort_cols, kind="stable", na_position="last")
    records = []
    for number, row in enumerate(stamped[data_columns].itertuples(index=False, name=None), 1):
        mapped = dict(zip(data_columns, row))
        values = []
        for name in columns:
            if name == "record_no":
                values.append(number)
            else:
                values.append(to_store(mapped[name]))
        records.append(tuple(values))
    return records


def _insert_sql(table: str, spec: dict, upsert: bool) -> str:
    columns = [name for name, _ in spec["columns"]]
    placeholders = ",".join("?" for _ in columns)
    insert_cols = ",".join(q(column) for column in columns)
    if not upsert:
        return f"INSERT INTO {q(table)} ({insert_cols}) VALUES ({placeholders})"
    pk_sql = ",".join(q(column) for column in spec["pk"])
    updates = ",".join(
        f"{q(column)}=excluded.{q(column)}" for column in columns if column not in spec["pk"]
    )
    return (
        f"INSERT INTO {q(table)} ({insert_cols}) VALUES ({placeholders}) "
        f"ON CONFLICT ({pk_sql}) DO UPDATE SET {updates}"
    )


def _executemany(conn: sqlite3.Connection, sql: str, records: list[tuple]) -> None:
    for start in range(0, len(records), 5000):
        conn.executemany(sql, records[start:start + 5000])


def upsert_rows(conn: sqlite3.Connection, table: str, df: pd.DataFrame, fills: dict | None = None, expect_date: str | None = None, date_range: tuple[str, str] | None = None) -> int:
    if df is None or df.empty:
        return 0
    spec = SPECS[table]
    work = prepare_frame(df, spec, fills, expect_date, date_range)
    missing = pd.Series(False, index=work.index)
    for column in spec["pk"]:
        missing = missing | _blank(work[column])
    if missing.any():
        log(f"  {table} 丢弃 {int(missing.sum())} 行缺少主键的记录")
        work = work.loc[~missing]
    if work.empty:
        return 0
    work = work.drop_duplicates(subset=list(spec["pk"]), keep="last")
    records = _records(work, spec, with_record_no=False)
    _executemany(conn, _insert_sql(table, spec, upsert=True), records)
    return len(records)


def replace_rows(conn: sqlite3.Connection, table: str, trade_date: str, df: pd.DataFrame) -> int:
    """成功返回的数据整日替换。调用方只有在请求成功后才能进入这里。"""
    spec = SPECS[table]
    ymd = to_ymd(compact_date(trade_date))
    if df is None or df.empty:
        records = []
    else:
        work = prepare_frame(df, spec, expect_date=ymd)
        _check_required(work, spec, table)
        records = _records(work, spec, with_record_no=True)
    conn.execute(f"DELETE FROM {q(table)} WHERE {q('trade_date')}=?", (ymd,))
    if records:
        _executemany(conn, _insert_sql(table, spec, upsert=False), records)
    return len(records)


def load_done(conn: sqlite3.Connection, api_name: str) -> set[str]:
    return {
        row[0]
        for row in conn.execute(
            "SELECT slice_key FROM board_topic_slice WHERE api_name=? AND status='ok'",
            (api_name,),
        )
    }


def mark_slice(conn: sqlite3.Connection, api_name: str, slice_key: str, rows: int, status: str) -> None:
    conn.execute(
        """
        INSERT INTO board_topic_slice (api_name, slice_key, rows, status, finished_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT (api_name, slice_key) DO UPDATE SET
            rows=excluded.rows,
            status=excluded.status,
            finished_at=excluded.finished_at
        """,
        (api_name, slice_key, rows, status, datetime.now().isoformat(timespec="seconds")),
    )


def commit_slice(conn: sqlite3.Connection, api_name: str, slice_key: str, writer) -> int:
    with conn:
        saved = writer()
        mark_slice(conn, api_name, slice_key, saved, "ok")
    return saved


def mark_failed(conn: sqlite3.Connection, api_name: str, slice_key: str) -> None:
    mark_slice(conn, api_name, slice_key, 0, "failed")
    conn.commit()


def load_ths_codes(conn: sqlite3.Connection) -> list[str]:
    exists = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='ths_index'"
    ).fetchone()
    if not exists:
        return []
    return [row[0] for row in conn.execute(f"SELECT {q('ts_code')} FROM {q('ths_index')} ORDER BY {q('ts_code')}")]


def _fields(spec: dict) -> str:
    return ",".join(spec["api_fields"])


def _fetch(pro, api_name: str, spec: dict, **params) -> pd.DataFrame:
    fields = _fields(spec)
    if spec["paginate"]:
        return fetch_pages(
            pro, api_name, page_size=spec["page_size"], interval=spec["interval"], fields=fields, **params,
        )
    return call_api(pro, api_name, interval=spec["interval"], fields=fields, **params)


def _fills_from(spec: dict, params: dict) -> dict:
    return {column: params[source] for column, source in spec["fills"].items() if source in params}


def _result(rows: int, errors: list[str], skipped: int, permission: bool) -> tuple[int, str, str]:
    if permission and rows == 0 and skipped == 0:
        status = "failed"
    elif errors or permission:
        status = "partial" if (rows or skipped) else "failed"
    else:
        status = "ok"
    parts = []
    if skipped:
        parts.append(f"跳过已完成切片 {skipped} 个")
    if errors:
        shown = "; ".join(errors[:30])
        if len(errors) > 30:
            shown += f"; 另有 {len(errors) - 30} 条错误"
        parts.append(shown)
    return rows, status, "; ".join(parts)


def _fail_slice(conn, api_name: str, key: str, exc: BaseException, errors: list[str]) -> bool:
    if is_permission_error(exc):
        errors.append(str(exc))
        return True
    errors.append(f"{key}: {exc}")
    log(f"  {api_name} {key} 失败: {exc}")
    mark_failed(conn, api_name, key)
    return False


def _thread_conn() -> sqlite3.Connection:
    conn = getattr(_THREAD_DB, "conn", None)
    if conn is None:
        conn = init_db(DB_PATH)
        _THREAD_DB.conn = conn
    return conn


def _collect_codes_parallel(pro, api_name: str, jobs: list[tuple]) -> tuple[int, list[str], bool]:
    """同一接口内用少量并发把文档允许的每分钟次数打满。每个线程单独持有数据库连接。"""
    rows = 0
    errors: list[str] = []
    permission = False
    total = len(jobs)
    finished = 0
    stop = threading.Event()
    workers = min(SPECS[api_name]["workers"], total)

    def run_job(job: tuple):
        _key, params, date_range = job
        if stop.is_set():
            return _key, 0, None
        conn = _thread_conn()
        try:
            frame = _fetch(pro, api_name, SPECS[api_name], **params)
            saved = commit_slice(
                conn, api_name, _key,
                lambda frame=frame, date_range=date_range: upsert_rows(
                    conn, api_name, frame, date_range=date_range,
                ),
            )
            return _key, saved, None
        except Exception as exc:  # noqa: BLE001
            if is_permission_error(exc):
                stop.set()
                return _key, 0, exc
            mark_failed(conn, api_name, _key)
            return _key, 0, exc

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(run_job, job) for job in jobs]
        for future in as_completed(futures):
            key, saved, exc = future.result()
            finished += 1
            if exc is not None:
                if is_permission_error(exc):
                    permission = True
                    if str(exc) not in errors:
                        errors.append(str(exc))
                else:
                    errors.append(f"{key}: {exc}")
                    log(f"  {api_name} {key} 失败: {exc}")
            else:
                rows += saved
            if finished == 1 or finished % 100 == 0 or finished == total:
                log(f"  {api_name} 进度 {finished}/{total}")
    return rows, errors, permission


def collect_api(pro, conn: sqlite3.Connection, api_name: str, trade_dates: list[str], start_date: str, end_date: str) -> tuple[int, str, str]:
    spec = SPECS[api_name]
    done = load_done(conn, api_name)
    rows = 0
    errors: list[str] = []
    skipped = 0
    permission = False
    kind = spec["kind"]

    if kind == "snapshot":
        key = "all"
        if key in done:
            return _result(0, [], 1, False)
        try:
            frame = _fetch(pro, api_name, spec)
            rows = commit_slice(conn, api_name, key, lambda: upsert_rows(conn, api_name, frame))
            log(f"  {api_name}: {rows} 行")
        except Exception as exc:  # noqa: BLE001
            permission = _fail_slice(conn, api_name, key, exc, errors)
        return _result(rows, errors, skipped, permission)

    if kind == "ths_index":
        for type_code in THS_INDEX_TYPES:
            if type_code in done:
                skipped += 1
                continue
            try:
                frame = call_api(
                    pro, api_name, interval=spec["interval"], fields=_fields(spec), type=type_code,
                )
                if len(frame) >= THS_INDEX_CAP:
                    saved = 0
                    for exchange in THS_INDEX_EXCHANGES:
                        part_key = f"{type_code}|{exchange}"
                        if part_key in done:
                            skipped += 1
                            continue
                        part = call_api(
                            pro, api_name, interval=spec["interval"], fields=_fields(spec),
                            type=type_code, exchange=exchange,
                        )
                        if len(part) >= THS_INDEX_CAP:
                            raise ValueError(f"ths_index {type_code} {exchange} 达到 {THS_INDEX_CAP} 行上限，拒绝截断写入")
                        saved += commit_slice(
                            conn, api_name, part_key, lambda part=part: upsert_rows(conn, api_name, part),
                        )
                        done.add(part_key)
                    rows += saved
                    with conn:
                        mark_slice(conn, api_name, type_code, saved, "ok")
                    done.add(type_code)
                    log(f"  ths_index {type_code}: {saved} 行（按交易所拆分）")
                else:
                    saved = commit_slice(conn, api_name, type_code, lambda frame=frame: upsert_rows(conn, api_name, frame))
                    rows += saved
                    done.add(type_code)
                    log(f"  ths_index {type_code}: {saved} 行")
            except Exception as exc:  # noqa: BLE001
                permission = _fail_slice(conn, api_name, type_code, exc, errors)
                if permission:
                    break
        return _result(rows, errors, skipped, permission)

    if kind in {"per_code", "code_range"}:
        codes = load_ths_codes(conn)
        if not codes:
            return 0, "failed", "ths_index 中没有板块代码"
        start_ymd, end_ymd = to_ymd(start_date), to_ymd(end_date)
        jobs = []
        for code in codes:
            key = f"{code}|{start_date}|{end_date}" if kind == "code_range" else code
            if key in done:
                skipped += 1
                continue
            params = {"ts_code": code}
            if kind == "code_range":
                params["start_date"] = start_date
                params["end_date"] = end_date
            jobs.append((key, params, (start_ymd, end_ymd) if kind == "code_range" else None))
        if spec["workers"] > 1 and len(jobs) > 1:
            saved_rows, code_errors, permission = _collect_codes_parallel(pro, api_name, jobs)
            return _result(rows + saved_rows, errors + code_errors, skipped, permission)
        for index, (key, params, date_range) in enumerate(jobs, 1):
            try:
                frame = _fetch(pro, api_name, spec, **params)
                saved = commit_slice(
                    conn, api_name, key,
                    lambda frame=frame, date_range=date_range: upsert_rows(
                        conn, api_name, frame, date_range=date_range,
                    ),
                )
                rows += saved
                done.add(key)
                if index == 1 or index % 100 == 0 or index == len(jobs):
                    log(f"  {api_name} {key}: {saved} 行 ({index}/{len(jobs)})")
            except Exception as exc:  # noqa: BLE001
                permission = _fail_slice(conn, api_name, key, exc, errors)
                if permission:
                    break
        return _result(rows, errors, skipped, permission)

    for trade_date in trade_dates:
        for params, label in variant_combos(spec):
            key = f"{trade_date}|{label}" if label else trade_date
            if key in done:
                skipped += 1
                continue
            try:
                call_params = {**spec["const"], **params, "trade_date": trade_date}
                frame = _fetch(pro, api_name, spec, **call_params)
                fills = _fills_from(spec, params)
                if kind == "daily_replace":
                    writer = lambda frame=frame, trade_date=trade_date: replace_rows(conn, api_name, trade_date, frame)
                else:
                    writer = lambda frame=frame, fills=fills, trade_date=trade_date: upsert_rows(
                        conn, api_name, frame, fills, expect_date=to_ymd(trade_date),
                    )
                saved = commit_slice(conn, api_name, key, writer)
                rows += saved
                done.add(key)
                log(f"  {api_name} {key}: {saved} 行")
            except Exception as exc:  # noqa: BLE001
                permission = _fail_slice(conn, api_name, key, exc, errors)
                if permission:
                    break
        if permission:
            break
    return _result(rows, errors, skipped, permission)


def list_trade_dates(pro, start_date: str, end_date: str) -> list[str]:
    calendar = call_api(
        pro, "trade_cal", interval=DEFAULT_INTERVAL, fields="cal_date",
        exchange="SSE", start_date=start_date, end_date=end_date, is_open="1",
    )
    if calendar is None or calendar.empty:
        return []
    dates = sorted({compact_date(value) for value in calendar["cal_date"]})
    if any(day < start_date or day > end_date for day in dates):
        raise ValueError("交易日历超出请求范围")
    return dates


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="采集 Tushare 打板专题数据到 storage/stock/data.sqlite")
    parser.add_argument("apis", nargs="*", help="只跑指定接口名，默认全部")
    parser.add_argument("--days", type=int, default=DEFAULT_DAYS, help=f"自然日回溯窗口，默认 {DEFAULT_DAYS}")
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


def run_api(token: str, api_name: str, trade_dates: list[str], start_date: str, end_date: str) -> str:
    conn = init_db(DB_PATH)
    pro = BoardClient(token)
    started_at = datetime.now().isoformat(timespec="seconds")
    log(f"\n开始 {api_name}")
    try:
        rows, status, message = collect_api(pro, conn, api_name, trade_dates, start_date, end_date)
    except Exception as exc:  # noqa: BLE001
        rows, status, message = 0, "failed", str(exc)
        log(f"  {api_name} 失败: {exc}")
    write_import_log(conn, api_name, start_date, end_date, rows, status, message, started_at)
    log(f"完成 {api_name}: {status}, {rows} 行")
    conn.close()
    return status


def main(argv: list[str] | None = None) -> int:
    try:
        args = parse_args(argv)
        start_date, end_date = resolve_window(args)
    except (ValueError, argparse.ArgumentError) as exc:
        log(str(exc))
        return 1
    selected = list(args.apis) or list(API_ORDER)
    unknown = [name for name in selected if name not in SPECS]
    if unknown:
        log("未知接口：" + ", ".join(unknown))
        return 1
    selected = [name for name in API_ORDER if name in selected]
    token = load_token()
    pro = BoardClient(token)
    conn = init_db(DB_PATH)
    exit_code = 0
    try:
        need_dates = any(SPECS[name]["kind"] in DAILY_KINDS for name in selected)
        trade_dates: list[str] = []
        if need_dates:
            trade_dates = list_trade_dates(pro, start_date, end_date)
            if not trade_dates:
                log("交易日历为空，退出")
                return 1
            log(f"开市日 {len(trade_dates)} 个：{trade_dates[0]} ~ {trade_dates[-1]}")
        log(f"采集区间：{start_date} ~ {end_date}；数据库：{DB_PATH}")
        if ("ths_member" in selected or "ths_daily" in selected) and not load_ths_codes(conn):
            if "ths_index" not in selected:
                log("ths_member / ths_daily 依赖板块代码，先采集 ths_index")
            status = run_api(token, "ths_index", trade_dates, start_date, end_date)
            if status != "ok":
                exit_code = 1
            selected = [name for name in selected if name != "ths_index"]
            if not load_ths_codes(conn):
                log("ths_index 没有板块代码，成分和行情无法继续")
                return 1
        elif "ths_index" in selected and load_done(conn, "ths_index") >= set(THS_INDEX_TYPES):
            selected = [name for name in selected if name != "ths_index"]
            log("ths_index 已完成，跳过")
        if not selected:
            return exit_code
        log(f"并发采集 {len(selected)} 个接口")
        with ThreadPoolExecutor(max_workers=len(selected)) as pool:
            futures = [
                pool.submit(run_api, token, api_name, trade_dates, start_date, end_date)
                for api_name in selected
            ]
            for future in as_completed(futures):
                if future.result() != "ok":
                    exit_code = 1
    finally:
        conn.close()
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
