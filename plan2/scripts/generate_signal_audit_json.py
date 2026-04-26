from __future__ import annotations

import argparse
import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT.parent / "database" / "local_fut_pulse.sqlite"
DEFAULT_OUTPUT = ROOT / "artifacts" / "data" / "signal_audit_full.json"
MOMENTUM_LOOKBACK = 30

POOL_A: list[tuple[str, str]] = [
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
POOL_A_NAMES = [name for name, _ in POOL_A]
POOL_A_SECTOR_BY_NAME = dict(POOL_A)
ALL_SECTOR_BY_NAME = {
    "铁矿石": "黑色系",
    "螺纹钢": "黑色系",
    "热卷": "黑色系",
    "锰硅": "黑色系",
    "沪铜": "有色金属",
    "沪铝": "有色金属",
    "沪锌": "有色金属",
    "沪铅": "有色金属",
    "沪锡": "有色金属",
    "工业硅": "有色金属",
    "多晶硅": "有色金属",
    "碳酸锂": "有色金属",
    "沪金": "贵金属",
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
    "PTA": "化工能化",
    "对二甲苯": "化工能化",
    "聚丙烯": "化工能化",
    "苯乙烯": "化工能化",
    "纯苯": "化工能化",
    "烧碱": "化工能化",
    "尿素": "化工能化",
    "橡胶": "化工能化",
    "丁二烯胶": "化工能化",
    "原木": "轻工建材",
    "纸浆": "轻工建材",
    "上证": "股指",
    "氧化铝": "有色金属",
    "沪镍": "有色金属",
    "沪银": "贵金属",
    "生猪": "农产品",
    "燃油": "化工能化",
    "低硫燃油": "化工能化",
    "甲醇": "化工能化",
    "PVC": "化工能化",
    "纯碱": "化工能化",
    "玻璃": "轻工建材",
    "塑料": "化工能化",
    "乙二醇": "化工能化",
    "沥青": "化工能化",
    "LPG": "化工能化",
    "焦煤": "黑色系",
    "欧线集运": "航运",
}


@dataclass(frozen=True)
class VarietyMeta:
    variety_id: int
    name: str
    key: str
    sector: str
    in_pool_a: bool


def to_float(value: object) -> float | None:
    if value is None or pd.isna(value):
        return None
    return float(value)


def to_int(value: object) -> int | None:
    if value is None or pd.isna(value):
        return None
    return int(value)


def mark_breakpoints(dates: pd.Series) -> pd.Series:
    diffs = dates.diff().dt.days.fillna(1)
    return diffs.le(7)


def trade_return(side: int, entry_price: float, exit_price: float) -> float:
    return float(side * (exit_price - entry_price) / entry_price)


def load_varieties(con: sqlite3.Connection) -> list[VarietyMeta]:
    df = pd.read_sql_query("SELECT id, name, key FROM fut_variety ORDER BY id", con)
    metas: list[VarietyMeta] = []
    for row in df.to_dict("records"):
        name = str(row["name"])
        metas.append(
            VarietyMeta(
                variety_id=int(row["id"]),
                name=name,
                key=str(row["key"]),
                sector=ALL_SECTOR_BY_NAME.get(name, "未分类"),
                in_pool_a=name in POOL_A_NAMES,
            )
        )
    return metas


def load_variety_df(con: sqlite3.Connection, variety_id: int) -> pd.DataFrame:
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


def compute_signals(df: pd.DataFrame) -> pd.DataFrame:
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
    out["close_return"] = out["close"].pct_change().fillna(0.0)

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
    return out


def validate_aligned_dates(signal_map: dict[str, pd.DataFrame]) -> list[str]:
    names = sorted(signal_map)
    base = pd.DatetimeIndex(signal_map[names[0]]["trade_date"])
    for name in names[1:]:
        dates = pd.DatetimeIndex(signal_map[name]["trade_date"])
        if not base.equals(dates):
            raise ValueError(f"{name} 的交易日与其它品种不一致。")
    return [d.strftime("%Y-%m-%d") for d in base]


def simulate_single_variety(meta: VarietyMeta, data: pd.DataFrame) -> tuple[list[dict], list[dict], list[dict], dict]:
    trades: list[dict] = []
    events: list[dict] = []
    orphan_exits: list[dict] = []
    holding_side = 0
    entry_idx: int | None = None
    entry_price: float | None = None
    entry_date: str | None = None

    for i, row in data.iterrows():
        trade_date = row["trade_date"].strftime("%Y-%m-%d")
        exit_reasons: list[str] = []
        if bool(row["exit_long_signal"]):
            exit_reasons.append("exit_long_signal")
        if bool(row["exit_short_signal"]):
            exit_reasons.append("exit_short_signal")

        if holding_side == 1 and bool(row["exit_long_signal"]):
            exit_price = float(row["close"])
            trades.append(
                {
                    "entry_date": entry_date,
                    "exit_date": trade_date,
                    "side": "long",
                    "entry_price": float(entry_price),
                    "exit_price": exit_price,
                    "holding_days": i - int(entry_idx),
                    "pnl_ratio": trade_return(1, float(entry_price), exit_price),
                    "exit_reason": "tp3_main_turn_down",
                }
            )
            events.append(
                {
                    "date": trade_date,
                    "event_type": "raw_exit",
                    "layer": "single_variety",
                    "side": "long",
                    "price": exit_price,
                    "reason": "tp3_main_turn_down",
                }
            )
            holding_side = 0
            entry_idx = None
            entry_price = None
            entry_date = None
        elif holding_side == -1 and bool(row["exit_short_signal"]):
            exit_price = float(row["close"])
            trades.append(
                {
                    "entry_date": entry_date,
                    "exit_date": trade_date,
                    "side": "short",
                    "entry_price": float(entry_price),
                    "exit_price": exit_price,
                    "holding_days": i - int(entry_idx),
                    "pnl_ratio": trade_return(-1, float(entry_price), exit_price),
                    "exit_reason": "tp3_main_turn_up",
                }
            )
            events.append(
                {
                    "date": trade_date,
                    "event_type": "raw_exit",
                    "layer": "single_variety",
                    "side": "short",
                    "price": exit_price,
                    "reason": "tp3_main_turn_up",
                }
            )
            holding_side = 0
            entry_idx = None
            entry_price = None
            entry_date = None
        elif holding_side == 0 and exit_reasons:
            orphan_exits.append(
                {
                    "date": trade_date,
                    "price": float(row["close"]),
                    "reasons": exit_reasons,
                    "main_force": float(row["main_force"]),
                    "retail": float(row["retail"]),
                }
            )
            events.append(
                {
                    "date": trade_date,
                    "event_type": "orphan_exit_condition",
                    "layer": "single_variety",
                    "side": None,
                    "price": float(row["close"]),
                    "reason": ",".join(exit_reasons),
                }
            )

        if holding_side == 0:
            if bool(row["long_signal"]):
                holding_side = 1
                entry_idx = i
                entry_price = float(row["close"])
                entry_date = trade_date
                events.append(
                    {
                        "date": trade_date,
                    "event_type": "raw_entry",
                    "layer": "single_variety",
                    "side": "long",
                    "price": float(row["close"]),
                        "reason": "a_channel_long",
                        "main_score": to_float(row["main_score"]),
                    }
                )
            elif bool(row["short_signal"]):
                holding_side = -1
                entry_idx = i
                entry_price = float(row["close"])
                entry_date = trade_date
                events.append(
                    {
                        "date": trade_date,
                    "event_type": "raw_entry",
                    "layer": "single_variety",
                    "side": "short",
                    "price": float(row["close"]),
                        "reason": "a_channel_short",
                        "main_score": to_float(row["main_score"]),
                    }
                )

    if holding_side != 0:
        last = data.iloc[-1]
        exit_price = float(last["close"])
        trade_date = last["trade_date"].strftime("%Y-%m-%d")
        trades.append(
            {
                "entry_date": entry_date,
                "exit_date": trade_date,
                "side": "long" if holding_side == 1 else "short",
                "entry_price": float(entry_price),
                "exit_price": exit_price,
                "holding_days": len(data) - 1 - int(entry_idx),
                "pnl_ratio": trade_return(holding_side, float(entry_price), exit_price),
                "exit_reason": "final_close",
            }
        )
        events.append(
            {
                "date": trade_date,
                "event_type": "raw_exit",
                "layer": "single_variety",
                "side": "long" if holding_side == 1 else "short",
                "price": exit_price,
                "reason": "final_close",
            }
        )

    raw_open_long_count = int(sum(1 for event in events if event["event_type"] == "raw_entry" and event["side"] == "long"))
    raw_open_short_count = int(sum(1 for event in events if event["event_type"] == "raw_entry" and event["side"] == "short"))
    raw_close_long_count = int(sum(1 for event in events if event["event_type"] == "raw_exit" and event["side"] == "long"))
    raw_close_short_count = int(sum(1 for event in events if event["event_type"] == "raw_exit" and event["side"] == "short"))

    summary = {
        "raw_open_long_count": raw_open_long_count,
        "raw_open_short_count": raw_open_short_count,
        "raw_close_long_count": raw_close_long_count,
        "raw_close_short_count": raw_close_short_count,
        "exit_condition_long_hit_count": int(data["exit_long_signal"].sum()),
        "exit_condition_short_hit_count": int(data["exit_short_signal"].sum()),
        "executed_trade_count": len(trades),
        "orphan_exit_condition_count": len(orphan_exits),
        "win_rate": to_float(pd.Series([t["pnl_ratio"] for t in trades]).gt(0).mean()) if trades else None,
        "avg_trade_return": to_float(pd.Series([t["pnl_ratio"] for t in trades]).mean()) if trades else None,
    }
    return trades, events, orphan_exits, summary


def build_pool_a_audit(
    signal_map: dict[str, pd.DataFrame],
    metas_by_name: dict[str, VarietyMeta],
) -> tuple[dict[str, list[dict]], dict[str, list[dict]], list[dict], list[dict], list[dict], dict[str, dict]]:
    dates = validate_aligned_dates(signal_map)
    holdings: dict[str, dict] = {}
    variety_events = {name: [] for name in signal_map}
    variety_decisions = {name: [] for name in signal_map}
    portfolio_daily: list[dict] = []
    trades: list[dict] = []
    orphan_exit_signals: list[dict] = []
    summary_by_name: dict[str, dict] = {
        name: {
            "pool_entry_count": 0,
            "pool_exit_count": 0,
            "pool_selected_signal_count": 0,
            "pool_rejected_signal_count": 0,
        }
        for name in signal_map
    }

    for idx, trade_date in enumerate(dates):
        start_holdings = {name: pos.copy() for name, pos in holdings.items()}
        start_sectors = {POOL_A_SECTOR_BY_NAME[name] for name in start_holdings}
        entry_capacity = 3 - len(start_holdings)
        closed_today: set[str] = set()
        opened_today: list[str] = []

        for name in POOL_A_NAMES:
            row = signal_map[name].iloc[idx]
            meta = metas_by_name[name]
            if bool(row["exit_long_signal"]) or bool(row["exit_short_signal"]):
                if name not in start_holdings:
                    orphan_exit_signals.append(
                        {
                            "variety_name": name,
                            "date": trade_date,
                            "price": float(row["close"]),
                            "exit_long_signal": bool(row["exit_long_signal"]),
                            "exit_short_signal": bool(row["exit_short_signal"]),
                        }
                    )
                    variety_events[name].append(
                        {
                            "date": trade_date,
                            "event_type": "orphan_exit_signal",
                            "layer": "pool_a",
                            "side": None,
                            "price": float(row["close"]),
                            "reason": "flat_position_exit_signal",
                            "sector": meta.sector,
                        }
                    )

            if name not in start_holdings:
                continue

            pos = start_holdings[name]
            should_close = (pos["side"] == 1 and bool(row["exit_long_signal"])) or (
                pos["side"] == -1 and bool(row["exit_short_signal"])
            )
            if not should_close:
                continue

            exit_reason = "tp3_main_turn_down" if pos["side"] == 1 else "tp3_main_turn_up"
            trades.append(
                {
                    "variety_name": name,
                    "sector": meta.sector,
                    "entry_date": pos["entry_date"],
                    "exit_date": trade_date,
                    "side": "long" if pos["side"] == 1 else "short",
                    "entry_price": float(pos["entry_price"]),
                    "exit_price": float(row["close"]),
                    "holding_days": idx - int(pos["entry_idx"]),
                    "pnl_ratio": trade_return(int(pos["side"]), float(pos["entry_price"]), float(row["close"])),
                    "entry_main_score": pos["main_score"],
                    "exit_reason": exit_reason,
                }
            )
            summary_by_name[name]["pool_exit_count"] += 1
            variety_events[name].append(
                {
                    "date": trade_date,
                    "event_type": "trade_exit",
                    "layer": "pool_a",
                    "side": "long" if pos["side"] == 1 else "short",
                    "price": float(row["close"]),
                    "reason": exit_reason,
                    "sector": meta.sector,
                }
            )
            holdings.pop(name, None)
            closed_today.add(name)

        candidates: list[dict] = []
        for name, data in signal_map.items():
            row = data.iloc[idx]
            meta = metas_by_name[name]
            side = 0
            if bool(row["long_signal"]):
                side = 1
            elif bool(row["short_signal"]):
                side = -1
            if side == 0:
                continue

            raw_side = "long" if side == 1 else "short"
            variety_events[name].append(
                {
                    "date": trade_date,
                    "event_type": "raw_signal",
                    "layer": "all_varieties",
                    "side": raw_side,
                    "price": float(row["close"]),
                    "reason": "a_channel_signal",
                    "main_score": to_float(row["main_score"]),
                    "sector": meta.sector,
                }
            )

            if not meta.in_pool_a:
                variety_decisions[name].append(
                    {
                        "date": trade_date,
                        "decision": "rejected",
                        "reason": "not_in_pool_a",
                        "side": raw_side,
                        "price": float(row["close"]),
                        "main_score": to_float(row["main_score"]),
                    }
                )
                variety_events[name].append(
                    {
                        "date": trade_date,
                        "event_type": "pool_decision",
                        "layer": "pool_a",
                        "side": raw_side,
                        "price": float(row["close"]),
                        "reason": "not_in_pool_a",
                        "decision": "rejected",
                        "sector": meta.sector,
                    }
                )
                continue

            if name in start_holdings:
                variety_decisions[name].append(
                    {
                        "date": trade_date,
                        "decision": "rejected",
                        "reason": "already_holding_at_open",
                        "side": raw_side,
                        "price": float(row["close"]),
                        "main_score": to_float(row["main_score"]),
                    }
                )
                summary_by_name[name]["pool_rejected_signal_count"] += 1
                continue

            if name in closed_today:
                variety_decisions[name].append(
                    {
                        "date": trade_date,
                        "decision": "rejected",
                        "reason": "same_day_reentry_forbidden",
                        "side": raw_side,
                        "price": float(row["close"]),
                        "main_score": to_float(row["main_score"]),
                    }
                )
                variety_events[name].append(
                    {
                        "date": trade_date,
                        "event_type": "pool_decision",
                        "layer": "pool_a",
                        "side": raw_side,
                        "price": float(row["close"]),
                        "reason": "same_day_reentry_forbidden",
                        "decision": "rejected",
                        "sector": meta.sector,
                    }
                )
                summary_by_name[name]["pool_rejected_signal_count"] += 1
                continue

            candidates.append(
                {
                    "variety_name": name,
                    "sector": meta.sector,
                    "side": side,
                    "side_label": raw_side,
                    "price": float(row["close"]),
                    "main_score": to_float(row["main_score"]),
                }
            )

        used_sectors = set(start_sectors)
        selected_names: set[str] = set()

        def sort_key(item: dict) -> tuple[bool, float, str]:
            score = item["main_score"]
            return (score is None, -(score or 0.0), item["variety_name"])

        if entry_capacity > 0:
            for item in sorted(candidates, key=sort_key):
                if item["sector"] in used_sectors:
                    variety_decisions[item["variety_name"]].append(
                        {
                            "date": trade_date,
                            "decision": "rejected",
                            "reason": "sector_mutex_conflict",
                            "side": item["side_label"],
                            "price": item["price"],
                            "main_score": item["main_score"],
                        }
                    )
                    variety_events[item["variety_name"]].append(
                        {
                            "date": trade_date,
                            "event_type": "pool_decision",
                            "layer": "pool_a",
                            "side": item["side_label"],
                            "price": item["price"],
                            "reason": "sector_mutex_conflict",
                            "decision": "rejected",
                            "sector": item["sector"],
                        }
                    )
                    summary_by_name[item["variety_name"]]["pool_rejected_signal_count"] += 1
                    continue
                if len(selected_names) >= entry_capacity:
                    variety_decisions[item["variety_name"]].append(
                        {
                            "date": trade_date,
                            "decision": "rejected",
                            "reason": "slot_full",
                            "side": item["side_label"],
                            "price": item["price"],
                            "main_score": item["main_score"],
                        }
                    )
                    variety_events[item["variety_name"]].append(
                        {
                            "date": trade_date,
                            "event_type": "pool_decision",
                            "layer": "pool_a",
                            "side": item["side_label"],
                            "price": item["price"],
                            "reason": "slot_full",
                            "decision": "rejected",
                            "sector": item["sector"],
                        }
                    )
                    summary_by_name[item["variety_name"]]["pool_rejected_signal_count"] += 1
                    continue

                selected_names.add(item["variety_name"])
                used_sectors.add(item["sector"])
                holdings[item["variety_name"]] = {
                    "side": item["side"],
                    "entry_idx": idx,
                    "entry_date": trade_date,
                    "entry_price": item["price"],
                    "main_score": item["main_score"],
                }
                opened_today.append(item["variety_name"])
                variety_decisions[item["variety_name"]].append(
                    {
                        "date": trade_date,
                        "decision": "selected",
                        "reason": "selected_into_pool_a",
                        "side": item["side_label"],
                        "price": item["price"],
                        "main_score": item["main_score"],
                    }
                )
                variety_events[item["variety_name"]].append(
                    {
                        "date": trade_date,
                        "event_type": "trade_entry",
                        "layer": "pool_a",
                        "side": item["side_label"],
                        "price": item["price"],
                        "reason": "selected_into_pool_a",
                        "decision": "selected",
                        "sector": item["sector"],
                        "main_score": item["main_score"],
                    }
                )
                summary_by_name[item["variety_name"]]["pool_entry_count"] += 1
                summary_by_name[item["variety_name"]]["pool_selected_signal_count"] += 1
        else:
            for item in candidates:
                variety_decisions[item["variety_name"]].append(
                    {
                        "date": trade_date,
                        "decision": "rejected",
                        "reason": "slot_full",
                        "side": item["side_label"],
                        "price": item["price"],
                        "main_score": item["main_score"],
                    }
                )
                variety_events[item["variety_name"]].append(
                    {
                        "date": trade_date,
                        "event_type": "pool_decision",
                        "layer": "pool_a",
                        "side": item["side_label"],
                        "price": item["price"],
                        "reason": "slot_full",
                        "decision": "rejected",
                        "sector": item["sector"],
                    }
                )
                summary_by_name[item["variety_name"]]["pool_rejected_signal_count"] += 1

        portfolio_daily.append(
            {
                "date": trade_date,
                "holdings_after_close": [
                    {
                        "variety_name": name,
                        "side": "long" if pos["side"] == 1 else "short",
                        "sector": metas_by_name[name].sector,
                        "entry_date": pos["entry_date"],
                        "entry_price": float(pos["entry_price"]),
                    }
                    for name, pos in sorted(holdings.items())
                ],
                "opened_today": sorted(opened_today),
                "closed_today": sorted(closed_today),
                "slot_count_after_close": len(holdings),
            }
        )

    if holdings:
        last_date = dates[-1]
        for name, pos in sorted(holdings.items()):
            row = signal_map[name].iloc[-1]
            exit_price = float(row["close"])
            trades.append(
                {
                    "variety_name": name,
                    "sector": metas_by_name[name].sector,
                    "entry_date": pos["entry_date"],
                    "exit_date": last_date,
                    "side": "long" if pos["side"] == 1 else "short",
                    "entry_price": float(pos["entry_price"]),
                    "exit_price": exit_price,
                    "holding_days": len(dates) - 1 - int(pos["entry_idx"]),
                    "pnl_ratio": trade_return(int(pos["side"]), float(pos["entry_price"]), exit_price),
                    "entry_main_score": pos["main_score"],
                    "exit_reason": "final_close",
                }
            )
            summary_by_name[name]["pool_exit_count"] += 1
            variety_events[name].append(
                {
                    "date": last_date,
                    "event_type": "trade_exit",
                    "layer": "pool_a",
                    "side": "long" if pos["side"] == 1 else "short",
                    "price": exit_price,
                    "reason": "final_close",
                    "sector": metas_by_name[name].sector,
                }
            )

    return variety_events, variety_decisions, portfolio_daily, trades, orphan_exit_signals, summary_by_name


def build_variety_payload(
    meta: VarietyMeta,
    data: pd.DataFrame,
    single_trades: list[dict],
    single_events: list[dict],
    single_orphans: list[dict],
    single_summary: dict,
    pool_events: list[dict],
    pool_decisions: list[dict],
    pool_summary: dict,
    pool_trades: list[dict],
) -> dict:
    pool_trade_rows = [trade for trade in pool_trades if trade["variety_name"] == meta.name]
    pool_trade_by_entry = {trade["entry_date"]: trade for trade in pool_trade_rows}
    pool_trade_by_exit = {trade["exit_date"]: trade for trade in pool_trade_rows}
    decision_by_date = {
        item["date"]: {
            "decision": item["decision"],
            "reason": item["reason"],
            "side": item["side"],
            "price": item["price"],
            "main_score": item["main_score"],
        }
        for item in pool_decisions
    }
    raw_entry_by_date = {
        (event["date"], event["side"]): event
        for event in single_events
        if event["event_type"] == "raw_entry"
    }
    raw_exit_by_date = {
        (event["date"], event["side"]): event
        for event in single_events
        if event["event_type"] == "raw_exit"
    }

    rows: list[dict] = []
    holding_side = 0
    for _, row in data.iterrows():
        trade_date = row["trade_date"].strftime("%Y-%m-%d")
        decision = decision_by_date.get(trade_date)
        if trade_date in pool_trade_by_entry:
            holding_side = 1 if pool_trade_by_entry[trade_date]["side"] == "long" else -1
        if trade_date in pool_trade_by_exit:
            holding_side = 0

        rows.append(
            {
                "date": trade_date,
                "main_force": float(row["main_force"]),
                "retail": float(row["retail"]),
                "close": float(row["close"]),
                "main_score": to_float(row["main_score"]),
                "m3": to_float(row["m3"]),
                "raw_open_long": (trade_date, "long") in raw_entry_by_date,
                "raw_open_short": (trade_date, "short") in raw_entry_by_date,
                "raw_close_long": (trade_date, "long") in raw_exit_by_date,
                "raw_close_short": (trade_date, "short") in raw_exit_by_date,
                "exit_condition_long_hit": bool(row["exit_long_signal"]),
                "exit_condition_short_hit": bool(row["exit_short_signal"]),
                "pool_decision": decision["decision"] if decision else None,
                "pool_decision_reason": decision["reason"] if decision else None,
                "pool_decision_side": decision["side"] if decision else None,
                "pool_holding_after_close": holding_side,
            }
        )

    return {
        "variety_id": meta.variety_id,
        "name": meta.name,
        "key": meta.key,
        "sector": meta.sector,
        "in_pool_a": meta.in_pool_a,
        "rows": rows,
        "single_variety": {
            "summary": single_summary,
            "trades": single_trades,
            "orphan_exit_signals": single_orphans,
            "events": single_events,
        },
        "pool_a": {
            "summary": pool_summary,
            "trades": pool_trade_rows,
            "decisions": pool_decisions,
            "events": pool_events,
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="生成 55 品种全量信号审计 JSON。")
    parser.add_argument("--db", type=Path, default=DB_PATH, help="SQLite 数据库路径")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="输出 JSON 路径")
    args = parser.parse_args()

    output_path = args.output.resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with sqlite3.connect(args.db) as con:
        metas = load_varieties(con)
        signal_map: dict[str, pd.DataFrame] = {}
        metas_by_name = {meta.name: meta for meta in metas}
        for meta in metas:
            signal_map[meta.name] = compute_signals(load_variety_df(con, meta.variety_id))

    trade_dates = validate_aligned_dates(signal_map)

    all_single_results: dict[str, dict] = {}
    for meta in metas:
        trades, events, orphans, summary = simulate_single_variety(meta, signal_map[meta.name])
        all_single_results[meta.name] = {
            "trades": trades,
            "events": events,
            "orphans": orphans,
            "summary": summary,
        }

    pool_events, pool_decisions, portfolio_daily, pool_trades, pool_orphans, pool_summary = build_pool_a_audit(
        signal_map,
        metas_by_name,
    )

    varieties_payload = {}
    for meta in metas:
        single = all_single_results[meta.name]
        varieties_payload[meta.name] = build_variety_payload(
            meta=meta,
            data=signal_map[meta.name],
            single_trades=single["trades"],
            single_events=single["events"],
            single_orphans=single["orphans"],
            single_summary=single["summary"],
            pool_events=pool_events[meta.name],
            pool_decisions=pool_decisions[meta.name],
            pool_summary=pool_summary[meta.name],
            pool_trades=pool_trades,
        )

    payload = {
        "meta": {
            "source_db": str(args.db.resolve()),
            "output_file": str(output_path),
            "trade_date_start": trade_dates[0],
            "trade_date_end": trade_dates[-1],
            "trade_date_count": len(trade_dates),
            "variety_count": len(metas),
            "pool_a_count": len(POOL_A_NAMES),
            "strategy_rules": {
                "entry": "strict_7_day_overlap_5_plus_3_a_channel",
                "exit": "tp3_main_force_turn_only",
                "same_day_reentry": "forbidden",
                "same_day_slot_refill_after_exit": "forbidden",
                "pool_a_max_slots": 3,
                "pool_a_sector_mutex": True,
            },
        },
        "pool_a_varieties": [
            {
                "name": name,
                "sector": POOL_A_SECTOR_BY_NAME[name],
            }
            for name in POOL_A_NAMES
        ],
        "trade_dates": trade_dates,
        "variety_order": [meta.name for meta in metas],
        "portfolio_audit": {
            "daily": portfolio_daily,
            "trades": pool_trades,
            "orphan_exit_signals": pool_orphans,
        },
        "varieties": varieties_payload,
    }

    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote signal audit JSON to {output_path}")


if __name__ == "__main__":
    main()
