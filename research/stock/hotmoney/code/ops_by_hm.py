#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""117 个游资的操作次数柱状图，以及一张统计表。

名录来自 hm_list。一次操作是 hm_detail 的一行。
占比的分母是全部明细行。平均流通市值、平均总市值、七成区间用操作当日市值
（daily_basic.circ_mv / total_mv，万元换算成亿元）；没有对应市值的行不进该列。
七成区间仍按流通市值计算。

七成区间：把该游资有市值的操作按流通市值排序，取覆盖至少 70% 次数、
且宽度最小的一段。宽度相同则取市值更小的那段。
"""

from __future__ import annotations

import csv
import math
import sqlite3
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
matplotlib.rcParams["font.family"] = "sans-serif"
matplotlib.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei"]
matplotlib.rcParams["axes.unicode_minus"] = False

import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle
from matplotlib.ticker import FuncFormatter

COVER = 0.70


def find_repo(start: Path) -> Path:
    for folder in (start, *start.parents):
        if (folder / "storage" / "stock" / "data.sqlite").is_file():
            return folder
    raise FileNotFoundError("找不到 storage/stock/data.sqlite")


REPO = find_repo(Path(__file__).resolve())
DB_PATH = REPO / "storage" / "stock" / "data.sqlite"
OUT_DIR = Path(__file__).resolve().parents[1] / "output"


def shortest_cover(values: list[float], frac: float = COVER) -> tuple[float, float] | None:
    n = len(values)
    if n == 0:
        return None
    k = max(1, math.ceil(frac * n - 1e-12))
    ordered = sorted(values)
    best_i = 0
    best_w = ordered[k - 1] - ordered[0]
    for i in range(1, n - k + 1):
        width = ordered[i + k - 1] - ordered[i]
        if width < best_w:
            best_w = width
            best_i = i
    return ordered[best_i], ordered[best_i + k - 1]


def fmt_yi(value: float) -> str:
    if value >= 100:
        return f"{value:.0f}"
    if value >= 10:
        text = f"{value:.1f}"
    else:
        text = f"{value:.2f}"
    return text.rstrip("0").rstrip(".")


def fmt_avg_range(values: list[float]) -> str:
    """平均值，括号内为最小–最大。"""
    if not values:
        return "—"
    avg = sum(values) / len(values)
    return f"{fmt_yi(avg)}（{fmt_yi(min(values))}–{fmt_yi(max(values))}）"


def fmt_span(low: float, high: float) -> str:
    a, b = fmt_yi(low), fmt_yi(high)
    if a == b:
        return f"{a}亿元"
    return f"{a}–{b}亿元"


def fmt_pct(count: int, total: int) -> str:
    if total <= 0 or count <= 0:
        return "0.00%"
    pct = 100.0 * count / total
    if pct >= 0.01:
        return f"{pct:.2f}%"
    return f"{pct:.4f}%"


def load(conn: sqlite3.Connection) -> tuple[list[dict], dict]:
    cur = conn.cursor()
    names = [row[0] for row in cur.execute("SELECT name FROM hm_list")]
    date_min, date_max, n_rows = cur.execute(
        "SELECT MIN(trade_date), MAX(trade_date), COUNT(*) FROM hm_detail"
    ).fetchone()
    circs: dict[str, list[float]] = {name: [] for name in names}
    totals: dict[str, list[float]] = {name: [] for name in names}
    counts = {name: 0 for name in names}
    for hm_name, circ_wan, total_wan in cur.execute(
        """
        SELECT d.hm_name, b.circ_mv, b.total_mv
        FROM hm_detail d
        LEFT JOIN daily_basic b
          ON d.ts_code = b.ts_code AND d.trade_date = b.trade_date
        """
    ):
        if hm_name not in counts:
            continue
        counts[hm_name] += 1
        if circ_wan is not None and circ_wan > 0:
            circs[hm_name].append(circ_wan / 10_000.0)
        if total_wan is not None and total_wan > 0:
            totals[hm_name].append(total_wan / 10_000.0)

    n_detail = int(n_rows)
    rows = []
    for name in names:
        circ = circs[name]
        total_mv = totals[name]
        count = counts[name]
        span = shortest_cover(circ)
        rows.append(
            {
                "name": name,
                "count": count,
                "pct": fmt_pct(count, n_detail),
                "avg": fmt_avg_range(circ),
                "avg_total": fmt_avg_range(total_mv),
                "span": fmt_span(*span) if span else "—",
                "n_mv": len(circ),
            }
        )
    rows.sort(key=lambda item: (-item["count"], item["name"]))
    meta = {
        "date_min": str(date_min),
        "date_max": str(date_max),
        "n_rows": n_detail,
        "n_names": len(names),
        "n_idle": sum(1 for item in rows if item["count"] == 0),
    }
    return rows, meta


def draw_bars(rows: list[dict], meta: dict) -> Path:
    names = [item["name"] for item in rows]
    counts = [item["count"] for item in rows]
    fig, ax = plt.subplots(figsize=(26, 9))
    ax.bar(range(len(rows)), counts, width=0.82, color="#3C6E9F", zorder=2)
    ax.set_xlim(-0.6, len(rows) - 0.4)
    ax.set_ylim(0, max(counts) * 1.08 if counts else 1)
    ax.set_xticks(range(len(rows)))
    ax.set_xticklabels(names, fontsize=8)
    for label in ax.get_xticklabels():
        label.set_rotation(90)
        label.set_ha("center")
        label.set_va("top")
        label.set_rotation_mode("anchor")
    ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _p: f"{int(v):,}"))
    ax.set_axisbelow(True)
    ax.yaxis.grid(True, color="#E2E6EA", linewidth=0.8)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.tick_params(axis="y", labelsize=10)
    ax.set_ylabel("操作次数", fontsize=12)
    ax.set_title(
        f"{meta['n_names']} 个游资的操作次数\n按次数从高到低 · {meta['date_min']} 至 {meta['date_max']}",
        fontsize=16,
        pad=12,
    )
    note = (
        f"名录 hm_list 共 {meta['n_names']} 个，其中 {meta['n_idle']} 个在此区间没有明细，次数为 0。"
        f"一次操作计 hm_detail 一行，合计 {meta['n_rows']:,} 次。"
    )
    fig.text(0.012, 0.012, note, fontsize=9, color="#5C6570", ha="left", va="bottom")
    fig.tight_layout(rect=(0, 0.04, 1, 1))
    fig.subplots_adjust(bottom=0.22)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / "游资操作次数.png"
    fig.savefig(path, dpi=140)
    plt.close(fig)
    return path


def draw_table(rows: list[dict], meta: dict) -> Path:
    headers = [
        "游资名称",
        "操作次数",
        "占全部比例",
        "平均流通市值（亿元）",
        "平均总市值（亿元）",
        "七成操作的流通市值区间",
    ]
    col_w = [2.3, 1.5, 1.6, 3.5, 3.5, 4.2]
    row_h = 0.34
    left = 0.28
    top_pad = 1.15
    bottom_pad = 0.85
    width = left + sum(col_w) + 0.28
    height = top_pad + row_h * (len(rows) + 1) + bottom_pad
    fig = plt.figure(figsize=(width, height), dpi=130)
    ax = fig.add_axes((0, 0, 1, 1))
    ax.set_xlim(0, width)
    ax.set_ylim(0, height)
    ax.axis("off")
    fig.patch.set_facecolor("white")

    ax.text(
        width / 2,
        height - 0.42,
        "游资操作统计",
        ha="center",
        va="center",
        fontsize=16,
        color="#1A1A1A",
    )
    ax.text(
        width / 2,
        height - 0.82,
        f"{meta['date_min']} 至 {meta['date_max']} · 按操作次数从高到低",
        ha="center",
        va="center",
        fontsize=10,
        color="#5C6570",
    )

    def cell_text(item: dict, col: int) -> str:
        if col == 0:
            return item["name"]
        if col == 1:
            return f"{item['count']:,}"
        if col == 2:
            return item["pct"]
        if col == 3:
            return item["avg"]
        if col == 4:
            return item["avg_total"]
        return item["span"]

    y = height - top_pad - row_h
    header_color = "#1F3A5F"
    ax.add_patch(Rectangle((left, y), sum(col_w), row_h, facecolor=header_color, edgecolor="none"))
    x = left
    for header, w in zip(headers, col_w):
        ax.text(
            x + 0.12,
            y + row_h / 2,
            header,
            ha="left",
            va="center",
            fontsize=10,
            color="white",
        )
        x += w

    for i, item in enumerate(rows):
        y -= row_h
        bg = "#F4F7FB" if i % 2 == 0 else "#FFFFFF"
        ax.add_patch(Rectangle((left, y), sum(col_w), row_h, facecolor=bg, edgecolor="none"))
        x = left
        for col, w in enumerate(col_w):
            ax.text(
                x + 0.12,
                y + row_h / 2,
                cell_text(item, col),
                ha="left",
                va="center",
                fontsize=9.5,
                color="#1A1A1A",
            )
            x += w

    note = (
        "次数为游资每日明细行数，比例的分母是全部明细。"
        "平均流通市值、平均总市值是各次操作当日市值的算术平均，括号内为最小–最大。"
        "七成区间是覆盖至少 70% 有流通市值的操作、且跨度最小的流通市值范围；没有对应市值的操作不计入该列。"
        f"名录 {meta['n_names']} 个，明细 {meta['n_rows']:,} 行，{meta['n_idle']} 个游资次数为 0。"
    )
    ax.text(left, 0.38, note, ha="left", va="center", fontsize=8.5, color="#5C6570")
    path = OUT_DIR / "游资操作统计.png"
    fig.savefig(path, dpi=130)
    plt.close(fig)
    return path


def write_md(rows: list[dict], meta: dict) -> Path:
    path = OUT_DIR / "游资操作统计.md"
    headers = [
        "游资名称",
        "操作次数",
        "占全部比例",
        "平均流通市值（亿元）",
        "平均总市值（亿元）",
        "七成操作的流通市值区间",
    ]
    lines = [
        "# 游资操作统计",
        "",
        (
            f"区间 {meta['date_min']} 至 {meta['date_max']}，按操作次数从高到低。"
            f"次数为 hm_detail 行数，比例分母为全部 {meta['n_rows']:,} 行。"
            "平均流通市值、平均总市值使用操作当日市值（亿元），括号内为最小–最大；没有对应市值的行不计入该列。"
            "七成区间按流通市值计算，为覆盖至少 70% 有流通市值操作且宽度最小的一段。"
        ),
        "",
        "| " + " | ".join(headers) + " |",
        "| --- | ---: | ---: | --- | --- | --- |",
    ]
    for item in rows:
        cells = [
            item["name"],
            f"{item['count']:,}",
            item["pct"],
            item["avg"],
            item["avg_total"],
            item["span"],
        ]
        lines.append("| " + " | ".join(cells) + " |")
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def write_csv(rows: list[dict], meta: dict) -> Path:
    path = OUT_DIR / "游资操作统计.csv"
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            ["游资名称", "操作次数", "占全部比例", "平均流通市值（亿元）", "平均总市值（亿元）", "七成操作的流通市值区间"]
        )
        for item in rows:
            writer.writerow(
                [
                    item["name"],
                    item["count"],
                    item["pct"],
                    "" if item["avg"] == "—" else item["avg"],
                    "" if item["avg_total"] == "—" else item["avg_total"],
                    "" if item["span"] == "—" else item["span"],
                ]
            )
        writer.writerow([])
        writer.writerow(
            [
                "说明",
                (
                    f"次数为 hm_detail 行数，比例分母为全部 {meta['n_rows']} 行。"
                    "平均流通市值、平均总市值使用操作当日市值（亿元），括号内为最小–最大；没有对应市值的行不计入该列。"
                    "七成区间按流通市值计算，为覆盖至少 70% 有流通市值操作且宽度最小的一段。"
                    f"区间 {meta['date_min']} 至 {meta['date_max']}。"
                ),
            ]
        )
    return path


def main() -> None:
    with sqlite3.connect(f"file:{DB_PATH.as_posix()}?mode=ro", uri=True) as conn:
        rows, meta = load(conn)
    if sum(item["count"] for item in rows) != meta["n_rows"]:
        raise SystemExit("游资次数合计与明细行数不一致")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    bar_path = draw_bars(rows, meta)
    table_path = draw_table(rows, meta)
    csv_path = write_csv(rows, meta)
    md_path = write_md(rows, meta)
    print(bar_path)
    print(table_path)
    print(csv_path)
    print(md_path)
    print(f"names={meta['n_names']} rows={meta['n_rows']} idle={meta['n_idle']}")


if __name__ == "__main__":
    main()
