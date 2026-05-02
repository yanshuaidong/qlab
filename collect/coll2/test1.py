from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sqlite3
import subprocess
import time
from dataclasses import dataclass
from urllib.parse import parse_qs, urlencode, urlparse
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterable

import akshare as ak
import pandas as pd
import requests


DEFAULT_DB_PATH = Path(__file__).with_name("data") / "stock.sqlite"
TABLE_NAME = "stock_basic_info"
DAILY_LOG_TABLE = "stock_daily_import_log"
EASTMONEY_KLINE_URL = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
EASTMONEY_UT = "fa5fd1943c7b386f172d6893dbfba10b"
EASTMONEY_COLL2_DIR = Path(__file__).resolve().parent
EASTMONEY_CURL_MD_PATH = Path(r"D:\ysd\qlab\collect\coll2\curl1.md")


class EastmoneyUnavailableError(Exception):
    """Eastmoney 返回异常或可判定为不可用（如无 data / 无效 JSON）。可能触发切换到下一 Markdown 会话（若有）。"""


class EastmoneyProfilesExhausted(RuntimeError):
    """配置的 eastmoney Markdown 会话（当前仅 curl1.md）已全部失败。"""


@dataclass(frozen=True)
class EastmoneyCurlProfile:
    """从 Markdown 粘贴的 curl 文本解析出的会话参数。"""

    cookie: str
    ut: str | None = None
    cb: str | None = None
    label: str = ""

    def ut_value(self) -> str:
        return self.ut or EASTMONEY_UT

    def cb_value(self) -> str:
        return self.cb or "quote_jp1"


def _normalize_windows_curl_cookie(raw: str) -> str:
    """将 cmd 里 Chrome 粘贴的转义还原为 Cookie 中的 %20 / %3A 等。"""
    s = raw.strip()
    s = re.sub(r"\^%\^", "%", s)
    s = re.sub(r"\^%", "%", s)
    return s


def parse_eastmoney_curl_markdown(content: str) -> EastmoneyCurlProfile | None:
    blob = " ".join(s for line in content.splitlines() if (s := line.strip()))
    if not blob.casefold().startswith("curl"):
        return None

    um = re.search(r'curl\s+\^"(https://push2his\.eastmoney\.com[^"]+?)\^"', blob)
    ut: str | None = None
    cb: str | None = None
    if um:
        qs = urlparse(um.group(1).replace("^&", "&")).query
        qd = parse_qs(qs)
        raw_ut = (qd.get("ut") or [None])[0]
        raw_cb = (qd.get("cb") or [None])[0]
        ut = raw_ut.strip() if raw_ut else None
        cb = raw_cb.strip() if raw_cb else None

    cm = re.search(r"-b\s+\^\"(.+?)\^\"", blob)
    if not cm:
        cm = re.search(r'-b\s+"([^"]+)"', blob)
    if not cm:
        return None
    cookie = _normalize_windows_curl_cookie(cm.group(1))
    if not cookie:
        return None
    return EastmoneyCurlProfile(cookie=cookie, ut=ut, cb=cb, label="")


def load_ordered_eastmoney_curl_profiles() -> list[tuple[str, EastmoneyCurlProfile]]:
    """仅从 EASTMONEY_CURL_MD_PATH 读取一份 curl 会话；每项为 (展示名, profile)。"""
    out: list[tuple[str, EastmoneyCurlProfile]] = []
    path = EASTMONEY_CURL_MD_PATH.resolve()
    if not path.is_file():
        return out
    text = path.read_text(encoding="utf-8", errors="replace")
    prof = parse_eastmoney_curl_markdown(text)
    if prof is None:
        return out
    name = path.name
    out.append((name, EastmoneyCurlProfile(cookie=prof.cookie, ut=prof.ut, cb=prof.cb, label=name)))
    return out


@dataclass
class EastmoneyMarkdownState:
    """Eastmoney Markdown 会话列表（当前仅载入 curl1.md）；失败后 active_slot 进位。"""

    profiles: list[tuple[str, EastmoneyCurlProfile]]
    active_slot: list[int]


# Browser session cookie fallback when curl1.md 无效或缺失（可被 EASTMONEY_COOKIE / --eastmoney-cookie 覆盖）。
EASTMONEY_DEFAULT_COOKIE = (
    "qgqp_b_id=1383c5afdb5e5ab972a424fbccc9c88f; "
    "st_nvi=AnmJIvg1ox67FtBWa7h7Ge8c4; "
    "st_si=16780206032260; "
    "nid18=000842679b010e1a44cbeba60a0c8e65; "
    "nid18_create_time=1777733137573; "
    "gviem=zFRJ6mz3EREWQO7j4eEdrb71f; "
    "gviem_create_time=1777733137573; "
    "st_pvi=23655418220541; "
    "st_sp=2026-05-02%2022%3A45%3A37; "
    "st_inirUrl=; "
    "st_sn=2; "
    "st_psi=20260502224825673-113200354966-7443571177; "
    "wsc_checkuser_ok=1; "
    "st_asi=20260502224825673-113200354966-7443571177-web.xgnhqdy.rk-1"
)


def create_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {TABLE_NAME} (
            exchange TEXT NOT NULL,
            code TEXT NOT NULL,
            name TEXT NOT NULL,
            full_name TEXT,
            board TEXT,
            security_type TEXT NOT NULL,
            listing_date TEXT,
            total_shares INTEGER,
            circulating_shares INTEGER,
            industry TEXT,
            source TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (exchange, code)
        )
        """
    )
    conn.execute(
        f"""
        CREATE INDEX IF NOT EXISTS idx_{TABLE_NAME}_code
        ON {TABLE_NAME} (code)
        """
    )


def parse_int(value: object) -> int | None:
    if pd.isna(value):
        return None

    text = str(value).strip().replace(",", "")
    if not text or text in {"-", "--"}:
        return None

    try:
        return int(float(text))
    except ValueError:
        return None


def parse_date(value: object) -> str | None:
    if pd.isna(value):
        return None

    text = str(value).strip()
    if not text or text in {"-", "--"}:
        return None

    parsed = pd.to_datetime(text, errors="coerce")
    if pd.isna(parsed):
        return text
    return parsed.strftime("%Y-%m-%d")


def clean_text(value: object) -> str | None:
    if pd.isna(value):
        return None

    text = str(value).strip()
    return text or None


def normalize_shanghai(symbol: str) -> pd.DataFrame:
    raw = ak.stock_info_sh_name_code(symbol=symbol)
    now = datetime.now().isoformat(timespec="seconds")

    df = pd.DataFrame(
        {
            "exchange": "SSE",
            "code": raw["证券代码"].astype(str).str.zfill(6),
            "name": raw["证券简称"].map(clean_text),
            "full_name": raw["公司全称"].map(clean_text),
            "board": symbol,
            "security_type": "B股" if "B股" in symbol else "A股",
            "listing_date": raw["上市日期"].map(parse_date),
            "total_shares": None,
            "circulating_shares": None,
            "industry": None,
            "source": f"akshare.stock_info_sh_name_code:{symbol}",
            "updated_at": now,
        }
    )
    return df


def normalize_shenzhen(symbol: str) -> pd.DataFrame:
    raw = ak.stock_info_sz_name_code(symbol=symbol)
    now = datetime.now().isoformat(timespec="seconds")

    if symbol == "A股列表":
        code_col = "A股代码"
        name_col = "A股简称"
        listing_col = "A股上市日期"
        total_col = "A股总股本"
        circulating_col = "A股流通股本"
        security_type = "A股"
    elif symbol == "B股列表":
        code_col = "B股代码"
        name_col = "B股简称"
        listing_col = "B股上市日期"
        total_col = "B股总股本"
        circulating_col = "B股流通股本"
        security_type = "B股"
    elif symbol == "CDR列表":
        code_col = "CDR代码"
        name_col = "CDR简称"
        listing_col = "上市日期"
        total_col = None
        circulating_col = None
        security_type = "CDR"
    else:
        code_col = "证券代码"
        name_col = "证券简称"
        listing_col = "上市日期"
        total_col = None
        circulating_col = None
        security_type = symbol.replace("列表", "")

    df = pd.DataFrame(
        {
            "exchange": "SZSE",
            "code": raw[code_col].astype(str).str.zfill(6),
            "name": raw[name_col].map(clean_text),
            "full_name": None,
            "board": raw["板块"].map(clean_text) if "板块" in raw.columns else symbol,
            "security_type": security_type,
            "listing_date": raw[listing_col].map(parse_date) if listing_col in raw.columns else None,
            "total_shares": raw[total_col].map(parse_int) if total_col in raw.columns else None,
            "circulating_shares": (
                raw[circulating_col].map(parse_int)
                if circulating_col in raw.columns
                else None
            ),
            "industry": raw["所属行业"].map(clean_text) if "所属行业" in raw.columns else None,
            "source": f"akshare.stock_info_sz_name_code:{symbol}",
            "updated_at": now,
        }
    )
    return df


def fetch_stock_basic_info() -> pd.DataFrame:
    frames = [
        normalize_shanghai("主板A股"),
        normalize_shanghai("科创板"),
        normalize_shanghai("主板B股"),
        normalize_shenzhen("A股列表"),
        normalize_shenzhen("B股列表"),
        normalize_shenzhen("CDR列表"),
    ]

    df = pd.concat(frames, ignore_index=True)
    df = df.dropna(subset=["code", "name"])
    df = df.drop_duplicates(subset=["exchange", "code"], keep="last")
    return df


def upsert_rows(conn: sqlite3.Connection, rows: Iterable[dict[str, object]]) -> int:
    sql = f"""
        INSERT INTO {TABLE_NAME} (
            exchange, code, name, full_name, board, security_type, listing_date,
            total_shares, circulating_shares, industry, source, updated_at
        )
        VALUES (
            :exchange, :code, :name, :full_name, :board, :security_type, :listing_date,
            :total_shares, :circulating_shares, :industry, :source, :updated_at
        )
        ON CONFLICT(exchange, code) DO UPDATE SET
            name = excluded.name,
            full_name = excluded.full_name,
            board = excluded.board,
            security_type = excluded.security_type,
            listing_date = excluded.listing_date,
            total_shares = excluded.total_shares,
            circulating_shares = excluded.circulating_shares,
            industry = excluded.industry,
            source = excluded.source,
            updated_at = excluded.updated_at
    """

    row_list = list(rows)
    conn.executemany(sql, row_list)
    return len(row_list)


def save_to_sqlite(df: pd.DataFrame, db_path: Path) -> int:
    db_path.parent.mkdir(parents=True, exist_ok=True)

    with sqlite3.connect(db_path) as conn:
        create_table(conn)
        inserted = upsert_rows(conn, df.to_dict(orient="records"))
        conn.commit()
    return inserted


def quote_identifier(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def daily_table_name(exchange: str, code: str) -> str:
    return f"daily_{exchange.lower()}_{code}"


def create_daily_table(conn: sqlite3.Connection, table_name: str) -> None:
    conn.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {quote_identifier(table_name)} (
            trade_date TEXT NOT NULL PRIMARY KEY,
            stock_code TEXT NOT NULL,
            stock_name TEXT,
            exchange TEXT NOT NULL,
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
            updated_at TEXT NOT NULL
        )
        """
    )


def create_daily_log_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {DAILY_LOG_TABLE} (
            exchange TEXT NOT NULL,
            code TEXT NOT NULL,
            name TEXT,
            table_name TEXT NOT NULL,
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
    exchanges: Iterable[str],
    security_types: Iterable[str],
    limit: int | None,
) -> list[dict[str, str]]:
    exchange_list = list(exchanges)
    security_type_list = list(security_types)
    if not exchange_list:
        raise ValueError("At least one exchange is required.")
    if not security_type_list:
        raise ValueError("At least one security type is required.")

    placeholders_exchange = ",".join("?" for _ in exchange_list)
    placeholders_security_type = ",".join("?" for _ in security_type_list)
    sql = f"""
        SELECT exchange, code, name
        FROM {TABLE_NAME}
        WHERE exchange IN ({placeholders_exchange})
          AND security_type IN ({placeholders_security_type})
        ORDER BY exchange, code
    """
    params: list[object] = [*exchange_list, *security_type_list]
    if limit:
        sql += " LIMIT ?"
        params.append(limit)

    rows = conn.execute(sql, params).fetchall()
    return [{"exchange": row[0], "code": row[1], "name": row[2]} for row in rows]


def daily_table_has_rows(
    conn: sqlite3.Connection,
    table_name: str,
    minimum_rows: int,
) -> bool:
    exists = conn.execute(
        """
        SELECT 1
        FROM sqlite_master
        WHERE type = 'table' AND name = ?
        """,
        (table_name,),
    ).fetchone()
    if not exists:
        return False

    row_count = conn.execute(
        f"SELECT COUNT(*) FROM {quote_identifier(table_name)}"
    ).fetchone()[0]
    return row_count >= minimum_rows


def normalize_daily_hist(
    raw: pd.DataFrame,
    stock: dict[str, str],
    adjust: str,
    days: int,
    source: str,
) -> pd.DataFrame:
    if raw.empty:
        return pd.DataFrame()

    if source == "em":
        rename_columns = {
            "日期": "trade_date",
            "股票代码": "stock_code",
            "开盘": "open",
            "收盘": "close",
            "最高": "high",
            "最低": "low",
            "成交量": "volume",
            "成交额": "amount",
            "振幅": "amplitude",
            "涨跌幅": "pct_change",
            "涨跌额": "change_amount",
            "换手率": "turnover_rate",
        }
        source_name = "akshare.stock_zh_a_hist"
    elif source == "eastmoney":
        rename_columns = {
            "trade_date": "trade_date",
            "open": "open",
            "close": "close",
            "high": "high",
            "low": "low",
            "volume": "volume",
            "amount": "amount",
            "amplitude": "amplitude",
            "pct_change": "pct_change",
            "change_amount": "change_amount",
            "turnover_rate": "turnover_rate",
        }
        source_name = "eastmoney.push2his.kline"
    elif source == "tx":
        rename_columns = {
            "date": "trade_date",
            "open": "open",
            "close": "close",
            "high": "high",
            "low": "low",
            "amount": "volume",
        }
        source_name = "akshare.stock_zh_a_hist_tx"
    else:
        raise ValueError(f"Unknown daily data source: {source}")

    df = raw.rename(columns=rename_columns).copy()
    df["trade_date"] = df["trade_date"].map(parse_date)
    df = df.dropna(subset=["trade_date"]).sort_values("trade_date").tail(days)

    now = datetime.now().isoformat(timespec="seconds")
    df["stock_code"] = stock["code"]
    df["stock_name"] = stock["name"]
    df["exchange"] = stock["exchange"]
    df["amount"] = df["amount"] if "amount" in df.columns else None
    df["amplitude"] = df["amplitude"] if "amplitude" in df.columns else None
    df["pct_change"] = df["pct_change"] if "pct_change" in df.columns else None
    df["change_amount"] = df["change_amount"] if "change_amount" in df.columns else None
    df["turnover_rate"] = df["turnover_rate"] if "turnover_rate" in df.columns else None
    df["adjust"] = adjust
    df["source"] = source_name
    df["updated_at"] = now

    columns = [
        "trade_date",
        "stock_code",
        "stock_name",
        "exchange",
        "open",
        "close",
        "high",
        "low",
        "volume",
        "amount",
        "amplitude",
        "pct_change",
        "change_amount",
        "turnover_rate",
        "adjust",
        "source",
        "updated_at",
    ]
    return df[columns]


def eastmoney_fqt(adjust: str) -> int:
    if adjust == "qfq":
        return 1
    if adjust == "hfq":
        return 2
    return 0


def parse_json_or_jsonp(text: str) -> dict[str, object]:
    stripped = text.strip()
    match = re.match(r"^[^(]+\((.*)\);?$", stripped, re.S)
    if match:
        stripped = match.group(1)
    return json.loads(stripped)


def _eastmoney_use_system_curl_only() -> bool:
    flag = os.getenv("EASTMONEY_USE_SYSTEM_CURL", "").strip().lower()
    return flag in ("1", "true", "yes")


def _eastmoney_http_get(full_url: str, headers: dict[str, str], timeout: float | None) -> str:
    deadline = 60.0 if timeout is None else float(timeout)
    max_time = max(1, int(round(deadline)))
    curl_bin = shutil.which("curl")

    def via_requests() -> str:
        with requests.Session() as session:
            resp = session.get(full_url, headers=headers, timeout=timeout)
            resp.raise_for_status()
            return resp.text

    def via_curl() -> str:
        if not curl_bin:
            raise RuntimeError(
                "EASTMONEY_USE_SYSTEM_CURL is enabled or requests failed, "
                "but no curl executable was found in PATH."
            )
        cmd: list[str] = [curl_bin, "-sS", "-g", "--max-time", str(max_time), full_url]
        for key, val in headers.items():
            cmd.extend(["-H", f"{key}: {val}"])
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=deadline + 10.0,
            check=False,
        )
        if proc.returncode != 0:
            detail = proc.stderr.strip() or proc.stdout.strip() or "(no stderr/stdout)"
            raise RuntimeError(f"eastmoney curl failed (exit {proc.returncode}): {detail}")
        return proc.stdout

    if _eastmoney_use_system_curl_only():
        return via_curl()
    try:
        return via_requests()
    except requests.exceptions.ConnectionError:
        if curl_bin:
            return via_curl()
        raise


def fetch_eastmoney_daily_hist(
    stock: dict[str, str],
    adjust: str,
    end_date: str,
    days: int,
    timeout: float | None,
    eastmoney_cookie: str | None,
    markdown_profile: EastmoneyCurlProfile | None = None,
) -> pd.DataFrame:
    secid_prefix = "1" if stock["exchange"] == "SSE" else "0"
    code = stock["code"]
    market = "sh" if stock["exchange"] == "SSE" else "sz"
    if markdown_profile:
        ut = markdown_profile.ut_value()
        cb_param = markdown_profile.cb_value()
        cookie = markdown_profile.cookie
    else:
        ut = EASTMONEY_UT
        cb_param = "quote_jp1"
        cookie = (
            eastmoney_cookie
            if eastmoney_cookie
            else (os.getenv("EASTMONEY_COOKIE") or "").strip() or EASTMONEY_DEFAULT_COOKIE
        )
    params_list = [
        ("secid", f"{secid_prefix}.{code}"),
        ("ut", ut),
        ("fields1", "f1,f2,f3,f4,f5,f6"),
        ("fields2", "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61"),
        ("klt", "101"),
        ("fqt", str(eastmoney_fqt(adjust))),
        ("end", end_date),
        ("lmt", str(days + 10)),
        ("cb", cb_param),
    ]
    full_url = f"{EASTMONEY_KLINE_URL}?{urlencode(params_list)}"
    headers = {
        "Accept": "*/*",
        "Accept-Language": "zh-CN,zh;q=0.9",
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
        "Pragma": "no-cache",
        "Referer": f"https://quote.eastmoney.com/concept/{market}{code}.html?from=classic",
        "Sec-Fetch-Dest": "script",
        "Sec-Fetch-Mode": "no-cors",
        "Sec-Fetch-Site": "same-site",
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/147.0.0.0 Safari/537.36"
        ),
        "sec-ch-ua": '"Google Chrome";v="147", "Not.A/Brand";v="8", "Chromium";v="147"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Windows"',
    }
    if cookie:
        headers["Cookie"] = cookie

    body = _eastmoney_http_get(full_url, headers, timeout)
    try:
        payload = parse_json_or_jsonp(body)
    except json.JSONDecodeError as exc:
        raise EastmoneyUnavailableError(f"JSON/JSONP 解析失败 … {exc!s}") from exc
    if not isinstance(payload, dict):
        raise EastmoneyUnavailableError("响应不是 JSON 对象")
    data = payload.get("data")
    if data is None:
        raise EastmoneyUnavailableError("data 为 null（常见：Cookie 失效或风控）")
    if not isinstance(data, dict):
        raise EastmoneyUnavailableError("data 类型异常")
    klines_obj = data.get("klines")
    if klines_obj is None:
        raise EastmoneyUnavailableError("缺少 klines 字段")
    klines = klines_obj
    if not klines:
        return pd.DataFrame()

    rows = []
    for line in klines:
        parts = str(line).split(",")
        if len(parts) < 11:
            continue
        rows.append(
            {
                "trade_date": parts[0],
                "open": parts[1],
                "close": parts[2],
                "high": parts[3],
                "low": parts[4],
                "volume": parts[5],
                "amount": parts[6],
                "amplitude": parts[7],
                "pct_change": parts[8],
                "change_amount": parts[9],
                "turnover_rate": parts[10],
            }
        )

    return pd.DataFrame(rows)


def fetch_eastmoney_daily_hist_with_profiles(
    stock: dict[str, str],
    adjust: str,
    end_date: str,
    days: int,
    timeout: float | None,
    md_state: EastmoneyMarkdownState,
) -> pd.DataFrame:
    items = md_state.profiles
    if not items:
        raise RuntimeError(f"eastmoney 无 Markdown 配置，请维护 {EASTMONEY_CURL_MD_PATH}")

    slot = md_state.active_slot[0]
    slot = max(0, min(slot, len(items) - 1))
    md_state.active_slot[0] = slot

    while slot < len(items):
        label, profile = items[slot]
        try:
            df = fetch_eastmoney_daily_hist(
                stock=stock,
                adjust=adjust,
                end_date=end_date,
                days=days,
                timeout=timeout,
                eastmoney_cookie=None,
                markdown_profile=profile,
            )
            md_state.active_slot[0] = slot
            return df
        except (EastmoneyUnavailableError, requests.RequestException, RuntimeError) as exc:
            nxt = slot + 1
            if nxt < len(items):
                snippet = str(exc).replace("\n", " ")[:160]
                print(
                    f"[Eastmoney] {label} 不可用（{type(exc).__name__}: {snippet}）→ 改用 {items[nxt][0]}",
                    flush=True,
                )
                slot = nxt
                md_state.active_slot[0] = slot
                continue
            joined = " / ".join(n for n, _ in items)
            raise EastmoneyProfilesExhausted(
                f"[Eastmoney] {joined} 均已不可用，请更新 {EASTMONEY_CURL_MD_PATH} 中的 Cookie 后重试。"
            ) from exc


def fetch_daily_hist(
    stock: dict[str, str],
    days: int,
    adjust: str,
    end_date: str,
    lookback_calendar_days: int,
    timeout: float | None,
    source: str,
    eastmoney_cookie: str | None,
    eastmoney_md: EastmoneyMarkdownState | None = None,
) -> pd.DataFrame:
    end = datetime.strptime(end_date, "%Y%m%d")
    start = end - timedelta(days=lookback_calendar_days)

    if source == "eastmoney":
        if eastmoney_md is not None:
            raw = fetch_eastmoney_daily_hist_with_profiles(
                stock=stock,
                adjust=adjust,
                end_date=end_date,
                days=days,
                timeout=timeout,
                md_state=eastmoney_md,
            )
        else:
            raw = fetch_eastmoney_daily_hist(
                stock=stock,
                adjust=adjust,
                end_date=end_date,
                days=days,
                timeout=timeout,
                eastmoney_cookie=eastmoney_cookie,
                markdown_profile=None,
            )
    elif source == "em":
        raw = ak.stock_zh_a_hist(
            symbol=stock["code"],
            period="daily",
            start_date=start.strftime("%Y%m%d"),
            end_date=end_date,
            adjust=adjust,
            timeout=timeout,
        )
    elif source == "tx":
        market_symbol = f"{'sh' if stock['exchange'] == 'SSE' else 'sz'}{stock['code']}"
        raw = ak.stock_zh_a_hist_tx(
            symbol=market_symbol,
            start_date=start.strftime("%Y%m%d"),
            end_date=end_date,
            adjust=adjust,
            timeout=timeout,
        )
    else:
        raise ValueError(f"Unknown daily data source: {source}")

    return normalize_daily_hist(
        raw,
        stock=stock,
        adjust=adjust,
        days=days,
        source=source,
    )


def fetch_daily_hist_with_retry(
    stock: dict[str, str],
    days: int,
    adjust: str,
    end_date: str,
    lookback_calendar_days: int,
    timeout: float | None,
    source: str,
    retries: int,
    retry_sleep_seconds: float,
    eastmoney_cookie: str | None,
    eastmoney_md: EastmoneyMarkdownState | None = None,
) -> pd.DataFrame:
    sources = ["tx", "eastmoney"] if source == "auto" else [source]
    errors: list[str] = []

    for current_source in sources:
        for attempt in range(1, retries + 2):
            try:
                use_md = (
                    eastmoney_md is not None
                    and current_source == "eastmoney"
                )
                return fetch_daily_hist(
                    stock=stock,
                    days=days,
                    adjust=adjust,
                    end_date=end_date,
                    lookback_calendar_days=lookback_calendar_days,
                    timeout=timeout,
                    source=current_source,
                    eastmoney_cookie=eastmoney_cookie,
                    eastmoney_md=eastmoney_md if use_md else None,
                )
            except EastmoneyProfilesExhausted:
                raise
            except Exception as exc:
                errors.append(f"{current_source} attempt {attempt}: {exc}")
                if attempt <= retries and retry_sleep_seconds > 0:
                    time.sleep(retry_sleep_seconds)

    raise RuntimeError("; ".join(errors))


def upsert_daily_rows(
    conn: sqlite3.Connection,
    table_name: str,
    rows: Iterable[dict[str, object]],
) -> int:
    sql = f"""
        INSERT INTO {quote_identifier(table_name)} (
            trade_date, stock_code, stock_name, exchange, open, close, high, low,
            volume, amount, amplitude, pct_change, change_amount, turnover_rate,
            adjust, source, updated_at
        )
        VALUES (
            :trade_date, :stock_code, :stock_name, :exchange, :open, :close, :high, :low,
            :volume, :amount, :amplitude, :pct_change, :change_amount, :turnover_rate,
            :adjust, :source, :updated_at
        )
        ON CONFLICT(trade_date) DO UPDATE SET
            stock_code = excluded.stock_code,
            stock_name = excluded.stock_name,
            exchange = excluded.exchange,
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
            adjust = excluded.adjust,
            source = excluded.source,
            updated_at = excluded.updated_at
    """
    row_list = list(rows)
    conn.executemany(sql, row_list)
    return len(row_list)


def upsert_daily_log(
    conn: sqlite3.Connection,
    stock: dict[str, str],
    table_name: str,
    rows_saved: int,
    status: str,
    message: str | None,
    started_at: str,
) -> None:
    finished_at = datetime.now().isoformat(timespec="seconds")
    conn.execute(
        f"""
        INSERT INTO {DAILY_LOG_TABLE} (
            exchange, code, name, table_name, rows_saved, status, message,
            started_at, finished_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(exchange, code) DO UPDATE SET
            name = excluded.name,
            table_name = excluded.table_name,
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
            table_name,
            rows_saved,
            status,
            message,
            started_at,
            finished_at,
        ),
    )


def save_recent_daily_data(
    db_path: Path,
    days: int,
    adjust: str,
    end_date: str,
    lookback_calendar_days: int,
    exchanges: Iterable[str],
    security_types: Iterable[str],
    limit: int | None,
    sleep_seconds: float,
    timeout: float | None,
    source: str,
    retries: int,
    retry_sleep_seconds: float,
    skip_ok: bool,
    eastmoney_cookie: str | None,
) -> None:
    explicit_ck = (
        (eastmoney_cookie.strip() if eastmoney_cookie else "")
        or (os.getenv("EASTMONEY_COOKIE") or "").strip()
    )
    eastmoney_md: EastmoneyMarkdownState | None = None
    if source in ("eastmoney", "auto") and not explicit_ck:
        ordered = load_ordered_eastmoney_curl_profiles()
        if not ordered:
            ordered = [
                (
                    "内置默认 Cookie",
                    EastmoneyCurlProfile(
                        cookie=EASTMONEY_DEFAULT_COOKIE,
                        ut=EASTMONEY_UT,
                        cb="quote_jp1",
                        label="内置默认 Cookie",
                    ),
                )
            ]
        eastmoney_md = EastmoneyMarkdownState(profiles=list(ordered), active_slot=[0])
        chain = " → ".join(n for n, _ in ordered)
        print(
            f"[Eastmoney] 仅从 {EASTMONEY_CURL_MD_PATH.resolve()} 读取 Markdown（{chain}；失败则退出）",
            flush=True,
        )

    with sqlite3.connect(db_path) as conn:
        create_daily_log_table(conn)
        stocks = load_stock_list(
            conn,
            exchanges=exchanges,
            security_types=security_types,
            limit=limit,
        )
        if skip_ok:
            finished = {
                (row[0], row[1])
                for row in conn.execute(
                    f"SELECT exchange, code FROM {DAILY_LOG_TABLE} WHERE status = 'ok'"
                )
            }
            stocks = [
                stock
                for stock in stocks
                if (stock["exchange"], stock["code"]) not in finished
                and not daily_table_has_rows(
                    conn,
                    daily_table_name(stock["exchange"], stock["code"]),
                    days,
                )
            ]

    total = len(stocks)
    print(f"Found {total} stocks in {db_path}")

    with sqlite3.connect(db_path) as conn:
        create_daily_log_table(conn)
        for index, stock in enumerate(stocks, start=1):
            table_name = daily_table_name(stock["exchange"], stock["code"])
            started_at = datetime.now().isoformat(timespec="seconds")
            try:
                df = fetch_daily_hist_with_retry(
                    stock=stock,
                    days=days,
                    adjust=adjust,
                    end_date=end_date,
                    lookback_calendar_days=lookback_calendar_days,
                    timeout=timeout,
                    source=source,
                    retries=retries,
                    retry_sleep_seconds=retry_sleep_seconds,
                    eastmoney_cookie=eastmoney_cookie,
                    eastmoney_md=eastmoney_md,
                )
                create_daily_table(conn, table_name)
                rows_saved = upsert_daily_rows(
                    conn,
                    table_name,
                    df.to_dict(orient="records"),
                )
                upsert_daily_log(
                    conn,
                    stock=stock,
                    table_name=table_name,
                    rows_saved=rows_saved,
                    status="ok",
                    message=None,
                    started_at=started_at,
                )
                conn.commit()
                print(f"[{index}/{total}] {stock['code']} {stock['name']}: {rows_saved} rows")
            except EastmoneyProfilesExhausted as exc:
                conn.rollback()
                print(str(exc), flush=True)
                raise SystemExit(1) from exc
            except Exception as exc:
                conn.rollback()
                upsert_daily_log(
                    conn,
                    stock=stock,
                    table_name=table_name,
                    rows_saved=0,
                    status="failed",
                    message=str(exc),
                    started_at=started_at,
                )
                conn.commit()
                print(f"[{index}/{total}] {stock['code']} {stock['name']}: failed - {exc}")

            if sleep_seconds > 0 and index < total:
                time.sleep(sleep_seconds)


def comma_values(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fetch Shanghai and Shenzhen stock data with akshare."
    )
    parser.add_argument(
        "task",
        nargs="?",
        choices=["basic", "daily", "all"],
        default="basic",
        help="basic: stock list; daily: recent daily bars; all: run basic then daily.",
    )
    parser.add_argument(
        "--db",
        type=Path,
        default=DEFAULT_DB_PATH,
        help=f"SQLite database path. Default: {DEFAULT_DB_PATH}",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=200,
        help="Keep the latest N trading days for each stock table.",
    )
    parser.add_argument(
        "--adjust",
        choices=["", "qfq", "hfq"],
        default="",
        help="复权方式（东财 ak.stock_zh_a_hist / 腾讯 ak.stock_zh_a_hist_tx 均支持）。空字符串为不复权。",
    )
    parser.add_argument(
        "--end-date",
        default=datetime.now().strftime("%Y%m%d"),
        help="End date in YYYYMMDD format.",
    )
    parser.add_argument(
        "--lookback-calendar-days",
        type=int,
        default=500,
        help="Calendar-day lookback window used before taking the latest --days rows.",
    )
    parser.add_argument(
        "--exchanges",
        default="SSE,SZSE",
        help="Comma-separated exchanges from stock_basic_info.",
    )
    parser.add_argument(
        "--security-types",
        default="A股",
        help="Comma-separated security types from stock_basic_info.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limit number of stocks. Useful for testing.",
    )
    parser.add_argument(
        "--sleep",
        type=float,
        default=0.5,
        help="Seconds to sleep between each stock in daily import.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=15,
        help="Request timeout passed to akshare.",
    )
    parser.add_argument(
        "--source",
        choices=["auto", "eastmoney", "em", "tx"],
        default="tx",
        help="日线：tx 腾讯（默认，无振幅/换手等）；auto 先腾讯再东财；eastmoney 东财直连；em akshare 东财接口。",
    )
    parser.add_argument(
        "--retries",
        type=int,
        default=2,
        help="Retry count per data source for each stock.",
    )
    parser.add_argument(
        "--retry-sleep",
        type=float,
        default=2,
        help="Seconds to sleep between retries.",
    )
    parser.add_argument(
        "--skip-ok",
        action="store_true",
        help="Skip stocks already marked ok in stock_daily_import_log.",
    )
    parser.add_argument(
        "--eastmoney-cookie",
        default=None,
        help=(
            "Cookie for push2his：若设置则覆盖固定路径 curl 文件解析与 EASTMONEY_COOKIE。 "
            f"未设置时仅从 {EASTMONEY_CURL_MD_PATH} 解析 Cookie/ut/cb。ConnectionError 可走 PATH 的 curl；"
            "EASTMONEY_USE_SYSTEM_CURL=1 强制使用 curl。"
        ),
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    if args.task in {"basic", "all"}:
        df = fetch_stock_basic_info()
        saved_count = save_to_sqlite(df, args.db)
        print(f"Saved {saved_count} basic rows into {args.db}")
        print(df.groupby(["exchange", "security_type"]).size().to_string())

    if args.task in {"daily", "all"}:
        save_recent_daily_data(
            db_path=args.db,
            days=args.days,
            adjust=args.adjust,
            end_date=args.end_date,
            lookback_calendar_days=args.lookback_calendar_days,
            exchanges=comma_values(args.exchanges),
            security_types=comma_values(args.security_types),
            limit=args.limit,
            sleep_seconds=args.sleep,
            timeout=args.timeout,
            source=args.source,
            retries=args.retries,
            retry_sleep_seconds=args.retry_sleep,
            skip_ok=args.skip_ok,
            eastmoney_cookie=args.eastmoney_cookie,
        )


if __name__ == "__main__":
    main()
