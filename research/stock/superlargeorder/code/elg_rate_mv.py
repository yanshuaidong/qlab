#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""东财超大单净流入占比大于 40% 的次数，以及流通市值分布。

数据：storage/stock/data.sqlite 中已有的近一年记录。
  - moneyflow_dc.buy_elg_amount_rate：东财超大单净流入占比（%）
  - daily_basic.circ_mv：当日流通市值，单位万元

一次 = 一只股票一个交易日。明细表只保留当日流通市值大于 50 亿元、
且信号日前 30 个交易日的东财超大单净流入占比都没有大于 10% 的记录，按流通市值从小到大排列。
横轴每根柱为 10 亿元，区间左闭右开。
长尾若把主体压扁，则画到覆盖约 99% 次数的整百亿边界，其余在图注中说明。
"""

from __future__ import annotations

import math
import sqlite3
import textwrap
from collections import Counter
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
matplotlib.rcParams["font.family"] = "sans-serif"
matplotlib.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei"]
matplotlib.rcParams["axes.unicode_minus"] = False

import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter, MultipleLocator

BIN_YI = 10
BIN_WAN = BIN_YI * 10_000  # 10 亿元 = 100000 万元
COVER = 0.99
MAX_BINS = 160
RATE_GT = 40
PRIOR_RATE_GT = 10
LOOKBACK = 30
MV_GT_YI = 50
MV_GT_WAN = MV_GT_YI * 10_000  # 50 亿元 = 500000 万元


def find_repo(start: Path) -> Path:
    for folder in (start, *start.parents):
        if (folder / "storage" / "stock" / "data.sqlite").is_file():
            return folder
    raise FileNotFoundError("找不到 storage/stock/data.sqlite")


REPO = find_repo(Path(__file__).resolve())
DB_PATH = REPO / "storage" / "stock" / "data.sqlite"
OUT_DIR = Path(__file__).resolve().parents[1] / "output"
CHART_NAME = "流通市值_数量.png"
TABLE_NAME = "超大单净流入占比大于40.md"


def load(conn: sqlite3.Connection) -> tuple[list[tuple], Counter[int], dict[str, int | str]]:
    cur = conn.cursor()
    date_min, date_max, n_days = cur.execute(
        "SELECT MIN(trade_date), MAX(trade_date), COUNT(DISTINCT trade_date) FROM moneyflow_dc"
    ).fetchone()
    rows = cur.execute(
        """
        SELECT d.trade_date, d.ts_code, d.name, d.buy_elg_amount_rate, b.circ_mv
        FROM moneyflow_dc d
        LEFT JOIN daily_basic b
          ON d.ts_code = b.ts_code AND d.trade_date = b.trade_date
        WHERE d.buy_elg_amount_rate > ?
        ORDER BY d.trade_date, d.name, d.ts_code
        """,
        (RATE_GT,),
    ).fetchall()
    counts: Counter[int] = Counter()
    missing = 0
    stocks: set[str] = set()
    hit_days: set[str] = set()
    for _trade_date, ts_code, _name, _rate, circ_mv in rows:
        stocks.add(ts_code)
        hit_days.add(_trade_date)
        if circ_mv is None or circ_mv <= 0:
            missing += 1
            continue
        counts[int(circ_mv // BIN_WAN) * BIN_YI] += 1
    meta = {
        "date_min": str(date_min),
        "date_max": str(date_max),
        "n_days": int(n_days),
        "n_rows": len(rows),
        "n_stocks": len(stocks),
        "hit_days": len(hit_days),
        "matched": len(rows) - missing,
        "missing": missing,
    }
    return rows, counts, meta


def right_edge(counts: Counter[int]) -> int:
    """右边界（亿元，开区间端点）。能完整放下就全画，否则收到约 99% 的整百亿。"""
    if not counts:
        return BIN_YI
    full = max(counts) + BIN_YI
    if full / BIN_YI <= MAX_BINS:
        return full
    total = sum(counts.values())
    covered = 0
    edge = BIN_YI
    for left in sorted(counts):
        covered += counts[left]
        edge = left + BIN_YI
        if covered / total >= COVER:
            break
    edge = int(math.ceil(edge / 100.0) * 100)
    return max(edge, 100)


def draw(counts: Counter[int], meta: dict[str, int | str]) -> Path:
    right = right_edge(counts)
    xs = list(range(0, right, BIN_YI))
    ys = [counts.get(x, 0) for x in xs]
    shown = sum(ys)
    matched = int(meta["matched"])
    tail = matched - shown
    peak_x = max(xs, key=lambda x: counts.get(x, 0)) if xs else 0
    peak_n = counts.get(peak_x, 0)
    max_left = max(counts) if counts else 0

    fig, ax = plt.subplots(figsize=(16.5, 6.8))
    ax.bar(
        xs,
        ys,
        width=BIN_YI,
        align="edge",
        color="#3C6E9F",
        edgecolor="white",
        linewidth=0.35,
        zorder=2,
    )
    ax.set_xlim(0, right)
    ax.set_ylim(0, max(ys) * 1.12 if ys else 1)
    ax.xaxis.set_major_locator(MultipleLocator(100))
    ax.xaxis.set_minor_locator(MultipleLocator(BIN_YI))
    ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _p: f"{int(v):,}"))
    ax.set_axisbelow(True)
    ax.yaxis.grid(True, color="#E2E6EA", linewidth=0.8)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.tick_params(axis="x", which="major", length=5, labelsize=10)
    ax.tick_params(axis="x", which="minor", length=2.5)
    ax.tick_params(axis="y", labelsize=10)
    ax.set_xlabel(f"流通市值（亿元，每柱 {BIN_YI} 亿元，左闭右开）", fontsize=12)
    ax.set_ylabel("数量", fontsize=12)
    ax.set_title(
        f"东财超大单净流入占比大于 {RATE_GT}% 的流通市值分布",
        fontsize=15,
        pad=12,
    )
    ax.text(
        0.985,
        0.96,
        f"最多：{peak_x}–{peak_x + BIN_YI} 亿元\n{peak_n:,} 次",
        transform=ax.transAxes,
        ha="right",
        va="top",
        fontsize=11,
        color="#1F3A5F",
        linespacing=1.45,
    )

    if tail:
        tail_note = (
            f"图中为 0–{right:,} 亿元，覆盖已匹配次数的 {shown / matched:.1%}（{shown:,}/{matched:,}）。"
            f"{right:,} 亿元以上还有 {tail:,} 次，最大区间 {max_left:,}–{max_left + BIN_YI:,} 亿元，未画出。"
        )
    else:
        tail_note = f"横轴覆盖全部已匹配次数（{matched:,} 次），最大区间 {max_left:,}–{max_left + BIN_YI:,} 亿元。"
    note = (
        f"数据：moneyflow_dc.buy_elg_amount_rate > {RATE_GT}，按交易日与代码关联 daily_basic.circ_mv（万元）。"
        f"{meta['date_min']} 至 {meta['date_max']}，共 {meta['n_rows']:,} 次；"
        f"无流通市值 {meta['missing']:,} 次未计入。一次 = 一只股票一个交易日。{tail_note}"
    )
    wrapped = "\n".join(textwrap.wrap(note, width=92))
    fig.text(0.012, 0.012, wrapped, fontsize=8, color="#5C6570", ha="left", va="bottom", linespacing=1.35)
    fig.tight_layout(rect=(0, 0.11, 1, 1))

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / CHART_NAME
    fig.savefig(path, dpi=160)
    plt.close(fig)
    return path


def load_table(conn: sqlite3.Connection) -> list[tuple]:
    """流通市值大于 50 亿，且前 30 个交易日占比都没有大于 10%。"""
    return conn.execute(
        """
        WITH dates AS (
            SELECT trade_date,
                   ROW_NUMBER() OVER (ORDER BY trade_date) AS rn
            FROM (SELECT DISTINCT trade_date FROM moneyflow_dc)
        )
        SELECT d.trade_date, d.ts_code, d.name, d.buy_elg_amount_rate, b.circ_mv
        FROM moneyflow_dc d
        JOIN daily_basic b
          ON d.ts_code = b.ts_code AND d.trade_date = b.trade_date
        JOIN dates dt ON d.trade_date = dt.trade_date
        WHERE d.buy_elg_amount_rate > ?
          AND b.circ_mv > ?
          AND dt.rn > ?
          AND NOT EXISTS (
              SELECT 1
              FROM moneyflow_dc p
              JOIN dates pd ON p.trade_date = pd.trade_date
              WHERE p.ts_code = d.ts_code
                AND pd.rn BETWEEN dt.rn - ? AND dt.rn - 1
                AND p.buy_elg_amount_rate > ?
          )
        ORDER BY b.circ_mv, d.trade_date, d.name, d.ts_code
        """,
        (RATE_GT, MV_GT_WAN, LOOKBACK, LOOKBACK, PRIOR_RATE_GT),
    ).fetchall()


def write_table(rows: list[tuple], meta: dict[str, int | str]) -> Path:
    stocks = len({row[1] for row in rows})
    lines = [
        f"# 东财超大单净流入占比大于 {RATE_GT}%",
        "",
        (
            f"{meta['date_min']} 至 {meta['date_max']}，`buy_elg_amount_rate > {RATE_GT}` 共 {meta['n_rows']:,} 次。"
            f"下表再要求当日流通市值大于 {MV_GT_YI} 亿元，"
            f"且该日前 {LOOKBACK} 个交易日（不含当日）里，东财超大单净流入占比都没有大于 {PRIOR_RATE_GT}%。"
            f"库内向前不足 {LOOKBACK} 个交易日的信号日未列入。"
            f"共 **{len(rows):,}** 次、{stocks:,} 只股票，按流通市值从小到大排列。"
            "一次 = 一只股票一个交易日。占比单位为 %，流通市值为当日 `daily_basic.circ_mv`（万元换算成亿元）。"
        ),
        "",
        "| 时间 | 股票名字 | 东财超大单净流入占比 | 流通市值（亿元） |",
        "| --- | --- | ---: | ---: |",
    ]
    for trade_date, ts_code, name, rate, circ_mv in rows:
        label = str(name).replace("|", "\\|")
        lines.append(f"| {trade_date} | {label}（{ts_code}） | {rate:.2f}% | {circ_mv / 10_000:.2f} |")
    lines.append("")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / TABLE_NAME
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def main() -> None:
    with sqlite3.connect(f"file:{DB_PATH.as_posix()}?mode=ro", uri=True) as conn:
        rows, counts, meta = load(conn)
        table_rows = load_table(conn)
    chart = draw(counts, meta)
    table = write_table(table_rows, meta)
    print(f"明细: {len(table_rows):,}")
    print(f"次数: {meta['n_rows']:,}")
    print(f"区间: {meta['date_min']} ~ {meta['date_max']}")
    print(f"股票: {meta['n_stocks']:,}  有记录交易日: {meta['hit_days']}")
    print(f"流通市值已匹配: {meta['matched']:,}  缺失: {meta['missing']:,}")
    print(chart)
    print(table)


if __name__ == "__main__":
    main()
