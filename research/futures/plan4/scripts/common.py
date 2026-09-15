"""
Plan 4 公共模块：数据库、品种池、严格7日信号、Plan1/3 特征、LightGBM 样本构建。
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
ARTIFACT_DATA = ROOT / "artifacts" / "data"
ARTIFACT_MODELS = ROOT / "artifacts" / "models"
DOCS_DIR = ROOT / "docs"

REPO_ROOT = ROOT.parents[2]
DB_CANDIDATES = [
    REPO_ROOT / "storage" / "futures" / "futures_main_retail" / "data.sqlite",
    ROOT.parent / "database" / "local_fut_pulse.sqlite",
    ROOT.parent / "plan2" / "database" / "local_fut_pulse.sqlite",
]

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
TRAIN_RATIO = 0.70
MIN_PROB_DEFAULT = 0.52

FEATURE_COLUMNS = [
    "main_force",
    "retail",
    "m3",
    "main_score",
    "z_main",
    "diff2",
    "run_streak",
    "cum_z_5",
    "cum_z_10",
    "res_main_close_3",
    "res_retail_close_opp_3",
    "res_main_retail_opp_3",
    "main_minus_retail",
    "side",
]


def resolve_db() -> Path:
    for path in DB_CANDIDATES:
        if path.is_file():
            return path
    raise FileNotFoundError(
        "未找到期货 SQLite，已尝试：\n" + "\n".join(str(p) for p in DB_CANDIDATES)
    )


def load_varieties(con: sqlite3.Connection) -> pd.DataFrame:
    return pd.read_sql_query("SELECT id, name, key FROM fut_variety ORDER BY id", con)


def load_df(con: sqlite3.Connection, variety_id: int) -> pd.DataFrame:
    strength = pd.read_sql_query(
        (
            "SELECT trade_date, main_force, retail "
            "FROM fut_strength WHERE variety_id=? ORDER BY trade_date"
        ),
        con,
        params=(variety_id,),
    )
    close = pd.read_sql_query(
        (
            "SELECT trade_date, close_price AS close "
            "FROM fut_daily_close WHERE variety_id=? ORDER BY trade_date"
        ),
        con,
        params=(variety_id,),
    )
    df = strength.merge(close, on="trade_date", how="inner").dropna()
    df["trade_date"] = pd.to_datetime(df["trade_date"])
    return df.sort_values("trade_date").reset_index(drop=True)


def mark_breakpoints(dates: pd.Series) -> pd.Series:
    diffs = dates.diff().dt.days.fillna(1)
    return diffs.le(7)


def trade_return(side: int, entry_price: float, exit_price: float) -> float:
    return float(side * (exit_price - entry_price) / entry_price)


def zscore_series(series: pd.Series) -> pd.Series:
    arr = series.to_numpy(dtype=float)
    mu, sigma = np.nanmean(arr), np.nanstd(arr)
    if sigma == 0 or np.isnan(sigma):
        return pd.Series(np.zeros(len(arr)), index=series.index)
    return pd.Series((arr - mu) / sigma, index=series.index)


def _dir_net(delta: float) -> int:
    if delta > 0:
        return 1
    if delta < 0:
        return -1
    return 0


def rolling_resonance_features(df: pd.DataFrame, window: int = 3) -> pd.DataFrame:
    out = df.copy()
    main_d = out["main_force"].diff()
    retail_d = out["retail"].diff()
    close_d = out["close"].diff()

    main_dir = main_d.map(_dir_net)
    retail_dir = retail_d.map(_dir_net)
    close_dir = close_d.map(_dir_net)

    same_main_close = (main_dir == close_dir).astype(float)
    opp_retail_close = ((retail_dir != 0) & (close_dir != 0) & (retail_dir == -close_dir)).astype(float)
    opp_main_retail = ((main_dir != 0) & (retail_dir != 0) & (main_dir == -retail_dir)).astype(float)

    out["res_main_close_3"] = same_main_close.rolling(window, min_periods=window).mean()
    out["res_retail_close_opp_3"] = opp_retail_close.rolling(window, min_periods=window).mean()
    out["res_main_retail_opp_3"] = opp_main_retail.rolling(window, min_periods=window).mean()
    return out


def run_streak_features(z_main: pd.Series) -> tuple[pd.Series, pd.Series]:
    diff2 = z_main - z_main.shift(2)
    sign = pd.Series(0, index=z_main.index, dtype=int)
    sign[diff2 > 0] = 1
    sign[diff2 < 0] = -1

    streak = []
    cur = 0
    prev = 0
    for s in sign:
        if s == 0:
            cur = 0
        elif s == prev:
            cur += 1
        else:
            cur = 1
            prev = s
        streak.append(cur)
    return diff2, pd.Series(streak, index=z_main.index)


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
    out["tp3_delta_main"] = out["m3"]
    out["exit_long_signal"] = cont3 & out["tp3_delta_main"].lt(0)
    out["exit_short_signal"] = cont3 & out["tp3_delta_main"].gt(0)

    scores: list[float] = []
    abs_m3 = out["abs_m3"]
    for i in range(len(out)):
        current = abs_m3.iloc[i]
        hist = abs_m3.iloc[max(0, i - MOMENTUM_LOOKBACK) : i].dropna()
        if pd.isna(current) or len(hist) < MOMENTUM_LOOKBACK:
            scores.append(np.nan)
            continue
        scores.append(float(hist.le(current).sum() / MOMENTUM_LOOKBACK))
    out["main_score"] = scores

    out["z_main"] = zscore_series(out["main_force"])
    diff2, out["run_streak"] = run_streak_features(out["z_main"])
    out["diff2"] = diff2
    out["cum_z_5"] = out["z_main"] - out["z_main"].shift(5)
    out["cum_z_10"] = out["z_main"] - out["z_main"].shift(10)
    out["main_minus_retail"] = out["main_force"] - out["retail"]
    out["close_return"] = out["close"].pct_change().fillna(0.0)

    out = rolling_resonance_features(out, window=3)
    return out


def simulate_trade_outcome(data: pd.DataFrame, entry_idx: int, side: int) -> dict:
    entry_row = data.iloc[entry_idx]
    entry_price = float(entry_row["close"])
    for j in range(entry_idx + 1, len(data)):
        row = data.iloc[j]
        if side == 1 and bool(row["exit_long_signal"]):
            exit_price = float(row["close"])
            return {
                "exit_idx": j,
                "exit_date": row["trade_date"],
                "pnl_ratio": trade_return(1, entry_price, exit_price),
                "holding_days": j - entry_idx,
                "exit_reason": "tp3_main_turn_down",
            }
        if side == -1 and bool(row["exit_short_signal"]):
            exit_price = float(row["close"])
            return {
                "exit_idx": j,
                "exit_date": row["trade_date"],
                "pnl_ratio": trade_return(-1, entry_price, exit_price),
                "holding_days": j - entry_idx,
                "exit_reason": "tp3_main_turn_up",
            }
    last = data.iloc[-1]
    exit_price = float(last["close"])
    return {
        "exit_idx": len(data) - 1,
        "exit_date": last["trade_date"],
        "pnl_ratio": trade_return(side, entry_price, exit_price),
        "holding_days": len(data) - 1 - entry_idx,
        "exit_reason": "final_close",
    }


def build_entry_samples(
    data: pd.DataFrame,
    variety_name: str,
) -> pd.DataFrame:
    rows: list[dict] = []
    i = 0
    n = len(data)
    while i < n:
        row = data.iloc[i]
        side = 0
        if bool(row["long_signal"]):
            side = 1
        elif bool(row["short_signal"]):
            side = -1
        if side == 0:
            i += 1
            continue

        outcome = simulate_trade_outcome(data, i, side)
        feat = {col: row[col] for col in FEATURE_COLUMNS if col in row.index}
        feat["side"] = float(side)
        rows.append(
            {
                "variety_name": variety_name,
                "sector": SECTOR_BY_VARIETY[variety_name],
                "trade_date": row["trade_date"],
                "side_label": "long" if side == 1 else "short",
                "entry_idx": i,
                "y": int(outcome["pnl_ratio"] > 0),
                "pnl_ratio": outcome["pnl_ratio"],
                "holding_days": outcome["holding_days"],
                "exit_reason": outcome["exit_reason"],
                **feat,
            }
        )
        i = int(outcome["exit_idx"]) + 1

    return pd.DataFrame(rows)


def load_signal_map() -> tuple[dict[str, pd.DataFrame], pd.Timestamp]:
    db = resolve_db()
    con = sqlite3.connect(db)
    varieties = load_varieties(con)
    name_to_id = dict(zip(varieties["name"], varieties["id"]))

    signal_map: dict[str, pd.DataFrame] = {}
    for name in TARGET_VARIETIES:
        vid = int(name_to_id[name])
        raw = load_df(con, vid)
        signal_map[name] = compute_signals_strict7_tp3(raw)

    con.close()
    dates = pd.DatetimeIndex(signal_map[TARGET_VARIETIES[0]]["trade_date"])
    split_idx = int(len(dates) * TRAIN_RATIO)
    train_end = dates[split_idx - 1] if split_idx > 0 else dates[0]
    return signal_map, train_end


def build_all_entry_samples(signal_map: dict[str, pd.DataFrame]) -> pd.DataFrame:
    frames = [build_entry_samples(signal_map[name], name) for name in TARGET_VARIETIES]
    samples = pd.concat(frames, ignore_index=True)
    samples["trade_date"] = pd.to_datetime(samples["trade_date"])
    return samples.sort_values(["trade_date", "variety_name"]).reset_index(drop=True)


@dataclass(frozen=True)
class PortfolioConfig:
    strategy_name: str
    max_slots: int
    weight_slots: int
    sector_mutex: bool
    use_lgb: bool
    min_prob: float
    train_end: pd.Timestamp | None = None


def save_json(path: Path, obj: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
