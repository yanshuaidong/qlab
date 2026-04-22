"""
9 个推荐品种的 3 日连续主力/散户反转波段回测。

策略解释（按当前对需求的实现）：
1. 开多：最近连续 3 个交易日，`main_force` 日变动都 > 0，且 `retail` 日变动都 < 0。
2. 开空：最近连续 3 个交易日，`main_force` 日变动都 < 0，且 `retail` 日变动都 > 0。
3. 反转止盈：持多过程中一旦出现开空信号，则平多并反手开空；持空同理。
4. 执行价格：使用信号当日收盘价成交，收益从下一交易日开始计入。
5. 未计手续费、滑点、合约乘数；跨品种比较统一使用收益率口径。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
ARTIFACT_DATA = ROOT / "artifacts" / "data"
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


def compute_signals(df: pd.DataFrame, streak: int = 3) -> pd.DataFrame:
    out = df.copy()
    out["main_diff"] = out["main_force"].diff()
    out["retail_diff"] = out["retail"].diff()
    out["date_cont"] = mark_breakpoints(out["trade_date"])

    main_up = out["main_diff"].gt(0)
    main_down = out["main_diff"].lt(0)
    retail_up = out["retail_diff"].gt(0)
    retail_down = out["retail_diff"].lt(0)
    cont_ok = out["date_cont"].rolling(streak, min_periods=streak).sum().eq(streak)

    out["long_signal"] = (
        main_up.rolling(streak, min_periods=streak).sum().eq(streak)
        & retail_down.rolling(streak, min_periods=streak).sum().eq(streak)
        & cont_ok
    )
    out["short_signal"] = (
        main_down.rolling(streak, min_periods=streak).sum().eq(streak)
        & retail_up.rolling(streak, min_periods=streak).sum().eq(streak)
        & cont_ok
    )
    return out


def trade_return(side: int, entry_price: float, exit_price: float) -> float:
    if side == 1:
        return exit_price / entry_price - 1.0
    return entry_price / exit_price - 1.0


def compute_max_drawdown(equity: pd.Series) -> float:
    running_peak = equity.cummax()
    drawdown = equity / running_peak - 1.0
    return float(drawdown.min())


def backtest_reversal_wave_strategy(
    df: pd.DataFrame,
    variety_name: str,
    streak: int = 3,
) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    data = compute_signals(df, streak=streak).copy()
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

            if desired_position != 0:
                entry_idx = i
                entry_price = float(row["close"])
                entry_date = row["trade_date"]
            else:
                entry_idx = None
                entry_price = None
                entry_date = None

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


def run_wave_strategy_backtest(
    variety_names: list[str] | None = None,
    streak: int = 3,
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
        curve_df, trades_df, summary = backtest_reversal_wave_strategy(
            df=df,
            variety_name=variety_name,
            streak=streak,
        )
        summary["variety_id"] = variety_id
        summary_rows.append(summary)
        all_trades.append(trades_df)
        curves.append(
            curve_df[
                [
                    "trade_date",
                    "close",
                    "position_after_close",
                    "strategy_daily_return",
                    "equity_curve",
                    "long_signal",
                    "short_signal",
                ]
            ].rename(
                columns={
                    "close": f"{variety_name}_close",
                    "position_after_close": f"{variety_name}_position",
                    "strategy_daily_return": f"{variety_name}_daily_return",
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

    ARTIFACT_DATA.mkdir(parents=True, exist_ok=True)
    summary_path = ARTIFACT_DATA / "wave_strategy_summary.csv"
    trades_path = ARTIFACT_DATA / "wave_strategy_trades.csv"
    portfolio_path = ARTIFACT_DATA / "wave_strategy_portfolio_curve.csv"

    summary_df.to_csv(summary_path, index=False)
    trades_df.to_csv(trades_path, index=False)
    portfolio.to_csv(portfolio_path, index=False)

    return {
        "summary": summary_df,
        "trades": trades_df,
        "portfolio_curve": portfolio,
    }


def main() -> None:
    result = run_wave_strategy_backtest()
    summary = result["summary"].copy()

    print("=" * 96)
    print("3 日连续主力/散户反转波段回测")
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
    print(summary[cols].to_string(index=False, float_format=lambda x: f"{x:.4f}"))
    print()
    print("交付物：")
    print(f"  - {ARTIFACT_DATA / 'wave_strategy_summary.csv'}")
    print(f"  - {ARTIFACT_DATA / 'wave_strategy_trades.csv'}")
    print(f"  - {ARTIFACT_DATA / 'wave_strategy_portfolio_curve.csv'}")


if __name__ == "__main__":
    main()
