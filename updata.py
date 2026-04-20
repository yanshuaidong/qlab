"""
更新 local_fut_pulse.sqlite 中的 fut_daily_close 表。
逻辑参考 workstation/database/fut_pulse 的 close_price + pipeline 交易日生成。

默认从 fut_strength 中取所有出现过的交易日作为目标日期，对每个品种写入收盘价；
若某日 AkShare 无原始行，则按主连序列向前填充，尽量保证目标交易日均有价。
"""

from __future__ import annotations

import argparse
import logging
import random
import sqlite3
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Iterable

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "database" / "local_fut_pulse.sqlite"

MAX_RETRIES = 3
RETRY_SLEEP_RANGE = (0.8, 1.5)

# 与 workstation/database/fut_pulse/close_price.py 保持一致
CLOSE_API_SYMBOL_MAP = {
    "im": "I0",
    "rbm": "RB0",
    "hcm": "HC0",
    "smm": "SM0",
    "cum": "CU0",
    "alm": "AL0",
    "znm": "ZN0",
    "pbm": "PB0",
    "snm": "SN0",
    "sim": "SI0",
    "psm": "PS0",
    "lcm": "LC0",
    "aum": "AU0",
    "am": "A0",
    "bm": "B0",
    "ym": "Y0",
    "mm": "M0",
    "oim": "OI0",
    "rmm": "RM0",
    "pm": "P0",
    "cm": "C0",
    "jdm": "JD0",
    "cfm": "CF0",
    "srm": "SR0",
    "apm": "AP0",
    "cjm": "CJ0",
    "pkm": "PK0",
    "tam": "TA0",
    "pxm": "PX0",
    "ppm": "PP0",
    "ebm": "EB0",
    "bzm": "BZ0",
    "shm": "SH0",
    "urm": "UR0",
    "rum": "RU0",
    "brm": "BR0",
    "lgm": "LG0",
    "spm": "SP0",
    "ihm": "IH0",
    "aom": "AO0",
    "nim": "NI0",
    "agm": "AG0",
    "lhm": "LH0",
    "fum": "FU0",
    "lum": "LU0",
    "mam": "MA0",
    "vm": "V0",
    "sam": "SA0",
    "fgm": "FG0",
    "lm": "L0",
    "egm": "EG0",
    "bum": "BU0",
    "pgm": "PG0",
    "jmm": "JM0",
    "ecm": "EC0",
}


def _import_market_libs():
    try:
        import akshare as ak  # noqa: F401
    except ImportError as exc:
        raise RuntimeError("缺少 akshare，请先安装: pip install akshare") from exc
    try:
        import pandas as pd  # noqa: F401
    except ImportError as exc:
        raise RuntimeError("缺少 pandas，请先安装: pip install pandas") from exc
    import akshare as ak
    import pandas as pd

    return ak, pd


def safe_float(value, default=None):
    if value is None:
        return default
    if isinstance(value, str):
        value = value.strip()
        if value in ("", "-", "None", "null"):
            return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def fetch_main_history_df(api_symbol: str, max_retries: int = MAX_RETRIES):
    ak, pd = _import_market_libs()
    col_map = {
        "日期": "trade_date",
        "开盘价": "open_price",
        "最高价": "high_price",
        "最低价": "low_price",
        "收盘价": "close_price",
        "成交量": "volume",
        "持仓量": "open_interest",
    }

    for attempt in range(1, max_retries + 1):
        try:
            df = ak.futures_main_sina(symbol=api_symbol)
            if df is None or df.empty:
                return None

            rename_map = {k: v for k, v in col_map.items() if k in df.columns}
            df = df.rename(columns=rename_map).copy()
            if "trade_date" not in df.columns or "close_price" not in df.columns:
                return None

            df["trade_date"] = pd.to_datetime(df["trade_date"]).dt.strftime("%Y-%m-%d")
            return df
        except Exception as exc:
            if attempt < max_retries:
                wait_secs = 2**attempt + random.uniform(0.5, 1.5)
                logger.warning(
                    "AkShare 拉取 %s 失败（第 %d 次）: %s，%.1fs 后重试",
                    api_symbol,
                    attempt,
                    exc,
                    wait_secs,
                )
                time.sleep(wait_secs)
            else:
                raise RuntimeError(
                    f"AkShare 拉取 {api_symbol} 失败（已重试 {max_retries} 次）：{exc}"
                ) from exc
    return None


def is_trade_day(d: date) -> bool:
    return d.weekday() < 5


def generate_trade_dates(
    days: int | None = None,
    start: str | None = None,
    end: str | None = None,
) -> list[str]:
    """生成交易日列表（倒序，最新在前），仅排除周末。"""
    today = date.today()

    if start and end:
        d_start = date.fromisoformat(start)
        d_end = date.fromisoformat(end)
        all_days: list[str] = []
        cur = d_end
        while cur >= d_start:
            if is_trade_day(cur):
                all_days.append(cur.isoformat())
            cur -= timedelta(days=1)
        return all_days

    if days:
        collected: list[str] = []
        cur = today
        while len(collected) < days:
            if is_trade_day(cur):
                collected.append(cur.isoformat())
            cur -= timedelta(days=1)
        return collected

    if is_trade_day(today):
        return [today.isoformat()]
    cur = today - timedelta(days=1)
    while not is_trade_day(cur):
        cur -= timedelta(days=1)
    return [cur.isoformat()]


def load_varieties(conn: sqlite3.Connection) -> list[dict]:
    cur = conn.execute(
        'SELECT id, name, "key" FROM fut_variety ORDER BY id'
    )
    rows = cur.fetchall()
    return [{"id": r[0], "name": r[1], "key": r[2]} for r in rows]


def load_target_dates_from_strength(conn: sqlite3.Connection) -> list[str]:
    cur = conn.execute(
        "SELECT DISTINCT trade_date FROM fut_strength ORDER BY trade_date"
    )
    dates = [str(r[0]).strip()[:10] for r in cur.fetchall() if r[0]]
    return dates


def prune_close_outside_strength_dates(conn: sqlite3.Connection) -> int:
    """删除 fut_daily_close 中不在 fut_strength 出现过的交易日（保持两表日期域一致）。"""
    cur = conn.execute(
        """
        DELETE FROM fut_daily_close
        WHERE trade_date NOT IN (SELECT DISTINCT trade_date FROM fut_strength)
        """
    )
    conn.commit()
    return cur.rowcount if cur.rowcount is not None else 0


def build_close_series_for_targets(df_hist, target_dates: list[str], pd):
    """按目标交易日对齐收盘价，缺失则前向填充（主连常见缺口）。"""
    if df_hist is None or df_hist.empty:
        return None, []

    s = df_hist.set_index("trade_date")["close_price"].apply(safe_float)
    s = s.dropna()
    if s.empty:
        return None, list(target_dates)

    s = s[~s.index.duplicated(keep="last")].sort_index()
    ordered = sorted(target_dates)
    aligned = s.reindex(ordered)
    aligned = aligned.ffill()

    still_missing = [d for d in ordered if pd.isna(aligned.loc[d])]
    return aligned, still_missing


def upsert_close_sqlite(
    conn: sqlite3.Connection,
    rows: list[tuple[int, str, float]],
    collected_at: str | None = None,
) -> dict[str, int]:
    if collected_at is None:
        collected_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    sql = """
        INSERT INTO fut_daily_close (variety_id, trade_date, close_price, collected_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(variety_id, trade_date) DO UPDATE SET
            close_price = excluded.close_price,
            collected_at = excluded.collected_at
    """
    params = [
        (variety_id, trade_date, close_price, collected_at)
        for variety_id, trade_date, close_price in rows
    ]
    with conn:
        conn.executemany(sql, params)
    return {"inserted": len(rows), "updated": 0}


def sync_local_close(
    conn: sqlite3.Connection,
    target_dates: list[str],
    varieties: list[dict],
) -> dict:
    _, pd = _import_market_libs()
    failures: list[str] = []
    total_written = 0

    total = len(varieties)
    for idx, item in enumerate(varieties, 1):
        key = str(item["key"]).lower()
        label = f"{item['key']}({item['name']})"
        if key not in CLOSE_API_SYMBOL_MAP:
            failures.append(f"{label} 无 CLOSE_API_SYMBOL_MAP 映射，跳过")
            logger.warning("无映射，跳过: %s", label)
            continue

        api_symbol = CLOSE_API_SYMBOL_MAP[key]
        try:
            df_hist = fetch_main_history_df(api_symbol)
            aligned, still_missing = build_close_series_for_targets(
                df_hist, target_dates, pd
            )
            if aligned is None:
                raise RuntimeError("AkShare 无有效收盘价序列")

            rows: list[tuple[int, str, float]] = []
            for td in sorted(target_dates):
                val = aligned.loc[td]
                if pd.isna(val):
                    continue
                rows.append((int(item["id"]), td, float(val)))

            if not rows:
                raise RuntimeError("目标交易日对齐后仍无可用收盘价")

            stat = upsert_close_sqlite(conn, rows)
            total_written += stat["inserted"]
            logger.info(
                "[%d/%d] %s 完成：写入 %d 条",
                idx,
                total,
                label,
                stat["inserted"],
            )
            if still_missing:
                failures.append(
                    f"{label} 以下日期在填充后仍缺原始行情（已尽量 ffill）: {', '.join(still_missing[:5])}"
                    + (f" ...共{len(still_missing)}天" if len(still_missing) > 5 else "")
                )
        except Exception as exc:
            failures.append(f"{label} 同步失败: {exc}")
            logger.warning("[%d/%d] %s 失败: %s", idx, total, label, exc)

        if idx < total:
            time.sleep(random.uniform(*RETRY_SLEEP_RANGE))

    print(f"fut_daily_close 写入完成：共 {total_written} 条。")
    if failures:
        print("提示 / 异常项：")
        for item in failures:
            print(f"  - {item}")

    return {
        "rows_written": total_written,
        "failures": failures,
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="更新 local_fut_pulse.sqlite 的 fut_daily_close")
    p.add_argument(
        "--symbol",
        metavar="k1,k2",
        help="只同步指定品种 key，例如 rbm,cum",
    )
    g = p.add_mutually_exclusive_group()
    g.add_argument(
        "--days",
        type=int,
        metavar="N",
        help="从今天起向前 N 个交易日（覆盖默认的 from-strength）",
    )
    g.add_argument(
        "--start",
        metavar="YYYY-MM-DD",
        help="与 --end 指定区间（覆盖默认）",
    )
    p.add_argument("--end", metavar="YYYY-MM-DD", help="区间结束日，默认今天")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    if not DB_PATH.exists():
        print(f"数据库不存在: {DB_PATH}", file=sys.stderr)
        return 1

    conn = sqlite3.connect(DB_PATH)

    varieties = load_varieties(conn)
    if not varieties:
        print("fut_variety 为空，请先导入品种。", file=sys.stderr)
        conn.close()
        return 1

    if args.symbol:
        want = {s.strip().lower() for s in args.symbol.split(",") if s.strip()}
        all_keys = {str(v["key"]).lower() for v in varieties}
        missing = want - all_keys
        if missing:
            print(f"未找到品种 key: {', '.join(sorted(missing))}", file=sys.stderr)
            conn.close()
            return 1
        varieties = [v for v in varieties if str(v["key"]).lower() in want]

    use_strength_calendar = False
    if args.start:
        end = args.end or date.today().isoformat()
        target_dates = generate_trade_dates(start=args.start, end=end)
    elif args.days:
        target_dates = generate_trade_dates(days=args.days)
    else:
        use_strength_calendar = True
        target_dates = load_target_dates_from_strength(conn)
        if not target_dates:
            target_dates = generate_trade_dates(days=30)
            use_strength_calendar = False
            logger.warning("fut_strength 无日期，改用最近 30 个交易日。")

    # 统一为升序去重
    seen: set[str] = set()
    normalized: list[str] = []
    for d in sorted(target_dates):
        d = str(d).strip()[:10]
        if not d or d in seen:
            continue
        seen.add(d)
        normalized.append(d)

    if not normalized:
        print("没有目标交易日。", file=sys.stderr)
        conn.close()
        return 1

    logger.info(
        "目标交易日: %s ~ %s，共 %d 天；品种数 %d",
        normalized[0],
        normalized[-1],
        len(normalized),
        len(varieties),
    )
    print(
        f"目标交易日：{normalized[0]} ~ {normalized[-1]}，共 {len(normalized)} 天；"
        f"品种 {len(varieties)} 个。"
    )

    try:
        sync_local_close(conn, normalized, varieties)
        if use_strength_calendar:
            n = prune_close_outside_strength_dates(conn)
            if n:
                logger.info("已清理不在 fut_strength 日历内的 fut_daily_close 行数: %d", n)
    finally:
        conn.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
