"""
全品种同期趋势共振验证
逻辑与 run_cooc.py 完全一致，循环遍历所有 variety_id。
输出：
  artifacts/data/all_varieties_summary.csv   每个品种×S×配对 的汇总
  artifacts/data/all_varieties_bootstrap.csv 每个品种×S 的 bootstrap 摘要
"""
import sqlite3
from pathlib import Path
from math import comb

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
ARTIFACT_DATA = ROOT / "artifacts" / "data"
DB = ROOT.parent / "database" / "local_fut_pulse.sqlite"

SPANS = (2, 3, 4)
WINDOW_STRIDE = 1
BOOT_ITER = 2000
BOOT_SEED = 42


def load_varieties(con: sqlite3.Connection) -> pd.DataFrame:
    return pd.read_sql_query("SELECT id, name, key FROM fut_variety ORDER BY id", con)


def load_df(con: sqlite3.Connection, variety_id: int) -> pd.DataFrame:
    s = pd.read_sql_query(
        "SELECT trade_date, main_force, retail FROM fut_strength WHERE variety_id=? ORDER BY trade_date",
        con, params=(variety_id,),
    )
    c = pd.read_sql_query(
        "SELECT trade_date, close_price AS close FROM fut_daily_close WHERE variety_id=? ORDER BY trade_date",
        con, params=(variety_id,),
    )
    df = s.merge(c, on="trade_date", how="inner").dropna()
    df["trade_date"] = pd.to_datetime(df["trade_date"])
    return df.sort_values("trade_date").reset_index(drop=True)


def mark_breakpoints(dates: pd.Series) -> np.ndarray:
    diffs = dates.diff().dt.days.fillna(1).to_numpy()
    return diffs <= 7


def dir_net(delta: float) -> int:
    if delta > 0:
        return 1
    if delta < 0:
        return -1
    return 0


def scan_windows(df: pd.DataFrame, S: int, stride: int = 1) -> pd.DataFrame:
    cont = mark_breakpoints(df["trade_date"])
    mf = df["main_force"].to_numpy()
    rt = df["retail"].to_numpy()
    cl = df["close"].to_numpy()
    n = len(df)
    rows = []
    for lo in range(0, n - S + 1, stride):
        hi = lo + S - 1
        if not np.all(cont[lo + 1: hi + 1]):
            continue
        dm = float(mf[hi] - mf[lo])
        dr = float(rt[hi] - rt[lo])
        dc = float(cl[hi] - cl[lo])
        rows.append({
            "delta_main": dm, "delta_retail": dr, "delta_close": dc,
            "dir_main": dir_net(dm), "dir_retail": dir_net(dr), "dir_close": dir_net(dc),
        })
    return pd.DataFrame(rows)


def binom_p_two_sided(k: int, n: int, p: float = 0.5) -> float:
    if n == 0:
        return float("nan")
    mean = n * p
    target = abs(k - mean)
    total = 0.0
    for i in range(n + 1):
        if abs(i - mean) >= target - 1e-12:
            total += comb(n, i) * (p ** i) * ((1 - p) ** (n - i))
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
    n = len(w)
    if n == 0:
        return {"pair": f"{x_col}~{y_col}", "n": 0}
    same = int((w[col_x] == w[col_y]).sum())
    opp = int(((w[col_x] != 0) & (w[col_y] != 0) & (w[col_x] == -w[col_y])).sum())
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
    }


def bootstrap_same_rate(w: pd.DataFrame, x_col: str, n_iter: int, seed: int) -> dict:
    col_x = f"dir_{x_col}"
    col_y = "dir_close"
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
    con = sqlite3.connect(DB)
    varieties = load_varieties(con)
    print(f"共 {len(varieties)} 个品种，开始计算…")

    all_pair_rows = []
    all_boot_rows = []

    for _, vrow in varieties.iterrows():
        vid = int(vrow["id"])
        vname = vrow["name"]
        df = load_df(con, vid)
        if len(df) < 4:
            print(f"  [{vid:02d}] {vname}: 数据不足，跳过")
            continue

        for S in SPANS:
            w = scan_windows(df, S, stride=WINDOW_STRIDE)
            for pair in ["main", "retail"]:
                r = pair_stats(w, pair, "close")
                r.update({"variety_id": vid, "variety_name": vname, "S": S})
                all_pair_rows.append(r)
            r = pair_stats(w, "main", "retail")
            r.update({"variety_id": vid, "variety_name": vname, "S": S})
            all_pair_rows.append(r)

            for pair in ["main", "retail"]:
                br = bootstrap_same_rate(w, pair, n_iter=BOOT_ITER, seed=BOOT_SEED)
                br.update({"variety_id": vid, "variety_name": vname, "S": S, "pair": f"{pair}~close"})
                all_boot_rows.append(br)

        print(f"  [{vid:02d}] {vname} ✓")

    con.close()

    summary_df = pd.DataFrame(all_pair_rows)
    boot_df = pd.DataFrame(all_boot_rows)

    ARTIFACT_DATA.mkdir(parents=True, exist_ok=True)
    summary_df.to_csv(ARTIFACT_DATA / "all_varieties_summary.csv", index=False)
    boot_df.to_csv(ARTIFACT_DATA / "all_varieties_bootstrap.csv", index=False)

    # ── 打印 S=3 main~close 汇总 ──────────────────────────────────────────────
    mc3 = summary_df[(summary_df["S"] == 3) & (summary_df["pair"] == "main~close")].copy()
    mc3 = mc3.sort_values("same_rate", ascending=False)

    print()
    print("=" * 90)
    print("全品种汇总（S=3，main~close）")
    print("=" * 90)
    cols = ["variety_id", "variety_name", "n", "same_rate", "opp_rate",
            "long_same_rate", "short_same_rate", "binom_p_same"]
    print(mc3[cols].to_string(index=False, float_format=lambda x: f"{x:.4f}"))

    # ── 通过门槛统计 ──────────────────────────────────────────────────────────
    passed = mc3[(mc3["same_rate"] >= 0.55) & (mc3["binom_p_same"] < 0.05)]
    print()
    print(f"满足 same_rate≥55% 且 binom_p<0.05 的品种：{len(passed)} / {len(mc3)}")

    # ── S 敏感性：各 S 下全品种中位同向率 ────────────────────────────────────
    print()
    print("=" * 60)
    print("S 敏感性（main~close，全品种中位同向率）")
    print("=" * 60)
    for S in SPANS:
        sub = summary_df[(summary_df["S"] == S) & (summary_df["pair"] == "main~close")]
        print(f"  S={S}  中位 same_rate={sub['same_rate'].median():.4f}  "
              f"通过[≥55%,p<0.05]={((sub['same_rate']>=0.55)&(sub['binom_p_same']<0.05)).sum()}/{len(sub)}")

    print()
    print("交付物：")
    print(f"  - {ARTIFACT_DATA / 'all_varieties_summary.csv'}")
    print(f"  - {ARTIFACT_DATA / 'all_varieties_bootstrap.csv'}")


if __name__ == "__main__":
    main()
