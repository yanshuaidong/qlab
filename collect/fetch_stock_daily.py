"""
Maintain stock daily OHLCV data for stocks present in ths_fund_flow.

The ths_fund_flow table is treated as the authority for both the stock
universe and each stock's required trade-date range. This script creates the
stock_daily table when needed, finds missing daily rows, fetches those spans
from akshare, and upserts the returned daily data.
"""
from __future__ import annotations

import argparse
import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable


BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "ths_fund_flow.sqlite"
DATE_FMT = "%Y-%m-%d"
AK_DATE_FMT = "%Y%m%d"
SOURCE_EM = "akshare.stock_zh_a_hist"
SOURCE_TX = "akshare.stock_zh_a_hist_tx"


@dataclass(frozen=True)
class StockRange:
    stock_code: str
    start_date: str
    end_date: str
    ths_rows: int


@dataclass(frozen=True)
class MissingSpan:
    start_date: str
    end_date: str
    dates: tuple[str, ...]


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def compact_date(value: str) -> str:
    return value.replace("-", "")


def offset_date(value: str, days: int) -> str:
    return (datetime.strptime(value, DATE_FMT) + timedelta(days=days)).strftime(DATE_FMT)


def normalize_trade_date(value: Any) -> str:
    if value is None:
        raise ValueError("date is empty")
    if hasattr(value, "strftime"):
        return value.strftime(DATE_FMT)
    text = str(value).strip()
    for fmt in (DATE_FMT, AK_DATE_FMT, "%Y/%m/%d"):
        try:
            return datetime.strptime(text, fmt).strftime(DATE_FMT)
        except ValueError:
            pass
    raise ValueError(f"invalid date value: {value!r}")


def parse_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        if value != value:  # pandas/numpy NaN
            return None
    except Exception:
        pass
    text = str(value).strip().replace(",", "").replace("%", "")
    if not text or text in {"-", "--", "None", "nan", "NaN"}:
        return None
    return float(text)


def parse_int(value: Any) -> int | None:
    number = parse_float(value)
    return int(number) if number is not None else None


def connect_db(db_path: Path) -> sqlite3.Connection:
    if not db_path.exists():
        raise FileNotFoundError(f"SQLite not found: {db_path}")
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def init_stock_daily_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS stock_daily (
            stock_code TEXT NOT NULL,
            trade_date TEXT NOT NULL,
            open_price REAL,
            close_price REAL,
            high_price REAL,
            low_price REAL,
            volume_shou INTEGER,
            amount_yuan REAL,
            amplitude_percent REAL,
            change_percent REAL,
            change_amount REAL,
            turnover_rate_percent REAL,
            source TEXT NOT NULL,
            adjust TEXT NOT NULL DEFAULT '',
            updated_at TEXT NOT NULL,
            PRIMARY KEY (stock_code, trade_date, adjust)
        )
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_stock_daily_trade_date
        ON stock_daily (trade_date)
        """
    )


def load_stock_ranges(conn: sqlite3.Connection, only_codes: Iterable[str] | None = None) -> list[StockRange]:
    params: list[str] = []
    where = ""
    codes = [normalize_stock_code(code) for code in only_codes or []]
    if codes:
        placeholders = ", ".join("?" for _ in codes)
        where = f"WHERE stock_code IN ({placeholders})"
        params.extend(codes)

    rows = conn.execute(
        f"""
        SELECT
            stock_code,
            MIN(trade_date) AS start_date,
            MAX(trade_date) AS end_date,
            COUNT(*) AS ths_rows
        FROM ths_fund_flow
        {where}
        GROUP BY stock_code
        ORDER BY stock_code
        """,
        params,
    ).fetchall()
    return [
        StockRange(
            stock_code=str(row["stock_code"]),
            start_date=str(row["start_date"]),
            end_date=str(row["end_date"]),
            ths_rows=int(row["ths_rows"]),
        )
        for row in rows
    ]


def normalize_stock_code(value: str) -> str:
    text = str(value).strip()
    if not text:
        raise ValueError("stock code is empty")
    digits = "".join(ch for ch in text if ch.isdigit())
    if not digits:
        raise ValueError(f"invalid stock code: {value!r}")
    return digits.zfill(6)[-6:]


def load_required_dates(conn: sqlite3.Connection, stock_code: str) -> list[str]:
    rows = conn.execute(
        """
        SELECT trade_date
        FROM ths_fund_flow
        WHERE stock_code = ?
        ORDER BY trade_date
        """,
        (stock_code,),
    ).fetchall()
    return [str(row["trade_date"]) for row in rows]


def load_existing_dates(
    conn: sqlite3.Connection,
    stock_code: str,
    start_date: str,
    end_date: str,
    adjust: str,
) -> set[str]:
    rows = conn.execute(
        """
        SELECT trade_date
        FROM stock_daily
        WHERE stock_code = ?
          AND trade_date BETWEEN ? AND ?
          AND adjust = ?
        """,
        (stock_code, start_date, end_date, adjust),
    ).fetchall()
    return {str(row["trade_date"]) for row in rows}


def build_missing_spans(required_dates: list[str], existing_dates: set[str]) -> list[MissingSpan]:
    spans: list[MissingSpan] = []
    current: list[str] = []
    for date_value in required_dates:
        if date_value not in existing_dates:
            current.append(date_value)
            continue
        if current:
            spans.append(MissingSpan(current[0], current[-1], tuple(current)))
            current = []
    if current:
        spans.append(MissingSpan(current[0], current[-1], tuple(current)))
    return spans


def market_symbol_tx(stock_code: str) -> str:
    if stock_code.startswith(("5", "6", "9")):
        return f"sh{stock_code}"
    if stock_code.startswith(("4", "8")):
        return f"bj{stock_code}"
    return f"sz{stock_code}"


def fetch_daily_frame_em(stock_code: str, start_date: str, end_date: str, adjust: str, timeout: float | None):
    try:
        import akshare as ak
    except ImportError as exc:
        raise RuntimeError("缺少 akshare，请先安装 akshare。") from exc

    return ak.stock_zh_a_hist(
        symbol=stock_code,
        period="daily",
        start_date=compact_date(start_date),
        end_date=compact_date(end_date),
        adjust=adjust,
        timeout=timeout,
    )


def fetch_daily_frame_tx(stock_code: str, start_date: str, end_date: str, adjust: str, timeout: float | None):
    try:
        import akshare as ak
    except ImportError as exc:
        raise RuntimeError("缺少 akshare，请先安装 akshare。") from exc

    # Fetch a little extra history so derived change/amplitude values have a
    # previous close for the first required date.
    extended_start = offset_date(start_date, -14)
    return ak.stock_zh_a_hist_tx(
        symbol=market_symbol_tx(stock_code),
        start_date=compact_date(extended_start),
        end_date=compact_date(end_date),
        adjust=adjust,
        timeout=timeout,
    )


def fetch_daily_frame_with_retry(
    stock_code: str,
    start_date: str,
    end_date: str,
    adjust: str,
    timeout: float | None,
    retries: int,
    sleep_seconds: float,
) -> tuple[Any, str]:
    last_error: Exception | None = None
    attempts = max(1, retries + 1)
    providers = [
        (SOURCE_EM, fetch_daily_frame_em),
        (SOURCE_TX, fetch_daily_frame_tx),
    ]
    errors: list[str] = []
    for source, fetcher in providers:
        for attempt in range(1, attempts + 1):
            try:
                frame = fetcher(stock_code, start_date, end_date, adjust, timeout)
                return frame, source
            except Exception as exc:
                last_error = exc
                errors.append(f"{source}: {exc}")
                if attempt >= attempts:
                    break
                print(f"    {source} 失败，第 {attempt}/{attempts} 次：{exc}；稍后重试")
                time.sleep(max(0.0, sleep_seconds))
        print(f"    {source} 不可用，尝试备用数据源")
    raise RuntimeError(
        f"akshare failed for {stock_code} {start_date}..{end_date}: {'; '.join(errors)}"
    ) from last_error


def find_column(columns: Iterable[Any], candidates: Iterable[str]) -> str:
    column_names = [str(column) for column in columns]
    for candidate in candidates:
        if candidate in column_names:
            return candidate
    raise ValueError(f"akshare result missing column, candidates={list(candidates)}, columns={column_names}")


def row_value(row: dict[str, Any], *names: str) -> Any:
    for name in names:
        if name in row:
            return row.get(name)
    return None


def previous_close_by_date(frame: Any, date_col: str, close_col: str | None) -> dict[str, float]:
    if close_col is None:
        return {}
    rows: list[tuple[str, float]] = []
    for row in frame.to_dict(orient="records"):
        close_price = parse_float(row.get(close_col))
        if close_price is None:
            continue
        rows.append((normalize_trade_date(row.get(date_col)), close_price))
    rows.sort(key=lambda item: item[0])

    previous: dict[str, float] = {}
    prev_close: float | None = None
    for trade_date, close_price in rows:
        if prev_close is not None:
            previous[trade_date] = prev_close
        prev_close = close_price
    return previous


def daily_records_from_frame(
    stock_code: str,
    frame: Any,
    required_dates: set[str],
    adjust: str,
    source: str,
) -> list[dict[str, Any]]:
    if frame is None or getattr(frame, "empty", False):
        return []

    date_col = find_column(frame.columns, ["日期", "date", "trade_date"])
    close_col = next((name for name in ["收盘", "close"] if name in frame.columns), None)
    previous_close = previous_close_by_date(frame, date_col, close_col)
    updated_at = now_iso()
    records: list[dict[str, Any]] = []

    for row in frame.to_dict(orient="records"):
        trade_date = normalize_trade_date(row.get(date_col))
        if trade_date not in required_dates:
            continue
        open_price = parse_float(row_value(row, "开盘", "open"))
        close_price = parse_float(row_value(row, "收盘", "close"))
        high_price = parse_float(row_value(row, "最高", "high"))
        low_price = parse_float(row_value(row, "最低", "low"))
        prev_close = previous_close.get(trade_date)
        change_amount = parse_float(row.get("涨跌额"))
        change_percent = parse_float(row.get("涨跌幅"))
        amplitude_percent = parse_float(row.get("振幅"))
        if prev_close and close_price is not None:
            if change_amount is None:
                change_amount = round(close_price - prev_close, 4)
            if change_percent is None:
                change_percent = round((close_price - prev_close) / prev_close * 100, 4)
        if prev_close and high_price is not None and low_price is not None and amplitude_percent is None:
            amplitude_percent = round((high_price - low_price) / prev_close * 100, 4)

        volume_shou = parse_int(row_value(row, "成交量", "volume"))
        amount_yuan = parse_float(row.get("成交额"))
        if volume_shou is None and amount_yuan is None and "amount" in row:
            volume_shou = parse_int(row.get("amount"))

        records.append(
            {
                "stock_code": stock_code,
                "trade_date": trade_date,
                "open_price": open_price,
                "close_price": close_price,
                "high_price": high_price,
                "low_price": low_price,
                "volume_shou": volume_shou,
                "amount_yuan": amount_yuan,
                "amplitude_percent": amplitude_percent,
                "change_percent": change_percent,
                "change_amount": change_amount,
                "turnover_rate_percent": parse_float(row.get("换手率")),
                "source": source,
                "adjust": adjust,
                "updated_at": updated_at,
            }
        )
    return records


def upsert_daily_records(conn: sqlite3.Connection, records: Iterable[dict[str, Any]]) -> int:
    rows = list(records)
    if not rows:
        return 0
    conn.executemany(
        """
        INSERT INTO stock_daily (
            stock_code,
            trade_date,
            open_price,
            close_price,
            high_price,
            low_price,
            volume_shou,
            amount_yuan,
            amplitude_percent,
            change_percent,
            change_amount,
            turnover_rate_percent,
            source,
            adjust,
            updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(stock_code, trade_date, adjust) DO UPDATE SET
            open_price=excluded.open_price,
            close_price=excluded.close_price,
            high_price=excluded.high_price,
            low_price=excluded.low_price,
            volume_shou=excluded.volume_shou,
            amount_yuan=excluded.amount_yuan,
            amplitude_percent=excluded.amplitude_percent,
            change_percent=excluded.change_percent,
            change_amount=excluded.change_amount,
            turnover_rate_percent=excluded.turnover_rate_percent,
            source=excluded.source,
            adjust=excluded.adjust,
            updated_at=excluded.updated_at
        """,
        [
            (
                row["stock_code"],
                row["trade_date"],
                row["open_price"],
                row["close_price"],
                row["high_price"],
                row["low_price"],
                row["volume_shou"],
                row["amount_yuan"],
                row["amplitude_percent"],
                row["change_percent"],
                row["change_amount"],
                row["turnover_rate_percent"],
                row["source"],
                row["adjust"],
                row["updated_at"],
            )
            for row in rows
        ],
    )
    return len(rows)


def maintain_stock(
    conn: sqlite3.Connection,
    stock_range: StockRange,
    adjust: str,
    timeout: float | None,
    retries: int,
    sleep_seconds: float,
    dry_run: bool,
) -> tuple[int, int, list[str]]:
    required_dates = load_required_dates(conn, stock_range.stock_code)
    existing_dates = load_existing_dates(
        conn,
        stock_range.stock_code,
        stock_range.start_date,
        stock_range.end_date,
        adjust,
    )
    spans = build_missing_spans(required_dates, existing_dates)
    if not spans:
        print(
            f"{stock_range.stock_code}: OK，{stock_range.start_date}..{stock_range.end_date} "
            f"已有 {len(existing_dates)}/{len(required_dates)} 条"
        )
        return 0, 0, []

    missing_count = sum(len(span.dates) for span in spans)
    print(
        f"{stock_range.stock_code}: 需要补 {missing_count}/{len(required_dates)} 条，"
        f"{len(spans)} 个区间"
    )
    if dry_run:
        for span in spans:
            print(f"    DRY-RUN {span.start_date}..{span.end_date} ({len(span.dates)} 天)")
        return missing_count, 0, []

    inserted = 0
    still_missing: set[str] = set()
    for span in spans:
        print(f"    拉取 {span.start_date}..{span.end_date} ({len(span.dates)} 天)")
        frame, source = fetch_daily_frame_with_retry(
            stock_range.stock_code,
            span.start_date,
            span.end_date,
            adjust,
            timeout,
            retries,
            sleep_seconds,
        )
        records = daily_records_from_frame(stock_range.stock_code, frame, set(span.dates), adjust, source)
        inserted += upsert_daily_records(conn, records)
        fetched_dates = {record["trade_date"] for record in records}
        still_missing.update(set(span.dates) - fetched_dates)
        time.sleep(max(0.0, sleep_seconds))

    return missing_count, inserted, sorted(still_missing)


def count_missing(conn: sqlite3.Connection, stock_range: StockRange, adjust: str) -> int:
    required_dates = load_required_dates(conn, stock_range.stock_code)
    existing_dates = load_existing_dates(
        conn,
        stock_range.stock_code,
        stock_range.start_date,
        stock_range.end_date,
        adjust,
    )
    return sum(len(span.dates) for span in build_missing_spans(required_dates, existing_dates))


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="维护股票日线 stock_daily 表。")
    parser.add_argument("--db", type=Path, default=DB_PATH, help=f"SQLite 路径，默认：{DB_PATH}")
    parser.add_argument("--stock", action="append", help="只处理指定股票代码；可重复传入")
    parser.add_argument("--limit", type=int, default=None, help="只处理前 N 只股票，方便测试")
    parser.add_argument("--adjust", default="", choices=["", "qfq", "hfq"], help="复权方式，默认不复权")
    parser.add_argument("--timeout", type=float, default=20.0, help="akshare 单次请求超时秒数")
    parser.add_argument("--retries", type=int, default=2, help="akshare 失败重试次数")
    parser.add_argument("--sleep", type=float, default=0.8, help="请求间隔秒数")
    parser.add_argument("--dry-run", action="store_true", help="只打印缺口，不请求 akshare、不写入数据")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    conn = connect_db(args.db)
    try:
        init_stock_daily_table(conn)
        ranges = load_stock_ranges(conn, args.stock)
        if args.limit is not None:
            ranges = ranges[: max(0, args.limit)]
        if not ranges:
            print("没有找到需要维护的股票。")
            return 0

        print(f"DB: {args.db}")
        print(f"stock_daily 表已就绪；股票数：{len(ranges)}；adjust={args.adjust!r}")
        total_missing = 0
        total_written = 0
        failures: list[str] = []
        missing_after: list[str] = []

        for index, stock_range in enumerate(ranges, 1):
            try:
                print(f"\n{index:03d}/{len(ranges):03d} {stock_range.stock_code}")
                missing, written, missing_dates = maintain_stock(
                    conn=conn,
                    stock_range=stock_range,
                    adjust=args.adjust,
                    timeout=args.timeout,
                    retries=args.retries,
                    sleep_seconds=args.sleep,
                    dry_run=args.dry_run,
                )
                total_missing += missing
                total_written += written
                if missing_dates:
                    preview = ", ".join(missing_dates[:8])
                    suffix = "..." if len(missing_dates) > 8 else ""
                    missing_after.append(f"{stock_range.stock_code}: {len(missing_dates)} ({preview}{suffix})")
                conn.commit()
            except Exception as exc:
                conn.rollback()
                total_missing += count_missing(conn, stock_range, args.adjust)
                failures.append(f"{stock_range.stock_code}: {exc}")
                print(f"    失败：{exc}")

        print("\n完成")
        print(f"发现缺口：{total_missing} 条")
        print(f"写入/更新：{total_written} 条")
        if missing_after:
            print("\nakshare 未返回的日期：")
            for item in missing_after:
                print(f"- {item}")
        if failures:
            print("\n处理失败：")
            for item in failures:
                print(f"- {item}")
            return 1
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
