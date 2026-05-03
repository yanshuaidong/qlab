from __future__ import annotations

import math
import sqlite3
from dataclasses import dataclass
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd


@dataclass(frozen=True)
class Params:
    limit_up_min_pct: float = 9.8
    limit_up_max_pct: float = 10.2
    quiet_days: int = 5
    prev_flow_days: int = 5
    min_prev_flow_days: int = 3
    day1_vs_prev_abs_max_multiple: float = 2.0
    massive_exit_days: int = 2
    exit_vs_day1_multiple: float = 0.2
    strict_no_sell_days: int = 3
    trend_window_days: int = 20
    trend_success_return: float = 0.15
    extended_window_days: int = 30


ROOT = Path(__file__).resolve().parents[3]
DB_PATH = ROOT / "storage" / "stock" / "stock_capital_flow" / "stock.sqlite"
OUT_DIR = Path(__file__).resolve().parent / "output"
REPORT_PATH = Path(__file__).resolve().parent / "report.md"


def fmt_money(value: float | int | None) -> str:
    if value is None or pd.isna(value):
        return "-"
    value = float(value)
    sign = "-" if value < 0 else ""
    value = abs(value)
    if value >= 100_000_000:
        return f"{sign}{value / 100_000_000:.2f}亿"
    return f"{sign}{value / 10_000:.0f}万"


def fmt_market_cap(value: float | int | None) -> str:
    if value is None or pd.isna(value):
        return "-"
    value = float(value)
    if value >= 100_000_000:
        return f"{value / 100_000_000:.1f}亿"
    return f"{value / 10_000:.0f}万"


def fmt_pct(value: float | int | None) -> str:
    if value is None or pd.isna(value):
        return "-"
    return f"{float(value) * 100:.1f}%"


def load_data() -> tuple[pd.DataFrame, pd.DataFrame]:
    with sqlite3.connect(DB_PATH) as con:
        candidates = pd.read_sql_query(
            """
            SELECT exchange, code, name, board, security_type, hit_dates
            FROM stock_limit_up_candidates_120
            """,
            con,
        )
        key = candidates[["exchange", "code"]].drop_duplicates()
        key.to_sql("_tmp_plan3_candidate_codes", con, if_exists="replace", index=False)

        daily = pd.read_sql_query(
            """
            SELECT d.exchange, d.stock_code AS code, d.stock_name AS name,
                   d.trade_date, d.open, d.close, d.high, d.low, d.volume, d.amount,
                   d.pct_change, d.turnover_rate
            FROM stock_daily d
            JOIN _tmp_plan3_candidate_codes k
              ON k.exchange = d.exchange AND k.code = d.stock_code
            WHERE d.adjust = ''
            ORDER BY d.exchange, d.stock_code, d.trade_date
            """,
            con,
        )
        flow = pd.read_sql_query(
            """
            SELECT f.exchange, f.code, f.trade_date,
                   f.main_net_inflow_amount,
                   f.super_large_net_inflow_amount,
                   f.super_large_net_inflow_ratio,
                   f.large_net_inflow_amount,
                   f.small_net_inflow_amount
            FROM stock_individual_fund_flow f
            JOIN _tmp_plan3_candidate_codes k
              ON k.exchange = f.exchange AND k.code = f.code
            ORDER BY f.exchange, f.code, f.trade_date
            """,
            con,
        )
        basic = pd.read_sql_query(
            """
            SELECT exchange, code, total_shares, circulating_shares, industry
            FROM stock_basic_info
            """,
            con,
        )
        con.execute("DROP TABLE IF EXISTS _tmp_plan3_candidate_codes")

    data = daily.merge(flow, on=["exchange", "code", "trade_date"], how="left")
    data = data.merge(
        candidates[["exchange", "code", "board", "security_type"]],
        on=["exchange", "code"],
        how="left",
    )
    data = data.merge(
        basic[["exchange", "code", "total_shares", "circulating_shares", "industry"]],
        on=["exchange", "code"],
        how="left",
    )
    data = data[
        ~data["code"].astype(str).str.startswith(("300", "301", "688"))
        & ~data["board"].fillna("").str.contains("创业|科创", regex=True)
    ].copy()
    data["trade_date"] = pd.to_datetime(data["trade_date"])
    data["is_limit_up"] = data["pct_change"].between(
        Params.limit_up_min_pct, Params.limit_up_max_pct, inclusive="both"
    )
    data = data.sort_values(["exchange", "code", "trade_date"]).reset_index(drop=True)
    return candidates, data


def window_return(rows: pd.DataFrame, start_idx: int, days: int) -> dict[str, float | int | None]:
    start_close = rows.iloc[start_idx]["close"]
    if pd.isna(start_close) or start_close <= 0:
        return {
            f"max_high_return_{days}d": math.nan,
            f"close_return_{days}d": math.nan,
            f"min_low_return_{days}d": math.nan,
            f"available_days_{days}d": 0,
        }
    future = rows.iloc[start_idx + 1 : start_idx + 1 + days]
    if future.empty:
        return {
            f"max_high_return_{days}d": math.nan,
            f"close_return_{days}d": math.nan,
            f"min_low_return_{days}d": math.nan,
            f"available_days_{days}d": 0,
        }
    return {
        f"max_high_return_{days}d": future["high"].max() / start_close - 1,
        f"close_return_{days}d": future.iloc[-1]["close"] / start_close - 1,
        f"min_low_return_{days}d": future["low"].min() / start_close - 1,
        f"available_days_{days}d": len(future),
    }


def analyze_events(data: pd.DataFrame, params: Params) -> pd.DataFrame:
    events: list[dict[str, object]] = []

    for (exchange, code), rows in data.groupby(["exchange", "code"], sort=False):
        rows = rows.sort_values("trade_date").reset_index(drop=True)
        for idx in range(params.quiet_days, len(rows)):
            day = rows.iloc[idx]
            if not bool(day["is_limit_up"]):
                continue
            prev_quiet = rows.iloc[idx - params.quiet_days : idx]
            if prev_quiet["is_limit_up"].any():
                continue

            prev_flow = rows.iloc[idx - params.prev_flow_days : idx]["super_large_net_inflow_amount"].dropna()
            day1_flow = day["super_large_net_inflow_amount"]
            if len(prev_flow) < params.min_prev_flow_days or pd.isna(day1_flow):
                continue

            prev_abs_max = float(prev_flow.abs().max())
            prev_max = float(prev_flow.max())
            day1_vs_prev_abs_max = float(day1_flow) / prev_abs_max if prev_abs_max > 0 else math.inf
            day1_significant = (
                float(day1_flow) > 0
                and (
                    prev_abs_max == 0
                    or float(day1_flow) >= params.day1_vs_prev_abs_max_multiple * prev_abs_max
                )
            )

            massive_watch = rows.iloc[idx + 1 : idx + 1 + params.massive_exit_days]
            strict_watch = rows.iloc[idx + 1 : idx + 1 + params.strict_no_sell_days]
            exit_threshold = abs(float(day1_flow)) * params.exit_vs_day1_multiple
            min_next_massive_watch_flow = (
                massive_watch["super_large_net_inflow_amount"].min()
                if not massive_watch.empty
                else math.nan
            )
            min_next_strict_watch_flow = (
                strict_watch["super_large_net_inflow_amount"].min()
                if not strict_watch.empty
                else math.nan
            )
            next3_cum_flow = (
                strict_watch["super_large_net_inflow_amount"].sum()
                if not strict_watch.empty
                else math.nan
            )
            no_exit_3d = (
                len(massive_watch) == params.massive_exit_days
                and not (massive_watch["super_large_net_inflow_amount"] <= -exit_threshold).any()
            )
            no_net_outflow_3d = (
                len(strict_watch) == params.strict_no_sell_days
                and not (strict_watch["super_large_net_inflow_amount"] < 0).any()
            )

            item: dict[str, object] = {
                "exchange": exchange,
                "code": code,
                "name": day["name"],
                "board": day["board"],
                "industry": day["industry"],
                "event_date": day["trade_date"].date().isoformat(),
                "pct_change": day["pct_change"],
                "close": day["close"],
                "turnover_rate": day["turnover_rate"],
                "total_shares": day["total_shares"],
                "circulating_shares": day["circulating_shares"],
                "market_cap": day["close"] * day["total_shares"]
                if not pd.isna(day["close"]) and not pd.isna(day["total_shares"])
                else math.nan,
                "circulating_market_cap": day["close"] * day["circulating_shares"]
                if not pd.isna(day["close"]) and not pd.isna(day["circulating_shares"])
                else math.nan,
                "day1_super_large_net_inflow": float(day1_flow),
                "prev5_super_large_abs_max": prev_abs_max,
                "prev5_super_large_max": prev_max,
                "day1_vs_prev_abs_max": day1_vs_prev_abs_max,
                "day1_significant": day1_significant,
                "next2_min_super_large_net_inflow": float(min_next_massive_watch_flow)
                if not pd.isna(min_next_massive_watch_flow)
                else math.nan,
                "next3_min_super_large_net_inflow": float(min_next_strict_watch_flow)
                if not pd.isna(min_next_strict_watch_flow)
                else math.nan,
                "next3_cum_super_large_net_inflow": float(next3_cum_flow)
                if not pd.isna(next3_cum_flow)
                else math.nan,
                "exit_threshold": exit_threshold,
                "no_exit_3d": no_exit_3d,
                "no_net_outflow_3d": no_net_outflow_3d,
                "massive_watch_days": len(massive_watch),
                "strict_watch_days": len(strict_watch),
            }
            item.update(window_return(rows, idx, 5))
            item.update(window_return(rows, idx, 10))
            item.update(window_return(rows, idx, params.trend_window_days))
            item.update(window_return(rows, idx, params.extended_window_days))
            events.append(item)

    result = pd.DataFrame(events)
    if result.empty:
        return result
    result["trend_success_20d"] = (
        result[f"available_days_{params.trend_window_days}d"] >= params.trend_window_days
    ) & (result[f"max_high_return_{params.trend_window_days}d"] >= params.trend_success_return)
    result["stock"] = result["code"].astype(str) + " " + result["name"].astype(str)
    return result


def summarize_group(df: pd.DataFrame, params: Params, flag_col: str, good_label: str, bad_label: str) -> pd.DataFrame:
    rows = []
    for label, part in [
        (good_label, df[df[flag_col]]),
        (bad_label, df[~df[flag_col]]),
    ]:
        rows.append(
            {
                "分组": label,
                "样本数": len(part),
                "20日趋势成功率": part["trend_success_20d"].mean() if len(part) else math.nan,
                "20日最大涨幅中位数": part[f"max_high_return_{params.trend_window_days}d"].median(),
                "20日收盘收益中位数": part[f"close_return_{params.trend_window_days}d"].median(),
                "30日最大涨幅中位数": part[f"max_high_return_{params.extended_window_days}d"].median(),
            }
        )
    return pd.DataFrame(rows)


def summarize_market_cap(df: pd.DataFrame, params: Params, cap_col: str) -> pd.DataFrame:
    bins = [
        ("<50亿", 0, 5_000_000_000),
        ("50-100亿", 5_000_000_000, 10_000_000_000),
        ("100-200亿", 10_000_000_000, 20_000_000_000),
        ("200-500亿", 20_000_000_000, 50_000_000_000),
        (">=500亿", 50_000_000_000, math.inf),
    ]
    known = df[df[cap_col].notna()]
    rows = []
    for label, low, high in bins:
        if math.isinf(high):
            part = known[known[cap_col] >= low]
        else:
            part = known[(known[cap_col] >= low) & (known[cap_col] < high)]
        rows.append(
            {
                "市值分档": label,
                "股票数": len(part),
                "占已知市值比例": len(part) / len(known) if len(known) else math.nan,
                "20日趋势成功率": part["trend_success_20d"].mean() if len(part) else math.nan,
                "20日最大涨幅中位数": part[f"max_high_return_{params.trend_window_days}d"].median()
                if len(part)
                else math.nan,
            }
        )
    unknown = len(df) - len(known)
    if unknown:
        rows.append(
            {
                "市值分档": "缺少股本数据",
                "股票数": unknown,
                "占已知市值比例": math.nan,
                "20日趋势成功率": math.nan,
                "20日最大涨幅中位数": math.nan,
            }
        )
    return pd.DataFrame(rows)


def make_plot(summary: pd.DataFrame, chart_path: Path) -> None:
    labels = ["No massive sell", "Massive sell/short"]
    success = summary["20日趋势成功率"].fillna(0).to_numpy() * 100
    median_return = summary["20日最大涨幅中位数"].fillna(0).to_numpy() * 100

    fig, ax = plt.subplots(figsize=(8, 4.5))
    x = range(len(labels))
    ax.bar([v - 0.18 for v in x], success, width=0.36, label="20d success rate")
    ax.bar([v + 0.18 for v in x], median_return, width=0.36, label="20d median max return")
    ax.set_xticks(list(x), labels)
    ax.set_ylabel("%")
    ax.set_title("Plan3 validation by D1+3 super-large order behavior")
    ax.legend()
    ax.grid(axis="y", alpha=0.25)
    fig.tight_layout()
    fig.savefig(chart_path, dpi=160)
    plt.close(fig)


def markdown_table(df: pd.DataFrame, columns: list[str]) -> str:
    if df.empty:
        return "无样本。"
    return df[columns].to_markdown(index=False)


def write_report(
    candidates: pd.DataFrame,
    all_events: pd.DataFrame,
    model_events: pd.DataFrame,
    first_per_stock: pd.DataFrame,
    summary_massive: pd.DataFrame,
    summary_strict: pd.DataFrame,
    params: Params,
    chart_path: Path,
) -> None:
    sig_count = len(model_events)
    no_exit = first_per_stock[first_per_stock["no_exit_3d"]]
    exit_or_short = first_per_stock[~first_per_stock["no_exit_3d"]]
    strict_no_sell = first_per_stock[first_per_stock["no_net_outflow_3d"]]
    strict_sell = first_per_stock[~first_per_stock["no_net_outflow_3d"]]

    top = no_exit.sort_values(
        f"max_high_return_{params.trend_window_days}d", ascending=False
    ).head(20)
    strict_all = strict_no_sell.sort_values(
        f"max_high_return_{params.trend_window_days}d", ascending=False
    )
    top_table = top.assign(
        D1超大单=top["day1_super_large_net_inflow"].map(fmt_money),
        D2D3最小超大单=top["next2_min_super_large_net_inflow"].map(fmt_money),
        二十日最高涨幅=top[f"max_high_return_{params.trend_window_days}d"].map(fmt_pct),
        二十日收盘收益=top[f"close_return_{params.trend_window_days}d"].map(fmt_pct),
        三十日最高涨幅=top[f"max_high_return_{params.extended_window_days}d"].map(fmt_pct),
    )
    strict_table = strict_all.assign(
        总市值=strict_all["market_cap"].map(fmt_market_cap),
        流通市值=strict_all["circulating_market_cap"].map(fmt_market_cap),
        D1超大单=strict_all["day1_super_large_net_inflow"].map(fmt_money),
        前5日绝对值最大=strict_all["prev5_super_large_abs_max"].map(fmt_money),
        D1相对前5日绝对最大倍数=strict_all["day1_vs_prev_abs_max"].map(
            lambda v: "-" if pd.isna(v) else ("无限" if math.isinf(float(v)) else f"{float(v):.2f}x")
        ),
        D2D3D4最小超大单=strict_all["next3_min_super_large_net_inflow"].map(fmt_money),
        D2D3D4累计超大单=strict_all["next3_cum_super_large_net_inflow"].map(fmt_money),
        二十日最高涨幅=strict_all[f"max_high_return_{params.trend_window_days}d"].map(fmt_pct),
        二十日收盘收益=strict_all[f"close_return_{params.trend_window_days}d"].map(fmt_pct),
        三十日最高涨幅=strict_all[f"max_high_return_{params.extended_window_days}d"].map(fmt_pct),
    )

    summary_massive_fmt = summary_massive.copy()
    summary_strict_fmt = summary_strict.copy()
    for table in [summary_massive_fmt, summary_strict_fmt]:
        for col in ["20日趋势成功率", "20日最大涨幅中位数", "20日收盘收益中位数", "30日最大涨幅中位数"]:
            table[col] = table[col].map(fmt_pct)

    cap_summary = summarize_market_cap(strict_no_sell, params, "market_cap")
    float_cap_summary = summarize_market_cap(strict_no_sell, params, "circulating_market_cap")
    cap_summary_fmt = cap_summary.copy()
    float_cap_summary_fmt = float_cap_summary.copy()
    for table in [cap_summary_fmt, float_cap_summary_fmt]:
        for col in ["占已知市值比例", "20日趋势成功率", "20日最大涨幅中位数"]:
            table[col] = table[col].map(fmt_pct)

    base_success = first_per_stock["trend_success_20d"].mean() if len(first_per_stock) else math.nan
    no_exit_success = no_exit["trend_success_20d"].mean() if len(no_exit) else math.nan
    exit_success = exit_or_short["trend_success_20d"].mean() if len(exit_or_short) else math.nan
    strict_no_sell_success = (
        strict_no_sell["trend_success_20d"].mean() if len(strict_no_sell) else math.nan
    )
    strict_sell_success = strict_sell["trend_success_20d"].mean() if len(strict_sell) else math.nan
    known_market_cap = strict_no_sell["market_cap"].dropna()
    known_float_cap = strict_no_sell["circulating_market_cap"].dropna()
    small_mid_market_count = int((known_market_cap < 20_000_000_000).sum())
    small_mid_float_count = int((known_float_cap < 20_000_000_000).sum())
    small_mid_market_ratio = (
        small_mid_market_count / len(known_market_cap) if len(known_market_cap) else math.nan
    )
    small_mid_float_ratio = (
        small_mid_float_count / len(known_float_cap) if len(known_float_cap) else math.nan
    )

    lines = [
        "# Plan3：首次涨停后 3 日超大单未撤退验证",
        "",
        "## 结论摘要",
        "",
        f"- 候选股票池：`stock_limit_up_candidates_120` 共 {len(candidates)} 只。",
        f"- 排除创业板、科创板后，在候选池日线中找到“前 {params.quiet_days} 日无涨停的首次/重新启动涨停”事件 {len(all_events)} 个。",
        f"- 其中第 1 天超大单显著放量事件 {sig_count} 个；按每只股票取最早一次后，主样本为 {len(first_per_stock)} 只。",
        f"- 主样本里，D2/D3 未出现超大单巨量卖出的股票 {len(no_exit)} 只，20 日趋势成功率 {fmt_pct(no_exit_success)}。",
        f"- 对照组（D2/D3 出现巨量卖出或观察不足）{len(exit_or_short)} 只，20 日趋势成功率 {fmt_pct(exit_success)}。",
        f"- 严格无卖出口径：D2、D3、D4 这 {params.strict_no_sell_days} 个交易日每天超大单都不能净流出，满足条件 {len(strict_no_sell)} 只，20 日趋势成功率 {fmt_pct(strict_no_sell_success)}；不满足组 {len(strict_sell)} 只，成功率 {fmt_pct(strict_sell_success)}。",
        f"- 这 64 只里，有总股本数据的 {len(known_market_cap)} 只，按事件日收盘价估算总市值中位数 {fmt_market_cap(known_market_cap.median() if len(known_market_cap) else math.nan)}；其中总市值低于 200 亿的 {small_mid_market_count} 只，占已知样本 {fmt_pct(small_mid_market_ratio)}。",
        f"- 有流通股本数据的 {len(known_float_cap)} 只，事件日流通市值中位数 {fmt_market_cap(known_float_cap.median() if len(known_float_cap) else math.nan)}；流通市值低于 200 亿的 {small_mid_float_count} 只，占已知样本 {fmt_pct(small_mid_float_ratio)}。",
        f"- 不区分后 3 日行为时，D1 放量主样本的整体 20 日趋势成功率为 {fmt_pct(base_success)}。",
        "",
        "按当前参数看，`首次涨停 + D1 超大单显著放量 + D2/D3 没有巨量卖出` 的表现，需要结合下面的分组胜率和中位收益判断；`D2/D3/D4 严格无卖出` 组样本更少，但更接近“主力持续锁仓”的直觉。这里的“趋势成功”定义为：从第 1 天收盘价算起，后 20 个交易日内最高价涨幅达到 15%。",
        "",
        f"![group chart]({chart_path.as_posix()})",
        "",
        "## 参数定义",
        "",
        "- 股票范围：排除代码 `300/301/688` 开头以及板块名称包含创业、科创的股票，只统计主板候选。",
        f"- 首次/重新启动涨停：当日 `{params.limit_up_min_pct} <= pct_change <= {params.limit_up_max_pct}`，且前 {params.quiet_days} 个交易日没有涨停。",
        f"- D1 超大单显著放量：第 1 天超大单净流入为正，且 `D1超大单净流入 >= 前5日超大单净流入绝对值最大值 * {params.day1_vs_prev_abs_max_multiple}`。",
        f"- D2/D3 巨量卖出：D2 或 D3 任一交易日 `super_large_net_inflow_amount <= -(D1超大单净流入 * {params.exit_vs_day1_multiple})`。",
        f"- D2/D3 未巨量卖出：D2、D3 都有观察数据，且没有触发上面的巨量卖出。",
        f"- D2/D3/D4 严格无卖出口径：第 1 天之后完整 {params.strict_no_sell_days} 个观察日，也就是 D2、D3、D4，每天 `super_large_net_inflow_amount >= 0`。",
        f"- 趋势成功：第 1 天收盘后 {params.trend_window_days} 个交易日内最高价涨幅 >= {fmt_pct(params.trend_success_return)}。",
        "",
        "## 分组统计：巨量卖出口径",
        "",
        summary_massive_fmt.to_markdown(index=False),
        "",
        "## 分组统计：D2/D3/D4 严格无卖出口径",
        "",
        summary_strict_fmt.to_markdown(index=False),
        "",
        "## D2/D3/D4 严格无卖出组：全部 64 只",
        "",
        "这组是 `D1 放量 + D2/D3/D4 每天超大单非净流出`，按 20 日最高涨幅从高到低排列。",
        "",
        "市值按事件日收盘价估算：`总市值 = close * total_shares`，`流通市值 = close * circulating_shares`。股本字段来自 `stock_basic_info`，缺失时记为 `-`。",
        "",
        "### 事件日总市值分布",
        "",
        cap_summary_fmt.to_markdown(index=False),
        "",
        "### 事件日流通市值分布",
        "",
        float_cap_summary_fmt.to_markdown(index=False),
        "",
        markdown_table(
            strict_table,
            [
                "event_date",
                "stock",
                "board",
                "总市值",
                "流通市值",
                "D1超大单",
                "前5日绝对值最大",
                "D1相对前5日绝对最大倍数",
                "D2D3D4最小超大单",
                "D2D3D4累计超大单",
                "二十日最高涨幅",
                "二十日收盘收益",
                "三十日最高涨幅",
            ],
        ),
        "",
        "## D2/D3 未巨量卖出组：20 日最高涨幅前 20",
        "",
        markdown_table(
            top_table,
            [
                "event_date",
                "stock",
                "board",
                "D1超大单",
                "D2D3最小超大单",
                "二十日最高涨幅",
                "二十日收盘收益",
                "三十日最高涨幅",
            ],
        ),
        "",
        "## 输出文件",
        "",
        f"- 全部首次/重新启动涨停事件：`{(OUT_DIR / 'all_first_limit_up_events.csv').as_posix()}`",
        f"- D1 显著放量事件：`{(OUT_DIR / 'day1_significant_events.csv').as_posix()}`",
        f"- 每只股票最早 D1 显著放量事件：`{(OUT_DIR / 'first_model_event_per_stock.csv').as_posix()}`",
        f"- 巨量卖出口径分组统计：`{(OUT_DIR / 'summary_by_no_massive_exit.csv').as_posix()}`",
        f"- 严格无卖出口径分组统计：`{(OUT_DIR / 'summary_by_strict_no_sell.csv').as_posix()}`",
        "",
        "## 解读注意",
        "",
        "- 这是事件回测，不是因果证明；目前资金流数据只有 2025-09-26 到 2026-04-30，样本集中在 2025 年末到 2026 年初。",
        "- 参数对结论会有影响，尤其是“显著放量”和“巨量卖出”的阈值。脚本顶部 `Params` 可以直接调参重跑；当前 D2/D3 用来判断巨量卖出，D2/D3/D4 用来判断严格无卖出。",
        "- 当前候选表本身已经是涨停候选池，所以结论适用于这个候选池，不代表全市场基准。",
        "",
    ]
    REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    params = Params()
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    candidates, data = load_data()
    all_events = analyze_events(data, params)
    if all_events.empty:
        raise RuntimeError("没有找到可分析事件，请检查阈值或数据范围。")

    model_events = all_events[all_events["day1_significant"]].copy()
    first_per_stock = (
        model_events.sort_values(["exchange", "code", "event_date"])
        .groupby(["exchange", "code"], as_index=False)
        .first()
    )
    summary_massive = summarize_group(
        first_per_stock,
        params,
        "no_exit_3d",
        "D1放量 + D2/D3无巨量卖出",
        "D1放量 + D2/D3出现巨量卖出/观察不足",
    )
    summary_strict = summarize_group(
        first_per_stock,
        params,
        "no_net_outflow_3d",
        "D1放量 + D2/D3/D4每天超大单非净流出",
        "D1放量 + D2/D3/D4存在超大单净流出/观察不足",
    )

    all_events.to_csv(OUT_DIR / "all_first_limit_up_events.csv", index=False, encoding="utf-8-sig")
    model_events.to_csv(OUT_DIR / "day1_significant_events.csv", index=False, encoding="utf-8-sig")
    first_per_stock.to_csv(OUT_DIR / "first_model_event_per_stock.csv", index=False, encoding="utf-8-sig")
    summary_massive.to_csv(OUT_DIR / "summary_by_no_massive_exit.csv", index=False, encoding="utf-8-sig")
    summary_strict.to_csv(OUT_DIR / "summary_by_strict_no_sell.csv", index=False, encoding="utf-8-sig")

    chart_path = OUT_DIR / "summary_by_no_exit.png"
    make_plot(summary_massive, chart_path)
    write_report(candidates, all_events, model_events, first_per_stock, summary_massive, summary_strict, params, chart_path)

    print(f"candidates={len(candidates)}")
    print(f"all_first_limit_up_events={len(all_events)}")
    print(f"day1_significant_events={len(model_events)}")
    print(f"first_model_event_per_stock={len(first_per_stock)}")
    print(summary_massive.to_string(index=False))
    print(summary_strict.to_string(index=False))
    print(f"report={REPORT_PATH}")


if __name__ == "__main__":
    main()
