"""
9 个推荐品种的严格 7 日开仓 + 3 日 main_force 拐头止盈回测。

开多：
- 前 4 天 main_force 都小于 0
- 且第 4 天减第 1 天 < 0
- 后 3 天 main_force 连续上升
- 后 3 天 retail 连续下降

多头止盈：
- 看最近 3 天 main_force
- 当第 3 天减第 1 天 < 0 时，认为 main_force 拐头向下，当日收盘平多

开空：
- 前 4 天 main_force 都大于 0
- 且第 4 天减第 1 天 > 0
- 后 3 天 main_force 连续下降
- 后 3 天 retail 连续上升

空头止盈：
- 看最近 3 天 main_force
- 当第 3 天减第 1 天 > 0 时，认为 main_force 拐头向上，当日收盘平空

说明：
- 开仓与平仓都使用信号当日收盘价。
- 平仓后当天不反手，下一交易日再等待新的开仓信号。
- 未计手续费、滑点、合约乘数；跨品种统一按收益率比较。
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from plan1.scripts.backtest_wave_strategy_strict7 import (
    ARTIFACT_DATA,
    DB,
    DOCS_DIR,
    TARGET_VARIETIES,
    compute_max_drawdown,
    compute_signals_strict7,
    load_df,
    load_varieties,
    trade_return,
)


def compute_signals_strict7_tp3(df: pd.DataFrame) -> pd.DataFrame:
    out = compute_signals_strict7(df).copy()
    cont3 = out["date_cont"].rolling(2, min_periods=2).sum().eq(2)
    out["tp3_delta_main"] = out["main_force"] - out["main_force"].shift(2)
    out["exit_long_signal"] = cont3 & out["tp3_delta_main"].lt(0)
    out["exit_short_signal"] = cont3 & out["tp3_delta_main"].gt(0)
    return out


def backtest_wave_strategy_strict7_tp3(
    df: pd.DataFrame,
    variety_name: str,
) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    data = compute_signals_strict7_tp3(df).copy()
    data["position_after_close"] = 0

    trades: list[dict] = []
    position = 0
    entry_idx: int | None = None
    entry_price: float | None = None
    entry_date = None

    for i, row in data.iterrows():
        closed_today = False

        if position == 1 and row["exit_long_signal"]:
            exit_price = float(row["close"])
            pnl_ratio = trade_return(1, float(entry_price), exit_price)
            pnl_points = exit_price - float(entry_price)
            trades.append(
                {
                    "variety_name": variety_name,
                    "side": "long",
                    "entry_date": entry_date,
                    "exit_date": row["trade_date"],
                    "entry_price": float(entry_price),
                    "exit_price": exit_price,
                    "holding_days": i - int(entry_idx),
                    "pnl_ratio": pnl_ratio,
                    "pnl_points": pnl_points,
                    "exit_reason": "tp3_main_turn_down",
                }
            )
            position = 0
            entry_idx = None
            entry_price = None
            entry_date = None
            closed_today = True

        elif position == -1 and row["exit_short_signal"]:
            exit_price = float(row["close"])
            pnl_ratio = trade_return(-1, float(entry_price), exit_price)
            pnl_points = float(entry_price) - exit_price
            trades.append(
                {
                    "variety_name": variety_name,
                    "side": "short",
                    "entry_date": entry_date,
                    "exit_date": row["trade_date"],
                    "entry_price": float(entry_price),
                    "exit_price": exit_price,
                    "holding_days": i - int(entry_idx),
                    "pnl_ratio": pnl_ratio,
                    "pnl_points": pnl_points,
                    "exit_reason": "tp3_main_turn_up",
                }
            )
            position = 0
            entry_idx = None
            entry_price = None
            entry_date = None
            closed_today = True

        if position == 0 and not closed_today:
            if row["long_signal"]:
                position = 1
                entry_idx = i
                entry_price = float(row["close"])
                entry_date = row["trade_date"]
            elif row["short_signal"]:
                position = -1
                entry_idx = i
                entry_price = float(row["close"])
                entry_date = row["trade_date"]

        data.at[i, "position_after_close"] = position

    if position != 0:
        last_row = data.iloc[-1]
        exit_price = float(last_row["close"])
        pnl_ratio = trade_return(position, float(entry_price), exit_price)
        pnl_points = position * (exit_price - float(entry_price))
        trades.append(
            {
                "variety_name": variety_name,
                "side": "long" if position == 1 else "short",
                "entry_date": entry_date,
                "exit_date": last_row["trade_date"],
                "entry_price": float(entry_price),
                "exit_price": exit_price,
                "holding_days": len(data) - 1 - int(entry_idx),
                "pnl_ratio": pnl_ratio,
                "pnl_points": pnl_points,
                "exit_reason": "final_close",
            }
        )

    data["close_return"] = data["close"].pct_change().fillna(0.0)
    data["position_prev"] = data["position_after_close"].shift(1).fillna(0).astype(int)
    data["strategy_daily_return"] = data["position_prev"] * data["close_return"]
    data["equity_curve"] = (1.0 + data["strategy_daily_return"]).cumprod()
    data["benchmark_curve"] = (1.0 + data["close_return"]).cumprod()

    trades_df = pd.DataFrame(trades)
    total_return = float(data["equity_curve"].iloc[-1] - 1.0)
    benchmark_return = float(data["benchmark_curve"].iloc[-1] - 1.0)
    total_points = float((data["position_prev"] * data["close"].diff().fillna(0.0)).sum())

    summary = {
        "variety_name": variety_name,
        "trade_count": int(len(trades_df)),
        "long_count": int((trades_df["side"] == "long").sum()) if len(trades_df) else 0,
        "short_count": int((trades_df["side"] == "short").sum()) if len(trades_df) else 0,
        "win_rate": float((trades_df["pnl_ratio"] > 0).mean()) if len(trades_df) else np.nan,
        "avg_trade_return": float(trades_df["pnl_ratio"].mean()) if len(trades_df) else np.nan,
        "median_holding_days": float(trades_df["holding_days"].median()) if len(trades_df) else np.nan,
        "strategy_return": total_return,
        "buy_hold_return": benchmark_return,
        "excess_return": total_return - benchmark_return,
        "pnl_points": total_points,
        "max_drawdown": compute_max_drawdown(data["equity_curve"]),
        "signal_long_days": int(data["long_signal"].sum()),
        "signal_short_days": int(data["short_signal"].sum()),
        "exit_long_days": int(data["exit_long_signal"].sum()),
        "exit_short_days": int(data["exit_short_signal"].sum()),
    }
    return data, trades_df, summary


def run_wave_strategy_backtest_strict7_tp3(
    variety_names: list[str] | None = None,
) -> dict[str, pd.DataFrame]:
    names = variety_names or TARGET_VARIETIES
    con = sqlite3.connect(DB)
    variety_map = load_varieties(con).set_index("name")

    summary_rows: list[dict] = []
    all_trades: list[pd.DataFrame] = []
    curves: list[pd.DataFrame] = []

    for variety_name in names:
        variety_id = int(variety_map.loc[variety_name, "id"])
        df = load_df(con, variety_id)
        curve_df, trades_df, summary = backtest_wave_strategy_strict7_tp3(df, variety_name)
        summary["variety_id"] = variety_id
        summary_rows.append(summary)
        all_trades.append(trades_df)
        curves.append(
            curve_df[
                [
                    "trade_date",
                    "close_return",
                    "strategy_daily_return",
                    "position_after_close",
                    "equity_curve",
                    "long_signal",
                    "short_signal",
                    "exit_long_signal",
                    "exit_short_signal",
                ]
            ].rename(
                columns={
                    "close_return": f"{variety_name}_close_return",
                    "strategy_daily_return": f"{variety_name}_daily_return",
                    "position_after_close": f"{variety_name}_position",
                    "equity_curve": f"{variety_name}_equity_curve",
                    "long_signal": f"{variety_name}_long_signal",
                    "short_signal": f"{variety_name}_short_signal",
                    "exit_long_signal": f"{variety_name}_exit_long_signal",
                    "exit_short_signal": f"{variety_name}_exit_short_signal",
                }
            )
        )

    con.close()

    summary_df = pd.DataFrame(summary_rows).sort_values(
        ["strategy_return", "win_rate"],
        ascending=False,
    )
    trades_df = pd.concat(all_trades, ignore_index=True)

    portfolio = curves[0][["trade_date"]].copy()
    for curve in curves:
        portfolio = portfolio.merge(curve, on="trade_date", how="outer")
    portfolio = portfolio.sort_values("trade_date").reset_index(drop=True)

    daily_return_cols = [f"{name}_daily_return" for name in names]
    portfolio[daily_return_cols] = portfolio[daily_return_cols].fillna(0.0)
    portfolio["portfolio_daily_return"] = portfolio[daily_return_cols].mean(axis=1)
    portfolio["portfolio_equity_curve"] = (1.0 + portfolio["portfolio_daily_return"]).cumprod()

    portfolio_summary = {
        "variety_name": "组合等权",
        "trade_count": int(summary_df["trade_count"].sum()),
        "long_count": int(summary_df["long_count"].sum()),
        "short_count": int(summary_df["short_count"].sum()),
        "win_rate": float(trades_df["pnl_ratio"].gt(0).mean()) if len(trades_df) else np.nan,
        "avg_trade_return": float(trades_df["pnl_ratio"].mean()) if len(trades_df) else np.nan,
        "median_holding_days": float(trades_df["holding_days"].median()) if len(trades_df) else np.nan,
        "strategy_return": float(portfolio["portfolio_equity_curve"].iloc[-1] - 1.0),
        "buy_hold_return": np.nan,
        "excess_return": np.nan,
        "pnl_points": float(summary_df["pnl_points"].sum()),
        "max_drawdown": compute_max_drawdown(portfolio["portfolio_equity_curve"]),
        "signal_long_days": int(summary_df["signal_long_days"].sum()),
        "signal_short_days": int(summary_df["signal_short_days"].sum()),
        "exit_long_days": int(summary_df["exit_long_days"].sum()),
        "exit_short_days": int(summary_df["exit_short_days"].sum()),
    }
    summary_df = pd.concat([pd.DataFrame([portfolio_summary]), summary_df], ignore_index=True)

    return {
        "summary": summary_df,
        "trades": trades_df,
        "portfolio_curve": portfolio,
    }


def build_summary_markdown(summary_df: pd.DataFrame) -> str:
    lines = [
        "# 严格 7 日开仓 + 3 日止盈策略汇总",
        "",
        "规则口径：前 4 日做背景过滤，后 3 日做连续触发；持仓后再用最近 3 天 `main_force` 的第 3 天减第 1 天判断拐头止盈。",
        "",
        "| 品种 | 交易次数 | 多单次数 | 空单次数 | 胜率 | 单笔平均收益 | 策略收益 | 买入持有收益 | 超额收益 | 最大回撤 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for _, row in summary_df.iterrows():
        def fmt_pct(v: float) -> str:
            if pd.isna(v):
                return ""
            return f"{v * 100:.2f}%"

        lines.append(
            f"| {row['variety_name']} | {int(row['trade_count'])} | {int(row['long_count'])} | "
            f"{int(row['short_count'])} | {fmt_pct(row['win_rate'])} | {fmt_pct(row['avg_trade_return'])} | "
            f"{fmt_pct(row['strategy_return'])} | {fmt_pct(row['buy_hold_return'])} | "
            f"{fmt_pct(row['excess_return'])} | {fmt_pct(row['max_drawdown'])} |"
        )
    lines.append("")
    return "\n".join(lines)


def build_jiaomei_detail_markdown(signal_df: pd.DataFrame, trades_df: pd.DataFrame) -> str:
    signal_df = signal_df.reset_index(drop=True)
    rows = []
    for seq, trade in trades_df.reset_index(drop=True).iterrows():
        entry_date = pd.Timestamp(trade["entry_date"])
        exit_date = pd.Timestamp(trade["exit_date"])
        entry_idx = signal_df.index[signal_df["trade_date"] == entry_date][0]
        exit_idx = signal_df.index[signal_df["trade_date"] == exit_date][0]

        bg = signal_df.iloc[entry_idx - 6 : entry_idx - 2]
        tg = signal_df.iloc[entry_idx - 2 : entry_idx + 1]
        exit_win = signal_df.iloc[max(0, exit_idx - 2) : exit_idx + 1]

        rows.append(
            {
                "seq": seq + 1,
                "side": "多" if trade["side"] == "long" else "空",
                "entry_date": entry_date.date().isoformat(),
                "exit_date": exit_date.date().isoformat(),
                "entry_price": float(trade["entry_price"]),
                "exit_price": float(trade["exit_price"]),
                "holding_days": int(trade["holding_days"]),
                "pnl_ratio_pct": f"{float(trade['pnl_ratio']) * 100:.2f}%",
                "pnl_points": float(trade["pnl_points"]),
                "exit_reason": trade["exit_reason"],
                "bg_dates": " / ".join(x.date().isoformat() for x in bg["trade_date"]),
                "bg_main_values": " / ".join(f"{x:+.2f}" for x in bg["main_force"]),
                "bg_main_delta": f"{float(bg['main_force'].iloc[-1] - bg['main_force'].iloc[0]):+.2f}",
                "tg_dates": " / ".join(x.date().isoformat() for x in tg["trade_date"]),
                "tg_main_diffs": " / ".join(f"{x:+.2f}" for x in tg["main_diff"]),
                "tg_retail_diffs": " / ".join(f"{x:+.2f}" for x in tg["retail_diff"]),
                "exit_dates": " / ".join(x.date().isoformat() for x in exit_win["trade_date"]),
                "exit_main_values": " / ".join(f"{x:+.2f}" for x in exit_win["main_force"]),
                "exit_tp3_delta": (
                    f"{float(exit_win['main_force'].iloc[-1] - exit_win['main_force'].iloc[0]):+.2f}"
                    if len(exit_win) == 3
                    else ""
                ),
            }
        )

    lines = [
        "# 焦煤严格 7 日开仓 + 3 日止盈交易明细",
        "",
        "规则口径：",
        "",
        "- 开多：前 4 日 `main_force` 全部小于 0，且第 4 日 - 第 1 日 < 0；后 3 日 `main_force` 连续上升且 `retail` 连续下降",
        "- 开空：前 4 日 `main_force` 全部大于 0，且第 4 日 - 第 1 日 > 0；后 3 日 `main_force` 连续下降且 `retail` 连续上升",
        "- 多头止盈：最近 3 日 `main_force` 的第 3 日 - 第 1 日 < 0",
        "- 空头止盈：最近 3 日 `main_force` 的第 3 日 - 第 1 日 > 0",
        "- 平仓后当天不反手",
        "",
        "| 序号 | 方向 | 开仓日期 | 平仓日期 | 开仓价 | 平仓价 | 持有天数 | 收益率 | 点数收益 | 平仓原因 | 背景4日日期 | 背景4日主力值 | 背景净变化(4-1) | 触发3日日期 | 触发3日主力变化 | 触发3日散户变化 | 止盈3日日期 | 止盈3日主力值 | 止盈窗口净变化(3-1) |",
        "|---|---|---|---|---:|---:|---:|---:|---:|---|---|---|---:|---|---|---|---|---|---:|",
    ]
    for row in rows:
        lines.append(
            "| {seq} | {side} | {entry_date} | {exit_date} | {entry_price} | {exit_price} | "
            "{holding_days} | {pnl_ratio_pct} | {pnl_points} | {exit_reason} | {bg_dates} | "
            "{bg_main_values} | {bg_main_delta} | {tg_dates} | {tg_main_diffs} | {tg_retail_diffs} | "
            "{exit_dates} | {exit_main_values} | {exit_tp3_delta} |".format(**row)
        )
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    result = run_wave_strategy_backtest_strict7_tp3()
    summary_df = result["summary"].copy()
    trades_df = result["trades"].copy()
    portfolio_df = result["portfolio_curve"].copy()

    ARTIFACT_DATA.mkdir(parents=True, exist_ok=True)
    DOCS_DIR.mkdir(parents=True, exist_ok=True)

    summary_csv = ARTIFACT_DATA / "wave_strategy_strict7_tp3_summary.csv"
    trades_csv = ARTIFACT_DATA / "wave_strategy_strict7_tp3_trades.csv"
    portfolio_csv = ARTIFACT_DATA / "wave_strategy_strict7_tp3_portfolio_curve.csv"
    summary_md = DOCS_DIR / "wave_strategy_strict7_tp3_summary.md"
    jiaomei_md = DOCS_DIR / "jiaomei_wave_trades_strict7_tp3.md"

    summary_df.to_csv(summary_csv, index=False)
    trades_df.to_csv(trades_csv, index=False)
    portfolio_df.to_csv(portfolio_csv, index=False)
    summary_md.write_text(build_summary_markdown(summary_df), encoding="utf-8")

    con = sqlite3.connect(DB)
    variety_map = load_varieties(con).set_index("name")
    jiaomei_id = int(variety_map.loc["焦煤", "id"])
    jiaomei_df = load_df(con, jiaomei_id)
    con.close()
    jiaomei_signal_df = compute_signals_strict7_tp3(jiaomei_df)
    jiaomei_trades_df = trades_df[trades_df["variety_name"] == "焦煤"].copy()
    jiaomei_md.write_text(
        build_jiaomei_detail_markdown(jiaomei_signal_df, jiaomei_trades_df),
        encoding="utf-8",
    )

    print("=" * 96)
    print("严格 7 日开仓 + 3 日止盈回测")
    print("=" * 96)
    cols = [
        "variety_name",
        "trade_count",
        "long_count",
        "short_count",
        "win_rate",
        "avg_trade_return",
        "strategy_return",
        "buy_hold_return",
        "excess_return",
        "max_drawdown",
    ]
    print(summary_df[cols].to_string(index=False, float_format=lambda x: f"{x:.4f}"))
    print()
    print("交付物：")
    print(f"  - {summary_csv}")
    print(f"  - {trades_csv}")
    print(f"  - {portfolio_csv}")
    print(f"  - {summary_md}")
    print(f"  - {jiaomei_md}")


if __name__ == "__main__":
    main()
