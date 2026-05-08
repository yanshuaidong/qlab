"""
Plan 3: price-path synchronization after strict 5+3 futures signals.

Outputs signal-level features plus market, variety, sector, joint-group,
ablation, and simple fixed-effect regression summaries.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parent.parent
PROJECT_ROOT = ROOT.parents[2]
ARTIFACT_DATA = ROOT / "artifacts" / "data"
DB = PROJECT_ROOT / "storage" / "futures" / "futures_main_retail" / "data.sqlite"

HORIZONS = (3, 5, 7, 10)
MOMENTUM_LOOKBACK = 30
MIN_VARIETY_GROUP_N = 5

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
TARGET_VARIETIES = {name for name, _ in TARGET_POOL}

SECTOR_BY_VARIETY = {
    "铁矿石": "黑色系",
    "螺纹钢": "黑色系",
    "热卷": "黑色系",
    "锰硅": "黑色系",
    "焦煤": "黑色系",
    "沪铜": "有色金属",
    "沪铝": "有色金属",
    "沪锌": "有色金属",
    "沪铅": "有色金属",
    "沪锡": "有色金属",
    "工业硅": "有色金属",
    "多晶硅": "有色金属",
    "碳酸锂": "有色金属",
    "氧化铝": "有色金属",
    "沪镍": "有色金属",
    "沪金": "贵金属",
    "沪银": "贵金属",
    "豆一": "油脂油料",
    "豆二": "油脂油料",
    "豆油": "油脂油料",
    "豆粕": "油脂油料",
    "菜油": "油脂油料",
    "菜粕": "油脂油料",
    "棕榈油": "油脂油料",
    "玉米": "农产品",
    "鸡蛋": "农产品",
    "棉花": "农产品",
    "白糖": "农产品",
    "苹果": "农产品",
    "红枣": "农产品",
    "花生": "农产品",
    "生猪": "农产品",
    "PTA": "化工能化",
    "对二甲苯": "化工能化",
    "聚丙烯": "化工能化",
    "苯乙烯": "化工能化",
    "纯苯": "化工能化",
    "烧碱": "化工能化",
    "尿素": "化工能化",
    "橡胶": "化工能化",
    "丁二烯胶": "化工能化",
    "原木": "建材轻工",
    "纸浆": "建材轻工",
    "燃油": "化工能化",
    "低硫燃油": "化工能化",
    "甲醇": "化工能化",
    "PVC": "化工能化",
    "纯碱": "建材轻工",
    "玻璃": "建材轻工",
    "塑料": "化工能化",
    "乙二醇": "化工能化",
    "沥青": "化工能化",
    "LPG": "化工能化",
    "上证": "股指",
    "欧线集运": "航运",
}


def load_varieties(con: sqlite3.Connection) -> pd.DataFrame:
    return pd.read_sql_query("SELECT id, name, key FROM fut_variety ORDER BY id", con)


def load_df(con: sqlite3.Connection, variety_id: int) -> pd.DataFrame:
    strength = pd.read_sql_query(
        "SELECT trade_date, main_force, retail FROM fut_strength WHERE variety_id=? ORDER BY trade_date",
        con,
        params=(variety_id,),
    )
    close = pd.read_sql_query(
        "SELECT trade_date, close_price AS close FROM fut_daily_close WHERE variety_id=? ORDER BY trade_date",
        con,
        params=(variety_id,),
    )
    df = strength.merge(close, on="trade_date", how="inner").dropna()
    df["trade_date"] = pd.to_datetime(df["trade_date"])
    return df.sort_values("trade_date").reset_index(drop=True)


def mark_breakpoints(dates: pd.Series) -> pd.Series:
    return dates.diff().dt.days.fillna(1).le(7)


def compute_signals_strict7_tp3(df: pd.DataFrame) -> pd.DataFrame:
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
        bg1.lt(0)
        & bg2.lt(0)
        & bg3.lt(0)
        & bg4.lt(0)
        & bg5.lt(0)
        & bg5.le(bg1)
        & bg5.le(bg2)
        & bg5.le(bg3)
        & bg5.le(bg4)
    )
    short_bg = (
        bg1.gt(0)
        & bg2.gt(0)
        & bg3.gt(0)
        & bg4.gt(0)
        & bg5.gt(0)
        & bg5.ge(bg1)
        & bg5.ge(bg2)
        & bg5.ge(bg3)
        & bg5.ge(bg4)
    )

    out["long_signal"] = cont7 & long_bg & trigger_main_up & trigger_retail_down
    out["short_signal"] = cont7 & short_bg & trigger_main_down & trigger_retail_up
    out["m3"] = out["main_force"] - out["main_force"].shift(2)
    out["abs_m3"] = out["m3"].abs()
    out["exit_long_signal"] = cont3 & out["m3"].lt(0)
    out["exit_short_signal"] = cont3 & out["m3"].gt(0)

    scores: list[float] = []
    for i, current in enumerate(out["abs_m3"]):
        hist = out["abs_m3"].iloc[max(0, i - MOMENTUM_LOOKBACK) : i].dropna()
        if pd.isna(current) or len(hist) < MOMENTUM_LOOKBACK:
            scores.append(np.nan)
        else:
            scores.append(float(hist.le(current).sum() / MOMENTUM_LOOKBACK))
    out["main_score"] = scores
    return out


def sign_label(value: float) -> tuple[int, str]:
    if value > 0:
        return 1, "P3_follow"
    if value < 0:
        return -1, "P3_against"
    return 0, "P3_flat"


def zscore_by_variety(df: pd.DataFrame, col: str) -> pd.Series:
    grouped = df.groupby("variety_name")[col]
    mean = grouped.transform("mean")
    std = grouped.transform("std").replace(0, np.nan)
    return (df[col] - mean) / std


def build_signal_features(
    df: pd.DataFrame,
    variety_id: int,
    variety_name: str,
    variety_key: str,
) -> tuple[list[dict], dict | None]:
    data = compute_signals_strict7_tp3(df)
    rows: list[dict] = []
    excluded_reason: str | None = None

    if len(data) < 24:
        excluded_reason = "merged_rows_lt_24"

    close = data["close"].to_numpy(dtype=float)
    for i, row in data.iterrows():
        side = 1 if bool(row["long_signal"]) else -1 if bool(row["short_signal"]) else 0
        if side == 0:
            continue
        if i < 13 or i + max(HORIZONS) >= len(data):
            continue

        c_t13 = close[i - 13]
        c_t6 = close[i - 6]
        c_t2 = close[i - 2]
        c_t = close[i]

        p3_signed_delta = side * (c_t - c_t2)
        price_trend_3, p3_group = sign_label(p3_signed_delta)
        bg_sync_7 = int(side * (c_t2 - c_t6) < 0)
        turn_sync_7 = int(side * (c_t - c_t2) > 0)
        bg_sync_14 = int(side * (c_t2 - c_t13) < 0)
        turn_sync_14 = turn_sync_7

        feature = {
            "variety_id": variety_id,
            "variety_name": variety_name,
            "variety_key": variety_key,
            "sector": SECTOR_BY_VARIETY.get(variety_name, "其他"),
            "trade_date": row["trade_date"],
            "side": side,
            "side_label": "long" if side == 1 else "short",
            "close": c_t,
            "main_force": float(row["main_force"]),
            "retail": float(row["retail"]),
            "main_score": float(row["main_score"]) if pd.notna(row["main_score"]) else np.nan,
            "price_trend_3": price_trend_3,
            "price_trend_3_group": p3_group,
            "price_ret_3": side * (c_t / c_t2 - 1.0),
            "bg_sync_7": bg_sync_7,
            "turn_sync_7": turn_sync_7,
            "price_sync_7": 0.5 * bg_sync_7 + 0.5 * turn_sync_7,
            "bg_ret_7": -side * (c_t2 / c_t6 - 1.0),
            "turn_ret_7": side * (c_t / c_t2 - 1.0),
            "bg_sync_14": bg_sync_14,
            "turn_sync_14": turn_sync_14,
            "price_sync_14": 0.5 * bg_sync_14 + 0.5 * turn_sync_14,
            "bg_ret_14": -side * (c_t2 / c_t13 - 1.0),
            "turn_ret_14": side * (c_t / c_t2 - 1.0),
            "is_plan2_pool": variety_name in TARGET_VARIETIES,
        }

        for h in HORIZONS:
            future_close = close[i + h]
            future_ret = side * (future_close / c_t - 1.0)
            path_ret = side * (close[i + 1 : i + h + 1] / c_t - 1.0)
            future_trend = np.sign(side * (future_close - c_t))
            feature[f"future_ret_{h}"] = future_ret
            feature[f"future_win_{h}"] = int(future_ret > 0)
            feature[f"future_trend_{h}"] = int(future_trend)
            feature[f"trend_continue_{h}"] = int(price_trend_3 != 0 and price_trend_3 == future_trend)
            feature[f"mae_{h}"] = float(np.min(path_ret))
            feature[f"mfe_{h}"] = float(np.max(path_ret))

        rows.append(feature)

    if not rows and excluded_reason is None:
        excluded_reason = "no_signal_with_t13_to_t10"

    exclusion = None
    if excluded_reason:
        exclusion = {
            "variety_id": variety_id,
            "variety_name": variety_name,
            "variety_key": variety_key,
            "merged_rows": len(data),
            "reason": excluded_reason,
        }
    return rows, exclusion


def summarize_group(df: pd.DataFrame, group_cols: list[str], label: str) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame()
    rows: list[dict] = []
    for keys, sub in df.groupby(group_cols, dropna=False):
        if not isinstance(keys, tuple):
            keys = (keys,)
        base = {"summary_scope": label, "sample_count": int(len(sub))}
        base.update(dict(zip(group_cols, keys)))
        for h in HORIZONS:
            ret = sub[f"future_ret_{h}"]
            base[f"avg_ret_{h}"] = float(ret.mean())
            base[f"median_ret_{h}"] = float(ret.median())
            base[f"win_rate_{h}"] = float(sub[f"future_win_{h}"].mean())
            base[f"trend_continue_rate_{h}"] = float(sub[f"trend_continue_{h}"].mean())
            base[f"mae_avg_{h}"] = float(sub[f"mae_{h}"].mean())
            base[f"mfe_avg_{h}"] = float(sub[f"mfe_{h}"].mean())
            base[f"ret_q25_{h}"] = float(ret.quantile(0.25))
            base[f"ret_q75_{h}"] = float(ret.quantile(0.75))
        rows.append(base)
    return pd.DataFrame(rows).sort_values(group_cols).reset_index(drop=True)


def market_summary(df: pd.DataFrame) -> pd.DataFrame:
    base = {
        "variety_count": int(df["variety_name"].nunique()),
        "sector_count": int(df["sector"].nunique()),
        "signal_count": int(len(df)),
        "long_count": int((df["side"] == 1).sum()),
        "short_count": int((df["side"] == -1).sum()),
        "start_date": df["trade_date"].min(),
        "end_date": df["trade_date"].max(),
    }
    for h in HORIZONS:
        base[f"avg_ret_{h}"] = float(df[f"future_ret_{h}"].mean())
        base[f"median_ret_{h}"] = float(df[f"future_ret_{h}"].median())
        base[f"win_rate_{h}"] = float(df[f"future_win_{h}"].mean())
        base[f"mae_avg_{h}"] = float(df[f"mae_{h}"].mean())
        base[f"mfe_avg_{h}"] = float(df[f"mfe_{h}"].mean())
    return pd.DataFrame([base])


def build_joint_summary(df: pd.DataFrame) -> pd.DataFrame:
    joint = df.copy()
    joint["joint_p3_sync7"] = np.select(
        [
            (joint["price_trend_3_group"] == "P3_follow") & (joint["price_sync_7"] == 1.0),
            (joint["price_trend_3_group"] == "P3_follow") & (joint["price_sync_7"] < 1.0),
            (joint["price_trend_3_group"] == "P3_against") & (joint["bg_sync_7"] == 1),
            (joint["price_trend_3_group"] == "P3_against") & (joint["bg_sync_7"] == 0),
        ],
        [
            "P3_follow & sync7=1",
            "P3_follow & sync7<1",
            "P3_against & bg_sync_7=1",
            "P3_against & bg_sync_7=0",
        ],
        default="other",
    )
    joint["joint_sync7_sync14"] = np.select(
        [
            (joint["price_sync_7"] == 1.0) & (joint["price_sync_14"] == 1.0),
            (joint["price_sync_7"] == 1.0) & (joint["price_sync_14"] == 0.0),
        ],
        ["sync7=1 & sync14=1", "sync7=1 & sync14=0"],
        default="other",
    )
    return pd.concat(
        [
            summarize_group(joint, ["joint_p3_sync7"], "joint_p3_sync7"),
            summarize_group(joint, ["joint_sync7_sync14"], "joint_sync7_sync14"),
        ],
        ignore_index=True,
    )


def build_ablation_summary(df: pd.DataFrame, prefix: str = "all_market") -> pd.DataFrame:
    rules = {
        "baseline_all": pd.Series(True, index=df.index),
        "filter_p3_follow": df["price_trend_3_group"].eq("P3_follow"),
        "filter_sync7_full": df["price_sync_7"].eq(1.0),
        "filter_sync14_full": df["price_sync_14"].eq(1.0),
        "filter_p3_follow_bg7": df["price_trend_3_group"].eq("P3_follow") & df["bg_sync_7"].eq(1),
        "filter_p3_follow_bg14": df["price_trend_3_group"].eq("P3_follow") & df["bg_sync_14"].eq(1),
        "p3_against_only": df["price_trend_3_group"].eq("P3_against"),
    }
    baseline_n = len(df)
    rows = []
    for name, mask in rules.items():
        sub = df[mask]
        row = {
            "sample_scope": prefix,
            "version": name,
            "signal_count": int(len(sub)),
            "filtered_out_count": int(baseline_n - len(sub)),
            "variety_count": int(sub["variety_name"].nunique()) if len(sub) else 0,
        }
        for h in HORIZONS:
            row[f"win_rate_{h}"] = float(sub[f"future_win_{h}"].mean()) if len(sub) else np.nan
            row[f"avg_ret_{h}"] = float(sub[f"future_ret_{h}"].mean()) if len(sub) else np.nan
            row[f"median_ret_{h}"] = float(sub[f"future_ret_{h}"].median()) if len(sub) else np.nan
            row[f"mae_avg_{h}"] = float(sub[f"mae_{h}"].mean()) if len(sub) else np.nan
            row[f"mfe_avg_{h}"] = float(sub[f"mfe_{h}"].mean()) if len(sub) else np.nan
            if name != "baseline_all" and len(sub):
                baseline_by_variety = df.groupby("variety_name")[f"future_ret_{h}"].mean()
                rule_by_variety = sub.groupby("variety_name")[f"future_ret_{h}"].mean()
                aligned = pd.concat([baseline_by_variety, rule_by_variety], axis=1, keys=["base", "rule"]).dropna()
                row[f"improved_variety_count_{h}"] = int(aligned["rule"].gt(aligned["base"]).sum())
                row[f"worsened_variety_count_{h}"] = int(aligned["rule"].lt(aligned["base"]).sum())
            else:
                row[f"improved_variety_count_{h}"] = np.nan
                row[f"worsened_variety_count_{h}"] = np.nan
        rows.append(row)
    return pd.DataFrame(rows)


def build_variety_summary(df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for variety_name, sub in df.groupby("variety_name"):
        row = {
            "variety_name": variety_name,
            "sector": sub["sector"].iloc[0],
            "signal_count": int(len(sub)),
            "p3_follow_count": int(sub["price_trend_3_group"].eq("P3_follow").sum()),
            "p3_against_count": int(sub["price_trend_3_group"].eq("P3_against").sum()),
            "sync7_full_count": int(sub["price_sync_7"].eq(1.0).sum()),
            "sync14_full_count": int(sub["price_sync_14"].eq(1.0).sum()),
        }
        for h in HORIZONS:
            follow = sub[sub["price_trend_3_group"] == "P3_follow"]
            against = sub[sub["price_trend_3_group"] == "P3_against"]
            sync7_full = sub[sub["price_sync_7"] == 1.0]
            sync7_not_full = sub[sub["price_sync_7"] < 1.0]
            sync14_full = sub[sub["price_sync_14"] == 1.0]
            sync14_not_full = sub[sub["price_sync_14"] < 1.0]

            row[f"p3_follow_winrate_{h}"] = float(follow[f"future_win_{h}"].mean()) if len(follow) else np.nan
            row[f"p3_against_winrate_{h}"] = float(against[f"future_win_{h}"].mean()) if len(against) else np.nan
            row[f"p3_follow_avg_ret_{h}"] = float(follow[f"future_ret_{h}"].mean()) if len(follow) else np.nan
            row[f"p3_against_avg_ret_{h}"] = float(against[f"future_ret_{h}"].mean()) if len(against) else np.nan
            row[f"sync7_full_avg_ret_{h}"] = float(sync7_full[f"future_ret_{h}"].mean()) if len(sync7_full) else np.nan
            row[f"sync7_edge_{h}"] = (
                float(sync7_full[f"future_ret_{h}"].mean() - sync7_not_full[f"future_ret_{h}"].mean())
                if len(sync7_full) and len(sync7_not_full)
                else np.nan
            )
            row[f"sync14_edge_{h}"] = (
                float(sync14_full[f"future_ret_{h}"].mean() - sync14_not_full[f"future_ret_{h}"].mean())
                if len(sync14_full) and len(sync14_not_full)
                else np.nan
            )

        if row["signal_count"] < 12:
            row["suggested_use"] = "样本不足"
        else:
            edges = [row.get(f"sync7_edge_{h}", np.nan) for h in (5, 7)]
            p3_edges = [
                row.get(f"p3_follow_avg_ret_{h}", np.nan) - row.get(f"p3_against_avg_ret_{h}", np.nan)
                for h in (5, 7)
            ]
            if np.nanmean(edges) > 0.006 and row["sync7_full_count"] >= MIN_VARIETY_GROUP_N:
                row["suggested_use"] = "硬过滤"
            elif np.nanmean(edges) > 0.003 and row["sync7_full_count"] >= MIN_VARIETY_GROUP_N:
                row["suggested_use"] = "排序加分"
            elif np.nanmean(p3_edges) < -0.003 and row["p3_against_count"] >= MIN_VARIETY_GROUP_N:
                row["suggested_use"] = "反向观察"
            else:
                row["suggested_use"] = "不使用"
        rows.append(row)
    return pd.DataFrame(rows).sort_values(["sector", "variety_name"]).reset_index(drop=True)


def build_regression_summary(df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    base_cols = ["price_ret_3", "price_sync_7", "price_sync_14", "main_score"]
    data = df.dropna(subset=base_cols).copy()
    if data.empty:
        return pd.DataFrame()
    dummies = pd.get_dummies(data["variety_name"], prefix="variety", drop_first=True, dtype=float)
    x = pd.concat([pd.Series(1.0, index=data.index, name="const"), data[base_cols], dummies], axis=1)
    x_mat = x.to_numpy(dtype=float)
    for h in HORIZONS:
        y = data[f"future_ret_{h}"].to_numpy(dtype=float)
        beta, *_ = np.linalg.lstsq(x_mat, y, rcond=None)
        pred = x_mat @ beta
        resid = y - pred
        dof = max(len(y) - x_mat.shape[1], 1)
        sigma2 = float((resid @ resid) / dof)
        xtx_inv = np.linalg.pinv(x_mat.T @ x_mat)
        se = np.sqrt(np.diag(xtx_inv) * sigma2)
        y_var = float(((y - y.mean()) @ (y - y.mean())))
        r2 = 1.0 - float((resid @ resid) / y_var) if y_var > 0 else np.nan
        coef = pd.DataFrame({"term": x.columns, "coef": beta, "std_err": se})
        coef["t_stat"] = coef["coef"] / coef["std_err"].replace(0, np.nan)
        for _, r in coef[coef["term"].isin(base_cols)].iterrows():
            rows.append(
                {
                    "horizon": h,
                    "term": r["term"],
                    "coef": float(r["coef"]),
                    "std_err": float(r["std_err"]),
                    "t_stat": float(r["t_stat"]),
                    "n": int(len(y)),
                    "r_squared": r2,
                    "fixed_effect": "C(variety)",
                }
            )
    return pd.DataFrame(rows)


def main() -> None:
    if not DB.exists():
        raise FileNotFoundError(DB)

    con = sqlite3.connect(DB)
    varieties = load_varieties(con)

    signal_rows: list[dict] = []
    exclusions: list[dict] = []
    for _, variety in varieties.iterrows():
        df = load_df(con, int(variety["id"]))
        rows, exclusion = build_signal_features(
            df,
            int(variety["id"]),
            str(variety["name"]),
            str(variety["key"]),
        )
        signal_rows.extend(rows)
        if exclusion:
            exclusions.append(exclusion)
        print(f"{variety['id']:02d} {variety['name']}: merged={len(df)}, signals={len(rows)}")
    con.close()

    features = pd.DataFrame(signal_rows)
    if features.empty:
        raise RuntimeError("No valid signals found.")

    features["price_sync_strength_7"] = zscore_by_variety(features, "bg_ret_7") + zscore_by_variety(
        features, "turn_ret_7"
    )
    features["price_sync_strength_14"] = zscore_by_variety(features, "bg_ret_14") + zscore_by_variety(
        features, "turn_ret_14"
    )

    overall = market_summary(features)
    group_by_p3 = pd.concat(
        [
            summarize_group(features, ["price_trend_3_group"], "market"),
            summarize_group(features, ["variety_name", "price_trend_3_group"], "variety"),
            summarize_group(features, ["sector", "price_trend_3_group"], "sector"),
        ],
        ignore_index=True,
    )
    group_by_sync7 = pd.concat(
        [
            summarize_group(features, ["price_sync_7"], "market"),
            summarize_group(features, ["variety_name", "price_sync_7"], "variety"),
            summarize_group(features, ["sector", "price_sync_7"], "sector"),
        ],
        ignore_index=True,
    )
    group_by_sync14 = pd.concat(
        [
            summarize_group(features, ["price_sync_14"], "market"),
            summarize_group(features, ["variety_name", "price_sync_14"], "variety"),
            summarize_group(features, ["sector", "price_sync_14"], "sector"),
        ],
        ignore_index=True,
    )
    joint = build_joint_summary(features)
    variety_summary = build_variety_summary(features)
    sector_summary = summarize_group(features, ["sector"], "sector")
    all_ablation = build_ablation_summary(features, "all_market")
    plan2_ablation = build_ablation_summary(features[features["is_plan2_pool"]].copy(), "plan2_12_pool")
    regression = build_regression_summary(features)
    exclusions_df = pd.DataFrame(exclusions)

    ARTIFACT_DATA.mkdir(parents=True, exist_ok=True)
    features.to_csv(ARTIFACT_DATA / "signal_price_sync_features.csv", index=False)
    overall.to_csv(ARTIFACT_DATA / "market_summary_overall.csv", index=False)
    group_by_p3.to_csv(ARTIFACT_DATA / "group_summary_by_p3.csv", index=False)
    group_by_sync7.to_csv(ARTIFACT_DATA / "group_summary_by_sync7.csv", index=False)
    group_by_sync14.to_csv(ARTIFACT_DATA / "group_summary_by_sync14.csv", index=False)
    joint.to_csv(ARTIFACT_DATA / "group_summary_joint.csv", index=False)
    variety_summary.to_csv(ARTIFACT_DATA / "variety_price_sync_summary.csv", index=False)
    sector_summary.to_csv(ARTIFACT_DATA / "sector_price_sync_summary.csv", index=False)
    all_ablation.to_csv(ARTIFACT_DATA / "signal_level_ablation_summary.csv", index=False)
    plan2_ablation.to_csv(ARTIFACT_DATA / "plan2_pool_ablation_summary.csv", index=False)
    regression.to_csv(ARTIFACT_DATA / "regression_summary.csv", index=False)
    exclusions_df.to_csv(ARTIFACT_DATA / "excluded_varieties.csv", index=False)

    print()
    print("=" * 88)
    print("Plan 3 price-sync analysis complete")
    print("=" * 88)
    print(overall.to_string(index=False))
    print()
    print("Key artifacts:")
    for name in [
        "signal_price_sync_features.csv",
        "market_summary_overall.csv",
        "group_summary_by_p3.csv",
        "group_summary_by_sync7.csv",
        "group_summary_by_sync14.csv",
        "group_summary_joint.csv",
        "variety_price_sync_summary.csv",
        "sector_price_sync_summary.csv",
        "signal_level_ablation_summary.csv",
        "plan2_pool_ablation_summary.csv",
        "regression_summary.csv",
        "excluded_varieties.csv",
    ]:
        print(f"  - {ARTIFACT_DATA / name}")


if __name__ == "__main__":
    main()
