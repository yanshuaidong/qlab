"""
Plan 4 — 组合回测：Plan 2 规则 + LightGBM 概率过滤/排序。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from common import (  # noqa: E402
    ARTIFACT_DATA,
    ARTIFACT_MODELS,
    DOCS_DIR,
    FEATURE_COLUMNS,
    MIN_PROB_DEFAULT,
    SECTOR_BY_VARIETY,
    TARGET_POOL,
    TARGET_VARIETIES,
    PortfolioConfig,
    load_signal_map,
    save_json,
    trade_return,
)

SECTORS = list(dict.fromkeys(sec for _, sec in TARGET_POOL))


def compute_max_drawdown(curve: pd.Series) -> float:
    peak = curve.cummax()
    return float((curve / peak - 1.0).min())


def attach_lgb_prob(
    signal_map: dict[str, pd.DataFrame],
    model,
    train_end: pd.Timestamp,
) -> dict[str, pd.DataFrame]:
    out: dict[str, pd.DataFrame] = {}
    for name, df in signal_map.items():
        data = df.copy()
        probs = np.full(len(data), np.nan)
        for i in range(len(data)):
            row = data.iloc[i]
            if not (bool(row["long_signal"]) or bool(row["short_signal"])):
                continue
            if row["trade_date"] <= train_end:
                continue
            side = 1.0 if bool(row["long_signal"]) else -1.0
            feat = {
                col: float(row[col]) if col in row.index and pd.notna(row[col]) else np.nan
                for col in FEATURE_COLUMNS
                if col != "side"
            }
            feat["side"] = side
            X = pd.DataFrame([feat])[FEATURE_COLUMNS].astype(float)
            probs[i] = float(model.predict_proba(X)[0, 1])
        data["lgb_prob"] = probs
        out[name] = data
    return out


def validate_aligned_dates(signal_map: dict[str, pd.DataFrame]) -> pd.DatetimeIndex:
    base = pd.DatetimeIndex(signal_map[TARGET_VARIETIES[0]]["trade_date"])
    for name in TARGET_VARIETIES[1:]:
        if not base.equals(pd.DatetimeIndex(signal_map[name]["trade_date"])):
            raise ValueError(f"{name} 交易日与基准不一致")
    return base


def _rank_score(row: pd.Series, config: PortfolioConfig, is_oos: bool) -> tuple[float, bool]:
    main_score = float(row["main_score"]) if pd.notna(row["main_score"]) else np.nan
    lgb_prob = float(row["lgb_prob"]) if "lgb_prob" in row.index and pd.notna(row["lgb_prob"]) else np.nan
    if config.use_lgb and is_oos:
        if pd.isna(lgb_prob) or lgb_prob < config.min_prob:
            return np.nan, False
        return lgb_prob, True
    return main_score, True


def simulate_portfolio(
    signal_map: dict[str, pd.DataFrame],
    config: PortfolioConfig,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, dict]:
    dates = validate_aligned_dates(signal_map)
    holdings: dict[str, dict] = {}
    trades: list[dict] = []
    daily_rows: list[dict] = []

    for i, trade_date in enumerate(dates):
        is_oos = config.train_end is not None and trade_date > config.train_end
        day_ret = 0.0
        for variety_name, pos in holdings.items():
            day_ret += pos["side"] * float(signal_map[variety_name].iloc[i]["close_return"]) / config.weight_slots

        start_holdings = {n: p.copy() for n, p in holdings.items()}
        start_sectors = {SECTOR_BY_VARIETY[n] for n in start_holdings}
        entry_capacity = config.max_slots - len(start_holdings)
        closed_today: set[str] = set()
        closed_count = 0

        for variety_name, pos in list(start_holdings.items()):
            row = signal_map[variety_name].iloc[i]
            if pos["side"] == 1 and bool(row["exit_long_signal"]):
                exit_price = float(row["close"])
                trades.append(_trade_row(config, variety_name, pos, trade_date, i, exit_price, "tp3_main_turn_down"))
                holdings.pop(variety_name)
                closed_today.add(variety_name)
                closed_count += 1
            elif pos["side"] == -1 and bool(row["exit_short_signal"]):
                exit_price = float(row["close"])
                trades.append(_trade_row(config, variety_name, pos, trade_date, i, exit_price, "tp3_main_turn_up"))
                holdings.pop(variety_name)
                closed_today.add(variety_name)
                closed_count += 1

        sector_reject = 0
        capacity_reject = 0
        ml_reject = 0
        raw_signals: list[dict] = []

        for variety_name in TARGET_VARIETIES:
            if variety_name in start_holdings or variety_name in closed_today:
                continue
            row = signal_map[variety_name].iloc[i]
            side = 0
            if bool(row["long_signal"]):
                side = 1
            elif bool(row["short_signal"]):
                side = -1
            if side == 0:
                continue

            rank_score, ok = _rank_score(row, config, is_oos)
            if not ok:
                ml_reject += 1
                continue

            raw_signals.append(
                {
                    "variety_name": variety_name,
                    "sector": SECTOR_BY_VARIETY[variety_name],
                    "side": side,
                    "close": float(row["close"]),
                    "main_score": float(row["main_score"]) if pd.notna(row["main_score"]) else np.nan,
                    "lgb_prob": float(row["lgb_prob"]) if "lgb_prob" in row.index and pd.notna(row["lgb_prob"]) else np.nan,
                    "rank_score": rank_score,
                }
            )

        selected: list[dict] = []
        if entry_capacity <= 0:
            capacity_reject = len(raw_signals)
        else:
            filtered = []
            for c in raw_signals:
                if config.sector_mutex and c["sector"] in start_sectors:
                    sector_reject += 1
                    continue
                filtered.append(c)
            filtered.sort(
                key=lambda x: (
                    pd.isna(x["rank_score"]),
                    -(x["rank_score"] if pd.notna(x["rank_score"]) else 0.0),
                    x["variety_name"],
                )
            )
            used = set(start_sectors)
            for c in filtered:
                if config.sector_mutex and c["sector"] in used:
                    sector_reject += 1
                    continue
                if len(selected) >= entry_capacity:
                    capacity_reject += 1
                    continue
                selected.append(c)
                used.add(c["sector"])

        for c in selected:
            holdings[c["variety_name"]] = {
                "side": c["side"],
                "entry_idx": i,
                "entry_date": trade_date,
                "entry_price": c["close"],
                "main_score": c["main_score"],
                "lgb_prob": c["lgb_prob"],
            }

        daily_rows.append(
            {
                "trade_date": trade_date,
                "strategy_name": config.strategy_name,
                "is_oos": is_oos,
                "opened_count": len(selected),
                "closed_count": closed_count,
                "occupied_slots_after_close": len(holdings),
                "sector_reject_count": sector_reject,
                "capacity_reject_count": capacity_reject,
                "ml_reject_count": ml_reject,
                "portfolio_daily_return": day_ret,
            }
        )
    if holdings:
        last_date = dates[-1]
        for variety_name, pos in sorted(holdings.items()):
            last_row = signal_map[variety_name].iloc[-1]
            trades.append(
                _trade_row(
                    config,
                    variety_name,
                    pos,
                    last_date,
                    len(dates) - 1,
                    float(last_row["close"]),
                    "final_close",
                )
            )

    daily_df = pd.DataFrame(daily_rows)
    daily_df["equity_curve"] = (1.0 + daily_df["portfolio_daily_return"]).cumprod()
    daily_df["occupied_slots_prev"] = daily_df["occupied_slots_after_close"].shift(1).fillna(0)

    trades_df = pd.DataFrame(trades)
    summary = {
        "strategy_name": config.strategy_name,
        "trade_count": int(len(trades_df)),
        "win_rate": float(trades_df["pnl_ratio"].gt(0).mean()) if len(trades_df) else np.nan,
        "avg_trade_return": float(trades_df["pnl_ratio"].mean()) if len(trades_df) else np.nan,
        "strategy_return": float(daily_df["equity_curve"].iloc[-1] - 1.0),
        "max_drawdown": compute_max_drawdown(daily_df["equity_curve"]),
        "avg_occupied_slots": float(daily_df["occupied_slots_after_close"].mean()),
        "sector_reject_count": int(daily_df["sector_reject_count"].sum()),
        "capacity_reject_count": int(daily_df["capacity_reject_count"].sum()),
        "ml_reject_count": int(daily_df["ml_reject_count"].sum()),
    }
    oos_mask = daily_df["is_oos"]
    if oos_mask.any():
        oos_curve = (1.0 + daily_df.loc[oos_mask, "portfolio_daily_return"]).cumprod()
        summary["oos_return"] = float(oos_curve.iloc[-1] - 1.0)
        summary["oos_max_drawdown"] = compute_max_drawdown(oos_curve)

    contribution_rows = []
    for variety_name in TARGET_VARIETIES:
        v_trades = trades_df[trades_df["variety_name"] == variety_name] if len(trades_df) else trades_df
        contribution_rows.append(
            {
                "strategy_name": config.strategy_name,
                "variety_name": variety_name,
                "return_contribution": float(v_trades["pnl_ratio"].sum() / config.weight_slots) if len(v_trades) else 0.0,
                "trade_count": int(len(v_trades)),
            }
        )
    contribution_df = pd.DataFrame(contribution_rows).sort_values("return_contribution", ascending=False)
    return daily_df, trades_df, contribution_df, summary


def _trade_row(config, variety_name, pos, exit_date, exit_idx, exit_price, reason):
    side = int(pos["side"])
    return {
        "strategy_name": config.strategy_name,
        "variety_name": variety_name,
        "sector": SECTOR_BY_VARIETY[variety_name],
        "side": "long" if side == 1 else "short",
        "entry_date": pos["entry_date"],
        "exit_date": exit_date,
        "entry_price": float(pos["entry_price"]),
        "exit_price": exit_price,
        "holding_days": exit_idx - int(pos["entry_idx"]),
        "pnl_ratio": trade_return(side, float(pos["entry_price"]), exit_price),
        "entry_main_score": pos.get("main_score"),
        "entry_lgb_prob": pos.get("lgb_prob"),
        "exit_reason": reason,
    }


def write_report(summaries: list[dict], metrics: dict | None) -> None:
    lines = [
        "# Plan 4：LightGBM 增强组合策略回测报告",
        "",
        "**规则骨架**：Plan 2 严格 7 日开仓 + 3 日主力拐头离场 + 3 槽板块互斥",
        "**ML 层**：LightGBM 预测开仓样本盈利概率，样本外过滤/排序",
        "",
        "## 回测汇总",
        "",
        "| 策略 | 交易数 | 胜率 | 累计收益 | 最大回撤 | OOS收益 | ML拒单 |",
        "|------|--------|------|----------|----------|---------|--------|",
    ]
    for s in summaries:
        lines.append(
            f"| {s['strategy_name']} | {s.get('trade_count', '-')} | "
            f"{s.get('win_rate', np.nan):.2%} | {s.get('strategy_return', np.nan):.2%} | "
            f"{s.get('max_drawdown', np.nan):.2%} | "
            f"{s.get('oos_return', np.nan):.2%} | {s.get('ml_reject_count', 0)} |"
        )
    if metrics:
        lines.extend(["", "## 模型验证集", ""])
        valid_m = next((m for m in metrics.get("metrics", []) if m.get("split") == "valid"), {})
        for k, v in valid_m.items():
            lines.append(f"- **{k}**: {v}")
    backend = metrics.get("backend", "unknown") if metrics else "unknown"
    lines.extend(
        [
            "",
            f"**训练后端**：{backend}（本机若缺 `libomp` 会回退 sklearn）",
            "",
            "## 结论要点",
            "",
            "1. **Plan 2 规则**仍是交易骨架；Plan 4 在信号日叠加 Plan 1 共振 + Plan 3 积累质量特征。",
            "2. 样本外（后 30% 交易日）对比：`plan4_full` 最大回撤通常浅于 `plan2_baseline`，收益需更长样本验证。",
            "3. `plan4_no_filter`（仅 ML 排序不过滤）可用于观察排序本身是否带来增益。",
            "4. 验证集 AUC 接近 0.5 时说明 180 日开仓样本偏少，应延长数据或放宽特征后再训 LightGBM。",
            "",
        ]
    )
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    (DOCS_DIR / "report.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    model_path = ARTIFACT_MODELS / "lgbm_entry.pkl"
    if not model_path.is_file():
        print("未找到模型，先运行: python scripts/train_lgbm.py")
        raise SystemExit(1)

    bundle = joblib.load(model_path)
    if isinstance(bundle, dict):
        model = bundle["model"]
        print(f"模型后端: {bundle.get('backend', 'unknown')}")
    else:
        model = bundle
    meta = json.loads((ARTIFACT_MODELS / "feature_meta.json").read_text(encoding="utf-8"))
    metrics_path = ARTIFACT_MODELS / "metrics.json"
    metrics = json.loads(metrics_path.read_text(encoding="utf-8")) if metrics_path.is_file() else None
    train_end = pd.Timestamp(metrics["train_end"]) if metrics else None

    signal_map, default_train_end = load_signal_map()
    if train_end is None:
        train_end = default_train_end
    signal_map = attach_lgb_prob(signal_map, model, train_end)

    configs = [
        PortfolioConfig(
            strategy_name="plan2_baseline",
            max_slots=3,
            weight_slots=3,
            sector_mutex=True,
            use_lgb=False,
            min_prob=0.0,
            train_end=train_end,
        ),
        PortfolioConfig(
            strategy_name="plan4_full",
            max_slots=3,
            weight_slots=3,
            sector_mutex=True,
            use_lgb=True,
            min_prob=MIN_PROB_DEFAULT,
            train_end=train_end,
        ),
        PortfolioConfig(
            strategy_name="plan4_no_filter",
            max_slots=3,
            weight_slots=3,
            sector_mutex=True,
            use_lgb=True,
            min_prob=0.0,
            train_end=train_end,
        ),
    ]

    ARTIFACT_DATA.mkdir(parents=True, exist_ok=True)
    summaries = []
    for cfg in configs:
        daily_df, trades_df, contrib_df, summary = simulate_portfolio(signal_map, cfg)
        prefix = cfg.strategy_name
        daily_df.to_csv(ARTIFACT_DATA / f"{prefix}_daily.csv", index=False)
        trades_df.to_csv(ARTIFACT_DATA / f"{prefix}_trades.csv", index=False)
        contrib_df.to_csv(ARTIFACT_DATA / f"{prefix}_contribution.csv", index=False)
        summaries.append(summary)
        print(f"\n=== {cfg.strategy_name} ===")
        for k, v in summary.items():
            print(f"  {k}: {v}")

    pd.DataFrame(summaries).to_csv(ARTIFACT_DATA / "backtest_summary.csv", index=False)
    write_report(summaries, metrics)
    print(f"\n报告: {DOCS_DIR / 'report.md'}")


if __name__ == "__main__":
    main()
