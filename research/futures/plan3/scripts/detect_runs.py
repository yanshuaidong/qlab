"""
Plan 3 — 连续单调区间识别
对每个品种，识别 main_force z-score 的连续单增/单跌区间（run），
计算每个 run 的 cumulative_delta 和同期 price_change%。

输出：artifacts/data/runs_all.csv
"""
import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
ARTIFACT_DATA = ROOT / "artifacts" / "data"
DB = ROOT.parent.parent.parent / "storage" / "futures" / "futures_main_retail" / "data.sqlite"

MIN_RUN_DURATION = 3  # duration <= 2 的 run 视为噪声，过滤掉


def load_varieties(con: sqlite3.Connection) -> pd.DataFrame:
    return pd.read_sql_query("SELECT id, name, key FROM fut_variety ORDER BY id", con)


def load_df(con: sqlite3.Connection, variety_id: int) -> pd.DataFrame:
    s = pd.read_sql_query(
        "SELECT trade_date, main_force FROM fut_strength WHERE variety_id=? ORDER BY trade_date",
        con, params=(variety_id,),
    )
    c = pd.read_sql_query(
        "SELECT trade_date, close_price AS close FROM fut_daily_close WHERE variety_id=? ORDER BY trade_date",
        con, params=(variety_id,),
    )
    df = s.merge(c, on="trade_date", how="inner").dropna()
    df["trade_date"] = pd.to_datetime(df["trade_date"])
    return df.sort_values("trade_date").reset_index(drop=True)


def zscore(series: pd.Series) -> np.ndarray:
    """品种内 z-score 标准化"""
    arr = series.to_numpy(dtype=float)
    mu, sigma = np.nanmean(arr), np.nanstd(arr)
    if sigma == 0 or np.isnan(sigma):
        return np.zeros_like(arr)
    return (arr - mu) / sigma


def detect_runs(z_score: np.ndarray, close: np.ndarray, dates: pd.DatetimeIndex) -> list[dict]:
    """
    基于 diff2 = z_score[t] - z_score[t-2] 识别连续单调区间。
    返回每个 run 的详细信息。
    """
    n = len(z_score)
    if n < 3:
        return []

    # diff2[t] = z_score[t] - z_score[t-2]，前 2 天无值
    diff2 = np.full(n, np.nan, dtype=float)
    diff2[2:] = z_score[2:] - z_score[:-2]

    # 符号：+1（增）、-1（减）、0（持平）
    sign = np.zeros(n, dtype=int)
    sign[diff2 > 0] = 1
    sign[diff2 < 0] = -1

    runs = []
    i = 2  # diff2 从索引 2 开始有效
    while i < n:
        if sign[i] == 0:
            i += 1
            continue

        # 寻找连续相同符号的 run
        start_idx = i
        cur_sign = sign[i]
        while i < n and sign[i] == cur_sign:
            i += 1
        end_idx = i - 1  # 最后一个相同符号的索引

        duration = end_idx - start_idx + 1
        if duration < MIN_RUN_DURATION:
            continue

        # run 对应的实际数据范围：第一个 diff2 的 t-2 到最后一个 diff2 的 t
        data_start = start_idx - 2
        data_end = end_idx

        cumulative_delta = float(z_score[data_end] - z_score[data_start])
        price_change_pct = float(
            (close[data_end] - close[data_start]) / close[data_start]
        )

        runs.append({
            "start_date": dates[data_start],
            "end_date": dates[data_end],
            "duration": duration,
            "direction": int(cur_sign),
            "start_z": float(z_score[data_start]),
            "end_z": float(z_score[data_end]),
            "cumulative_delta": cumulative_delta,
            "start_price": float(close[data_start]),
            "end_price": float(close[data_end]),
            "price_change_pct": price_change_pct,
        })

    return runs


def main():
    con = sqlite3.connect(DB)
    varieties = load_varieties(con)
    print(f"共 {len(varieties)} 个品种，开始识别 runs…")

    all_runs = []

    for _, vrow in varieties.iterrows():
        vid = int(vrow["id"])
        vname = vrow["name"]
        df = load_df(con, vid)
        if len(df) < 3:
            print(f"  [{vid:02d}] {vname}: 数据不足，跳过")
            continue

        df["z_score"] = zscore(df["main_force"])
        runs = detect_runs(
            df["z_score"].to_numpy(),
            df["close"].to_numpy(),
            pd.DatetimeIndex(df["trade_date"]),
        )

        for run in runs:
            run["variety_id"] = vid
            run["variety_name"] = vname
            all_runs.append(run)

        print(f"  [{vid:02d}] {vname}: 识别到 {len(runs)} 个 runs")

    con.close()

    if not all_runs:
        print("未识别到任何 runs")
        return

    runs_df = pd.DataFrame(all_runs)
    cols = [
        "variety_id", "variety_name", "start_date", "end_date",
        "duration", "direction", "start_z", "end_z", "cumulative_delta",
        "start_price", "end_price", "price_change_pct",
    ]
    runs_df = runs_df[cols]

    ARTIFACT_DATA.mkdir(parents=True, exist_ok=True)
    runs_df.to_csv(ARTIFACT_DATA / "runs_all.csv", index=False)

    print()
    print("=" * 60)
    print("runs_all.csv 汇总")
    print("=" * 60)
    print(f"总 runs 数: {len(runs_df)}")
    print(f"做多 runs (+1): {len(runs_df[runs_df['direction'] == 1])}")
    print(f"做空 runs (-1): {len(runs_df[runs_df['direction'] == -1])}")
    print(f"平均 duration: {runs_df['duration'].mean():.2f} 天")
    print(f"duration 分布: min={runs_df['duration'].min()}, max={runs_df['duration'].max()}")
    print(f"cumulative_delta 范围: [{runs_df['cumulative_delta'].min():.3f}, {runs_df['cumulative_delta'].max():.3f}]")
    print(f"price_change% 范围: [{runs_df['price_change_pct'].min():.4f}, {runs_df['price_change_pct'].max():.4f}]")
    print()
    print(f"输出文件: {ARTIFACT_DATA / 'runs_all.csv'}")


if __name__ == "__main__":
    main()
