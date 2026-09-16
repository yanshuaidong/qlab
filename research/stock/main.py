#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""千亿市值特大单买入占比与短期涨幅研究，结果写入同目录 report.md。"""

from __future__ import annotations

import sqlite3
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DB_PATH = REPO_ROOT / "storage" / "stock" / "data.sqlite"
REPORT_PATH = Path(__file__).resolve().parent / "report.md"

# daily_basic / moneyflow 金额单位均为万元；1000 亿 = 1e7 万元。
MV_MIN = 1e7
ELG_BUY_PCT = 0.05
WINDOWS = (3, 5, 10, 20)
AVG_OFFSETS = (19, 20, 21)
# 独立信号冷却：信号日后 COOLDOWN 个交易日内，同股不再计新信号。
COOLDOWN = 20
FLOAT_SPLIT = 0.30
BUCKETS = (
    (0.05, 0.10, "5%–10%"),
    (0.10, 0.20, "10%–20%"),
    (0.20, 0.30, "20%–30%"),
    (0.30, 0.50, "30%–50%"),
    (0.50, None, "≥50%"),
)
# 普通投资者可自由买：沪深主板（含原中小板）。排除科创板、创业板、北交所。
MAINBOARD_PREFIXES = (
    ("000", "SZ"),
    ("001", "SZ"),
    ("002", "SZ"),
    ("003", "SZ"),
    ("600", "SH"),
    ("601", "SH"),
    ("603", "SH"),
    ("605", "SH"),
)


def mainboard_sql(col: str = "ts_code") -> str:
    return "(" + " OR ".join(f"{col} LIKE '{p}%.{ex}'" for p, ex in MAINBOARD_PREFIXES) + ")"


def wan_to_yi(value: float) -> float:
    return value / 1e4


def fmt_yi(value: float | None, digits: int = 2) -> str:
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return "—"
    return f"{wan_to_yi(value):.{digits}f}"


def fmt_pct(value: float | None, digits: int = 2) -> str:
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return "—"
    return f"{value * 100:.{digits}f}%"


def fmt_int(value: int) -> str:
    return f"{value:,}"


def md_table(headers: list[str], rows: list[list[str]]) -> str:
    align = "| " + " | ".join(headers) + " |"
    sep = "| " + " | ".join("---" for _ in headers) + " |"
    body = ["| " + " | ".join(row) + " |" for row in rows]
    return "\n".join([align, sep, *body])


def assert_db(path: Path) -> None:
    if not path.is_file():
        raise SystemExit(f"未找到数据库：{path}")


def assert_daily_basic_coverage(conn: sqlite3.Connection) -> tuple[int, int]:
    n_daily = conn.execute("SELECT COUNT(DISTINCT trade_date) FROM daily").fetchone()[0]
    n_basic = conn.execute("SELECT COUNT(DISTINCT trade_date) FROM daily_basic").fetchone()[0]
    if n_basic < n_daily * 0.9:
        raise SystemExit(
            f"daily_basic 交易日 {n_basic} 明显少于 daily {n_daily}，"
            "请先运行: python collect/daily_basic.py --days 365"
        )
    return n_daily, n_basic


def load_names(conn: sqlite3.Connection) -> pd.DataFrame:
    return pd.read_sql_query(
        """
        SELECT ts_code, name
        FROM moneyflow_dc
        WHERE trade_date = (SELECT MAX(trade_date) FROM moneyflow_dc)
        """,
        conn,
    )


def load_universe_meta(conn: sqlite3.Connection) -> dict:
    row = conn.execute(
        f"""
        SELECT
            COUNT(*) AS stock_days,
            COUNT(DISTINCT m.ts_code) AS stocks,
            MIN(m.trade_date) AS start_date,
            MAX(m.trade_date) AS end_date
        FROM moneyflow m
        JOIN daily_basic b
          ON m.ts_code = b.ts_code AND m.trade_date = b.trade_date
        WHERE b.total_mv >= ?
          AND {mainboard_sql("m.ts_code")}
        """,
        (MV_MIN,),
    ).fetchone()
    daily_span = conn.execute(
        "SELECT MIN(trade_date), MAX(trade_date) FROM daily"
    ).fetchone()
    mf_span = conn.execute(
        "SELECT MIN(trade_date), MAX(trade_date) FROM moneyflow"
    ).fetchone()
    return {
        "stock_days": row[0],
        "stocks": row[1],
        "signal_pool_start": row[2],
        "signal_pool_end": row[3],
        "daily_start": daily_span[0],
        "daily_end": daily_span[1],
        "moneyflow_start": mf_span[0],
        "moneyflow_end": mf_span[1],
    }


def load_signals(conn: sqlite3.Connection) -> pd.DataFrame:
    return pd.read_sql_query(
        f"""
        SELECT
            m.ts_code,
            m.trade_date,
            m.buy_elg_amount,
            m.net_mf_amount,
            b.total_mv,
            b.circ_mv,
            d.close AS close_t
        FROM moneyflow m
        JOIN daily_basic b
          ON m.ts_code = b.ts_code AND m.trade_date = b.trade_date
        JOIN daily d
          ON m.ts_code = d.ts_code AND m.trade_date = d.trade_date
        WHERE b.total_mv >= ?
          AND b.circ_mv > 0
          AND (m.buy_elg_amount / b.circ_mv) >= ?
          AND {mainboard_sql("m.ts_code")}
        ORDER BY m.trade_date, m.ts_code
        """,
        conn,
        params=(MV_MIN, ELG_BUY_PCT),
    )


def load_daily_bars(conn: sqlite3.Connection, codes: list[str]) -> pd.DataFrame:
    if not codes:
        return pd.DataFrame(columns=["ts_code", "trade_date", "high", "low", "close"])
    placeholders = ",".join("?" for _ in codes)
    return pd.read_sql_query(
        f"""
        SELECT ts_code, trade_date, high, low, close
        FROM daily
        WHERE ts_code IN ({placeholders})
        ORDER BY ts_code, trade_date
        """,
        conn,
        params=codes,
    )


def forward_metrics(bars: pd.DataFrame, signal_date: str, close_t: float) -> dict:
    dates = bars["trade_date"].to_numpy()
    idx = np.where(dates == signal_date)[0]
    out = {f"high_ret_{w}": np.nan for w in WINDOWS}
    out["avg20_ret"] = np.nan
    if len(idx) == 0 or close_t is None or close_t <= 0:
        return out
    i = int(idx[0])
    highs = bars["high"].to_numpy(dtype=float)
    lows = bars["low"].to_numpy(dtype=float)
    n = len(bars)
    for w in WINDOWS:
        last = i + w
        if last >= n:
            continue
        window = highs[i + 1 : last + 1]
        if window.size == w and np.isfinite(window).all():
            out[f"high_ret_{w}"] = float(window.max() / close_t - 1.0)
    last_avg = i + AVG_OFFSETS[-1]
    if last_avg < n:
        vals = []
        ok = True
        for k in AVG_OFFSETS:
            h = highs[i + k]
            low = lows[i + k]
            if not (np.isfinite(h) and np.isfinite(low)):
                ok = False
                break
            vals.extend((h, low))
        if ok and len(vals) == 6:
            out["avg20_ret"] = float((sum(vals) / 6.0) / close_t - 1.0)
    return out


def add_forward_returns(signals: pd.DataFrame, daily: pd.DataFrame) -> pd.DataFrame:
    by_code = {code: g.reset_index(drop=True) for code, g in daily.groupby("ts_code", sort=False)}
    rows = []
    for row in signals.itertuples(index=False):
        bars = by_code.get(row.ts_code)
        metrics = (
            forward_metrics(bars, row.trade_date, row.close_t)
            if bars is not None
            else {f"high_ret_{w}": np.nan for w in WINDOWS} | {"avg20_ret": np.nan}
        )
        rows.append(metrics)
    return pd.concat([signals.reset_index(drop=True), pd.DataFrame(rows)], axis=1)


def mark_independent_signals(
    df: pd.DataFrame, daily: pd.DataFrame, cooldown: int = COOLDOWN
) -> pd.DataFrame:
    """同股：保留首个信号，其后 cooldown 个交易日内的触发视为延续，不记新信号。"""
    out = df.sort_values(["ts_code", "trade_date"]).copy()
    pos = {
        code: {d: i for i, d in enumerate(g["trade_date"].tolist())}
        for code, g in daily.groupby("ts_code", sort=False)
    }
    flags: list[bool] = []
    for code, g in out.groupby("ts_code", sort=False):
        mapping = pos.get(code, {})
        last_kept: int | None = None
        for trade_date in g["trade_date"]:
            i = mapping.get(trade_date)
            keep = last_kept is None or i is None or i > last_kept + cooldown
            flags.append(keep)
            if keep and i is not None:
                last_kept = i
    out["independent"] = flags
    return out.sort_values(["trade_date", "ts_code"]).reset_index(drop=True)


def bucket_label(pct: float) -> str:
    for lo, hi, label in BUCKETS:
        if hi is None:
            if pct >= lo:
                return label
        elif lo <= pct < hi:
            return label
    return "其他"


def stats(series: pd.Series) -> dict:
    s = pd.to_numeric(series, errors="coerce").dropna()
    n = int(len(s))
    if n == 0:
        return {"n": 0, "win": np.nan, "mean": np.nan, "median": np.nan}
    return {
        "n": n,
        "win": float((s > 0).mean()),
        "mean": float(s.mean()),
        "median": float(s.median()),
    }


def stats_row(label: str, frame: pd.DataFrame) -> list[str]:
    cells = [label, fmt_int(len(frame))]
    for col in [f"high_ret_{w}" for w in WINDOWS] + ["avg20_ret"]:
        st = stats(frame[col])
        if st["n"] == 0:
            cells.append("—")
            continue
        suffix = "" if st["n"] == len(frame) else f" n={st['n']}"
        cells.append(
            f"胜率 {fmt_pct(st['win'])} / 均 {fmt_pct(st['mean'])} / 中 {fmt_pct(st['median'])}{suffix}"
        )
    return cells


def metric_headers() -> list[str]:
    return [
        "分组",
        "条数",
        "3日最高涨幅",
        "5日最高涨幅",
        "10日最高涨幅",
        "20日最高涨幅",
        "第20日均价涨幅",
    ]


DETAIL_HEADERS = [
    "日期",
    "名称",
    "类型",
    "总市值(亿)",
    "流通市值(亿)",
    "超大单买入(亿)",
    "超大单占比",
    "净流入占比",
    "3日最高涨幅",
    "5日最高涨幅",
    "10日最高涨幅",
    "20日最高涨幅",
    "第20日均价涨幅",
]


def detail_row(row) -> list[str]:
    return [
        row.trade_date,
        row.name or "—",
        "独立" if row.independent else "延续",
        fmt_yi(row.total_mv),
        fmt_yi(row.circ_mv),
        fmt_yi(row.buy_elg_amount),
        fmt_pct(row.elg_buy_pct),
        fmt_pct(row.net_pct),
        fmt_pct(row.high_ret_3),
        fmt_pct(row.high_ret_5),
        fmt_pct(row.high_ret_10),
        fmt_pct(row.high_ret_20),
        fmt_pct(row.avg20_ret),
    ]


def build_report(df: pd.DataFrame, meta: dict, n_daily: int, n_basic: int) -> str:
    today = date.today().isoformat()
    n_raw = len(df)
    indep = df[df["independent"]].copy() if n_raw else df
    n = len(indep)
    n_stocks = indep["ts_code"].nunique() if n else 0
    low_float = indep[indep["float_ratio"] < FLOAT_SPLIT] if n else indep
    high_float = indep[indep["float_ratio"] >= FLOAT_SPLIT] if n else indep

    by_date = df.sort_values(["trade_date", "ts_code"], kind="mergesort") if n_raw else df
    by_stock = (
        df.assign(_name=df["name"].fillna(""))
        .sort_values(["_name", "ts_code", "trade_date"], kind="mergesort")
        .drop(columns=["_name"])
        if n_raw
        else df
    )
    detail_rows = [detail_row(row) for row in by_date.itertuples(index=False)]
    stock_rows = [detail_row(row) for row in by_stock.itertuples(index=False)]

    overall_rows = [
        stats_row("全样本（按日事件）", df),
        stats_row(f"独立信号（同股{COOLDOWN}个交易日冷却）", indep),
    ]
    bucket_rows = []
    if n:
        indep = indep.copy()
        indep["bucket"] = indep["elg_buy_pct"].map(bucket_label)
        for _, _, label in BUCKETS:
            part = indep[indep["bucket"] == label]
            bucket_rows.append(stats_row(label, part))
    float_rows = [
        stats_row(f"流通比 < {FLOAT_SPLIT:.0%}", low_float),
        stats_row(f"流通比 ≥ {FLOAT_SPLIT:.0%}", high_float),
    ]

    avg20 = stats(indep["avg20_ret"]) if n else stats(pd.Series(dtype=float))
    high20 = stats(indep["high_ret_20"]) if n else stats(pd.Series(dtype=float))
    raw_avg20 = stats(df["avg20_ret"]) if n_raw else stats(pd.Series(dtype=float))
    high_float_avg20 = stats(high_float["avg20_ret"]) if n else stats(pd.Series(dtype=float))

    conclusions = []
    if n == 0:
        conclusions.append(
            f"观察期内没有总市值≥1000 亿且特大单买入金额/流通市值≥{ELG_BUY_PCT:.0%} 的交易日，无法讨论后续涨幅。"
        )
    else:
        float_note = (
            f"低流通比（<{FLOAT_SPLIT:.0%}）{len(low_float)} 条，"
            f"流通比≥{FLOAT_SPLIT:.0%} {len(high_float)} 条。"
        )
        if len(low_float) > len(high_float):
            float_note += "信号仍偏集中在流通盘偏小的股票，不能直接当成高流通蓝筹的规律。"
        conclusions.append(
            f"按日触发 {n_raw} 条，同股{COOLDOWN}个交易日冷却后剩 {n} 条独立信号，覆盖 {n_stocks} 只股票。"
            f"{float_note}"
        )
        if avg20["n"] == 0:
            conclusions.append("没有算满 T+19/T+20/T+21 的样本，第20日均价涨幅无法评价。")
        else:
            direction = "正" if avg20["median"] > 0 else "负" if avg20["median"] < 0 else "零"
            conclusions.append(
                f"第20日均价涨幅（相对信号日收盘，更接近拿住而不是最高价）样本 {avg20['n']} 条："
                f"胜率 {fmt_pct(avg20['win'])}，均值 {fmt_pct(avg20['mean'])}，中位数 {fmt_pct(avg20['median'])}（{direction}）。"
            )
            if n and n_raw != n and raw_avg20["n"]:
                conclusions.append(
                    f"若按日事件不去冷却（{n_raw} 条），第20日均价涨幅："
                    f"胜率 {fmt_pct(raw_avg20['win'])}，均值 {fmt_pct(raw_avg20['mean'])}，"
                    f"中位数 {fmt_pct(raw_avg20['median'])}。"
                )
        if avg20["n"] and (avg20["mean"] - avg20["median"]) > 0.10:
            conclusions.append(
                "第20日均价的均值明显高于中位数，是个别股票暴涨拉开的，"
                "中位数更能代表典型结果。"
            )
        if high20["n"]:
            conclusions.append(
                f"20日最高涨幅胜率 {fmt_pct(high20['win'])}、均值 {fmt_pct(high20['mean'])}。"
                "最高价口径天然偏乐观：只要窗口内高点曾高于信号日收盘即记为正，不代表持有到期赚钱。"
            )
        if high_float_avg20["n"]:
            conclusions.append(
                f"流通比≥{FLOAT_SPLIT:.0%} 子集的第20日均价涨幅："
                f"胜率 {fmt_pct(high_float_avg20['win'])}，均值 {fmt_pct(high_float_avg20['mean'])}，"
                f"中位数 {fmt_pct(high_float_avg20['median'])}（n={high_float_avg20['n']}）。"
            )
        elif n:
            conclusions.append(
                f"流通比≥{FLOAT_SPLIT:.0%} 的信号为 0 条：观察期内千亿且高流通的股票，"
                f"从未达到特大单买入/流通市值 {ELG_BUY_PCT:.0%}。"
            )
        conclusions.append(
            f"因此：特大单买入占流通市值 {ELG_BUY_PCT:.0%} 以上，在千亿主板股里仍偏少；"
            f"不能根据最高价涨幅单独断言会形成一波上涨趋势，应以第20日均价与独立信号（{COOLDOWN}日冷却）为准。"
        )

    lines = [
        "# 千亿市值特大单与短期涨幅研究",
        "",
        f"**报告日期**：{today}",
        f"**数据区间**：日线 {meta['daily_start']} ～ {meta['daily_end']}（{n_daily} 个交易日）；"
        f"资金流向 {meta['moneyflow_start']} ～ {meta['moneyflow_end']}；"
        f"每日指标交易日 {n_basic} 个。",
        f"**样本池**：信号日 `daily_basic.total_mv` ≥ 1000 亿，且限于沪深主板"
        f"（不含科创板、创业板、北交所），共 {fmt_int(meta['stocks'])} 只、"
        f"{fmt_int(meta['stock_days'])} 个股票·日。",
        f"**主信号**：特大单买入金额 `buy_elg_amount` / 流通市值 `circ_mv` ≥ {ELG_BUY_PCT:.0%}。"
        f"明细表保留同股 {COOLDOWN} 个交易日内的全部触发（含延续）；"
        f"汇总表仍用独立信号对照。",
        "",
        "---",
        "",
        "## 一、研究问题与口径",
        "",
        f"问题：总市值大于 1000 亿的沪深主板 A 股，若某日特大单买入金额占流通市值 {ELG_BUY_PCT:.0%} 以上，其后 3/5/10/20 个交易日是否容易走出上涨。",
        "",
        "- 样本限于沪深主板（600/601/603/605、000/001/002/003），排除科创板、创业板、北交所。",
        "- 市值、流通市值取**信号当日** `daily_basic`（万元），不使用期末快照。",
        "- 特大单为 Tushare `moneyflow` 单笔成交额 ≥100 万的主动买入金额，不是净流入；净流入只作对照列。",
        "- 涨幅基准为信号日未复权收盘价。观察窗为 **T+1 至 T+N**，不含信号日。",
        "- N 日最高涨幅 = 窗口内最高价 / 信号日收盘 − 1。",
        "- 第20日均价 = T+19、T+20、T+21 的最高价与最低价共 6 个数的算术平均；涨幅相对信号日收盘。",
        "- 交易日按该股自己的日线序列对齐，停牌日自然跳过；窗口不够则该指标为空，不进入对应汇总。",
        f"- 同一股票发出信号后，其后 {COOLDOWN} 个交易日的再次触发记为「延续」，"
        f"{COOLDOWN} 个交易日后再触发才记为新的独立信号。明细表保留全部触发，不剔除延续。"
        "「类型」列标独立 / 延续。",
        "- 汇总表仍给出独立信号对照，便于看出冷却前后的差异。",
        "- 价格未复权，20 日内分红除权可能造成个别跳空。",
        "",
        "## 二、详细表",
        "",
    ]
    if n_raw == 0:
        lines.append("无信号。")
    else:
        n_cont = n_raw - n
        lines.append(
            f"共 {n_raw} 条按日触发（独立 {n} 条，同股{COOLDOWN}个交易日内延续 {n_cont} 条，均保留）。"
            "金额单位亿元；占比与涨幅为百分数。"
        )
        lines.append("")
        lines.append("### 2.1 按信号日")
        lines.append("")
        lines.append("按信号日、代码排序。")
        lines.append("")
        lines.append(md_table(DETAIL_HEADERS, detail_rows))
        lines.append("")
        lines.append("### 2.2 按股票")
        lines.append("")
        lines.append("同一只股票放在一起，组内仍按信号日；股票按名称排序。")
        lines.append("")
        lines.append(md_table(DETAIL_HEADERS, stock_rows))
    lines.extend(
        [
            "",
            "## 三、汇总表",
            "",
            "每个单元格为：涨幅>0 的比例 / 均值 / 中位数。窗口不足的事件不计入该列（以 `n=` 标明）。",
            "第20日均价涨幅更接近「拿住」，3/5/10/20 日最高涨幅是乐观口径。",
            f"3.2、3.3 均基于独立信号（同股{COOLDOWN}个交易日冷却）。",
            "",
            "### 3.1 全样本与独立信号",
            "",
            md_table(metric_headers(), overall_rows),
            "",
            "### 3.2 按超大单占比分档（短庄经验区间）",
            "",
        ]
    )
    if bucket_rows:
        lines.append(md_table(metric_headers(), bucket_rows))
    else:
        lines.append("无信号。")
    lines.extend(
        [
            "",
            "### 3.3 按流通比",
            "",
            md_table(metric_headers(), float_rows),
            "",
            "## 四、简要结论",
            "",
        ]
    )
    for i, text in enumerate(conclusions, start=1):
        lines.append(f"{i}. {text}")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    assert_db(DB_PATH)
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    try:
        n_daily, n_basic = assert_daily_basic_coverage(conn)
        meta = load_universe_meta(conn)
        names = load_names(conn)
        signals = load_signals(conn)
        if signals.empty:
            report = build_report(
                pd.DataFrame(),
                meta,
                n_daily,
                n_basic,
            )
            REPORT_PATH.write_text(report, encoding="utf-8")
            print(f"无信号。已写入 {REPORT_PATH}")
            return 0

        daily = load_daily_bars(conn, signals["ts_code"].drop_duplicates().tolist())
        out = add_forward_returns(signals, daily)
        out = mark_independent_signals(out, daily)
        out = out.merge(names, on="ts_code", how="left")
        out["elg_buy_pct"] = out["buy_elg_amount"] / out["circ_mv"]
        out["net_pct"] = out["net_mf_amount"] / out["circ_mv"]
        out["float_ratio"] = out["circ_mv"] / out["total_mv"]
        out = out.sort_values(["trade_date", "ts_code"]).reset_index(drop=True)
        report = build_report(out, meta, n_daily, n_basic)
        REPORT_PATH.write_text(report, encoding="utf-8")
        n_indep = int(out["independent"].sum())
        print(
            f"按日触发 {len(out)} 条 / {out['ts_code'].nunique()} 只，"
            f"独立信号 {n_indep} 条。已写入 {REPORT_PATH}"
        )
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
