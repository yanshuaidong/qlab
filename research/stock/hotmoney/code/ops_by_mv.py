#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""全部游资操作次数按公司市值分布。

数据：storage/stock/data.sqlite
  - hm_detail：游资每日明细，一行计一次操作
  - daily_basic.circ_mv / total_mv：当日流通市值 / 总市值，单位万元

横轴每根柱为 10 亿元，区间左闭右开，从 0 起按市值从小到大排列。
默认口径为流通市值。长尾若把主体压扁，则画到覆盖约 99% 操作的整百亿边界，其余在图注中说明。
"""

from __future__ import annotations

import argparse
import math
import sqlite3
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


def find_repo(start: Path) -> Path:
    for folder in (start, *start.parents):
        if (folder / "storage" / "stock" / "data.sqlite").is_file():
            return folder
    raise FileNotFoundError("找不到 storage/stock/data.sqlite")


REPO = find_repo(Path(__file__).resolve())
DB_PATH = REPO / "storage" / "stock" / "data.sqlite"
OUT_DIR = Path(__file__).resolve().parents[1] / "output"

BASES = {
    "circ": ("circ_mv", "流通市值", "流通市值_操作次数.png"),
    "total": ("total_mv", "总市值", "总市值_操作次数.png"),
}


def load(conn: sqlite3.Connection, column: str) -> tuple[Counter[int], dict[str, int | str]]:
    cur = conn.cursor()
    n_rows, n_names, date_min, date_max = cur.execute(
        "SELECT COUNT(*), COUNT(DISTINCT hm_name), MIN(trade_date), MAX(trade_date) FROM hm_detail"
    ).fetchone()
    counts: Counter[int] = Counter()
    missing = 0
    matched = 0
    query = f"""
        SELECT b.{column}
        FROM hm_detail h
        LEFT JOIN daily_basic b
          ON h.ts_code = b.ts_code AND h.trade_date = b.trade_date
    """
    for (mv_wan,) in cur.execute(query):
        if mv_wan is None or mv_wan <= 0:
            missing += 1
            continue
        matched += 1
        counts[int(mv_wan // BIN_WAN) * BIN_YI] += 1
    meta = {
        "n_rows": int(n_rows),
        "n_names": int(n_names),
        "date_min": str(date_min),
        "date_max": str(date_max),
        "matched": matched,
        "missing": missing,
    }
    return counts, meta


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


def draw(counts: Counter[int], meta: dict[str, int | str], label: str, filename: str) -> Path:
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
    ax.set_xlabel(f"{label}（亿元，每柱 {BIN_YI} 亿元，左闭右开）", fontsize=12)
    ax.set_ylabel("操作次数", fontsize=12)
    ax.set_title(
        f"全部游资对不同市值公司的操作次数分布\n口径：{label}",
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
            f"图中为 0–{right:,} 亿元，覆盖已匹配操作的 {shown / matched:.1%}（{shown:,}/{matched:,}）。"
            f"{right:,} 亿元以上还有 {tail:,} 次，最大区间 {max_left:,}–{max_left + BIN_YI:,} 亿元，未画出。"
        )
    else:
        tail_note = f"横轴覆盖全部已匹配操作（{matched:,} 次），最大区间 {max_left:,}–{max_left + BIN_YI:,} 亿元。"
    note = (
        f"数据：hm_detail 按交易日与代码关联 daily_basic.{'circ_mv' if label == '流通市值' else 'total_mv'}（万元）。"
        f"{meta['date_min']} 至 {meta['date_max']}，游资 {meta['n_names']} 个，明细 {meta['n_rows']:,} 行；"
        f"无市值 {meta['missing']:,} 行未计入。一行明细计一次操作。{tail_note}"
    )
    fig.text(0.012, 0.012, note, fontsize=8, color="#5C6570", ha="left", va="bottom")
    fig.tight_layout(rect=(0, 0.07, 1, 1))

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / filename
    fig.savefig(path, dpi=160)
    plt.close(fig)
    print(f"{label}: {path}")
    print(f"  matched={matched:,} missing={meta['missing']:,} shown={shown:,} tail={tail:,} right={right}")
    return path


def main() -> None:
    parser = argparse.ArgumentParser(description="游资操作次数按市值分布柱状图")
    parser.add_argument(
        "--mv",
        choices=("circ", "total", "both"),
        default="circ",
        help="市值口径：circ 流通市值（默认），total 总市值，both 两张都导出",
    )
    args = parser.parse_args()
    keys = ("circ", "total") if args.mv == "both" else (args.mv,)
    with sqlite3.connect(f"file:{DB_PATH.as_posix()}?mode=ro", uri=True) as conn:
        for key in keys:
            column, label, filename = BASES[key]
            counts, meta = load(conn, column)
            draw(counts, meta, label, filename)


if __name__ == "__main__":
    main()
