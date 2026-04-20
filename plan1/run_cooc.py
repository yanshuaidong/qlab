"""
同期趋势共振验证：variety_id=1
按 plan1/验证计划_main_force_共振.md 执行。
"""
import sqlite3
from pathlib import Path
from math import comb

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent
DB = ROOT.parent / "database" / "local_fut_pulse.sqlite"
VARIETY_ID = 1


def load_df() -> pd.DataFrame:
    con = sqlite3.connect(DB)
    s = pd.read_sql_query(
        "SELECT trade_date, main_force, retail FROM fut_strength WHERE variety_id=? ORDER BY trade_date",
        con, params=(VARIETY_ID,),
    )
    c = pd.read_sql_query(
        "SELECT trade_date, close_price AS close FROM fut_daily_close WHERE variety_id=? ORDER BY trade_date",
        con, params=(VARIETY_ID,),
    )
    con.close()
    df = s.merge(c, on="trade_date", how="inner").dropna()
    df["trade_date"] = pd.to_datetime(df["trade_date"])
    df = df.sort_values("trade_date").reset_index(drop=True)
    return df


def mark_breakpoints(dates: pd.Series) -> np.ndarray:
    """返回 i 是否与 i-1 为连续交易日。为简化，相邻记录即视为连续（剔除 NULL 后的)."""
    # 使用 index 连续性即可：我们已内连接并按日期排序，剔除 NULL 后相邻行视作连续序列。
    # 若要严格避免跨越周末外的长跳空，可检查 diff.days > 7。
    diffs = dates.diff().dt.days.fillna(1).to_numpy()
    return diffs <= 7  # 允许周末/节假日；超过 7 天视为断点


def window_direction_A(deltas: np.ndarray) -> int:
    """口径 A：K 个 Δ 全部同号 -> ±1；否则 0。"""
    if np.all(deltas > 0):
        return 1
    if np.all(deltas < 0):
        return -1
    return 0


def window_direction_B(x_start: float, x_end: float) -> int:
    """口径 B：净变化符号。"""
    d = x_end - x_start
    if d > 0:
        return 1
    if d < 0:
        return -1
    return 0


def scan_windows(df: pd.DataFrame, K: int) -> pd.DataFrame:
    """滑窗 t 从 K 扫到末尾，生成每个窗口的方向（A、B 两种口径，三条序列）。"""
    cont = mark_breakpoints(df["trade_date"])
    # cont[i] = 第 i 行与第 i-1 行是否连续
    mf = df["main_force"].to_numpy()
    rt = df["retail"].to_numpy()
    cl = df["close"].to_numpy()
    d_mf = np.diff(mf)  # 长度 n-1，d_mf[i] = mf[i+1] - mf[i]
    d_rt = np.diff(rt)
    d_cl = np.diff(cl)

    rows = []
    n = len(df)
    for t in range(K - 1, n):
        # 窗口覆盖索引 [t-K+1, t]，需要 K-1 个差分 d[t-K+1 .. t-1]
        lo, hi = t - K + 1, t
        # 检查窗口内所有相邻步都连续（cont[lo+1..hi] 都 True）
        if not np.all(cont[lo + 1 : hi + 1]):
            continue
        mf_d = d_mf[lo:hi]  # 长度 K-1
        rt_d = d_rt[lo:hi]
        cl_d = d_cl[lo:hi]
        row = {
            "t_start": df["trade_date"].iloc[lo].date(),
            "t_end": df["trade_date"].iloc[hi].date(),
            "A_main": window_direction_A(mf_d),
            "A_retail": window_direction_A(rt_d),
            "A_close": window_direction_A(cl_d),
            "B_main": window_direction_B(mf[lo], mf[hi]),
            "B_retail": window_direction_B(rt[lo], rt[hi]),
            "B_close": window_direction_B(cl[lo], cl[hi]),
        }
        rows.append(row)
    return pd.DataFrame(rows)


def binom_p_two_sided(k: int, n: int, p: float = 0.5) -> float:
    """精确二项双侧 p 值。"""
    if n == 0:
        return float("nan")
    # 双侧：所有 |X - np| >= |k - np| 的点质量之和
    mean = n * p
    target = abs(k - mean)
    total = 0.0
    for i in range(n + 1):
        if abs(i - mean) >= target - 1e-12:
            total += comb(n, i) * (p ** i) * ((1 - p) ** (n - i))
    return min(total, 1.0)


def chi2_p(table: np.ndarray) -> float:
    """2x2 列联表卡方 p 值（无连续性校正，自由度 1）。回退用 Wilson-Hilferty 近似，避免 scipy 依赖。"""
    table = np.asarray(table, dtype=float)
    if table.sum() == 0:
        return float("nan")
    row = table.sum(axis=1, keepdims=True)
    col = table.sum(axis=0, keepdims=True)
    exp = row @ col / table.sum()
    if (exp <= 0).any():
        return float("nan")
    chi2 = ((table - exp) ** 2 / exp).sum()
    # df=1 的卡方生存函数：P = erfc(sqrt(chi2/2))
    from math import erfc, sqrt
    return erfc(sqrt(chi2 / 2.0))


def pair_stats(w: pd.DataFrame, mode: str, x_col: str, y_col: str = "close") -> dict:
    """对一对方向序列做 2x2 列联表统计。"""
    col_x = f"{mode}_{x_col}"
    col_y = f"{mode}_{y_col}"
    sub = w[(w[col_x] != 0) & (w[col_y] != 0)].copy()
    n = len(sub)
    if n == 0:
        return {"mode": mode, "pair": f"{x_col}~{y_col}", "n": 0}
    same = int((sub[col_x] == sub[col_y]).sum())
    opp = n - same
    # 两方向拆开
    pos_y = sub[sub[col_y] == 1]
    neg_y = sub[sub[col_y] == -1]
    same_pos = int((pos_y[col_x] == 1).sum())
    same_neg = int((neg_y[col_x] == -1).sum())
    # 列联表：行=x(+,-)，列=y(+,-)
    a = int(((sub[col_x] == 1) & (sub[col_y] == 1)).sum())
    b = int(((sub[col_x] == 1) & (sub[col_y] == -1)).sum())
    c = int(((sub[col_x] == -1) & (sub[col_y] == 1)).sum())
    d = int(((sub[col_x] == -1) & (sub[col_y] == -1)).sum())
    return {
        "mode": mode,
        "pair": f"{x_col}~{y_col}",
        "n": n,
        "same_rate": same / n,
        "opp_rate": opp / n,
        "binom_p_same": binom_p_two_sided(same, n, 0.5),
        "chi2_p": chi2_p(np.array([[a, b], [c, d]])),
        "long_y_n": len(pos_y),
        "long_same_rate": (same_pos / len(pos_y)) if len(pos_y) else float("nan"),
        "short_y_n": len(neg_y),
        "short_same_rate": (same_neg / len(neg_y)) if len(neg_y) else float("nan"),
        "table_++": a, "table_+-": b, "table_-+": c, "table_--": d,
    }


def bootstrap_same_rate(w: pd.DataFrame, mode: str, x_col: str, n_iter: int = 1000, seed: int = 0) -> dict:
    """打乱 x 的方向序列，得到零假设下同向占比分布。"""
    col_x = f"{mode}_{x_col}"
    col_y = f"{mode}_close"
    sub = w[(w[col_x] != 0) & (w[col_y] != 0)].copy()
    if len(sub) == 0:
        return {"boot_mean": float("nan"), "boot_p_ge_obs": float("nan")}
    x = sub[col_x].to_numpy().copy()
    y = sub[col_y].to_numpy()
    rng = np.random.default_rng(seed)
    obs = (x == y).mean()
    rates = np.empty(n_iter)
    for i in range(n_iter):
        rng.shuffle(x)
        rates[i] = (x == y).mean()
    return {
        "boot_mean": float(rates.mean()),
        "boot_std": float(rates.std()),
        "boot_p_ge_obs": float((rates >= obs).mean()),
    }


def main():
    df = load_df()
    print(f"载入数据：{len(df)} 行，日期 {df['trade_date'].min().date()} ~ {df['trade_date'].max().date()}")
    print()

    all_pair_results = []
    boot_results = []
    for K in [2, 3, 4, 5]:
        w = scan_windows(df, K)
        for mode in ["A", "B"]:
            for pair in ["main", "retail"]:
                r = pair_stats(w, mode, pair, "close")
                r["K"] = K
                all_pair_results.append(r)
            r = pair_stats(w, mode, "main", "retail")
            r["K"] = K
            all_pair_results.append(r)
        # 主关系的 bootstrap
        for mode in ["A", "B"]:
            for pair in ["main", "retail"]:
                br = bootstrap_same_rate(w, mode, pair, n_iter=2000, seed=42)
                br.update({"K": K, "mode": mode, "pair": f"{pair}~close"})
                boot_results.append(br)

    res = pd.DataFrame(all_pair_results)
    boot_df = pd.DataFrame(boot_results)

    # 导出
    out_dir = ROOT
    # K=3 的窗口表
    w3 = scan_windows(df, 3)
    w3.to_csv(out_dir / "windows_K3.csv", index=False)
    res.to_csv(out_dir / "summary_pairs.csv", index=False)
    boot_df.to_csv(out_dir / "bootstrap.csv", index=False)

    # 打印核心结果
    print("=" * 80)
    print("核心结果（K=3 为主，A/B 两种口径）")
    print("=" * 80)
    main_res = res[(res["K"] == 3) & (res["pair"].isin(["main~close", "retail~close", "main~retail"]))]
    cols = ["K", "mode", "pair", "n", "same_rate", "opp_rate",
            "long_y_n", "long_same_rate", "short_y_n", "short_same_rate",
            "binom_p_same", "chi2_p"]
    print(main_res[cols].to_string(index=False, float_format=lambda x: f"{x:.4f}"))
    print()

    print("=" * 80)
    print("K 敏感性（main~close）")
    print("=" * 80)
    mk = res[res["pair"] == "main~close"][["K", "mode", "n", "same_rate", "binom_p_same"]]
    print(mk.to_string(index=False, float_format=lambda x: f"{x:.4f}"))
    print()

    print("=" * 80)
    print("K 敏感性（retail~close）")
    print("=" * 80)
    rk = res[res["pair"] == "retail~close"][["K", "mode", "n", "same_rate", "binom_p_same"]]
    print(rk.to_string(index=False, float_format=lambda x: f"{x:.4f}"))
    print()

    print("=" * 80)
    print("Bootstrap（打乱 x 方向 2000 次，零假设下同向占比的均值/p(>=obs)）")
    print("=" * 80)
    print(boot_df.to_string(index=False, float_format=lambda x: f"{x:.4f}"))
    print()

    print("交付物：")
    print(f"  - {out_dir/'windows_K3.csv'}")
    print(f"  - {out_dir/'summary_pairs.csv'}")
    print(f"  - {out_dir/'bootstrap.csv'}")


if __name__ == "__main__":
    main()
