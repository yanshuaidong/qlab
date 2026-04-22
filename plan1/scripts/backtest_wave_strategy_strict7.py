"""
9 个推荐品种的严格 7 日开仓条件波段回测。

开多条件（7 日判断）：
1. 背景段为第 1~4 日：`main_force` 全部 < 0，且第 4 日 - 第 1 日 < 0。
2. 触发段为第 5~7 日：`main_force` 连续 3 日上升，且 `retail` 连续 3 日下降。

开空条件（7 日判断）：
1. 背景段为第 1~4 日：`main_force` 全部 > 0，且第 4 日 - 第 1 日 > 0。
2. 触发段为第 5~7 日：`main_force` 连续 3 日下降，且 `retail` 连续 3 日上升。

交易逻辑：
- 信号当日收盘开仓。
- 持仓中若出现反向信号，则当日收盘平仓并反手。
- 收益从下一交易日开始计入。
- 未计手续费、滑点、合约乘数；跨品种统一按收益率比较。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
ARTIFACT_DATA = ROOT / "artifacts" / "data"
DOCS_DIR = ROOT / "docs"
DB = ROOT.parent / "database" / "local_fut_pulse.sqlite"

TARGET_VARIETIES = [
    "沪铅",
    "沪铝",
    "棕榈油",
    "纯碱",
    "菜粕",
    "PVC",
    "焦煤",
    "棉花",
    "热卷",
]


def load_varieties(con: sqlite3.Connection) -> pd.DataFrame:
    return pd.read_sql_query(
        "SELECT id, name, key FROM fut_variety ORDER BY id",
        con,
    )


def load_df(con: sqlite3.Connection, variety_id: int) -> pd.DataFrame:
    strength = pd.read_sql_query(
        """
        SELECT trade_date, main_force, retail
        FROM fut_strength
        WHERE variety_id=?
        ORDER BY trade_date
        """,
        con,
        params=(variety_id,),
    )
    close = pd.read_sql_query(
        """
        SELECT trade_date, close_price AS close
        FROM fut_daily_close
        WHERE variety_id=?
        ORDER BY trade_date
        """,
        con,
        params=(variety_id,),
    )
    df = strength.merge(close, on="trade_date", how="inner").dropna()
    df["trade_date"] = pd.to_datetime(df["trade_date"])
    return df.sort_values("trade_date").reset_index(drop=True)


def mark_breakpoints(dates: pd.Series) -> pd.Series:
    return dates.diff().dt.days.le(7).fillna(False)


def trade_return(side: int, entry_price: float, exit_price: float) -> float:
    if side == 1:
        return exit_price / entry_price - 1.0
    return entry_price / exit_price - 1.0


def compute_max_drawdown(equity: pd.Series) -> float:
    running_peak = equity.cummax()
    drawdown = equity / running_peak - 1.0
    return float(drawdown.min())


def compute_signals_strict7(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["main_diff"] = out["main_force"].diff()
    out["retail_diff"] = out["retail"].diff()
    out["date_cont"] = mark_breakpoints(out["trade_date"])

    bg1 = out["main_force"].shift(6)
    bg2 = out["main_force"].shift(5)
    bg3 = out["main_force"].shift(4)
    bg4 = out["main_force"].shift(3)
    out["bg_main_1"] = bg1
    out["bg_main_2"] = bg2
    out["bg_main_3"] = bg3
    out["bg_main_4"] = bg4
    out["bg_main_delta_4_1"] = bg4 - bg1

    cont7 = out["date_cont"].rolling(6, min_periods=6).sum().eq(6)
    main_up_3 = out["main_diff"].gt(0).rolling(3, min_periods=3).sum().eq(3)
    main_down_3 = out["main_diff"].lt(0).rolling(3, min_periods=3).sum().eq(3)
    retail_down_3 = out["retail_diff"].lt(0).rolling(3, min_periods=3).sum().eq(3)
    retail_up_3 = out["retail_diff"].gt(0).rolling(3, min_periods=3).sum().eq(3)

    bg_all_neg = bg1.lt(0) & bg2.lt(0) & bg3.lt(0) & bg4.lt(0)
    bg_all_pos = bg1.gt(0) & bg2.gt(0) & bg3.gt(0) & bg4.gt(0)
    bg_net_down = (bg4 - bg1).lt(0)
    bg_net_up = (bg4 - bg1).gt(0)

    out["long_signal"] = cont7 & bg_all_neg & bg_net_down & main_up_3 & retail_down_3
    out["short_signal"] = cont7 & bg_all_pos & bg_net_up & main_down_3 & retail_up_3
    return out


def backtest_reversal_wave_strategy_strict7(
    df: pd.DataFrame,
    variety_name: str,
) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    data = compute_signals_strict7(df).copy()
    data["position_after_close"] = 0

    trades: list[dict] = []
    position = 0
    entry_idx: int | None = None
    entry_price: float | None = None
    entry_date = None

    for i, row in data.iterrows():
        desired_position = position
        if row["long_signal"] and position != 1:
            desired_position = 1
        elif row["short_signal"] and position != -1:
            desired_position = -1

        if desired_position != position:
            if position != 0:
                exit_price = float(row["close"])
                pnl_ratio = trade_return(position, float(entry_price), exit_price)
                pnl_points = position * (exit_price - float(entry_price))
                trades.append(
                    {
                        "variety_name": variety_name,
                        "side": "long" if position == 1 else "short",
                        "entry_date": entry_date,
                        "exit_date": row["trade_date"],
                        "entry_price": float(entry_price),
                        "exit_price": exit_price,
                        "holding_days": i - int(entry_idx),
                        "pnl_ratio": pnl_ratio,
                        "pnl_points": pnl_points,
                        "exit_reason": "reverse_signal",
                    }
                )

            entry_idx = i
            entry_price = float(row["close"])
            entry_date = row["trade_date"]
            position = desired_position

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
    }
    return data, trades_df, summary


def run_wave_strategy_backtest_strict7(
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
        curve_df, trades_df, summary = backtest_reversal_wave_strategy_strict7(
            df=df,
            variety_name=variety_name,
        )
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
                ]
            ].rename(
                columns={
                    "close_return": f"{variety_name}_close_return",
                    "strategy_daily_return": f"{variety_name}_daily_return",
                    "position_after_close": f"{variety_name}_position",
                    "equity_curve": f"{variety_name}_equity_curve",
                    "long_signal": f"{variety_name}_long_signal",
                    "short_signal": f"{variety_name}_short_signal",
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
    }
    summary_df = pd.concat([pd.DataFrame([portfolio_summary]), summary_df], ignore_index=True)

    return {
        "summary": summary_df,
        "trades": trades_df,
        "portfolio_curve": portfolio,
    }


def build_jiaomei_detail_markdown(signal_df: pd.DataFrame, trades_df: pd.DataFrame) -> str:
    rows = []
    signal_df = signal_df.reset_index(drop=True)
    for seq, trade in trades_df.reset_index(drop=True).iterrows():
        entry_date = pd.Timestamp(trade["entry_date"])
        idx = signal_df.index[signal_df["trade_date"] == entry_date][0]
        bg = signal_df.iloc[idx - 6 : idx - 2]
        tg = signal_df.iloc[idx - 2 : idx + 1]
        rows.append(
            {
                "seq": seq + 1,
                "side": "多" if trade["side"] == "long" else "空",
                "entry_date": entry_date.date().isoformat(),
                "exit_date": pd.Timestamp(trade["exit_date"]).date().isoformat(),
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
            }
        )

    lines = [
        "# 焦煤严格 7 日波段策略交易明细",
        "",
        "规则口径：",
        "",
        "- 开多：前 4 日 `main_force` 全部小于 0，且第 4 日 - 第 1 日 < 0；后 3 日 `main_force` 连续上升且 `retail` 连续下降",
        "- 开空：前 4 日 `main_force` 全部大于 0，且第 4 日 - 第 1 日 > 0；后 3 日 `main_force` 连续下降且 `retail` 连续上升",
        "- 反向信号出现时，当日收盘平仓并反手",
        "- 以下收益未计手续费、滑点、合约乘数",
        "",
        "| 序号 | 方向 | 开仓日期 | 平仓日期 | 开仓价 | 平仓价 | 持有天数 | 收益率 | 点数收益 | 平仓原因 | 背景4日日期 | 背景4日主力值 | 背景净变化(4-1) | 触发3日日期 | 触发3日主力变化 | 触发3日散户变化 |",
        "|---|---|---|---|---:|---:|---:|---:|---:|---|---|---|---:|---|---|---|",
    ]
    for row in rows:
        lines.append(
            "| {seq} | {side} | {entry_date} | {exit_date} | {entry_price} | {exit_price} | "
            "{holding_days} | {pnl_ratio_pct} | {pnl_points} | {exit_reason} | {bg_dates} | "
            "{bg_main_values} | {bg_main_delta} | {tg_dates} | {tg_main_diffs} | {tg_retail_diffs} |".format(
                **row
            )
        )
    lines.append("")
    return "\n".join(lines)


def build_summary_markdown(summary_df: pd.DataFrame) -> str:
    lines = [
        "# 严格 7 日波段策略汇总",
        "",
        "规则口径：前 4 日做背景过滤，后 3 日做连续触发；反向信号出现时平仓并反手。",
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


def main() -> None:
    result = run_wave_strategy_backtest_strict7()
    summary_df = result["summary"].copy()
    trades_df = result["trades"].copy()
    portfolio_df = result["portfolio_curve"].copy()

    ARTIFACT_DATA.mkdir(parents=True, exist_ok=True)
    DOCS_DIR.mkdir(parents=True, exist_ok=True)

    summary_csv = ARTIFACT_DATA / "wave_strategy_strict7_summary.csv"
    trades_csv = ARTIFACT_DATA / "wave_strategy_strict7_trades.csv"
    portfolio_csv = ARTIFACT_DATA / "wave_strategy_strict7_portfolio_curve.csv"
    summary_md = DOCS_DIR / "wave_strategy_strict7_summary.md"
    jiaomei_md = DOCS_DIR / "jiaomei_wave_trades_strict7.md"

    summary_df.to_csv(summary_csv, index=False)
    trades_df.to_csv(trades_csv, index=False)
    portfolio_df.to_csv(portfolio_csv, index=False)
    summary_md.write_text(build_summary_markdown(summary_df), encoding="utf-8")

    con = sqlite3.connect(DB)
    variety_map = load_varieties(con).set_index("name")
    jiaomei_id = int(variety_map.loc["焦煤", "id"])
    jiaomei_df = load_df(con, jiaomei_id)
    con.close()
    jiaomei_signal_df = compute_signals_strict7(jiaomei_df)
    jiaomei_trades_df = trades_df[trades_df["variety_name"] == "焦煤"].copy()
    jiaomei_md.write_text(
        build_jiaomei_detail_markdown(jiaomei_signal_df, jiaomei_trades_df),
        encoding="utf-8",
    )

    print("=" * 96)
    print("严格 7 日波段回测")
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
