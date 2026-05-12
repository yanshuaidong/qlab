"""
计划 3：12 品种单品种逐笔交易明细分析

为策略 2 的 12 个品种各自独立运行策略 1（严格 7 日 + 3 日拐头），
输出：
  - 每笔交易的完整明细
  - 逐品种汇总统计（胜率、平均收益、盈亏比、多空分拆等）
  - 全品种整体统计
  - 可视化图表
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd

# ── matplotlib 非交互后端 ──
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
from matplotlib import font_manager as fm

# 注册系统 CJK 字体
for fp in [
    "/Library/Fonts/Arial Unicode.ttf",
    "/Users/zxxk/Library/Fonts/Alibaba-PuHuiTi-Regular.otf",
]:
    try:
        fm.fontManager.addfont(fp)
    except Exception:
        pass
plt.rcParams["font.sans-serif"] = ["Alibaba PuHuiTi", "Arial Unicode", "AppleGothic",
                                     "AppleMyungjo", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False

# ── 路径 ──
ROOT = Path(__file__).resolve().parent.parent
ARTIFACT_DATA = ROOT / "artifacts" / "data"
ARTIFACT_PLOTS = ROOT / "artifacts" / "plots"
DOCS_DIR = ROOT / "docs"
DB = Path("/Users/zxxk/ysd/ysdproject/qlab/storage/futures/futures_main_retail/data.sqlite")

# ── 12 品种池（与策略 2 完全一致）──
TARGET_POOL: list[tuple[str, str]] = [
    ("沪铜", "有色金属"),
    ("沪铝", "有色金属"),
    ("沪锌", "有色金属"),
    ("沪金", "贵金属"),
    ("铁矿石", "黑色系"),
    ("焦煤", "黑色系"),
    ("PTA", "化工能化"),
    ("甲醇", "化工能化"),
    ("橡胶", "化工能化"),
    ("豆粕", "油脂油料"),
    ("棕榈油", "油脂油料"),
    ("玉米", "农产品"),
]
TARGET_VARIETIES = [name for name, _ in TARGET_POOL]
SECTOR_BY_VARIETY = dict(TARGET_POOL)
MOMENTUM_LOOKBACK = 30


# ══════════════════════════════════════════════════════
#  数据加载
# ══════════════════════════════════════════════════════

def load_varieties(con: sqlite3.Connection) -> pd.DataFrame:
    return pd.read_sql_query(
        "SELECT id, name, key FROM fut_variety ORDER BY id", con
    )


def load_df(con: sqlite3.Connection, variety_id: int) -> pd.DataFrame:
    strength = pd.read_sql_query(
        ("SELECT trade_date, main_force, retail "
         "FROM fut_strength WHERE variety_id=? ORDER BY trade_date"),
        con, params=(variety_id,),
    )
    close = pd.read_sql_query(
        ("SELECT trade_date, close_price AS close "
         "FROM fut_daily_close WHERE variety_id=? ORDER BY trade_date"),
        con, params=(variety_id,),
    )
    df = strength.merge(close, on="trade_date", how="inner").dropna()
    df["trade_date"] = pd.to_datetime(df["trade_date"])
    return df.sort_values("trade_date").reset_index(drop=True)


def mark_breakpoints(dates: pd.Series) -> pd.Series:
    diffs = dates.diff().dt.days.fillna(1)
    return diffs.le(7)


def compute_max_drawdown(curve: pd.Series) -> float:
    peak = curve.cummax()
    drawdown = curve / peak - 1.0
    return float(drawdown.min())


def trade_return(side: int, entry_price: float, exit_price: float) -> float:
    return float(side * (exit_price - entry_price) / entry_price)


# ══════════════════════════════════════════════════════
#  信号计算（策略 1：严格 7 日 + 3 日拐头）
# ══════════════════════════════════════════════════════

def compute_signals_strict7_tp3(df: pd.DataFrame) -> pd.DataFrame:
    """
    开多：
      - 背景 4 日 main_force 全部 < 0，且第 4 日 ≤ 前 3 日
      - 触发 3 日 main_force 连续上升（main_diff > 0）
      - 触发 3 日 retail 连续下降（retail_diff < 0）
    开空：
      - 背景 4 日 main_force 全部 > 0，且第 4 日 ≥ 前 3 日
      - 触发 3 日 main_force 连续下降（main_diff < 0）
      - 触发 3 日 retail 连续上升（retail_diff > 0）
    平多：最近 3 日 main_delta < 0
    平空：最近 3 日 main_delta > 0
    """
    out = df.copy()
    out["date_cont"] = mark_breakpoints(out["trade_date"])
    out["main_diff"] = out["main_force"].diff()
    out["retail_diff"] = out["retail"].diff()

    cont7 = out["date_cont"].astype(int).rolling(6, min_periods=6).sum().eq(6)
    cont3 = out["date_cont"].astype(int).rolling(2, min_periods=2).sum().eq(2)

    bg1 = out["main_force"].shift(6)
    bg2 = out["main_force"].shift(5)
    bg3 = out["main_force"].shift(4)
    bg4 = out["main_force"].shift(3)
    bg5 = out["main_force"].shift(2)

    trigger_main_up = out["main_diff"].shift(1).gt(0) & out["main_diff"].gt(0)
    trigger_main_down = out["main_diff"].shift(1).lt(0) & out["main_diff"].lt(0)
    trigger_retail_down = out["retail_diff"].shift(1).lt(0) & out["retail_diff"].lt(0)
    trigger_retail_up = out["retail_diff"].shift(1).gt(0) & out["retail_diff"].gt(0)

    long_bg = (
        bg1.lt(0) & bg2.lt(0) & bg3.lt(0) & bg4.lt(0) & bg5.lt(0)
        & bg5.le(bg1) & bg5.le(bg2) & bg5.le(bg3) & bg5.le(bg4)
    )
    short_bg = (
        bg1.gt(0) & bg2.gt(0) & bg3.gt(0) & bg4.gt(0) & bg5.gt(0)
        & bg5.ge(bg1) & bg5.ge(bg2) & bg5.ge(bg3) & bg5.ge(bg4)
    )

    out["long_signal"] = cont7 & long_bg & trigger_main_up & trigger_retail_down
    out["short_signal"] = cont7 & short_bg & trigger_main_down & trigger_retail_up

    # 3 日主力动量（用于 main_score 和拐头判断）
    out["m3"] = out["main_force"] - out["main_force"].shift(2)
    out["abs_m3"] = out["m3"].abs()
    out["tp3_delta_main"] = out["m3"]
    out["exit_long_signal"] = cont3 & out["tp3_delta_main"].lt(0)
    out["exit_short_signal"] = cont3 & out["tp3_delta_main"].gt(0)

    # main_score：|m3| 的 30 日分位分
    scores: list[float] = []
    abs_m3 = out["abs_m3"]
    for i in range(len(out)):
        current = abs_m3.iloc[i]
        hist = abs_m3.iloc[max(0, i - MOMENTUM_LOOKBACK):i].dropna()
        if pd.isna(current) or len(hist) < MOMENTUM_LOOKBACK:
            scores.append(np.nan)
        else:
            scores.append(float(hist.le(current).sum() / MOMENTUM_LOOKBACK))
    out["main_score"] = scores

    out["close_return"] = out["close"].pct_change().fillna(0.0)
    return out


# ══════════════════════════════════════════════════════
#  单品种回测
# ══════════════════════════════════════════════════════

def backtest_single(df: pd.DataFrame, variety_name: str) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    data = compute_signals_strict7_tp3(df).copy()
    data["position_after_close"] = 0

    trades: list[dict] = []
    position = 0
    entry_idx: int | None = None
    entry_price: float | None = None
    entry_date = None
    entry_main_score: float | None = None
    entry_main_force: float | None = None

    for i, row in data.iterrows():
        closed_today = False

        # ── 平仓 ──
        if position == 1 and row["exit_long_signal"]:
            exit_price = float(row["close"])
            pnl = trade_return(1, float(entry_price), exit_price)
            trades.append(dict(
                variety_name=variety_name,
                sector=SECTOR_BY_VARIETY[variety_name],
                side="long",
                entry_date=str(entry_date.date()) if hasattr(entry_date, "date") else str(entry_date),
                exit_date=str(row["trade_date"].date()),
                entry_price=float(entry_price),
                exit_price=exit_price,
                holding_days=i - int(entry_idx),
                pnl_ratio=pnl,
                main_score_at_entry=float(entry_main_score) if entry_main_score is not None else None,
                main_force_at_entry=float(entry_main_force) if entry_main_force is not None else None,
                exit_reason="tp3_main_turn_down",
            ))
            position = 0
            entry_idx = None
            entry_price = None
            entry_date = None
            entry_main_score = None
            entry_main_force = None
            closed_today = True

        elif position == -1 and row["exit_short_signal"]:
            exit_price = float(row["close"])
            pnl = trade_return(-1, float(entry_price), exit_price)
            trades.append(dict(
                variety_name=variety_name,
                sector=SECTOR_BY_VARIETY[variety_name],
                side="short",
                entry_date=str(entry_date.date()) if hasattr(entry_date, "date") else str(entry_date),
                exit_date=str(row["trade_date"].date()),
                entry_price=float(entry_price),
                exit_price=exit_price,
                holding_days=i - int(entry_idx),
                pnl_ratio=pnl,
                main_score_at_entry=float(entry_main_score) if entry_main_score is not None else None,
                main_force_at_entry=float(entry_main_force) if entry_main_force is not None else None,
                exit_reason="tp3_main_turn_up",
            ))
            position = 0
            entry_idx = None
            entry_price = None
            entry_date = None
            entry_main_score = None
            entry_main_force = None
            closed_today = True

        # ── 开仓 ──
        if position == 0 and not closed_today:
            if row["long_signal"]:
                position = 1
                entry_idx = i
                entry_price = float(row["close"])
                entry_date = row["trade_date"]
                entry_main_score = float(row["main_score"]) if not pd.isna(row["main_score"]) else None
                entry_main_force = float(row["main_force"])
            elif row["short_signal"]:
                position = -1
                entry_idx = i
                entry_price = float(row["close"])
                entry_date = row["trade_date"]
                entry_main_score = float(row["main_score"]) if not pd.isna(row["main_score"]) else None
                entry_main_force = float(row["main_force"])

        data.at[i, "position_after_close"] = position

    # ── 尾日强平 ──
    if position != 0:
        last_row = data.iloc[-1]
        exit_price = float(last_row["close"])
        pnl = trade_return(position, float(entry_price), exit_price)
        trades.append(dict(
            variety_name=variety_name,
            sector=SECTOR_BY_VARIETY[variety_name],
            side="long" if position == 1 else "short",
            entry_date=str(entry_date.date()) if hasattr(entry_date, "date") else str(entry_date),
            exit_date=str(last_row["trade_date"].date()),
            entry_price=float(entry_price),
            exit_price=exit_price,
            holding_days=len(data) - 1 - int(entry_idx),
            pnl_ratio=pnl,
            main_score_at_entry=float(entry_main_score) if entry_main_score is not None else None,
            main_force_at_entry=float(entry_main_force) if entry_main_force is not None else None,
            exit_reason="final_close",
        ))

    # ── 净值曲线 ──
    data["position_prev"] = data["position_after_close"].shift(1).fillna(0).astype(int)
    data["strategy_daily_return"] = data["position_prev"] * data["close_return"]
    data["equity_curve"] = (1.0 + data["strategy_daily_return"]).cumprod()
    data["benchmark_curve"] = (1.0 + data["close_return"]).cumprod()

    trades_df = pd.DataFrame(trades)
    return data, trades_df


# ══════════════════════════════════════════════════════
#  逐品种汇总统计
# ══════════════════════════════════════════════════════

def compute_per_variety_stats(
    trades_df: pd.DataFrame, curve_df: pd.DataFrame, variety_name: str
) -> dict:
    stats: dict = dict(
        variety_name=variety_name,
        sector=SECTOR_BY_VARIETY[variety_name],
        trade_count=len(trades_df),
    )
    if len(trades_df) == 0:
        return stats

    # 基础统计
    pnl = trades_df["pnl_ratio"]
    stats["long_count"] = int((trades_df["side"] == "long").sum())
    stats["short_count"] = int((trades_df["side"] == "short").sum())
    stats["win_rate"] = float((pnl > 0).mean())
    stats["loss_rate"] = float((pnl <= 0).mean())
    stats["avg_trade_return"] = float(pnl.mean())
    stats["median_trade_return"] = float(pnl.median())
    stats["std_trade_return"] = float(pnl.std())
    stats["max_profit"] = float(pnl.max())
    stats["max_loss"] = float(pnl.min())
    stats["win_avg"] = float(pnl[pnl > 0].mean()) if (pnl > 0).any() else 0.0
    stats["loss_avg"] = float(pnl[pnl <= 0].mean()) if (pnl <= 0).any() else 0.0
    stats["profit_loss_ratio"] = (
        abs(stats["win_avg"] / stats["loss_avg"])
        if stats["loss_avg"] != 0 else np.nan
    )
    stats["median_holding_days"] = float(trades_df["holding_days"].median())
    stats["avg_holding_days"] = float(trades_df["holding_days"].mean())

    # 多空分拆
    long_df = trades_df[trades_df["side"] == "long"]
    short_df = trades_df[trades_df["side"] == "short"]
    stats["long_win_rate"] = float((long_df["pnl_ratio"] > 0).mean()) if len(long_df) else np.nan
    stats["short_win_rate"] = float((short_df["pnl_ratio"] > 0).mean()) if len(short_df) else np.nan
    stats["long_avg_return"] = float(long_df["pnl_ratio"].mean()) if len(long_df) else np.nan
    stats["short_avg_return"] = float(short_df["pnl_ratio"].mean()) if len(short_df) else np.nan

    # main_score 相关性
    valid_score = trades_df["main_score_at_entry"].dropna()
    valid_pnl = pnl[valid_score.index]
    stats["score_pnl_corr"] = (
        float(valid_score.corr(valid_pnl)) if len(valid_score) > 2 else np.nan
    )

    # 累计收益
    stats["strategy_return"] = float(curve_df["equity_curve"].iloc[-1] - 1.0)
    stats["buy_hold_return"] = float(curve_df["benchmark_curve"].iloc[-1] - 1.0)
    stats["excess_return"] = stats["strategy_return"] - stats["buy_hold_return"]
    stats["max_drawdown"] = compute_max_drawdown(curve_df["equity_curve"])

    return stats


def summarize_pool(trades_pool: pd.DataFrame) -> dict:
    """全品种合并池的整体统计"""
    stats: dict = {}
    pnl = trades_pool["pnl_ratio"]
    stats["total_trades"] = len(trades_pool)
    stats["total_win_rate"] = float((pnl > 0).mean())
    stats["total_loss_rate"] = float((pnl <= 0).mean())
    stats["total_avg_return"] = float(pnl.mean())
    stats["total_median_return"] = float(pnl.median())
    stats["total_std_return"] = float(pnl.std())
    stats["total_max_profit"] = float(pnl.max())
    stats["total_max_loss"] = float(pnl.min())
    stats["total_win_avg"] = float(pnl[pnl > 0].mean()) if (pnl > 0).any() else 0.0
    stats["total_loss_avg"] = float(pnl[pnl <= 0].mean()) if (pnl <= 0).any() else 0.0
    stats["total_profit_loss_ratio"] = (
        abs(stats["total_win_avg"] / stats["total_loss_avg"])
        if stats["total_loss_avg"] != 0 else np.nan
    )
    stats["total_avg_holding_days"] = float(trades_pool["holding_days"].mean())
    stats["total_median_holding_days"] = float(trades_pool["holding_days"].median())

    # main_score 分段胜率
    score_bins = [0, 0.2, 0.4, 0.6, 0.8, 1.0]
    score_labels = ["0-0.2", "0.2-0.4", "0.4-0.6", "0.6-0.8", "0.8-1.0"]
    trades_pool = trades_pool.copy()
    trades_pool["score_bin"] = pd.cut(
        trades_pool["main_score_at_entry"], bins=score_bins, labels=score_labels
    )
    bin_stats = trades_pool.groupby("score_bin", observed=True)["pnl_ratio"].agg(["count", "mean"])
    stats["score_bin_counts"] = bin_stats["count"].to_dict()
    stats["score_bin_win_rates"] = (bin_stats["mean"] > 0).to_dict()
    stats["score_bin_avg_returns"] = bin_stats["mean"].to_dict()

    return stats


# ══════════════════════════════════════════════════════
#  可视化
# ══════════════════════════════════════════════════════

def plot_win_rate_bar(per_var: pd.DataFrame) -> str:
    df = per_var.sort_values("win_rate", ascending=True)
    fig, ax = plt.subplots(figsize=(10, 6))
    colors = ["#2ecc71" if wr >= 0.5 else "#e74c3c" for wr in df["win_rate"]]
    bars = ax.barh(range(len(df)), df["win_rate"].values, color=colors, height=0.6)
    ax.set_yticks(range(len(df)))
    ax.set_yticklabels(df["variety_name"].values)
    ax.axvline(0.5, color="gray", linestyle="--", linewidth=0.8, label="50%")
    ax.set_xlabel("胜率")
    ax.set_title("各品种独立策略胜率（严格 7 日 + 3 日拐头）")
    ax.set_xlim(0, 1)
    # 标注交易笔数
    for bar, cnt in zip(bars, df["trade_count"]):
        ax.text(bar.get_width() + 0.01, bar.get_y() + bar.get_height() / 2,
                f"n={cnt}", va="center", fontsize=9)
    ax.legend()
    fig.tight_layout()
    path = str(ARTIFACT_PLOTS / "win_rate_bar.png")
    fig.savefig(path, dpi=150)
    plt.close(fig)
    return path


def plot_pnl_boxplot(per_var: pd.DataFrame, trades_pool: pd.DataFrame) -> str:
    varieties = per_var.sort_values("win_rate", ascending=False)["variety_name"].tolist()
    data = [trades_pool[trades_pool["variety_name"] == v]["pnl_ratio"].values * 100
            for v in varieties]
    fig, ax = plt.subplots(figsize=(12, 6))
    bp = ax.boxplot(data, labels=varieties, patch_artist=True, vert=True, showfliers=True)
    for patch in bp["boxes"]:
        patch.set_facecolor("#3498db")
        patch.set_alpha(0.6)
    ax.axhline(0, color="red", linestyle="--", linewidth=0.8)
    ax.set_ylabel("单笔收益率 (%)")
    ax.set_title("各品种单笔 P&L 分布")
    ax.tick_params(axis="x", rotation=45)
    fig.tight_layout()
    path = str(ARTIFACT_PLOTS / "pnl_boxplot.png")
    fig.savefig(path, dpi=150)
    plt.close(fig)
    return path


def plot_equity_curves(curves: dict[str, pd.DataFrame]) -> str:
    fig, ax = plt.subplots(figsize=(12, 6))
    for name, df in curves.items():
        ax.plot(df["trade_date"], df["equity_curve"], label=name, linewidth=0.8)
    ax.set_ylabel("净值")
    ax.set_title("各品种独立策略净值曲线")
    ax.legend(loc="best", fontsize=7, ncol=2)
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda y, _: f"{y:.2f}"))
    fig.tight_layout()
    path = str(ARTIFACT_PLOTS / "equity_curves.png")
    fig.savefig(path, dpi=150)
    plt.close(fig)
    return path


def plot_win_rate_vs_trades(per_var: pd.DataFrame) -> str:
    fig, ax = plt.subplots(figsize=(8, 6))
    colors = [SECTOR_BY_VARIETY[v] for v in per_var["variety_name"]]
    sector_color_map = {
        "有色金属": "#e74c3c", "贵金属": "#f39c12", "黑色系": "#2c3e50",
        "化工能化": "#3498db", "油脂油料": "#27ae60", "农产品": "#9b59b6",
    }
    color_list = [sector_color_map.get(s, "#95a5a6") for s in per_var["sector"]]
    scatter = ax.scatter(
        per_var["trade_count"], per_var["win_rate"] * 100,
        c=color_list, s=80, alpha=0.8, edgecolors="black", linewidth=0.5
    )
    for _, row in per_var.iterrows():
        ax.annotate(row["variety_name"],
                    (row["trade_count"], row["win_rate"] * 100),
                    fontsize=8, xytext=(5, 3), textcoords="offset points")
    ax.axhline(50, color="gray", linestyle="--", linewidth=0.8, label="50%")
    ax.set_xlabel("交易次数")
    ax.set_ylabel("胜率 (%)")
    ax.set_title("胜率 vs 交易次数")
    # 图例
    from matplotlib.patches import Patch
    legend_elements = [Patch(facecolor=c, label=s) for s, c in sector_color_map.items()]
    ax.legend(handles=legend_elements, fontsize=8, loc="lower right")
    fig.tight_layout()
    path = str(ARTIFACT_PLOTS / "win_rate_vs_trades.png")
    fig.savefig(path, dpi=150)
    plt.close(fig)
    return path


def plot_holding_days_hist(trades_pool: pd.DataFrame) -> str:
    fig, ax = plt.subplots(figsize=(8, 5))
    ax.hist(trades_pool["holding_days"], bins=20, color="#3498db", alpha=0.7, edgecolor="white")
    ax.set_xlabel("持有天数")
    ax.set_ylabel("交易笔数")
    ax.set_title("全品种持仓天数分布")
    fig.tight_layout()
    path = str(ARTIFACT_PLOTS / "holding_days_hist.png")
    fig.savefig(path, dpi=150)
    plt.close(fig)
    return path


def plot_pnl_histogram(trades_pool: pd.DataFrame) -> str:
    fig, ax = plt.subplots(figsize=(8, 5))
    pnl_pct = trades_pool["pnl_ratio"] * 100
    ax.hist(pnl_pct, bins=30, color="#2ecc71", alpha=0.7, edgecolor="white")
    ax.axvline(0, color="red", linestyle="--", linewidth=0.8)
    ax.set_xlabel("单笔收益率 (%)")
    ax.set_ylabel("交易笔数")
    ax.set_title("全品种单笔收益率分布")
    fig.tight_layout()
    path = str(ARTIFACT_PLOTS / "pnl_histogram.png")
    fig.savefig(path, dpi=150)
    plt.close(fig)
    return path


def plot_score_win_rate(trades_pool: pd.DataFrame) -> str:
    score_bins = [0, 0.2, 0.4, 0.6, 0.8, 1.0]
    score_labels = ["0-0.2", "0.2-0.4", "0.4-0.6", "0.6-0.8", "0.8-1.0"]
    pool = trades_pool.dropna(subset=["main_score_at_entry"]).copy()
    pool["score_bin"] = pd.cut(pool["main_score_at_entry"], bins=score_bins, labels=score_labels)
    grouped = pool.groupby("score_bin", observed=True)["pnl_ratio"]
    win_rates = grouped.apply(lambda x: (x > 0).mean())
    counts = grouped.count()
    avg_returns = grouped.mean()

    fig, ax1 = plt.subplots(figsize=(8, 5))
    bars = ax1.bar(range(len(win_rates)), win_rates.values * 100, color="#8e44ad", alpha=0.7)
    ax1.set_xticks(range(len(win_rates)))
    ax1.set_xticklabels(win_rates.index.tolist())
    ax1.set_ylabel("胜率 (%)")
    ax1.set_ylim(0, 100)
    ax1.set_title("main_score 分段胜率")
    for bar, cnt in zip(bars, counts):
        ax1.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 1,
                f"n={cnt}", ha="center", fontsize=9)

    ax2 = ax1.twinx()
    ax2.plot(range(len(avg_returns)), avg_returns.values * 100, "r-o", linewidth=1.5, markersize=5)
    ax2.set_ylabel("平均收益率 (%)", color="red")
    ax2.tick_params(axis="y", labelcolor="red")
    fig.tight_layout()
    path = str(ARTIFACT_PLOTS / "score_win_rate.png")
    fig.savefig(path, dpi=150)
    plt.close(fig)
    return path


def plot_long_short_comparison(per_var: pd.DataFrame) -> str:
    df = per_var.dropna(subset=["long_win_rate", "short_win_rate"]).copy()
    fig, ax = plt.subplots(figsize=(10, 6))
    x = range(len(df))
    width = 0.35
    ax.bar([i - width / 2 for i in x], df["long_win_rate"].values * 100,
           width, label="多头", color="#e74c3c", alpha=0.7)
    ax.bar([i + width / 2 for i in x], df["short_win_rate"].values * 100,
           width, label="空头", color="#3498db", alpha=0.7)
    ax.set_xticks(x)
    ax.set_xticklabels(df["variety_name"].values, rotation=45)
    ax.set_ylabel("胜率 (%)")
    ax.set_title("多空胜率对比")
    ax.axhline(50, color="gray", linestyle="--", linewidth=0.8)
    ax.legend()
    fig.tight_layout()
    path = str(ARTIFACT_PLOTS / "long_short_comparison.png")
    fig.savefig(path, dpi=150)
    plt.close(fig)
    return path


# ══════════════════════════════════════════════════════
#  主流程
# ══════════════════════════════════════════════════════

def main() -> None:
    ARTIFACT_DATA.mkdir(parents=True, exist_ok=True)
    ARTIFACT_PLOTS.mkdir(parents=True, exist_ok=True)
    DOCS_DIR.mkdir(parents=True, exist_ok=True)

    con = sqlite3.connect(str(DB))
    variety_map = load_varieties(con).set_index("name")

    all_trades: list[pd.DataFrame] = []
    per_variety_stats: list[dict] = []
    curves: dict[str, pd.DataFrame] = {}

    for variety_name in TARGET_VARIETIES:
        variety_id = int(variety_map.loc[variety_name, "id"])
        df = load_df(con, variety_id)
        print(f"  [{variety_name}] 加载完成，{len(df)} 行")

        curve_df, trades_df = backtest_single(df, variety_name)
        stats = compute_per_variety_stats(trades_df, curve_df, variety_name)
        per_variety_stats.append(stats)
        all_trades.append(trades_df)
        curves[variety_name] = curve_df

        # 保存逐品种交易明细
        if len(trades_df):
            trades_csv = ARTIFACT_DATA / f"trades_{variety_name}.csv"
            trades_df.to_csv(trades_csv, index=False)

        print(f"    → {stats['trade_count']} 笔交易, 胜率 {stats['win_rate']:.1%}, "
              f"累计收益 {stats['strategy_return']:.2%}")

    con.close()

    # ── 合并 ──
    trades_pool = pd.concat(all_trades, ignore_index=True)
    per_var_df = pd.DataFrame(per_variety_stats)

    # 保存
    per_var_df.to_csv(ARTIFACT_DATA / "per_variety_summary.csv", index=False)
    trades_pool.to_csv(ARTIFACT_DATA / "all_trades_pool.csv", index=False)

    # 全品种整体统计
    overall = summarize_pool(trades_pool)
    overall_df = pd.DataFrame([overall])
    overall_df.to_csv(ARTIFACT_DATA / "overall_summary.csv", index=False)

    # ── 图表 ──
    print("\n生成图表...")
    paths: list[str] = []
    paths.append(plot_win_rate_bar(per_var_df))
    paths.append(plot_pnl_boxplot(per_var_df, trades_pool))
    paths.append(plot_equity_curves(curves))
    paths.append(plot_win_rate_vs_trades(per_var_df))
    paths.append(plot_holding_days_hist(trades_pool))
    paths.append(plot_pnl_histogram(trades_pool))
    paths.append(plot_score_win_rate(trades_pool))
    paths.append(plot_long_short_comparison(per_var_df))
    for p in paths:
        print(f"  → {p}")

    print("\n✅ 全部完成")
    print(f"  逐品种汇总: {ARTIFACT_DATA / 'per_variety_summary.csv'}")
    print(f"  全品种整体: {ARTIFACT_DATA / 'overall_summary.csv'}")
    print(f"  全交易合并: {ARTIFACT_DATA / 'all_trades_pool.csv'}")


if __name__ == "__main__":
    main()