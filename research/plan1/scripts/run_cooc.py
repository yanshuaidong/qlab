"""
同期趋势共振验证：variety_id=1
按 plan1/docs/validation_plan_main_force_resonance.md 执行：仅「整窗首尾」差分，每滑窗一行。
"""
import sqlite3
from pathlib import Path
from math import comb

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
ARTIFACT_DATA = ROOT / "artifacts" / "data"
DB = ROOT.parent / "database" / "local_fut_pulse.sqlite"
VARIETY_ID = 1

SPANS = (2, 3, 4)
EXPORT_WINDOW_SPAN = 3
WINDOW_STRIDE = 1
BOOT_ITER = 2000
BOOT_SEED = 42


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
    diffs = dates.diff().dt.days.fillna(1).to_numpy()
    return diffs <= 7


def dir_net(delta: float) -> int:
    """首尾差分的方向：涨 +1，跌 −1，持平 0。"""
    if delta > 0:
        return 1
    if delta < 0:
        return -1
    return 0


def scan_windows(df: pd.DataFrame, S: int, stride: int = 1) -> pd.DataFrame:
    """定长 S 滑窗，每窗一行：delta = 末值 − 首值，dir 由 delta 符号决定。"""
    cont = mark_breakpoints(df["trade_date"])
    mf = df["main_force"].to_numpy()
    rt = df["retail"].to_numpy()
    cl = df["close"].to_numpy()
    n = len(df)
    rows = []
    for lo in range(0, n - S + 1, stride):
        hi = lo + S - 1
        if not np.all(cont[lo + 1 : hi + 1]):
            continue
        dm = float(mf[hi] - mf[lo])
        dr = float(rt[hi] - rt[lo])
        dc = float(cl[hi] - cl[lo])
        rows.append(
            {
                "t_start": df["trade_date"].iloc[lo].date(),
                "t_end": df["trade_date"].iloc[hi].date(),
                "S": S,
                "delta_main": dm,
                "delta_retail": dr,
                "delta_close": dc,
                "dir_main": dir_net(dm),
                "dir_retail": dir_net(dr),
                "dir_close": dir_net(dc),
            }
        )
    return pd.DataFrame(rows)


def binom_p_two_sided(k: int, n: int, p: float = 0.5) -> float:
    if n == 0:
        return float("nan")
    mean = n * p
    target = abs(k - mean)
    total = 0.0
    for i in range(n + 1):
        if abs(i - mean) >= target - 1e-12:
            total += comb(n, i) * (p**i) * ((1 - p) ** (n - i))
    return min(total, 1.0)


def chi2_p(table: np.ndarray) -> float:
    table = np.asarray(table, dtype=float)
    if table.sum() == 0:
        return float("nan")
    row = table.sum(axis=1, keepdims=True)
    col = table.sum(axis=0, keepdims=True)
    exp = row @ col / table.sum()
    if (exp <= 0).any():
        return float("nan")
    chi2 = ((table - exp) ** 2 / exp).sum()
    from math import erfc, sqrt
    return erfc(sqrt(chi2 / 2.0))


def pair_stats(w: pd.DataFrame, x_col: str, y_col: str = "close") -> dict:
    col_x = f"dir_{x_col}"
    col_y = f"dir_{y_col}"
    # 分母 = 全部有效窗口；同向包含 0==0（双方同步静止也是一种趋势一致）
    n = len(w)
    if n == 0:
        return {"pair": f"{x_col}~{y_col}", "n": 0}
    same = int((w[col_x] == w[col_y]).sum())          # +1==+1, -1==-1, 0==0 均计入
    opp  = int(((w[col_x] != 0) & (w[col_y] != 0) & (w[col_x] == -w[col_y])).sum())  # 严格反向（双方均非 0 且符号相反）
    pos_y = w[w[col_y] == 1]
    neg_y = w[w[col_y] == -1]
    same_pos = int((pos_y[col_x] == 1).sum())
    same_neg = int((neg_y[col_x] == -1).sum())
    a = int(((w[col_x] == 1) & (w[col_y] == 1)).sum())
    b = int(((w[col_x] == 1) & (w[col_y] == -1)).sum())
    c = int(((w[col_x] == -1) & (w[col_y] == 1)).sum())
    d = int(((w[col_x] == -1) & (w[col_y] == -1)).sum())
    return {
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


def bootstrap_same_rate(w: pd.DataFrame, x_col: str, n_iter: int, seed: int) -> dict:
    col_x = f"dir_{x_col}"
    col_y = "dir_close"
    # 分母与 pair_stats 保持一致：全部有效窗口
    if len(w) == 0:
        return {"boot_mean": float("nan"), "boot_p_ge_obs": float("nan"), "boot_std": float("nan")}
    x = w[col_x].to_numpy().copy()
    y = w[col_y].to_numpy()
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
    print(f"跨度 S∈{SPANS}，整窗首尾差分，滑窗 stride={WINDOW_STRIDE}")
    print()

    all_pair_results = []
    boot_results = []
    for S in SPANS:
        w = scan_windows(df, S, stride=WINDOW_STRIDE)
        for pair in ["main", "retail"]:
            r = pair_stats(w, pair, "close")
            r["S"] = S
            all_pair_results.append(r)
        r = pair_stats(w, "main", "retail")
        r["S"] = S
        all_pair_results.append(r)
        for pair in ["main", "retail"]:
            br = bootstrap_same_rate(w, pair, n_iter=BOOT_ITER, seed=BOOT_SEED)
            br.update({"S": S, "pair": f"{pair}~close"})
            boot_results.append(br)

    res = pd.DataFrame(all_pair_results)
    boot_df = pd.DataFrame(boot_results)

    out_dir = ARTIFACT_DATA
    out_dir.mkdir(parents=True, exist_ok=True)
    w_export = scan_windows(df, EXPORT_WINDOW_SPAN, stride=WINDOW_STRIDE)
    w_export.to_csv(out_dir / f"windows_S{EXPORT_WINDOW_SPAN}.csv", index=False)
    res.to_csv(out_dir / "summary_pairs.csv", index=False)
    boot_df.to_csv(out_dir / "bootstrap.csv", index=False)

    print("=" * 80)
    print(f"核心结果（S={EXPORT_WINDOW_SPAN}，整窗首尾）")
    print("=" * 80)
    sub = res[(res["S"] == EXPORT_WINDOW_SPAN) & (res["pair"].isin(["main~close", "retail~close", "main~retail"]))]
    cols = ["S", "pair", "n", "same_rate", "opp_rate",
            "long_y_n", "long_same_rate", "short_y_n", "short_same_rate",
            "binom_p_same", "chi2_p"]
    print(sub[cols].to_string(index=False, float_format=lambda x: f"{x:.4f}"))
    print()

    print("=" * 80)
    print("S 敏感性（main~close）")
    print("=" * 80)
    mk = res[res["pair"] == "main~close"][["S", "n", "same_rate", "binom_p_same"]]
    print(mk.sort_values(["S"]).to_string(index=False, float_format=lambda x: f"{x:.4f}"))
    print()

    print("交付物：")
    print(f"  - {out_dir / f'windows_S{EXPORT_WINDOW_SPAN}.csv'}")
    print(f"  - {out_dir / 'summary_pairs.csv'}")
    print(f"  - {out_dir / 'bootstrap.csv'}")


if __name__ == "__main__":
    main()
