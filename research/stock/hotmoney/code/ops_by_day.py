#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""近一年游资每日操作次数。

横轴覆盖样本区间内的每个自然日，纵轴是当日操作次数。
一次操作计 hm_detail 一行。下面这些名字不计入，其余游资都计入：

量化基金、T王、机构专用、量化打板、深股通专用、沪股通专用。
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
matplotlib.rcParams["font.family"] = "sans-serif"
matplotlib.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei"]
matplotlib.rcParams["axes.unicode_minus"] = False

import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter

EXCLUDE = (
    "量化基金",
    "T王",
    "机构专用",
    "量化打板",
    "深股通专用",
    "沪股通专用",
)


def find_repo(start: Path) -> Path:
    for folder in (start, *start.parents):
        if (folder / "storage" / "stock" / "data.sqlite").is_file():
            return folder
    raise FileNotFoundError("找不到 storage/stock/data.sqlite")


REPO = find_repo(Path(__file__).resolve())
DB_PATH = REPO / "storage" / "stock" / "data.sqlite"
OUT_DIR = Path(__file__).resolve().parents[1] / "output"


def load(conn: sqlite3.Connection) -> tuple[list[datetime], list[int], dict]:
    cur = conn.cursor()
    date_min, date_max, n_rows = cur.execute(
        "SELECT MIN(trade_date), MAX(trade_date), COUNT(*) FROM hm_detail"
    ).fetchone()
    placeholders = ",".join("?" * len(EXCLUDE))
    by_day = {
        trade_date: count
        for trade_date, count in cur.execute(
            f"""
            SELECT trade_date, COUNT(*)
            FROM hm_detail
            WHERE hm_name NOT IN ({placeholders})
            GROUP BY trade_date
            """,
            EXCLUDE,
        )
    }
    start = datetime.strptime(str(date_min), "%Y-%m-%d")
    end = datetime.strptime(str(date_max), "%Y-%m-%d")
    days: list[datetime] = []
    counts: list[int] = []
    cursor = start
    while cursor <= end:
        key = cursor.strftime("%Y-%m-%d")
        days.append(cursor)
        counts.append(int(by_day.get(key, 0)))
        cursor += timedelta(days=1)
    n_kept = sum(counts)
    trading = [n for n in counts if n > 0]
    meta = {
        "date_min": str(date_min),
        "date_max": str(date_max),
        "n_rows": int(n_rows),
        "n_kept": n_kept,
        "n_excluded": int(n_rows) - n_kept,
        "n_days": len(days),
        "n_trading": len(trading),
        "median": sorted(trading)[len(trading) // 2] if trading else 0,
    }
    return days, counts, meta


def month_centers(start: datetime, end: datetime) -> list[tuple[datetime, str]]:
    """每个月在可见区间内的中点，用作横轴刻度。"""
    labels: list[tuple[datetime, str]] = []
    year, month = start.year, start.month
    while True:
        month_start = datetime(year, month, 1)
        if month == 12:
            next_month = datetime(year + 1, 1, 1)
        else:
            next_month = datetime(year, month + 1, 1)
        month_end = next_month - timedelta(days=1)
        visible_start = max(month_start, start)
        visible_end = min(month_end, end)
        if visible_start <= visible_end:
            center = visible_start + (visible_end - visible_start) / 2
            labels.append((center, f"{year}-{month:02d}"))
        if next_month > end:
            break
        year, month = next_month.year, next_month.month
    return labels


def draw(days: list[datetime], counts: list[int], meta: dict) -> Path:
    fig, ax = plt.subplots(figsize=(18, 6.8))
    ax.bar(days, counts, width=0.86, color="#3C6E9F", zorder=2)

    peak_i = max(range(len(counts)), key=lambda i: counts[i])
    peak_n = counts[peak_i]
    peak_day = days[peak_i]
    ax.set_xlim(days[0] - timedelta(days=2), days[-1] + timedelta(days=2))
    ax.set_ylim(0, peak_n * 1.22 if peak_n else 1)

    centers = month_centers(days[0], days[-1])
    ax.set_xticks([item[0] for item in centers])
    ax.set_xticklabels([item[1] for item in centers], fontsize=9)
    ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _p: f"{int(v):,}"))
    ax.set_axisbelow(True)
    ax.yaxis.grid(True, color="#E2E6EA", linewidth=0.8)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.tick_params(axis="y", labelsize=10)
    ax.set_xlabel("自然日", fontsize=12)
    ax.set_ylabel("操作次数", fontsize=12)
    ax.set_title(
        "游资每日操作次数\n已去掉量化基金、T王、机构专用、量化打板、深股通专用、沪股通专用",
        fontsize=15,
        pad=12,
    )

    ax.annotate(
        f"最多 {peak_day:%Y-%m-%d}\n{peak_n} 次",
        xy=(peak_day, peak_n),
        xytext=(0, 6),
        textcoords="offset points",
        ha="center",
        va="bottom",
        fontsize=9,
        color="#1F3A5F",
        linespacing=1.35,
    )
    if meta["median"]:
        ax.axhline(meta["median"], color="#C4A35A", linewidth=1, linestyle="--", zorder=1)
        ax.text(
            days[0] + timedelta(days=3),
            meta["median"] + peak_n * 0.03,
            f"交易日中位数 {meta['median']} 次",
            fontsize=9,
            color="#8A6A2F",
            va="bottom",
        )

    note = (
        f"横轴是 {meta['date_min']} 至 {meta['date_max']} 的每个自然日，共 {meta['n_days']} 天。"
        f"纵轴是当日操作次数，一行明细计一次；非交易日为 0，图上留空。"
        f"已去掉 {len(EXCLUDE)} 类共 {meta['n_excluded']:,} 次，其余 {meta['n_kept']:,} 次，"
        f"分布在 {meta['n_trading']} 个交易日。"
    )
    fig.text(0.012, 0.012, note, fontsize=8.5, color="#5C6570", ha="left", va="bottom")
    fig.tight_layout(rect=(0, 0.06, 1, 1))

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / "游资每日操作次数.png"
    fig.savefig(path, dpi=160)
    plt.close(fig)
    return path


def main() -> None:
    with sqlite3.connect(f"file:{DB_PATH.as_posix()}?mode=ro", uri=True) as conn:
        days, counts, meta = load(conn)
    if sum(1 for n in counts if n > 0) != meta["n_trading"]:
        raise SystemExit("交易日数量不一致")
    path = draw(days, counts, meta)
    print(path)
    print(
        f"days={meta['n_days']} trading={meta['n_trading']} "
        f"kept={meta['n_kept']} excluded={meta['n_excluded']} median={meta['median']}"
    )


if __name__ == "__main__":
    main()
