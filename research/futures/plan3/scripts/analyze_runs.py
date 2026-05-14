"""
Plan 3 — 连续单调区间统计分析
读取 detect_runs.py 产出的 runs_all.csv，进行：
1. 方向准确率统计
2. 质量分组检验（低/中/高质量 vs |price_change%|）
3. 回归验证（|price_change%| ~ |cumulative_delta|）
4. 品种级 + 全局汇总 + 多空拆分 + 板块汇总

输出：
  artifacts/data/runs_summary.csv    各品种汇总统计
  artifacts/charts/                  图表
"""
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats
import matplotlib.pyplot as plt

# 设置中文字体
plt.rcParams["font.sans-serif"] = ["PingFang HK", "Arial Unicode MS", "Hiragino Sans GB"]
plt.rcParams["axes.unicode_minus"] = False

ROOT = Path(__file__).resolve().parent.parent
ARTIFACT_DATA = ROOT / "artifacts" / "data"
ARTIFACT_CHARTS = ROOT / "artifacts" / "charts"
RUNS_CSV = ARTIFACT_DATA / "runs_all.csv"

# 板块分类（与 Plan 1 保持一致）
SECTORS = {
    "有色金属": ["沪铜", "沪铝", "沪锌", "沪铅", "沪锡", "沪镍", "沪金", "沪银", "氧化铝"],
    "油脂油料": ["豆一", "豆二", "豆油", "豆粕", "菜油", "菜粕", "棕榈油", "花生"],
    "化工能化": ["PTA", "对二甲苯", "聚丙烯", "苯乙烯", "纯苯", "烧碱", "尿素", "橡胶", "丁二烯胶",
               "燃油", "低硫燃油", "甲醇", "PVC", "纯碱", "乙二醇", "沥青", "LPG", "塑料"],
    "黑色系": ["铁矿石", "螺纹钢", "热卷", "锰硅", "焦煤"],
    "农产品": ["玉米", "鸡蛋", "棉花", "白糖", "苹果", "红枣", "生猪"],
    "其他": ["工业硅", "多晶硅", "碳酸锂", "原木", "纸浆", "上证", "玻璃"],
}


def assign_sector(name: str) -> str:
    for sector, names in SECTORS.items():
        if name in names:
            return sector
    return "其他"


def direction_accuracy(df: pd.DataFrame) -> dict:
    """方向准确率：做多 run 中价格上涨的比例，做空 run 中价格下跌的比例"""
    long_runs = df[df["direction"] == 1]
    short_runs = df[df["direction"] == -1]
    return {
        "long_runs_n": len(long_runs),
        "long_acc": (long_runs["price_change_pct"] > 0).mean() if len(long_runs) else float("nan"),
        "short_runs_n": len(short_runs),
        "short_acc": (short_runs["price_change_pct"] < 0).mean() if len(short_runs) else float("nan"),
        "overall_acc": (
            ((df["direction"] == 1) & (df["price_change_pct"] > 0)).sum() +
            ((df["direction"] == -1) & (df["price_change_pct"] < 0)).sum()
        ) / len(df) if len(df) else float("nan"),
    }


def quality_group_test(df: pd.DataFrame) -> pd.DataFrame:
    """按 |cumulative_delta| 分三组，比较 |price_change%|"""
    df = df.copy()
    df["abs_delta"] = df["cumulative_delta"].abs()
    df["abs_price_change"] = df["price_change_pct"].abs()

    df["quality_group"] = pd.qcut(df["abs_delta"], q=3, labels=["低", "中", "高"])
    summary = df.groupby("quality_group")["abs_price_change"].agg(["mean", "median", "std", "count"]).reset_index()
    summary.columns = ["quality_group", "mean_abs_price_change", "median_abs_price_change", "std", "count"]
    return summary


def regression_test(df: pd.DataFrame) -> dict:
    """回归：|price_change%| ~ |cumulative_delta|"""
    x = df["cumulative_delta"].abs().to_numpy()
    y = df["price_change_pct"].abs().to_numpy()
    mask = np.isfinite(x) & np.isfinite(y)
    x, y = x[mask], y[mask]
    if len(x) < 3:
        return {"slope": float("nan"), "intercept": float("nan"), "r2": float("nan"), "pvalue": float("nan")}
    slope, intercept, r, pvalue, _ = stats.linregress(x, y)
    return {
        "slope": slope,
        "intercept": intercept,
        "r2": r ** 2,
        "pvalue": pvalue,
    }


def binom_p_two_sided(k: int, n: int, p: float = 0.5) -> float:
    """二项检验双尾 p 值"""
    from math import comb
    if n == 0:
        return float("nan")
    mean = n * p
    target = abs(k - mean)
    total = 0.0
    for i in range(n + 1):
        if abs(i - mean) >= target - 1e-12:
            total += comb(n, i) * (p ** i) * ((1 - p) ** (n - i))
    return min(total, 1.0)


def analyze_variety(df: pd.DataFrame) -> dict:
    """单个品种的全部统计"""
    acc = direction_accuracy(df)
    reg = regression_test(df)
    return {
        "runs_n": len(df),
        **acc,
        "reg_slope": reg["slope"],
        "reg_r2": reg["r2"],
        "reg_pvalue": reg["pvalue"],
    }


def plot_scatter(df: pd.DataFrame, save_path: Path):
    """散点图：|cumulative_delta| vs |price_change%|"""
    fig, ax = plt.subplots(figsize=(10, 6))
    df = df.copy()
    df["abs_delta"] = df["cumulative_delta"].abs()
    df["abs_price_change"] = df["price_change_pct"].abs()

    # 回归线
    x = df["abs_delta"].to_numpy()
    y = df["abs_price_change"].to_numpy()
    mask = np.isfinite(x) & np.isfinite(y)
    x, y = x[mask], y[mask]
    slope, intercept, r, pvalue, _ = stats.linregress(x, y)
    x_line = np.linspace(x.min(), x.max(), 200)
    y_line = slope * x_line + intercept

    ax.scatter(df["abs_delta"], df["abs_price_change"], alpha=0.3, s=15)
    ax.plot(x_line, y_line, color="red", linewidth=2,
            label=f"y={slope:.4f}x+{intercept:.4f}, R²={r**2:.4f}, p={pvalue:.2e}")
    ax.set_xlabel("|cumulative_delta| (z-score 累积变化绝对值)")
    ax.set_ylabel("|price_change%| (价格变化率绝对值)")
    ax.set_title("主力持续单向积累质量 vs 价格变动幅度（全品种汇总）")
    ax.legend()
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(save_path, dpi=150)
    plt.close(fig)
    print(f"  图表已保存: {save_path}")


def plot_quality_groups(summary: pd.DataFrame, save_path: Path):
    """分组柱状图：低/中/高质量 vs |price_change%|"""
    fig, ax = plt.subplots(figsize=(8, 5))
    bars = ax.bar(summary["quality_group"], summary["mean_abs_price_change"],
                  color=["#3498db", "#f39c12", "#e74c3c"], edgecolor="black")
    ax.set_xlabel("质量组（按 |cumulative_delta| 三分位）")
    ax.set_ylabel("平均 |price_change%|")
    ax.set_title("质量分组检验：高质量积累 → 更大价格变动")
    ax.grid(True, axis="y", alpha=0.3)

    for bar, mean_val in zip(bars, summary["mean_abs_price_change"]):
        ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.001,
                f"{mean_val:.4f}", ha="center", va="bottom", fontsize=11)

    fig.tight_layout()
    fig.savefig(save_path, dpi=150)
    plt.close(fig)
    print(f"  图表已保存: {save_path}")


def plot_direction_accuracy(summary_df: pd.DataFrame, save_path: Path):
    """各品种方向准确率柱状图"""
    fig, ax = plt.subplots(figsize=(14, 6))
    summary_df = summary_df.sort_values("overall_acc", ascending=True)
    colors = ["#2ecc71" if acc >= 0.55 else "#e74c3c" for acc in summary_df["overall_acc"]]
    bars = ax.barh(range(len(summary_df)), summary_df["overall_acc"], color=colors, edgecolor="black")
    ax.set_yticks(range(len(summary_df)))
    ax.set_yticklabels(summary_df["variety_name"], fontsize=8)
    ax.axvline(0.5, color="black", linestyle="--", linewidth=1, label="随机基线 50%")
    ax.axvline(0.55, color="orange", linestyle="--", linewidth=1, label="门槛 55%")
    ax.set_xlabel("方向准确率")
    ax.set_title("各品种方向准确率（按 |cumulative_delta| 方向判断价格方向）")
    ax.legend(loc="lower right")
    ax.grid(True, axis="x", alpha=0.3)
    fig.tight_layout()
    fig.savefig(save_path, dpi=150)
    plt.close(fig)
    print(f"  图表已保存: {save_path}")


def main():
    if not RUNS_CSV.exists():
        print(f"未找到 {RUNS_CSV}，请先运行 detect_runs.py")
        return

    df = pd.read_csv(RUNS_CSV)
    df["start_date"] = pd.to_datetime(df["start_date"])
    df["end_date"] = pd.to_datetime(df["end_date"])
    df["sector"] = df["variety_name"].apply(assign_sector)

    ARTIFACT_CHARTS.mkdir(parents=True, exist_ok=True)

    print("=" * 70)
    print("全局汇总")
    print("=" * 70)

    # 1. 方向准确率
    acc = direction_accuracy(df)
    print(f"总 runs 数: {len(df)}")
    print(f"做多 runs: {acc['long_runs_n']} 个，方向准确率: {acc['long_acc']:.2%}")
    print(f"做空 runs: {acc['short_runs_n']} 个，方向准确率: {acc['short_acc']:.2%}")
    print(f"整体方向准确率: {acc['overall_acc']:.2%}")

    # 2. 质量分组
    print()
    print("质量分组检验（按 |cumulative_delta| 三分位）:")
    qg = quality_group_test(df)
    print(qg.to_string(index=False, float_format=lambda x: f"{x:.4f}"))

    # 3. 回归
    reg = regression_test(df)
    print()
    print(f"回归验证: |price_change%| ~ |cumulative_delta|")
    print(f"  斜率: {reg['slope']:.6f}, R²: {reg['r2']:.4f}, p 值: {reg['pvalue']:.2e}")

    # 4. 多空拆分回归
    print()
    print("多空拆分回归:")
    long_df = df[df["direction"] == 1]
    short_df = df[df["direction"] == -1]
    reg_long = regression_test(long_df)
    reg_short = regression_test(short_df)
    print(f"  做多 runs: 斜率={reg_long['slope']:.6f}, R²={reg_long['r2']:.4f}, p={reg_long['pvalue']:.2e}")
    print(f"  做空 runs: 斜率={reg_short['slope']:.6f}, R²={reg_short['r2']:.4f}, p={reg_short['pvalue']:.2e}")

    # 5. 品种级分析
    print()
    print("=" * 70)
    print("品种级统计")
    print("=" * 70)

    variety_rows = []
    for vid, vdf in df.groupby("variety_id"):
        vname = vdf["variety_name"].iloc[0]
        stats_dict = analyze_variety(vdf)
        stats_dict.update({
            "variety_id": vid,
            "variety_name": vname,
            "sector": vdf["sector"].iloc[0],
        })
        variety_rows.append(stats_dict)

    summary_df = pd.DataFrame(variety_rows)
    # 计算二项检验 p 值
    summary_df["overall_acc_binom_p"] = summary_df.apply(
        lambda r: binom_p_two_sided(
            int(round(r["overall_acc"] * r["runs_n"])),
            int(r["runs_n"]),
        ), axis=1,
    )
    cols = [
        "variety_id", "variety_name", "sector", "runs_n",
        "long_runs_n", "long_acc", "short_runs_n", "short_acc",
        "overall_acc", "overall_acc_binom_p",
        "reg_slope", "reg_r2", "reg_pvalue",
    ]
    summary_df = summary_df[cols].sort_values("overall_acc", ascending=False)
    print(summary_df.head(10).to_string(index=False, float_format=lambda x: f"{x:.4f}"))
    print()
    passed = summary_df[(summary_df["overall_acc"] >= 0.55) & (summary_df["overall_acc_binom_p"] < 0.05)]
    print(f"方向准确率 ≥55% 且 binom_p < 0.05 的品种: {len(passed)} / {len(summary_df)}")

    # 6. 板块汇总
    print()
    print("=" * 70)
    print("板块汇总")
    print("=" * 70)
    sector_summary = summary_df.groupby("sector").agg({
        "overall_acc": "mean",
        "reg_r2": "mean",
        "variety_name": "count",
    }).rename(columns={"variety_name": "品种数"}).reset_index()
    sector_summary = sector_summary.sort_values("overall_acc", ascending=False)
    print(sector_summary.to_string(index=False, float_format=lambda x: f"{x:.4f}"))

    # 7. 保存汇总
    summary_df.to_csv(ARTIFACT_DATA / "runs_summary.csv", index=False)
    print()
    print(f"汇总文件已保存: {ARTIFACT_DATA / 'runs_summary.csv'}")

    # 8. 生成图表
    print()
    print("=" * 70)
    print("生成图表")
    print("=" * 70)
    plot_scatter(df, ARTIFACT_CHARTS / "scatter_quality_vs_price_change.png")
    plot_quality_groups(qg, ARTIFACT_CHARTS / "bar_quality_groups.png")
    plot_direction_accuracy(summary_df, ARTIFACT_CHARTS / "bar_direction_accuracy.png")

    print()
    print("分析完成。")


if __name__ == "__main__":
    main()
