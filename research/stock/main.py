#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""初筛资金流强流入日，写入 trend_mark（正确点 / 好信号）。

规则（方案.md）：
- 东财超大单净流入占比 >= 阈值
- 同花顺大单净流入占比 >= 阈值
- L2 主动超大单净流入占比 >= 阈值

默认任一来源达标、且最新总市值 >= 400 亿才入库，供后续人工删改。
人工标记不覆盖；重跑会替换「初筛」自动标记。
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_DB_PATH = REPO_ROOT / "storage" / "stock" / "data.sqlite"
REPORT_PATH = Path(__file__).resolve().parent / "report.md"
REASON_PREFIX = "初筛"
DEFAULT_THRESHOLD = 20.0
DEFAULT_MIN_MV_YI = 400.0
# daily_basic.total_mv 单位为万元，1 亿 = 10000 万元
MV_WAN_PER_YI = 10000.0
TREND_MARK_DDL = """
CREATE TABLE IF NOT EXISTS trend_mark (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts_code TEXT NOT NULL,
    trade_date TEXT NOT NULL,
    mark_type TEXT NOT NULL CHECK (mark_type IN ('correct', 'fail')),
    reason TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    UNIQUE (ts_code, trade_date)
)
"""


def log(message: str) -> None:
    print(message, flush=True)


def configure_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8")
            except (OSError, ValueError):
                pass


def to_ymd(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip().replace("-", "")
    if len(text) < 8 or not text[:8].isdigit():
        return None
    return f"{text[:4]}-{text[4:6]}-{text[6:8]}"


def fmt_pct(value: object) -> str:
    if value is None:
        return "—"
    return f"{float(value):.2f}%"


def build_reason(dc_rate: object, ths_rate: object, l2_rate: object) -> str:
    return (
        f"{REASON_PREFIX} 东财超大单{fmt_pct(dc_rate)} "
        f"同花顺大单{fmt_pct(ths_rate)} L2超大单{fmt_pct(l2_rate)}"
    )


def ensure_trend_mark(conn: sqlite3.Connection) -> None:
    conn.execute(TREND_MARK_DDL)


def candidate_sql(mode: str, extra_filter: str = "") -> str:
    if mode == "all":
        where = """
            dc.buy_elg_amount_rate >= :threshold
            AND ths.buy_lg_amount_rate >= :threshold
            AND l2.buy_elg_amount_rate >= :threshold
        """
    else:
        where = """
            COALESCE(dc.buy_elg_amount_rate, 0) >= :threshold
            OR COALESCE(ths.buy_lg_amount_rate, 0) >= :threshold
            OR COALESCE(l2.buy_elg_amount_rate, 0) >= :threshold
        """
    return f"""
        WITH keys AS (
            SELECT ts_code, trade_date
            FROM moneyflow_dc
            WHERE buy_elg_amount_rate >= :threshold
            UNION
            SELECT ts_code, trade_date
            FROM moneyflow_ths
            WHERE buy_lg_amount_rate >= :threshold
            UNION
            SELECT ts_code, trade_date
            FROM moneyflow
            WHERE buy_elg_amount_rate >= :threshold
        )
        SELECT
            k.ts_code,
            k.trade_date,
            COALESCE(dc.name, ths.name) AS name,
            dc.buy_elg_amount_rate AS dc_elg_rate,
            ths.buy_lg_amount_rate AS ths_lg_rate,
            l2.buy_elg_amount_rate AS l2_elg_rate,
            b.total_mv / {MV_WAN_PER_YI} AS total_mv_yi
        FROM keys k
        LEFT JOIN moneyflow_dc dc
          ON dc.ts_code = k.ts_code AND dc.trade_date = k.trade_date
        LEFT JOIN moneyflow_ths ths
          ON ths.ts_code = k.ts_code AND ths.trade_date = k.trade_date
        LEFT JOIN moneyflow l2
          ON l2.ts_code = k.ts_code AND l2.trade_date = k.trade_date
        INNER JOIN daily_basic b
          ON b.ts_code = k.ts_code
         AND b.trade_date = (SELECT MAX(trade_date) FROM daily_basic)
        WHERE ({where})
          AND b.total_mv >= :min_mv_wan
          {extra_filter}
        ORDER BY k.trade_date, k.ts_code
    """


def fetch_candidates(
    conn: sqlite3.Connection,
    threshold: float,
    mode: str,
    start_date: str | None,
    end_date: str | None,
    min_mv_yi: float,
) -> list[sqlite3.Row]:
    clauses: list[str] = []
    params: dict[str, object] = {
        "threshold": threshold,
        "min_mv_wan": min_mv_yi * MV_WAN_PER_YI,
    }
    if start_date:
        clauses.append("AND k.trade_date >= :start_date")
        params["start_date"] = start_date
    if end_date:
        clauses.append("AND k.trade_date <= :end_date")
        params["end_date"] = end_date
    sql = candidate_sql(mode, extra_filter="\n          ".join(clauses))
    return list(conn.execute(sql, params))


def source_counts(
    conn: sqlite3.Connection,
    threshold: float,
    start_date: str | None,
    end_date: str | None,
) -> dict[str, int]:
    extra = []
    params: list[object] = [threshold]
    if start_date:
        extra.append("AND trade_date >= ?")
        params.append(start_date)
    if end_date:
        extra.append("AND trade_date <= ?")
        params.append(end_date)
    extra_sql = " ".join(extra)
    dc = conn.execute(
        f"SELECT COUNT(*) FROM moneyflow_dc WHERE buy_elg_amount_rate >= ? {extra_sql}",
        params,
    ).fetchone()[0]
    ths = conn.execute(
        f"SELECT COUNT(*) FROM moneyflow_ths WHERE buy_lg_amount_rate >= ? {extra_sql}",
        params,
    ).fetchone()[0]
    l2 = conn.execute(
        f"SELECT COUNT(*) FROM moneyflow WHERE buy_elg_amount_rate >= ? {extra_sql}",
        params,
    ).fetchone()[0]
    return {"dc": int(dc), "ths": int(ths), "l2": int(l2)}


def replace_screen_marks(
    conn: sqlite3.Connection,
    rows: list[sqlite3.Row],
    created_at: str,
) -> tuple[int, int, int]:
    """替换自动初筛标记，不碰人工标记。"""
    deleted = conn.execute(
        "DELETE FROM trend_mark WHERE reason LIKE ?",
        (f"{REASON_PREFIX}%",),
    ).rowcount
    existing = {
        (r[0], r[1])
        for r in conn.execute("SELECT ts_code, trade_date FROM trend_mark")
    }
    records = []
    skipped = 0
    for row in rows:
        key = (row["ts_code"], row["trade_date"])
        if key in existing:
            skipped += 1
            continue
        records.append(
            (
                row["ts_code"],
                row["trade_date"],
                "correct",
                build_reason(row["dc_elg_rate"], row["ths_lg_rate"], row["l2_elg_rate"]),
                created_at,
            )
        )
    if records:
        conn.executemany(
            """
            INSERT INTO trend_mark (ts_code, trade_date, mark_type, reason, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            records,
        )
    return len(records), skipped, int(deleted or 0)


def write_report(
    path: Path,
    *,
    db_path: Path,
    threshold: float,
    min_mv_yi: float,
    mode: str,
    start_date: str | None,
    end_date: str | None,
    source: dict[str, int],
    candidates: list[sqlite3.Row],
    inserted: int,
    skipped: int,
    deleted: int,
    dry_run: bool,
    created_at: str,
) -> None:
    stocks = {row["ts_code"] for row in candidates}
    dates = [row["trade_date"] for row in candidates]
    date_span = f"{dates[0]} ~ {dates[-1]}" if dates else "—"
    mode_label = "三者同时达标" if mode == "all" else "任一来源达标"
    all3 = sum(
        1
        for row in candidates
        if (row["dc_elg_rate"] or 0) >= threshold
        and (row["ths_lg_rate"] or 0) >= threshold
        and (row["l2_elg_rate"] or 0) >= threshold
    )
    dc_only = sum(
        1
        for row in candidates
        if (row["dc_elg_rate"] or 0) >= threshold
        and (row["ths_lg_rate"] or 0) < threshold
        and (row["l2_elg_rate"] or 0) < threshold
    )
    samples = candidates[:12]
    sample_lines = [
        "| 代码 | 名称 | 交易日 | 市值(亿) | 东财超大单 | 同花顺大单 | L2超大单 |",
        "|---|---|---|---:|---:|---:|---:|",
    ]
    for row in samples:
        mv = row["total_mv_yi"]
        mv_text = f"{float(mv):.0f}" if mv is not None else "—"
        sample_lines.append(
            f"| {row['ts_code']} | {row['name'] or '—'} | {row['trade_date']} "
            f"| {mv_text} | {fmt_pct(row['dc_elg_rate'])} | {fmt_pct(row['ths_lg_rate'])} "
            f"| {fmt_pct(row['l2_elg_rate'])} |"
        )
    if not samples:
        sample_lines.append("| — | — | — | — | — | — | — |")

    window = "全部已入库区间"
    if start_date or end_date:
        window = f"{start_date or '起'} ~ {end_date or '止'}"

    text = f"""# 资金流强流入初筛

生成时间：{created_at}

从 `{db_path.as_posix()}` 筛选三类资金流占比，写入同库 `trend_mark`（`mark_type=correct`，即 K 线正确点 / 好信号）。已有人工标记不覆盖；重跑会替换原因以「{REASON_PREFIX}」开头的自动标记。

## 规则

- 东财 `moneyflow_dc.buy_elg_amount_rate`（超大单净流入占比）≥ {threshold:g}%
- 同花顺 `moneyflow_ths.buy_lg_amount_rate`（大单净流入占比）≥ {threshold:g}%
- L2 主动 `moneyflow.buy_elg_amount_rate`（超大单净流入占比）≥ {threshold:g}%
- 最新总市值 ≥ {min_mv_yi:g} 亿（`daily_basic.total_mv`）
- 入选方式：{mode_label}
- 日期窗口：{window}
- 本次写入：{'演练，未入库' if dry_run else '已写入 trend_mark'}

同花顺没有超大单档，用其大单净流入占比对应。市值取 `daily_basic` 最新交易日。原因字段形如：`{REASON_PREFIX} 东财超大单xx% 同花顺大单xx% L2超大单xx%`。

## 结果

| 项目 | 数量 |
|---|---:|
| 东财超大单 ≥ {threshold:g}%（未按市值过滤） | {source['dc']} |
| 同花顺大单 ≥ {threshold:g}%（未按市值过滤） | {source['ths']} |
| L2 超大单 ≥ {threshold:g}%（未按市值过滤） | {source['l2']} |
| 入选股票日 | {len(candidates)} |
| 入选股票数 | {len(stocks)} |
| 三者同时达标 | {all3} |
| 仅东财达标 | {dc_only} |
| 删除旧初筛 | {deleted} |
| 新写入正确点 | {inserted} |
| 已有人工标记跳过 | {skipped} |
| 入选日期跨度 | {date_span} |

## 样例（按日期前 12 条）

{chr(10).join(sample_lines)}

## 用法

```bash
python research/stock/main.py
python research/stock/main.py --min-mv-yi 400
python research/stock/main.py --mode all
python research/stock/main.py --dry-run
python research/stock/main.py --threshold 25 --start-date 2026-01-01
```
"""
    path.write_text(text, encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="资金流强流入初筛，写入 trend_mark 正确点")
    parser.add_argument("--db", default=str(DEFAULT_DB_PATH), help="SQLite 路径")
    parser.add_argument(
        "--threshold",
        type=float,
        default=DEFAULT_THRESHOLD,
        help=f"占比阈值，默认 {DEFAULT_THRESHOLD:g}",
    )
    parser.add_argument(
        "--mode",
        choices=("any", "all"),
        default="any",
        help="any=任一来源达标（默认）；all=三者同时达标",
    )
    parser.add_argument(
        "--min-mv-yi",
        type=float,
        default=DEFAULT_MIN_MV_YI,
        help=f"最新总市值下限（亿元），默认 {DEFAULT_MIN_MV_YI:g}",
    )
    parser.add_argument("--start-date", help="起始交易日 YYYY-MM-DD 或 YYYYMMDD")
    parser.add_argument("--end-date", help="结束交易日 YYYY-MM-DD 或 YYYYMMDD")
    parser.add_argument("--dry-run", action="store_true", help="只统计，不写入")
    parser.add_argument(
        "--report",
        default=str(REPORT_PATH),
        help="报告路径，默认 research/stock/report.md",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    db_path = Path(args.db)
    if not db_path.is_file():
        log(f"数据库不存在: {db_path}")
        return 1
    if args.threshold <= 0:
        log("--threshold 必须为正数")
        return 1
    if args.min_mv_yi < 0:
        log("--min-mv-yi 不能为负数")
        return 1

    start_date = to_ymd(args.start_date) if args.start_date else None
    end_date = to_ymd(args.end_date) if args.end_date else None
    created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    try:
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        missing = {"moneyflow", "moneyflow_dc", "moneyflow_ths", "daily_basic"} - tables
        if missing:
            log(f"缺少表: {', '.join(sorted(missing))}")
            return 1

        ensure_trend_mark(conn)
        source = source_counts(conn, args.threshold, start_date, end_date)
        rows = fetch_candidates(
            conn,
            args.threshold,
            args.mode,
            start_date,
            end_date,
            args.min_mv_yi,
        )
        log(
            f"阈值 {args.threshold:g}% 市值≥{args.min_mv_yi:g}亿 mode={args.mode}："
            f"东财 {source['dc']} / 同花顺 {source['ths']} / L2 {source['l2']}，"
            f"入选 {len(rows)} 条"
        )

        deleted = 0
        if args.dry_run:
            inserted, skipped = 0, 0
            log("dry-run，未写入")
        else:
            inserted, skipped, deleted = replace_screen_marks(conn, rows, created_at)
            conn.commit()
            log(
                f"删除旧初筛 {deleted} 条，写入 {inserted} 条正确点，"
                f"跳过已有人工标记 {skipped} 条"
            )

        report_path = Path(args.report)
        write_report(
            report_path,
            db_path=db_path,
            threshold=args.threshold,
            min_mv_yi=args.min_mv_yi,
            mode=args.mode,
            start_date=start_date,
            end_date=end_date,
            source=source,
            candidates=rows,
            inserted=inserted,
            skipped=skipped,
            deleted=deleted,
            dry_run=args.dry_run,
            created_at=created_at,
        )
        log(f"报告: {report_path}")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    configure_stdio()
    sys.exit(main())
