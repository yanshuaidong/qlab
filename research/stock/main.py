#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""超大单 × 价量背离：5 日窗口四类日子的随后收益与超额。"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[2]
DB_PATH = REPO_ROOT / "storage" / "stock" / "data.sqlite"
TABLE_PATH = Path(__file__).resolve().parent / "表格.md"
REPORT_PATH = Path(__file__).resolve().parent / "report.md"

HORIZONS = (1, 2, 3, 4, 5, 6, 8, 10, 15, 20)
WIN = 5
VOL_LOOKBACK = 20
NEED_DAYS = WIN + VOL_LOOKBACK  # 5 日窗口 + 再往前 20 日量
MIN_MV_YI = 500.0
MAX_MV_YI = 2000.0
MV_WAN_PER_YI = 10000.0
MIN_MV_WAN = MIN_MV_YI * MV_WAN_PER_YI
MAX_MV_WAN = MAX_MV_YI * MV_WAN_PER_YI
# 左闭右开；末档含 2000 亿。
MV_BUCKETS = (
    (500.0, 600.0),
    (600.0, 700.0),
    (700.0, 800.0),
    (800.0, 900.0),
    (900.0, 1000.0),
    (1000.0, 1500.0),
    (1500.0, 2000.0),
)
TYPES = ("吸筹", "追涨", "杀跌", "派发")
ABSORB_VOL_TYPES = ("缩量吸筹", "放量吸筹")
# daily.amount 千元；moneyflow_dc.buy_elg_amount 万元。
AMOUNT_QIAN_PER_WAN = 10.0


def mv_range_label(lo_yi: float, hi_yi: float) -> str:
    return f"{lo_yi:.0f}–{hi_yi:.0f} 亿"


def slice_mv(frame: pd.DataFrame, lo_yi: float, hi_yi: float, last: bool) -> pd.DataFrame:
    lo = lo_yi * MV_WAN_PER_YI
    hi = hi_yi * MV_WAN_PER_YI
    mv = frame["total_mv"]
    if last:
        mask = (mv >= lo) & (mv <= hi)
    else:
        mask = (mv >= lo) & (mv < hi)
    return frame.loc[mask].copy()


def group_roll(frame: pd.DataFrame, col: str, window: int, how: str) -> pd.Series:
    rolled = frame.groupby("ts_code", sort=False)[col].rolling(window, min_periods=window)
    if how == "sum":
        out = rolled.sum()
    elif how == "mean":
        out = rolled.mean()
    else:
        raise ValueError(how)
    return out.reset_index(level=0, drop=True)


def load_frame(conn: sqlite3.Connection) -> pd.DataFrame:
    daily = pd.read_sql_query(
        "SELECT ts_code, trade_date, close, pct_chg, vol, amount FROM daily",
        conn,
    )
    moneyflow = pd.read_sql_query(
        """
        SELECT ts_code, trade_date, buy_elg_amount, buy_elg_amount_rate
        FROM moneyflow_dc
        """,
        conn,
    )
    cap = pd.read_sql_query(
        """
        SELECT ts_code, trade_date, total_mv
        FROM daily_basic
        WHERE total_mv >= ? AND total_mv <= ?
        """,
        conn,
        params=(MIN_MV_WAN, MAX_MV_WAN),
    )

    frame = daily.merge(moneyflow, on=["ts_code", "trade_date"], how="left")
    frame = frame.sort_values(["ts_code", "trade_date"], kind="mergesort").reset_index(drop=True)

    cal = {d: i for i, d in enumerate(sorted(frame["trade_date"].unique()))}
    frame["di"] = frame["trade_date"].map(cal).astype(np.int32)

    g = frame.groupby("ts_code", sort=False)
    close_g = g["close"]
    for horizon in HORIZONS:
        frame[f"c{horizon}"] = close_g.shift(-horizon)

    frame["_log1p"] = np.log1p(frame["pct_chg"].to_numpy(dtype=np.float64) / 100.0)
    frame["elg_5"] = group_roll(frame, "buy_elg_amount", WIN, "sum")
    frame["amt_5"] = group_roll(frame, "amount", WIN, "sum")
    frame["vol_5"] = group_roll(frame, "vol", WIN, "mean")
    frame["vol_ma20"] = group_roll(frame, "vol", VOL_LOOKBACK, "mean")
    frame["log_5"] = group_roll(frame, "_log1p", WIN, "sum")

    g = frame.groupby("ts_code", sort=False)
    frame["vol_prev20"] = g["vol_ma20"].shift(WIN)
    frame["di_lag4"] = g["di"].shift(WIN - 1)
    frame["di_lag24"] = g["di"].shift(NEED_DAYS - 1)
    frame["ok5"] = frame["di"] - frame["di_lag4"] == (WIN - 1)
    frame["ok25"] = frame["di"] - frame["di_lag24"] == (NEED_DAYS - 1)
    frame["cum5"] = np.expm1(frame["log_5"].to_numpy(dtype=np.float64))
    frame["elg_ratio"] = frame["elg_5"] / (frame["amt_5"] / AMOUNT_QIAN_PER_WAN)

    for horizon in HORIZONS:
        frame[f"r{horizon}"] = frame[f"c{horizon}"] / frame["close"] - 1.0

    event = frame.merge(cap, on=["ts_code", "trade_date"], how="inner")
    event = event.loc[
        event["ok25"]
        & event["ok5"]
        & (event["close"] > 0)
        & event["cum5"].notna()
        & event["elg_ratio"].notna()
        & (event["elg_ratio"] != 0)
        & event["vol_5"].notna()
        & event["vol_prev20"].notna()
        & np.isfinite(event["elg_ratio"])
        & np.isfinite(event["cum5"])
        & np.isfinite(event["vol_5"])
        & np.isfinite(event["vol_prev20"])
    ].copy()

    up5 = event["cum5"].to_numpy() > 0
    buy = event["elg_ratio"].to_numpy() > 0
    kind = np.empty(len(event), dtype=object)
    kind[~up5 & buy] = "吸筹"
    kind[up5 & buy] = "追涨"
    kind[~up5 & ~buy] = "杀跌"
    kind[up5 & ~buy] = "派发"
    event["kind"] = kind
    vol_up = event["vol_5"].to_numpy() > event["vol_prev20"].to_numpy()
    absorb = np.full(len(event), "", dtype=object)
    is_abs = kind == "吸筹"
    absorb[is_abs & ~vol_up] = "缩量吸筹"
    absorb[is_abs & vol_up] = "放量吸筹"
    event["absorb_vol"] = absorb
    event["old_inflow"] = event["buy_elg_amount_rate"].to_numpy() > 0
    return event


def add_excess(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    dates = out["trade_date"]
    for horizon in HORIZONS:
        ret = out[f"r{horizon}"]
        mask = ret.notna() & np.isfinite(ret)
        out[f"ex{horizon}"] = np.nan
        if not mask.any():
            continue
        mu = ret.where(mask).groupby(dates).transform("mean")
        out.loc[mask, f"ex{horizon}"] = ret.loc[mask] - mu.loc[mask]
    return out


def _mask_stats(frame: pd.DataFrame, mask: pd.Series) -> dict[str, object]:
    n = int(mask.sum())
    up: list[float] = []
    mean_ret: list[float] = []
    excess: list[float] = []
    n_h: list[int] = []
    for horizon in HORIZONS:
        ret = frame.loc[mask, f"r{horizon}"]
        ex = frame.loc[mask, f"ex{horizon}"]
        valid = ret.notna() & np.isfinite(ret) & ex.notna() & np.isfinite(ex)
        n_valid = int(valid.sum())
        n_h.append(n_valid)
        if n_valid == 0:
            up.append(float("nan"))
            mean_ret.append(float("nan"))
            excess.append(float("nan"))
            continue
        r = ret.loc[valid].to_numpy(dtype=np.float64)
        e = ex.loc[valid].to_numpy(dtype=np.float64)
        up.append(float((r > 0).mean() * 100.0))
        mean_ret.append(float(r.mean() * 100.0))
        excess.append(float(e.mean() * 100.0))
    return {"n": n, "n_h": n_h, "up": up, "mean": mean_ret, "ex": excess}


def summarize(frame: pd.DataFrame) -> dict[str, object]:
    work = add_excess(frame)
    by_kind = {name: _mask_stats(work, work["kind"] == name) for name in TYPES}
    all_stats = _mask_stats(work, pd.Series(True, index=work.index))
    by_vol = {
        name: _mask_stats(work, work["absorb_vol"] == name) for name in ABSORB_VOL_TYPES
    }
    old_in = _mask_stats(work, work["old_inflow"])
    if len(work) == 0:
        date_min = ""
        date_max = ""
    else:
        date_min = str(work["trade_date"].min())
        date_max = str(work["trade_date"].max())
    return {
        "event_n": int(len(work)),
        "n_stocks": int(work["ts_code"].nunique()) if len(work) else 0,
        "date_min": date_min,
        "date_max": date_max,
        "by_kind": by_kind,
        "all": all_stats,
        "by_vol": by_vol,
        "old_in": old_in,
    }


def fmt_num(value: object, signed: bool = False) -> str:
    if value is None or (isinstance(value, float) and not np.isfinite(value)):
        return ""
    number = float(value)
    if signed:
        return f"{number:+.2f}"
    return f"{number:.2f}"


def render_metric_table(
    rows: list[tuple[str, dict[str, object]]],
    metric: str,
    signed: bool,
    n_h: list[int],
    zero_all_excess: bool = False,
) -> str:
    headers = ["类型", "条数", *[f"{h}日" for h in HORIZONS]]
    aligns = [" :---", "---:", *["---:" for _ in HORIZONS]]
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join(aligns) + " |",
    ]
    for name, stats in rows:
        values = list(stats[metric])  # type: ignore[index]
        if zero_all_excess and name == "全部" and metric == "ex":
            values = [0.0 if np.isfinite(v) else v for v in values]
        cells = [
            name,
            f"{int(stats['n']):,}",
            *[fmt_num(v, signed=signed) for v in values],
        ]
        lines.append("| " + " | ".join(cells) + " |")
    n_row = ["各持有期有效条数", "", *[f"{n:,}" for n in n_h]]
    lines.append("| " + " | ".join(n_row) + " |")
    return "\n".join(lines) + "\n"


def kind_rows(meta: dict[str, object]) -> list[tuple[str, dict[str, object]]]:
    by_kind: dict[str, dict[str, object]] = meta["by_kind"]  # type: ignore[assignment]
    rows = [(name, by_kind[name]) for name in TYPES]
    rows.append(("全部", meta["all"]))  # type: ignore[arg-type]
    return rows


def vol_rows(meta: dict[str, object]) -> list[tuple[str, dict[str, object]]]:
    by_vol: dict[str, dict[str, object]] = meta["by_vol"]  # type: ignore[assignment]
    return [(name, by_vol[name]) for name in ABSORB_VOL_TYPES]


def render_section_tables(meta: dict[str, object]) -> str:
    krows = kind_rows(meta)
    vrows = vol_rows(meta)
    all_nh: list[int] = meta["all"]["n_h"]  # type: ignore[index, assignment]
    abs_nh: list[int] = meta["by_kind"]["吸筹"]["n_h"]  # type: ignore[index, assignment]
    parts = [
        "#### 表 1：四种日子",
        "",
        "上涨概率（%）",
        "",
        render_metric_table(krows, "up", signed=False, n_h=all_nh),
        "平均涨跌（%）",
        "",
        render_metric_table(krows, "mean", signed=True, n_h=all_nh),
        "比别人高多少（超额，百分点）",
        "",
        render_metric_table(krows, "ex", signed=True, n_h=all_nh, zero_all_excess=True),
        "#### 表 2：吸筹按成交量拆开",
        "",
        "上涨概率（%）",
        "",
        render_metric_table(vrows, "up", signed=False, n_h=abs_nh),
        "平均涨跌（%）",
        "",
        render_metric_table(vrows, "mean", signed=True, n_h=abs_nh),
        "比别人高多少（超额，百分点）",
        "",
        render_metric_table(vrows, "ex", signed=True, n_h=abs_nh),
    ]
    return "\n".join(parts)


def _h_idx(horizon: int) -> int:
    return HORIZONS.index(horizon)


def _ex(stats: dict[str, object], horizon: int) -> float:
    return float(stats["ex"][_h_idx(horizon)])  # type: ignore[index]


def _up(stats: dict[str, object], horizon: int) -> float:
    return float(stats["up"][_h_idx(horizon)])  # type: ignore[index]


def _mean(stats: dict[str, object], horizon: int) -> float:
    return float(stats["mean"][_h_idx(horizon)])  # type: ignore[index]


def _finite(*values: float) -> bool:
    return all(np.isfinite(v) for v in values)


def checks(meta: dict[str, object]) -> dict[str, object]:
    by_kind: dict[str, dict[str, object]] = meta["by_kind"]  # type: ignore[assignment]
    by_vol: dict[str, dict[str, object]] = meta["by_vol"]  # type: ignore[assignment]
    abs_s = by_kind["吸筹"]
    chase = by_kind["追涨"]
    quiet = by_vol["缩量吸筹"]
    loud = by_vol["放量吸筹"]
    old_in: dict[str, object] = meta["old_in"]  # type: ignore[assignment]

    def cmp_pair(left: dict[str, object], right: dict[str, object], horizon: int) -> float:
        return _ex(left, horizon) - _ex(right, horizon)

    c1_1 = cmp_pair(abs_s, chase, 1)
    c1_5 = cmp_pair(abs_s, chase, 5)
    c2_1 = _ex(abs_s, 1)
    c2_5 = _ex(abs_s, 5)
    c3_1 = cmp_pair(quiet, loud, 1)
    c3_5 = cmp_pair(quiet, loud, 5)
    ok1 = _finite(c1_1, c1_5) and c1_1 > 0 and c1_5 > 0
    ok2 = _finite(c2_1, c2_5) and c2_1 > 0 and c2_5 > 0
    ok3 = _finite(c3_1, c3_5) and c3_1 >= 0 and c3_5 >= 0
    return {
        "c1_1": c1_1,
        "c1_5": c1_5,
        "c2_1": c2_1,
        "c2_5": c2_5,
        "c3_1": c3_1,
        "c3_5": c3_5,
        "ok1": ok1,
        "ok2": ok2,
        "ok3": ok3,
        "all_ok": ok1 and ok2 and ok3,
        "abs_n": int(abs_s["n"]),
        "chase_n": int(chase["n"]),
        "kill_n": int(by_kind["杀跌"]["n"]),
        "dist_n": int(by_kind["派发"]["n"]),
        "quiet_n": int(quiet["n"]),
        "loud_n": int(loud["n"]),
        "old_ex1": _ex(old_in, 1),
        "old_ex5": _ex(old_in, 5),
        "abs_up1": _up(abs_s, 1),
        "chase_up1": _up(chase, 1),
        "abs_m1": _mean(abs_s, 1),
        "chase_m1": _mean(chase, 1),
        "abs_up5": _up(abs_s, 5),
        "chase_up5": _up(chase, 5),
        "quiet_ex1": _ex(quiet, 1),
        "loud_ex1": _ex(loud, 1),
        "quiet_ex5": _ex(quiet, 5),
        "loud_ex5": _ex(loud, 5),
    }


def yn(ok: bool) -> str:
    return "成立" if ok else "不成立"


def render_observations(meta: dict[str, object]) -> str:
    event_n = int(meta["event_n"])
    if event_n == 0:
        return "该市值档没有有效事件。"
    c = checks(meta)
    return (
        f"- 有效事件 **{event_n:,}** 条、**{int(meta['n_stocks']):,}** 只股票。"
        f"吸筹 {c['abs_n']:,} 条，追涨 {c['chase_n']:,} 条，"
        f"杀跌 {c['kill_n']:,} 条，派发 {c['dist_n']:,} 条。\n"
        f"- 1 日超额：吸筹 {c['c2_1']:+.2f} 个百分点，追涨 {_ex(meta['by_kind']['追涨'], 1):+.2f} 个百分点，"
        f"吸筹比追涨 {c['c1_1']:+.2f} 个百分点。"
        f"5 日超额：吸筹 {c['c2_5']:+.2f}，追涨 {_ex(meta['by_kind']['追涨'], 5):+.2f}，"
        f"吸筹比追涨 {c['c1_5']:+.2f} 个百分点。\n"
        f"- 1 日上涨概率吸筹 {c['abs_up1']:.2f}%、追涨 {c['chase_up1']:.2f}%；"
        f"1 日平均涨跌吸筹 {c['abs_m1']:+.2f}%、追涨 {c['chase_m1']:+.2f}%。"
        f"5 日上涨概率吸筹 {c['abs_up5']:.2f}%、追涨 {c['chase_up5']:.2f}%。\n"
        f"- 吸筹相对当天同类：1 日{'跑赢' if c['c2_1'] > 0 else '跑输'}，"
        f"5 日{'跑赢' if c['c2_5'] > 0 else '跑输'}。\n"
        f"- 缩量吸筹 {c['quiet_n']:,} 条，1 日超额 {c['quiet_ex1']:+.2f}、5 日 {c['quiet_ex5']:+.2f}；"
        f"放量吸筹 {c['loud_n']:,} 条，1 日超额 {c['loud_ex1']:+.2f}、5 日 {c['loud_ex5']:+.2f}。"
        f"缩量相对放量：1 日 {c['c3_1']:+.2f}、5 日 {c['c3_5']:+.2f} 个百分点。\n"
        f"- 对照：旧办法「当天超大单净买入」1 日超额 {c['old_ex1']:+.2f} 个百分点，"
        f"5 日超额 {c['old_ex5']:+.2f} 个百分点。全部日子超额为 0。\n"
        f"- 三句判定（看 1 日和 5 日）：吸筹强于追涨 **{yn(bool(c['ok1']))}**；"
        f"吸筹超额为正 **{yn(bool(c['ok2']))}**；"
        f"缩量不差于放量 **{yn(bool(c['ok3']))}**。"
    )


def render_report(
    overall: dict[str, object],
    sections: list[tuple[float, float, dict[str, object]]],
    date_min: str,
    date_max: str,
) -> str:
    generated = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    bucket_txt = "、".join(mv_range_label(lo, hi) for lo, hi, _ in sections)
    oc = checks(overall)
    bucket_ok = [checks(meta) for _, _, meta in sections]
    n_ok1 = sum(1 for c in bucket_ok if c["ok1"])
    n_ok2 = sum(1 for c in bucket_ok if c["ok2"])
    n_ok3 = sum(1 for c in bucket_ok if c["ok3"])
    n_all = sum(1 for c in bucket_ok if c["all_ok"])
    parts = [
        "# 超大单 × 价量背离",
        "",
        f"生成时间：{generated}",
        "",
        "数据：`storage/stock/data.sqlite` 中东财 `moneyflow_dc.buy_elg_amount`（万元）+ `daily.pct_chg` / `vol` / `amount`（千元）+ `daily.close` + `daily_basic.total_mv`。",
        f"事件日区间：{date_min} ~ {date_max}。一只股票一个交易日算一条。先保留事件日总市值 **{MIN_MV_YI:.0f}–{MAX_MV_YI:.0f} 亿**，再按事件日市值拆成 7 档：{bucket_txt}。市值左闭右开，末档含 2000 亿。",
        "",
        "## 口径",
        "",
        f"- 窗口：最近 **{WIN}** 个交易日（含当天）。5 天里缺涨跌、成交量或超大单，或这 5 天在该股行情里不连续，这条丢掉，不拿更早的日子凑数。再往前 **{VOL_LOOKBACK}** 天成交量不够的也不进表。",
        "- 超大单比例：5 日 `buy_elg_amount` 之和 / 5 日成交额之和。成交额由 `daily.amount`（千元）换成万元再除。不用 5 个每日占比相加。比例正好为 0 的丢掉。",
        "- 股价：5 日 `pct_chg` 复利累计。`> 0` 算涨了；没涨、平、跌都算没涨。",
        "- 成交量：这 5 天均量 vs 再往前 20 天均量。更高算放量，否则算缩量。",
        "- 四种日子：吸筹（没涨且超大单买）、追涨（涨了且买）、杀跌（没涨且卖）、派发（涨了且卖）。表 2 只拆吸筹。",
        f"- 持有期 `h ∈ {{{', '.join(str(h) for h in HORIZONS)}}}`。从事件日收盘算到随后第 `h` 个该股交易日收盘。上涨定义为收盘价更高。无后续收盘价的，那一列不算它。",
        "- 超额：同一天、本表股票池里所有有效样本的平均涨跌当尺子。合计表用 500–2000 亿整天的平均，不用 7 档超额再混加。全部那一行超额为 0。",
        "- 对照：旧办法只看当天 `buy_elg_amount_rate > 0`。",
        "",
        "## 合计 500–2000 亿先看这三句",
        "",
        f"- 吸筹后面要比追涨强（1 日、5 日超额）：**{yn(bool(oc['ok1']))}**。"
        f"1 日吸筹比追涨 {oc['c1_1']:+.2f} 个百分点，5 日 {oc['c1_5']:+.2f}。",
        f"- 吸筹要真比当天同类强（超额为正）：**{yn(bool(oc['ok2']))}**。"
        f"1 日 {oc['c2_1']:+.2f}，5 日 {oc['c2_5']:+.2f}。",
        f"- 缩量吸筹应不差于放量吸筹：**{yn(bool(oc['ok3']))}**。"
        f"1 日缩量相对放量 {oc['c3_1']:+.2f}，5 日 {oc['c3_5']:+.2f}。",
        f"- 三句都成立才值得往下加条件：合计表 **{yn(bool(oc['all_ok']))}**。"
        f"7 档里条件 1 有 {n_ok1}/7 档成立，条件 2 有 {n_ok2}/7，条件 3 有 {n_ok3}/7，三句都成立 {n_all}/7。",
        f"- 旧办法当天净买入：1 日超额 {oc['old_ex1']:+.2f}，5 日 {oc['old_ex5']:+.2f}。",
        f"- 更长持有期表里能看到：10 日吸筹超额 {_ex(overall['by_kind']['吸筹'], 10):+.2f}、追涨 {_ex(overall['by_kind']['追涨'], 10):+.2f}；"
        f"20 日吸筹 {_ex(overall['by_kind']['吸筹'], 20):+.2f}、追涨 {_ex(overall['by_kind']['追涨'], 20):+.2f}。"
        f"方案事先盯的是 1 日和 5 日，那两天吸筹并不比追涨强，所以合计仍判不成立。",
        "",
        "## 总市值 500–2000 亿（合计）",
        "",
        render_section_tables(overall),
        "超额的尺子是当天整个 500–2000 亿池子的平均，不是 7 档超额再平均。",
        "",
        "### 观察",
        "",
        render_observations(overall),
        "",
    ]
    for lo, hi, meta in sections:
        parts.extend(
            [
                f"## 总市值 {mv_range_label(lo, hi)}",
                "",
                render_section_tables(meta),
                "超额的尺子是当天本档股票的平均。",
                "",
                "### 观察",
                "",
                render_observations(meta),
                "",
            ]
        )
    parts.extend(
        [
            "## 限制",
            "",
            "- 超大单只是单笔金额大，不是某个庄家的户头。这轮只问大钱和股价拧不拧。",
            "- 趋势里会连续很多天都算吸筹，条数会偏多，不是一笔一笔互不相干的赌局。",
            "- 收盘价用未复权 `daily.close`，除权除息日会把后续收益算偏；窗口内涨跌用 `pct_chg`。",
            "- 靠近样本期末的事件没有足够后续交易日，短的列和长的列不是同一批股票。",
            "- 没扣手续费，也没特意拿掉涨跌停、停牌日；不是可交易策略。",
            "",
        ]
    )
    return "\n".join(parts)


def render_tables_file(
    overall: dict[str, object],
    sections: list[tuple[float, float, dict[str, object]]],
) -> str:
    blocks = [
        "## 总市值 500–2000 亿（合计）\n",
        render_section_tables(overall),
    ]
    for lo, hi, meta in sections:
        blocks.append(f"## 总市值 {mv_range_label(lo, hi)}\n")
        blocks.append(render_section_tables(meta))
    return "\n".join(blocks).rstrip() + "\n"


def main() -> int:
    if not DB_PATH.is_file():
        print(f"数据库不存在: {DB_PATH}")
        return 1

    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    try:
        frame = load_frame(conn)
    finally:
        conn.close()

    overall = summarize(frame)
    print(
        f"500–2000 亿 条数={int(overall['event_n']):,} 股票={int(overall['n_stocks']):,}"
    )
    oc = checks(overall)
    print(
        f"吸筹={oc['abs_n']:,} 追涨={oc['chase_n']:,} 杀跌={oc['kill_n']:,} 派发={oc['dist_n']:,}"
    )
    print(
        f"1日超额 吸筹{oc['c2_1']:+.3f} 追涨差{oc['c1_1']:+.3f}；"
        f"5日超额 吸筹{oc['c2_5']:+.3f} 追涨差{oc['c1_5']:+.3f}"
    )

    sections: list[tuple[float, float, dict[str, object]]] = []
    for i, (lo, hi) in enumerate(MV_BUCKETS):
        last = i == len(MV_BUCKETS) - 1
        sliced = slice_mv(frame, lo, hi, last=last)
        meta = summarize(sliced)
        sections.append((lo, hi, meta))
        c = checks(meta)
        print(
            f"{mv_range_label(lo, hi)} 条数={int(meta['event_n']):,} 股票={int(meta['n_stocks']):,} "
            f"吸筹{c['c2_1']:+.2f}/{c['c2_5']:+.2f} vs追涨 {c['c1_1']:+.2f}/{c['c1_5']:+.2f} "
            f"三句={yn(bool(c['all_ok']))}"
        )

    covered = sum(int(meta["event_n"]) for _, _, meta in sections)
    if covered != len(frame):
        print(f"警告：分档合计 {covered:,} 条，全样本 {len(frame):,} 条，对不上。")

    TABLE_PATH.write_text(render_tables_file(overall, sections), encoding="utf-8")
    REPORT_PATH.write_text(
        render_report(
            overall,
            sections,
            date_min=str(frame["trade_date"].min()) if len(frame) else "",
            date_max=str(frame["trade_date"].max()) if len(frame) else "",
        ),
        encoding="utf-8",
    )
    print(f"写入 {TABLE_PATH}")
    print(f"写入 {REPORT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
