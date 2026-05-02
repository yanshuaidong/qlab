from __future__ import annotations

import csv
import json
import math
import sqlite3
import statistics
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable


ROOT_DIR = Path(__file__).resolve().parents[3]
DB_PATH = ROOT_DIR / "storage" / "stock" / "stock_net_inflow" / "data.sqlite"
OUTPUT_DIR = Path(__file__).resolve().parent / "output"
HORIZONS = [3, 5, 7, 10, 14]
COOLDOWN_WINDOWS = [5, 10, 14, 20, 30, 60]
ADJUST = ""

METRICS = [
    "net_inflow_wan_shou",
    "institution_buy_wan_shou",
    "institution_sell_wan_shou",
    "institution_activity_wan_shou",
    "institution_buy_delta_wan_shou",
    "institution_buy_ratio",
    "institution_buy_vs_prev5_mean",
]

METRIC_LABELS = {
    "net_inflow_wan_shou": "机构净买入",
    "institution_buy_wan_shou": "机构买入额",
    "institution_sell_wan_shou": "机构卖出额",
    "institution_activity_wan_shou": "机构买卖总额",
    "institution_buy_delta_wan_shou": "机构买入额较昨日增量",
    "institution_buy_ratio": "机构买入额较昨日倍数",
    "institution_buy_vs_prev5_mean": "机构买入额相对前5日均值倍数",
}

SIGNALS = [
    ("net_anomaly", "旧口径：净买入异常"),
    ("buy_attention", "机构买入额异常"),
    ("positive_net_buy_attention", "净买入为正 + 买入额异常"),
    ("positive_net_activity_attention", "净买入为正 + 买卖总额异常"),
    ("net_and_buy_anomaly", "净买入异常 + 买入额异常"),
    ("positive_net_top20_buy", "净买入为正 + 买入额处于本股前20%"),
    ("positive_net_buy_ratio_2x", "净买入为正 + 买入额较昨日翻倍"),
    ("positive_net_buy_ratio_2_to_3x", "净买入为正 + 买入额为昨日2-3倍"),
    ("positive_net_buy_ratio_3x", "净买入为正 + 买入额较昨日3倍"),
    ("positive_net_buy_vs_prev5_2x", "净买入为正 + 买入额达到前5日均值2倍"),
    ("positive_net_buy_delta_anomaly", "净买入为正 + 买入额较昨日增量异常"),
    ("positive_net_buy_ratio_top10", "净买入为正 + 买入额环比倍数前10%"),
]


@dataclass(frozen=True)
class MetricStats:
    stock_code: str
    metric: str
    count: int
    min_value: float
    max_value: float
    mean: float
    p95: float
    q1: float
    q3: float
    iqr: float
    median: float
    mad: float
    mad_scaled: float
    iqr_threshold: float
    mad_threshold: float
    anomaly_threshold: float
    event_count: int


def percentile(values: list[float], q: float) -> float:
    if not values:
        raise ValueError("percentile requires at least one value")
    if not 0 <= q <= 1:
        raise ValueError("q must be between 0 and 1")

    sorted_values = sorted(values)
    position = (len(sorted_values) - 1) * q
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return sorted_values[lower]

    upper_weight = position - lower
    lower_weight = 1 - upper_weight
    return sorted_values[lower] * lower_weight + sorted_values[upper] * upper_weight


def mean_or_none(values: Iterable[float]) -> float | None:
    values = list(values)
    if not values:
        return None
    return sum(values) / len(values)


def median_or_none(values: Iterable[float]) -> float | None:
    values = list(values)
    if not values:
        return None
    return statistics.median(values)


def pearson(xs: list[float], ys: list[float]) -> float | None:
    if len(xs) != len(ys) or len(xs) < 2:
        return None

    x_mean = sum(xs) / len(xs)
    y_mean = sum(ys) / len(ys)
    numerator = sum((x - x_mean) * (y - y_mean) for x, y in zip(xs, ys))
    x_denominator = math.sqrt(sum((x - x_mean) ** 2 for x in xs))
    y_denominator = math.sqrt(sum((y - y_mean) ** 2 for y in ys))
    if x_denominator == 0 or y_denominator == 0:
        return None
    return numerator / (x_denominator * y_denominator)


def average_ranks(values: list[float]) -> list[float]:
    indexed = sorted(enumerate(values), key=lambda item: item[1])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(indexed):
        j = i + 1
        while j < len(indexed) and indexed[j][1] == indexed[i][1]:
            j += 1
        rank = (i + 1 + j) / 2
        for k in range(i, j):
            ranks[indexed[k][0]] = rank
        i = j
    return ranks


def spearman(xs: list[float], ys: list[float]) -> float | None:
    if len(xs) != len(ys) or len(xs) < 2:
        return None
    return pearson(average_ranks(xs), average_ranks(ys))


def pct(value: float | None) -> str:
    if value is None:
        return ""
    return f"{value * 100:.2f}%"


def num(value: float | int | None, digits: int = 6) -> str:
    if value is None:
        return ""
    if isinstance(value, int):
        return str(value)
    return f"{value:.{digits}f}"


def read_fund_rows(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        """
        SELECT stock_code,
               trade_date,
               institution_buy_wan_shou,
               institution_sell_wan_shou,
               net_inflow_wan_shou
        FROM ths_fund_flow
        WHERE institution_buy_wan_shou IS NOT NULL
          AND institution_sell_wan_shou IS NOT NULL
          AND net_inflow_wan_shou IS NOT NULL
        ORDER BY stock_code, trade_date
        """
    ).fetchall()

    fund_rows: list[dict] = []
    for row in rows:
        item = dict(row)
        item["institution_buy_wan_shou"] = float(item["institution_buy_wan_shou"])
        item["institution_sell_wan_shou"] = float(item["institution_sell_wan_shou"])
        item["net_inflow_wan_shou"] = float(item["net_inflow_wan_shou"])
        item["institution_activity_wan_shou"] = (
            item["institution_buy_wan_shou"] + item["institution_sell_wan_shou"]
        )
        activity = item["institution_activity_wan_shou"]
        item["net_activity_ratio"] = (
            item["net_inflow_wan_shou"] / activity if activity else None
        )
        fund_rows.append(item)
    return fund_rows


def read_daily_rows(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        """
        SELECT stock_code, trade_date, close_price
        FROM stock_daily
        WHERE adjust = ? AND close_price IS NOT NULL
        ORDER BY stock_code, trade_date
        """,
        (ADJUST,),
    ).fetchall()
    return [dict(row) for row in rows]


def add_buy_jump_features(fund_rows: list[dict]) -> None:
    rows_by_stock: dict[str, list[dict]] = defaultdict(list)
    for row in fund_rows:
        rows_by_stock[row["stock_code"]].append(row)

    for rows in rows_by_stock.values():
        previous_buys: list[float] = []
        for index, row in enumerate(rows):
            buy = row["institution_buy_wan_shou"]
            prev_buy = previous_buys[-1] if previous_buys else None
            prev5 = previous_buys[-5:]
            prev5_mean = mean_or_none(prev5)

            if prev_buy is None or prev_buy <= 0:
                buy_delta = 0.0
                buy_ratio = 1.0
            else:
                buy_delta = buy - prev_buy
                buy_ratio = buy / prev_buy

            if prev5_mean is None or prev5_mean <= 0:
                buy_vs_prev5_mean = 1.0
            else:
                buy_vs_prev5_mean = buy / prev5_mean

            row["has_previous_fund_day"] = int(prev_buy is not None)
            row["stock_row_index"] = index
            row["previous_institution_buy_wan_shou"] = prev_buy
            row["previous_5day_buy_mean_wan_shou"] = prev5_mean
            row["institution_buy_delta_wan_shou"] = buy_delta
            row["institution_buy_ratio"] = buy_ratio
            row["institution_buy_vs_prev5_mean"] = buy_vs_prev5_mean
            previous_buys.append(buy)


def metric_stats(stock_code: str, metric: str, values: list[float]) -> MetricStats:
    median = statistics.median(values)
    deviations = [abs(value - median) for value in values]
    mad = statistics.median(deviations)
    mad_scaled = 1.4826 * mad
    q1 = percentile(values, 0.25)
    q3 = percentile(values, 0.75)
    iqr = q3 - q1
    p95 = percentile(values, 0.95)
    iqr_threshold = q3 + 1.5 * iqr
    mad_threshold = median + 3 * mad_scaled
    if mad == 0:
        anomaly_threshold = max(p95, iqr_threshold)
    else:
        anomaly_threshold = max(p95, iqr_threshold, mad_threshold)
    event_count = sum(value > 0 and value >= anomaly_threshold for value in values)

    return MetricStats(
        stock_code=stock_code,
        metric=metric,
        count=len(values),
        min_value=min(values),
        max_value=max(values),
        mean=sum(values) / len(values),
        p95=p95,
        q1=q1,
        q3=q3,
        iqr=iqr,
        median=median,
        mad=mad,
        mad_scaled=mad_scaled,
        iqr_threshold=iqr_threshold,
        mad_threshold=mad_threshold,
        anomaly_threshold=anomaly_threshold,
        event_count=event_count,
    )


def build_metric_stats(fund_rows: list[dict]) -> dict[str, dict[str, MetricStats]]:
    values_by_stock_metric: dict[str, dict[str, list[float]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for row in fund_rows:
        for metric in METRICS:
            values_by_stock_metric[row["stock_code"]][metric].append(float(row[metric]))

    stats_by_stock: dict[str, dict[str, MetricStats]] = {}
    for stock_code, metric_values in sorted(values_by_stock_metric.items()):
        stats_by_stock[stock_code] = {}
        for metric in METRICS:
            stats_by_stock[stock_code][metric] = metric_stats(
                stock_code,
                metric,
                metric_values[metric],
            )
    return stats_by_stock


def add_percentile_ranks(fund_rows: list[dict]) -> None:
    rows_by_stock: dict[str, list[dict]] = defaultdict(list)
    for row in fund_rows:
        rows_by_stock[row["stock_code"]].append(row)

    for rows in rows_by_stock.values():
        for metric in METRICS:
            values = [float(row[metric]) for row in rows]
            ranks = average_ranks(values)
            denominator = len(values) - 1
            for row, rank in zip(rows, ranks):
                row[f"{metric}_percentile"] = (
                    (rank - 1) / denominator if denominator > 0 else 1.0
                )


def build_price_lookup(
    daily_rows: list[dict],
) -> tuple[dict[str, list[dict]], dict[str, dict[str, int]]]:
    prices_by_stock: dict[str, list[dict]] = defaultdict(list)
    for row in daily_rows:
        prices_by_stock[row["stock_code"]].append(
            {
                "trade_date": row["trade_date"],
                "close_price": float(row["close_price"]),
            }
        )

    index_by_stock_date: dict[str, dict[str, int]] = {}
    for stock_code, rows in prices_by_stock.items():
        index_by_stock_date[stock_code] = {
            row["trade_date"]: index for index, row in enumerate(rows)
        }

    return prices_by_stock, index_by_stock_date


def anomaly_score(value: float, stats: MetricStats) -> float:
    scale = stats.mad_scaled if stats.mad_scaled > 0 else stats.iqr
    if scale <= 0:
        scale = max(abs(stats.anomaly_threshold), 1.0)
    return (value - stats.median) / scale


def is_metric_anomaly(value: float, stats: MetricStats) -> bool:
    return value > 0 and value >= stats.anomaly_threshold


def add_signal_flags(row: dict, stock_stats: dict[str, MetricStats]) -> None:
    net = row["net_inflow_wan_shou"]
    buy = row["institution_buy_wan_shou"]
    activity = row["institution_activity_wan_shou"]
    buy_delta = row["institution_buy_delta_wan_shou"]
    buy_ratio = row["institution_buy_ratio"]
    buy_vs_prev5_mean = row["institution_buy_vs_prev5_mean"]
    net_anomaly = is_metric_anomaly(net, stock_stats["net_inflow_wan_shou"])
    buy_attention = is_metric_anomaly(buy, stock_stats["institution_buy_wan_shou"])
    activity_attention = is_metric_anomaly(
        activity,
        stock_stats["institution_activity_wan_shou"],
    )
    buy_delta_anomaly = is_metric_anomaly(
        buy_delta,
        stock_stats["institution_buy_delta_wan_shou"],
    )

    row["net_anomaly"] = int(net_anomaly)
    row["buy_attention"] = int(buy_attention)
    row["positive_net_buy_attention"] = int(net > 0 and buy_attention)
    row["positive_net_activity_attention"] = int(net > 0 and activity_attention)
    row["net_and_buy_anomaly"] = int(net_anomaly and buy_attention)
    row["positive_net_top20_buy"] = int(
        net > 0 and row["institution_buy_wan_shou_percentile"] >= 0.8
    )
    row["positive_net_buy_ratio_2x"] = int(
        net > 0 and row["has_previous_fund_day"] and buy_ratio >= 2
    )
    row["positive_net_buy_ratio_2_to_3x"] = int(
        net > 0 and row["has_previous_fund_day"] and 2 <= buy_ratio < 3
    )
    row["positive_net_buy_ratio_3x"] = int(
        net > 0 and row["has_previous_fund_day"] and buy_ratio >= 3
    )
    row["positive_net_buy_vs_prev5_2x"] = int(
        net > 0 and row["has_previous_fund_day"] and buy_vs_prev5_mean >= 2
    )
    row["positive_net_buy_delta_anomaly"] = int(
        net > 0 and row["has_previous_fund_day"] and buy_delta_anomaly
    )
    row["positive_net_buy_ratio_top10"] = int(
        net > 0
        and row["has_previous_fund_day"]
        and row["institution_buy_ratio_percentile"] >= 0.9
    )


def enrich_rows(
    fund_rows: list[dict],
    stats_by_stock: dict[str, dict[str, MetricStats]],
    prices_by_stock: dict[str, list[dict]],
    index_by_stock_date: dict[str, dict[str, int]],
) -> list[dict]:
    enriched: list[dict] = []
    add_percentile_ranks(fund_rows)

    for row in fund_rows:
        stock_code = row["stock_code"]
        trade_date = row["trade_date"]
        stock_row_index = row.get("stock_row_index")
        if stock_code not in stats_by_stock:
            continue
        if stock_code not in prices_by_stock:
            continue
        price_index = index_by_stock_date[stock_code].get(trade_date)
        if price_index is None:
            continue

        stock_stats = stats_by_stock[stock_code]
        base_close = prices_by_stock[stock_code][price_index]["close_price"]
        enriched_row = {
            "stock_code": stock_code,
            "trade_date": trade_date,
            "stock_row_index": stock_row_index,
            "institution_buy_wan_shou": row["institution_buy_wan_shou"],
            "institution_sell_wan_shou": row["institution_sell_wan_shou"],
            "net_inflow_wan_shou": row["net_inflow_wan_shou"],
            "institution_activity_wan_shou": row["institution_activity_wan_shou"],
            "net_activity_ratio": row["net_activity_ratio"],
            "has_previous_fund_day": row["has_previous_fund_day"],
            "previous_institution_buy_wan_shou": row[
                "previous_institution_buy_wan_shou"
            ],
            "previous_5day_buy_mean_wan_shou": row["previous_5day_buy_mean_wan_shou"],
            "institution_buy_delta_wan_shou": row["institution_buy_delta_wan_shou"],
            "institution_buy_ratio": row["institution_buy_ratio"],
            "institution_buy_vs_prev5_mean": row["institution_buy_vs_prev5_mean"],
            "close_price": base_close,
        }

        for metric in METRICS:
            stats = stock_stats[metric]
            enriched_row[f"{metric}_p95"] = stats.p95
            enriched_row[f"{metric}_threshold"] = stats.anomaly_threshold
            enriched_row[f"{metric}_score"] = anomaly_score(row[metric], stats)
            enriched_row[f"{metric}_percentile"] = row[f"{metric}_percentile"]

        add_signal_flags(enriched_row, stock_stats)

        for horizon in HORIZONS:
            future_index = price_index + horizon
            if future_index < len(prices_by_stock[stock_code]):
                future_close = prices_by_stock[stock_code][future_index]["close_price"]
                enriched_row[f"future_close_{horizon}d"] = future_close
                enriched_row[f"future_return_{horizon}d"] = future_close / base_close - 1
                enriched_row[f"future_up_{horizon}d"] = int(future_close > base_close)
            else:
                enriched_row[f"future_close_{horizon}d"] = None
                enriched_row[f"future_return_{horizon}d"] = None
                enriched_row[f"future_up_{horizon}d"] = None

        enriched.append(enriched_row)

    return enriched


def summarize_signals(enriched_rows: list[dict]) -> list[dict]:
    summaries: list[dict] = []
    for horizon in HORIZONS:
        return_key = f"future_return_{horizon}d"
        up_key = f"future_up_{horizon}d"
        valid_rows = [row for row in enriched_rows if row[return_key] is not None]
        all_returns = [row[return_key] for row in valid_rows]
        baseline_mean = mean_or_none(all_returns)
        baseline_up_rate = mean_or_none(row[up_key] for row in valid_rows)

        for signal_key, signal_label in SIGNALS:
            event_rows = [row for row in valid_rows if row[signal_key] == 1]
            non_event_rows = [row for row in valid_rows if row[signal_key] == 0]
            event_returns = [row[return_key] for row in event_rows]
            non_event_returns = [row[return_key] for row in non_event_rows]
            event_mean = mean_or_none(event_returns)
            non_event_mean = mean_or_none(non_event_returns)
            event_up_rate = mean_or_none(row[up_key] for row in event_rows)
            non_event_up_rate = mean_or_none(row[up_key] for row in non_event_rows)
            xs_signal = [float(row[signal_key]) for row in valid_rows]
            ys_returns = [row[return_key] for row in valid_rows]

            summaries.append(
                {
                    "signal": signal_key,
                    "signal_label": signal_label,
                    "horizon_days": horizon,
                    "valid_sample_count": len(valid_rows),
                    "event_count": len(event_rows),
                    "non_event_count": len(non_event_rows),
                    "event_mean_return": event_mean,
                    "event_median_return": median_or_none(event_returns),
                    "event_up_rate": event_up_rate,
                    "baseline_mean_return": baseline_mean,
                    "baseline_up_rate": baseline_up_rate,
                    "non_event_mean_return": non_event_mean,
                    "non_event_median_return": median_or_none(non_event_returns),
                    "non_event_up_rate": non_event_up_rate,
                    "event_vs_baseline_mean_diff": None
                    if event_mean is None or baseline_mean is None
                    else event_mean - baseline_mean,
                    "event_vs_baseline_up_rate_diff": None
                    if event_up_rate is None or baseline_up_rate is None
                    else event_up_rate - baseline_up_rate,
                    "event_vs_non_event_mean_diff": None
                    if event_mean is None or non_event_mean is None
                    else event_mean - non_event_mean,
                    "event_vs_non_event_up_rate_diff": None
                    if event_up_rate is None or non_event_up_rate is None
                    else event_up_rate - non_event_up_rate,
                    "signal_return_pearson": pearson(xs_signal, ys_returns),
                }
            )
    return summaries


def first_signal_rows(
    enriched_rows: list[dict],
    signal_key: str,
    cooldown_days: int,
) -> list[dict]:
    rows_by_stock: dict[str, list[dict]] = defaultdict(list)
    for row in enriched_rows:
        rows_by_stock[row["stock_code"]].append(row)

    first_rows: list[dict] = []
    for rows in rows_by_stock.values():
        last_signal_index: int | None = None
        for row in sorted(rows, key=lambda item: item["stock_row_index"]):
            if row[signal_key] != 1:
                continue
            current_index = row["stock_row_index"]
            if (
                last_signal_index is None
                or current_index - last_signal_index > cooldown_days
            ):
                first_rows.append(row)
            last_signal_index = current_index
    return first_rows


def first_trigger_after_quiet_rows(
    enriched_rows: list[dict],
    trigger_signal_key: str,
    blocker_signal_key: str,
    quiet_days: int,
) -> list[dict]:
    rows_by_stock: dict[str, list[dict]] = defaultdict(list)
    for row in enriched_rows:
        rows_by_stock[row["stock_code"]].append(row)

    first_rows: list[dict] = []
    for rows in rows_by_stock.values():
        last_blocker_index: int | None = None
        for row in sorted(rows, key=lambda item: item["stock_row_index"]):
            current_index = row["stock_row_index"]
            had_recent_blocker = (
                last_blocker_index is not None
                and current_index - last_blocker_index <= quiet_days
            )
            if row[trigger_signal_key] == 1 and not had_recent_blocker:
                first_rows.append(row)
            if row[blocker_signal_key] == 1:
                last_blocker_index = current_index
    return first_rows


def summarize_first_signals(enriched_rows: list[dict]) -> list[dict]:
    summaries: list[dict] = []
    first_rows_cache: dict[tuple[str, int], list[dict]] = {}
    for signal_key, signal_label in SIGNALS:
        for cooldown_days in COOLDOWN_WINDOWS:
            first_rows_cache[(signal_key, cooldown_days)] = first_signal_rows(
                enriched_rows,
                signal_key,
                cooldown_days,
            )

    for horizon in HORIZONS:
        return_key = f"future_return_{horizon}d"
        up_key = f"future_up_{horizon}d"
        valid_rows = [row for row in enriched_rows if row[return_key] is not None]
        valid_ids = {id(row) for row in valid_rows}
        baseline_mean = mean_or_none(row[return_key] for row in valid_rows)
        baseline_up_rate = mean_or_none(row[up_key] for row in valid_rows)

        for signal_key, signal_label in SIGNALS:
            raw_event_rows = [row for row in valid_rows if row[signal_key] == 1]
            for cooldown_days in COOLDOWN_WINDOWS:
                event_rows = [
                    row
                    for row in first_rows_cache[(signal_key, cooldown_days)]
                    if id(row) in valid_ids
                ]
                event_returns = [row[return_key] for row in event_rows]
                event_mean = mean_or_none(event_returns)
                event_up_rate = mean_or_none(row[up_key] for row in event_rows)
                summaries.append(
                    {
                        "signal": signal_key,
                        "signal_label": signal_label,
                        "cooldown_days": cooldown_days,
                        "horizon_days": horizon,
                        "valid_sample_count": len(valid_rows),
                        "raw_event_count": len(raw_event_rows),
                        "first_event_count": len(event_rows),
                        "event_mean_return": event_mean,
                        "event_median_return": median_or_none(event_returns),
                        "event_up_rate": event_up_rate,
                        "baseline_mean_return": baseline_mean,
                        "baseline_up_rate": baseline_up_rate,
                        "event_vs_baseline_mean_diff": None
                        if event_mean is None or baseline_mean is None
                        else event_mean - baseline_mean,
                        "event_vs_baseline_up_rate_diff": None
                        if event_up_rate is None or baseline_up_rate is None
                        else event_up_rate - baseline_up_rate,
                    }
                )
    return summaries


def summarize_first_trigger_after_quiet(enriched_rows: list[dict]) -> list[dict]:
    trigger_signal_key = "positive_net_buy_ratio_2_to_3x"
    trigger_signal_label = "净买入为正 + 买入额为昨日2-3倍"
    blocker_signal_key = "positive_net_buy_ratio_2x"
    blocker_signal_label = "净买入为正 + 买入额较昨日>=2倍"
    rows: list[dict] = []
    first_rows_cache = {
        quiet_days: first_trigger_after_quiet_rows(
            enriched_rows,
            trigger_signal_key,
            blocker_signal_key,
            quiet_days,
        )
        for quiet_days in COOLDOWN_WINDOWS
    }

    for horizon in HORIZONS:
        return_key = f"future_return_{horizon}d"
        up_key = f"future_up_{horizon}d"
        valid_rows = [row for row in enriched_rows if row[return_key] is not None]
        valid_ids = {id(row) for row in valid_rows}
        baseline_mean = mean_or_none(row[return_key] for row in valid_rows)
        baseline_up_rate = mean_or_none(row[up_key] for row in valid_rows)
        raw_event_count = sum(row[trigger_signal_key] == 1 for row in valid_rows)

        for quiet_days in COOLDOWN_WINDOWS:
            event_rows = [
                row for row in first_rows_cache[quiet_days] if id(row) in valid_ids
            ]
            event_returns = [row[return_key] for row in event_rows]
            event_mean = mean_or_none(event_returns)
            event_up_rate = mean_or_none(row[up_key] for row in event_rows)
            rows.append(
                {
                    "trigger_signal": trigger_signal_key,
                    "trigger_signal_label": trigger_signal_label,
                    "blocker_signal": blocker_signal_key,
                    "blocker_signal_label": blocker_signal_label,
                    "quiet_days": quiet_days,
                    "horizon_days": horizon,
                    "valid_sample_count": len(valid_rows),
                    "raw_event_count": raw_event_count,
                    "first_event_count": len(event_rows),
                    "event_mean_return": event_mean,
                    "event_median_return": median_or_none(event_returns),
                    "event_up_rate": event_up_rate,
                    "baseline_mean_return": baseline_mean,
                    "baseline_up_rate": baseline_up_rate,
                    "event_vs_baseline_mean_diff": None
                    if event_mean is None or baseline_mean is None
                    else event_mean - baseline_mean,
                    "event_vs_baseline_up_rate_diff": None
                    if event_up_rate is None or baseline_up_rate is None
                    else event_up_rate - baseline_up_rate,
                }
            )
    return rows


def summarize_correlations(enriched_rows: list[dict]) -> list[dict]:
    feature_columns = [
        ("net_inflow_wan_shou_score", "净买入稳健强度"),
        ("institution_buy_wan_shou_score", "买入额稳健强度"),
        ("institution_activity_wan_shou_score", "买卖总额稳健强度"),
        ("institution_buy_delta_wan_shou_score", "买入额日增量稳健强度"),
        ("institution_buy_ratio", "买入额较昨日倍数"),
        ("institution_buy_vs_prev5_mean", "买入额相对前5日均值倍数"),
        ("net_inflow_wan_shou_percentile", "净买入本股分位"),
        ("institution_buy_wan_shou_percentile", "买入额本股分位"),
        ("institution_activity_wan_shou_percentile", "买卖总额本股分位"),
        ("institution_buy_delta_wan_shou_percentile", "买入额日增量本股分位"),
        ("institution_buy_ratio_percentile", "买入额环比倍数本股分位"),
        ("net_activity_ratio", "净买入/买卖总额"),
    ]

    rows: list[dict] = []
    for horizon in HORIZONS:
        return_key = f"future_return_{horizon}d"
        valid_rows = [
            row
            for row in enriched_rows
            if row[return_key] is not None and row["net_activity_ratio"] is not None
        ]
        ys = [row[return_key] for row in valid_rows]
        for feature, feature_label in feature_columns:
            xs = [row[feature] for row in valid_rows]
            rows.append(
                {
                    "horizon_days": horizon,
                    "feature": feature,
                    "feature_label": feature_label,
                    "sample_count": len(valid_rows),
                    "pearson": pearson(xs, ys),
                    "spearman": spearman(xs, ys),
                }
            )
    return rows


def buy_attention_group(row: dict) -> str:
    percentile_value = row["institution_buy_wan_shou_percentile"]
    if percentile_value >= 0.8:
        return "high_top20"
    if percentile_value >= 0.5:
        return "middle_50_80"
    return "low_bottom50"


def summarize_positive_net_attention(enriched_rows: list[dict]) -> list[dict]:
    rows: list[dict] = []
    group_labels = {
        "low_bottom50": "净买入为正，买入额低于本股中位",
        "middle_50_80": "净买入为正，买入额位于本股50%-80%",
        "high_top20": "净买入为正，买入额处于本股前20%",
    }

    for horizon in HORIZONS:
        return_key = f"future_return_{horizon}d"
        up_key = f"future_up_{horizon}d"
        valid_rows = [
            row
            for row in enriched_rows
            if row[return_key] is not None and row["net_inflow_wan_shou"] > 0
        ]
        baseline_mean = mean_or_none(row[return_key] for row in valid_rows)
        baseline_up_rate = mean_or_none(row[up_key] for row in valid_rows)

        for group in ["low_bottom50", "middle_50_80", "high_top20"]:
            group_rows = [row for row in valid_rows if buy_attention_group(row) == group]
            group_returns = [row[return_key] for row in group_rows]
            group_mean = mean_or_none(group_returns)
            group_up_rate = mean_or_none(row[up_key] for row in group_rows)
            rows.append(
                {
                    "horizon_days": horizon,
                    "group": group,
                    "group_label": group_labels[group],
                    "sample_count": len(group_rows),
                    "mean_return": group_mean,
                    "median_return": median_or_none(group_returns),
                    "up_rate": group_up_rate,
                    "positive_net_baseline_mean_return": baseline_mean,
                    "positive_net_baseline_up_rate": baseline_up_rate,
                    "mean_diff_vs_positive_net_baseline": None
                    if group_mean is None or baseline_mean is None
                    else group_mean - baseline_mean,
                    "up_rate_diff_vs_positive_net_baseline": None
                    if group_up_rate is None or baseline_up_rate is None
                    else group_up_rate - baseline_up_rate,
                }
            )
    return rows


def buy_jump_group(row: dict) -> str:
    ratio = row["institution_buy_ratio"]
    if ratio >= 3:
        return "jump_3x"
    if ratio >= 2:
        return "jump_2_3x"
    if ratio >= 1:
        return "flat_1_2x"
    return "down"


def summarize_positive_net_buy_jump(enriched_rows: list[dict]) -> list[dict]:
    rows: list[dict] = []
    group_labels = {
        "down": "净买入为正，买入额低于昨日",
        "flat_1_2x": "净买入为正，买入额为昨日1-2倍",
        "jump_2_3x": "净买入为正，买入额为昨日2-3倍",
        "jump_3x": "净买入为正，买入额达到昨日3倍以上",
    }

    for horizon in HORIZONS:
        return_key = f"future_return_{horizon}d"
        up_key = f"future_up_{horizon}d"
        valid_rows = [
            row
            for row in enriched_rows
            if row[return_key] is not None
            and row["net_inflow_wan_shou"] > 0
            and row["has_previous_fund_day"]
        ]
        baseline_mean = mean_or_none(row[return_key] for row in valid_rows)
        baseline_up_rate = mean_or_none(row[up_key] for row in valid_rows)

        for group in ["down", "flat_1_2x", "jump_2_3x", "jump_3x"]:
            group_rows = [row for row in valid_rows if buy_jump_group(row) == group]
            group_returns = [row[return_key] for row in group_rows]
            group_mean = mean_or_none(group_returns)
            group_up_rate = mean_or_none(row[up_key] for row in group_rows)
            rows.append(
                {
                    "horizon_days": horizon,
                    "group": group,
                    "group_label": group_labels[group],
                    "sample_count": len(group_rows),
                    "mean_return": group_mean,
                    "median_return": median_or_none(group_returns),
                    "up_rate": group_up_rate,
                    "positive_net_baseline_mean_return": baseline_mean,
                    "positive_net_baseline_up_rate": baseline_up_rate,
                    "mean_diff_vs_positive_net_baseline": None
                    if group_mean is None or baseline_mean is None
                    else group_mean - baseline_mean,
                    "up_rate_diff_vs_positive_net_baseline": None
                    if group_up_rate is None or baseline_up_rate is None
                    else group_up_rate - baseline_up_rate,
                }
            )
    return rows


def write_csv(path: Path, rows: list[dict], fieldnames: list[str]) -> None:
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def metric_detail(row: dict, metric: str) -> dict:
    return {
        "metric": metric,
        "metric_label": METRIC_LABELS[metric],
        "value": row[metric],
        "p95": row[f"{metric}_p95"],
        "threshold": row[f"{metric}_threshold"],
        "score": row[f"{metric}_score"],
        "percentile": row[f"{metric}_percentile"],
    }


def condition_detail(
    label: str,
    value: float | int | None,
    operator: str,
    target: float | int | None,
    note: str = "",
) -> dict:
    text = f"{label}: {num(value, 4)} {operator} {num(target, 4)}"
    if note:
        text = f"{text}，{note}"
    return {
        "label": label,
        "value": value,
        "operator": operator,
        "target": target,
        "note": note,
        "text": text,
    }


def threshold_note(metric: str) -> str:
    return (
        f"本股{METRIC_LABELS[metric]}异常阈值，"
        "max(P95, Q3+1.5*IQR, median+3*1.4826*MAD)"
    )


def signal_reason(row: dict, signal_key: str) -> dict:
    net_metric = "net_inflow_wan_shou"
    buy_metric = "institution_buy_wan_shou"
    activity_metric = "institution_activity_wan_shou"
    delta_metric = "institution_buy_delta_wan_shou"
    conditions: list[dict] = []

    net = row["net_inflow_wan_shou"]
    buy = row["institution_buy_wan_shou"]
    activity = row["institution_activity_wan_shou"]
    buy_delta = row["institution_buy_delta_wan_shou"]
    buy_ratio = row["institution_buy_ratio"]
    buy_vs_prev5_mean = row["institution_buy_vs_prev5_mean"]
    previous_buy = row["previous_institution_buy_wan_shou"]
    previous_5day_mean = row["previous_5day_buy_mean_wan_shou"]
    has_previous = row["has_previous_fund_day"]

    if signal_key == "net_anomaly":
        conditions.append(condition_detail("机构净买入", net, ">", 0))
        conditions.append(
            condition_detail(
                "机构净买入",
                net,
                ">=",
                row[f"{net_metric}_threshold"],
                threshold_note(net_metric),
            )
        )
    elif signal_key == "buy_attention":
        conditions.append(condition_detail("机构买入额", buy, ">", 0))
        conditions.append(
            condition_detail(
                "机构买入额",
                buy,
                ">=",
                row[f"{buy_metric}_threshold"],
                threshold_note(buy_metric),
            )
        )
    elif signal_key == "positive_net_buy_attention":
        conditions.append(condition_detail("机构净买入", net, ">", 0))
        conditions.append(
            condition_detail(
                "机构买入额",
                buy,
                ">=",
                row[f"{buy_metric}_threshold"],
                threshold_note(buy_metric),
            )
        )
    elif signal_key == "positive_net_activity_attention":
        conditions.append(condition_detail("机构净买入", net, ">", 0))
        conditions.append(
            condition_detail(
                "机构买卖总额",
                activity,
                ">=",
                row[f"{activity_metric}_threshold"],
                threshold_note(activity_metric),
            )
        )
    elif signal_key == "net_and_buy_anomaly":
        conditions.append(
            condition_detail(
                "机构净买入",
                net,
                ">=",
                row[f"{net_metric}_threshold"],
                threshold_note(net_metric),
            )
        )
        conditions.append(
            condition_detail(
                "机构买入额",
                buy,
                ">=",
                row[f"{buy_metric}_threshold"],
                threshold_note(buy_metric),
            )
        )
    elif signal_key == "positive_net_top20_buy":
        conditions.append(condition_detail("机构净买入", net, ">", 0))
        conditions.append(
            condition_detail(
                "机构买入额历史分位",
                row["institution_buy_wan_shou_percentile"],
                ">=",
                0.8,
                "处于本股历史前20%",
            )
        )
    elif signal_key == "positive_net_buy_ratio_2x":
        conditions.append(condition_detail("机构净买入", net, ">", 0))
        conditions.append(condition_detail("存在前一资金流日", has_previous, "=", 1))
        conditions.append(
            condition_detail(
                "机构买入额/昨日买入额",
                buy_ratio,
                ">=",
                2,
                f"{num(buy, 4)} / {num(previous_buy, 4)}",
            )
        )
    elif signal_key == "positive_net_buy_ratio_2_to_3x":
        conditions.append(condition_detail("机构净买入", net, ">", 0))
        conditions.append(condition_detail("存在前一资金流日", has_previous, "=", 1))
        conditions.append(
            condition_detail(
                "机构买入额/昨日买入额",
                buy_ratio,
                ">=",
                2,
                f"{num(buy, 4)} / {num(previous_buy, 4)}",
            )
        )
        conditions.append(condition_detail("机构买入额/昨日买入额", buy_ratio, "<", 3))
    elif signal_key == "positive_net_buy_ratio_3x":
        conditions.append(condition_detail("机构净买入", net, ">", 0))
        conditions.append(condition_detail("存在前一资金流日", has_previous, "=", 1))
        conditions.append(
            condition_detail(
                "机构买入额/昨日买入额",
                buy_ratio,
                ">=",
                3,
                f"{num(buy, 4)} / {num(previous_buy, 4)}",
            )
        )
    elif signal_key == "positive_net_buy_vs_prev5_2x":
        conditions.append(condition_detail("机构净买入", net, ">", 0))
        conditions.append(condition_detail("存在前一资金流日", has_previous, "=", 1))
        conditions.append(
            condition_detail(
                "机构买入额/前5日均值",
                buy_vs_prev5_mean,
                ">=",
                2,
                f"{num(buy, 4)} / {num(previous_5day_mean, 4)}",
            )
        )
    elif signal_key == "positive_net_buy_delta_anomaly":
        conditions.append(condition_detail("机构净买入", net, ">", 0))
        conditions.append(condition_detail("存在前一资金流日", has_previous, "=", 1))
        conditions.append(
            condition_detail(
                "机构买入额较昨日增量",
                buy_delta,
                ">=",
                row[f"{delta_metric}_threshold"],
                threshold_note(delta_metric),
            )
        )
    elif signal_key == "positive_net_buy_ratio_top10":
        conditions.append(condition_detail("机构净买入", net, ">", 0))
        conditions.append(condition_detail("存在前一资金流日", has_previous, "=", 1))
        conditions.append(
            condition_detail(
                "机构买入额环比倍数历史分位",
                row["institution_buy_ratio_percentile"],
                ">=",
                0.9,
                "处于本股历史前10%",
            )
        )

    return {
        "signal": signal_key,
        "signal_label": dict(SIGNALS)[signal_key],
        "summary": "；".join(condition["text"] for condition in conditions),
        "conditions": conditions,
    }


def build_signal_inspection_data(
    enriched_rows: list[dict],
    stats_by_stock: dict[str, dict[str, MetricStats]],
) -> dict:
    rows_by_stock: dict[str, list[dict]] = defaultdict(list)
    for row in enriched_rows:
        rows_by_stock[row["stock_code"]].append(row)

    total_signal_counts = {signal: 0 for signal, _ in SIGNALS}
    stocks: list[dict] = []
    for stock_code, stock_rows in sorted(rows_by_stock.items()):
        ordered_rows = sorted(
            stock_rows,
            key=lambda item: (item["trade_date"], item["stock_row_index"]),
        )
        events: list[dict] = []
        stock_signal_counts = {signal: 0 for signal, _ in SIGNALS}

        for index, row in enumerate(ordered_rows):
            triggered_signals = [
                signal_reason(row, signal)
                for signal, _ in SIGNALS
                if row[signal] == 1
            ]
            if not triggered_signals:
                continue

            for reason in triggered_signals:
                total_signal_counts[reason["signal"]] += 1
                stock_signal_counts[reason["signal"]] += 1

            event = {
                "series_index": index,
                "stock_code": stock_code,
                "trade_date": row["trade_date"],
                "stock_row_index": row["stock_row_index"],
                "close_price": row["close_price"],
                "institution_buy_wan_shou": row["institution_buy_wan_shou"],
                "institution_sell_wan_shou": row["institution_sell_wan_shou"],
                "net_inflow_wan_shou": row["net_inflow_wan_shou"],
                "institution_activity_wan_shou": row[
                    "institution_activity_wan_shou"
                ],
                "net_activity_ratio": row["net_activity_ratio"],
                "previous_institution_buy_wan_shou": row[
                    "previous_institution_buy_wan_shou"
                ],
                "previous_5day_buy_mean_wan_shou": row[
                    "previous_5day_buy_mean_wan_shou"
                ],
                "institution_buy_delta_wan_shou": row[
                    "institution_buy_delta_wan_shou"
                ],
                "institution_buy_ratio": row["institution_buy_ratio"],
                "institution_buy_vs_prev5_mean": row[
                    "institution_buy_vs_prev5_mean"
                ],
                "metrics": {
                    metric: metric_detail(row, metric)
                    for metric in METRICS
                },
                "future_returns": {
                    f"{horizon}d": row[f"future_return_{horizon}d"]
                    for horizon in HORIZONS
                },
                "future_up": {
                    f"{horizon}d": row[f"future_up_{horizon}d"]
                    for horizon in HORIZONS
                },
                "triggered_signals": triggered_signals,
            }
            events.append(event)

        if not events:
            continue

        stocks.append(
            {
                "stock_code": stock_code,
                "date_range": {
                    "start": ordered_rows[0]["trade_date"],
                    "end": ordered_rows[-1]["trade_date"],
                },
                "event_count": len(events),
                "signal_counts": stock_signal_counts,
                "series": {
                    "trade_date": [row["trade_date"] for row in ordered_rows],
                    "close_price": [row["close_price"] for row in ordered_rows],
                    "institution_buy_wan_shou": [
                        row["institution_buy_wan_shou"] for row in ordered_rows
                    ],
                    "institution_sell_wan_shou": [
                        row["institution_sell_wan_shou"] for row in ordered_rows
                    ],
                    "net_inflow_wan_shou": [
                        row["net_inflow_wan_shou"] for row in ordered_rows
                    ],
                    "institution_buy_ratio": [
                        row["institution_buy_ratio"] for row in ordered_rows
                    ],
                    "institution_buy_vs_prev5_mean": [
                        row["institution_buy_vs_prev5_mean"] for row in ordered_rows
                    ],
                },
                "thresholds": {
                    metric: {
                        "metric_label": METRIC_LABELS[metric],
                        "p95": stats_by_stock[stock_code][metric].p95,
                        "threshold": stats_by_stock[stock_code][metric].anomaly_threshold,
                        "median": stats_by_stock[stock_code][metric].median,
                        "mad_scaled": stats_by_stock[stock_code][metric].mad_scaled,
                        "q1": stats_by_stock[stock_code][metric].q1,
                        "q3": stats_by_stock[stock_code][metric].q3,
                        "iqr": stats_by_stock[stock_code][metric].iqr,
                    }
                    for metric in METRICS
                },
                "events": events,
            }
        )

    stocks.sort(key=lambda item: (-item["event_count"], item["stock_code"]))
    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "source": {
            "database": str(DB_PATH),
            "adjust": ADJUST,
            "horizons": HORIZONS,
        },
        "signals": [
            {
                "signal": signal,
                "signal_label": label,
                "event_count": total_signal_counts[signal],
            }
            for signal, label in SIGNALS
        ],
        "metrics": [
            {"metric": metric, "metric_label": METRIC_LABELS[metric]}
            for metric in METRICS
        ],
        "stock_count": len(stocks),
        "event_count": sum(stock["event_count"] for stock in stocks),
        "stocks": stocks,
    }


def signal_inspection_html(data: dict) -> str:
    data_json = json.dumps(data, ensure_ascii=False, allow_nan=False).replace(
        "</",
        "<\\/",
    )
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>股票信号触发位置检查</title>
  <script src="https://cdn.jsdelivr.net/npm/echarts@5/dist/echarts.min.js"></script>
  <style>
    :root {{
      color-scheme: light;
      --bg: #f6f7f9;
      --panel: #ffffff;
      --line: #d9dee7;
      --text: #1f2937;
      --muted: #667085;
      --accent: #2563eb;
      --accent-soft: #dbeafe;
      --red: #dc2626;
      --green: #059669;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      background: var(--bg);
      color: var(--text);
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Microsoft YaHei", sans-serif;
      font-size: 14px;
    }}
    header {{
      padding: 18px 24px 12px;
      border-bottom: 1px solid var(--line);
      background: var(--panel);
    }}
    h1 {{
      margin: 0 0 8px;
      font-size: 22px;
      font-weight: 700;
      letter-spacing: 0;
    }}
    .meta {{
      color: var(--muted);
      display: flex;
      flex-wrap: wrap;
      gap: 14px;
    }}
    main {{
      display: grid;
      grid-template-columns: minmax(260px, 320px) minmax(0, 1fr);
      gap: 16px;
      padding: 16px 24px 24px;
    }}
    aside, section {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
    }}
    aside {{
      padding: 14px;
      align-self: start;
      position: sticky;
      top: 12px;
      max-height: calc(100vh - 24px);
      overflow: auto;
    }}
    label {{
      display: block;
      margin: 12px 0 6px;
      color: var(--muted);
      font-size: 12px;
    }}
    select, input {{
      width: 100%;
      height: 34px;
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 0 10px;
      background: white;
      color: var(--text);
    }}
    .stats {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 8px;
      margin-top: 12px;
    }}
    .stat {{
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 9px;
      min-height: 58px;
    }}
    .stat b {{
      display: block;
      font-size: 18px;
      margin-bottom: 4px;
    }}
    .stat span {{ color: var(--muted); font-size: 12px; }}
    .signal-counts {{
      margin-top: 14px;
      display: grid;
      gap: 6px;
    }}
    .signal-count {{
      display: flex;
      justify-content: space-between;
      gap: 10px;
      border-bottom: 1px solid #eef1f5;
      padding: 5px 0;
      color: var(--muted);
      line-height: 1.35;
    }}
    .signal-count strong {{ color: var(--text); }}
    .content {{
      display: grid;
      gap: 16px;
    }}
    .chart {{
      height: 390px;
      width: 100%;
    }}
    .chart-wrap {{
      padding: 12px;
    }}
    .section-title {{
      display: flex;
      justify-content: space-between;
      gap: 12px;
      align-items: center;
      padding: 12px 14px 0;
      color: var(--muted);
    }}
    .section-title strong {{
      color: var(--text);
      font-size: 15px;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      table-layout: fixed;
      font-size: 13px;
    }}
    th, td {{
      border-top: 1px solid var(--line);
      padding: 8px 10px;
      vertical-align: top;
      text-align: left;
      word-break: break-word;
    }}
    th {{
      background: #f8fafc;
      color: var(--muted);
      font-weight: 600;
      position: sticky;
      top: 0;
      z-index: 1;
    }}
    tr:hover td {{ background: #f8fbff; }}
    .table-wrap {{
      max-height: 520px;
      overflow: auto;
      border-top: 1px solid var(--line);
      margin-top: 12px;
    }}
    .badge {{
      display: inline-flex;
      align-items: center;
      min-height: 20px;
      padding: 2px 6px;
      border-radius: 999px;
      background: var(--accent-soft);
      color: var(--accent);
      margin: 0 4px 4px 0;
      font-size: 12px;
      line-height: 1.25;
    }}
    .up {{ color: var(--red); }}
    .down {{ color: var(--green); }}
    @media (max-width: 900px) {{
      main {{ grid-template-columns: 1fr; padding: 12px; }}
      aside {{ position: static; max-height: none; }}
      .chart {{ height: 320px; }}
    }}
  </style>
</head>
<body>
  <header>
    <h1>股票信号触发位置检查</h1>
    <div class="meta">
      <span id="globalMeta"></span>
      <span>数据文件：signal_inspection.json</span>
    </div>
  </header>
  <main>
    <aside>
      <label for="stockSelect">股票</label>
      <select id="stockSelect"></select>
      <label for="signalSelect">信号过滤</label>
      <select id="signalSelect"></select>
      <label for="searchInput">日期/原因搜索</label>
      <input id="searchInput" placeholder="例如 2025-04 或 2-3倍" />
      <div class="stats">
        <div class="stat"><b id="stockEvents">0</b><span>当前事件数</span></div>
        <div class="stat"><b id="stockRange">-</b><span>日期范围</span></div>
      </div>
      <div class="signal-counts" id="signalCounts"></div>
    </aside>
    <div class="content">
      <section>
        <div class="section-title">
          <strong>价格与信号位置</strong>
          <span id="chartHint"></span>
        </div>
        <div class="chart-wrap"><div id="priceChart" class="chart"></div></div>
      </section>
      <section>
        <div class="section-title">
          <strong>资金流与触发点</strong>
          <span>买入/卖出/净流入单位：万手</span>
        </div>
        <div class="chart-wrap"><div id="fundChart" class="chart"></div></div>
      </section>
      <section>
        <div class="section-title">
          <strong>触发明细与计算原因</strong>
          <span id="tableMeta"></span>
        </div>
        <div class="table-wrap">
          <table>
            <thead>
              <tr>
                <th style="width: 96px;">日期</th>
                <th style="width: 86px;">收盘</th>
                <th style="width: 210px;">触发信号</th>
                <th>计算原因</th>
                <th style="width: 118px;">5日收益</th>
              </tr>
            </thead>
            <tbody id="eventRows"></tbody>
          </table>
        </div>
      </section>
    </div>
  </main>
  <script id="signal-data" type="application/json">{data_json}</script>
  <script>
    const data = JSON.parse(document.getElementById('signal-data').textContent);
    const stockSelect = document.getElementById('stockSelect');
    const signalSelect = document.getElementById('signalSelect');
    const searchInput = document.getElementById('searchInput');
    const priceChart = echarts.init(document.getElementById('priceChart'));
    const fundChart = echarts.init(document.getElementById('fundChart'));
    const byCode = new Map(data.stocks.map(stock => [stock.stock_code, stock]));
    const signalLabels = new Map(data.signals.map(signal => [signal.signal, signal.signal_label]));

    function fmt(value, digits = 2) {{
      if (value === null || value === undefined || Number.isNaN(value)) return '-';
      return Number(value).toFixed(digits);
    }}
    function pct(value) {{
      if (value === null || value === undefined || Number.isNaN(value)) return '-';
      const cls = value >= 0 ? 'up' : 'down';
      return `<span class="${{cls}}">${{(value * 100).toFixed(2)}}%</span>`;
    }}
    function esc(text) {{
      return String(text ?? '').replace(/[&<>"']/g, char => ({{
        '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
      }}[char]));
    }}
    function activeStock() {{
      return byCode.get(stockSelect.value) || data.stocks[0];
    }}
    function eventSignals(event) {{
      const selected = signalSelect.value;
      return selected === 'all'
        ? event.triggered_signals
        : event.triggered_signals.filter(signal => signal.signal === selected);
    }}
    function filteredEvents(stock) {{
      const query = searchInput.value.trim().toLowerCase();
      return stock.events.filter(event => {{
        const signals = eventSignals(event);
        if (!signals.length) return false;
        if (!query) return true;
        const haystack = [
          event.trade_date,
          event.stock_code,
          ...signals.map(signal => signal.signal_label),
          ...signals.map(signal => signal.summary)
        ].join(' ').toLowerCase();
        return haystack.includes(query);
      }});
    }}
    function tooltipEvent(event) {{
      const reasons = eventSignals(event).map(signal => {{
        const items = signal.conditions.map(item => `<li>${{esc(item.text)}}</li>`).join('');
        return `<div style="margin-top:8px"><b>${{esc(signal.signal_label)}}</b><ul style="margin:5px 0 0 18px;padding:0">${{items}}</ul></div>`;
      }}).join('');
      return `
        <div style="max-width:520px;white-space:normal;line-height:1.45">
          <b>${{esc(event.stock_code)}} ${{esc(event.trade_date)}}</b><br/>
          收盘：${{fmt(event.close_price)}}，净买入：${{fmt(event.net_inflow_wan_shou, 4)}}，买入额：${{fmt(event.institution_buy_wan_shou, 4)}}<br/>
          昨日买入：${{fmt(event.previous_institution_buy_wan_shou, 4)}}，买入/昨日：${{fmt(event.institution_buy_ratio, 4)}}，买入/前5均：${{fmt(event.institution_buy_vs_prev5_mean, 4)}}
          ${{reasons}}
        </div>`;
    }}
    function renderControls() {{
      stockSelect.innerHTML = data.stocks.map(stock => (
        `<option value="${{esc(stock.stock_code)}}">${{esc(stock.stock_code)}}（${{stock.event_count}}）</option>`
      )).join('');
      signalSelect.innerHTML = '<option value="all">全部信号</option>' + data.signals.map(signal => (
        `<option value="${{esc(signal.signal)}}">${{esc(signal.signal_label)}}（${{signal.event_count}}）</option>`
      )).join('');
      document.getElementById('globalMeta').textContent =
        `生成时间：${{data.generated_at}}，股票：${{data.stock_count}}，事件：${{data.event_count}}`;
    }}
    function renderCharts(stock, events) {{
      const dates = stock.series.trade_date;
      const close = stock.series.close_price;
      const buy = stock.series.institution_buy_wan_shou;
      const sell = stock.series.institution_sell_wan_shou;
      const net = stock.series.net_inflow_wan_shou;
      const markersOnPrice = events.map(event => ({{
        value: [event.trade_date, event.close_price],
        event,
        symbolSize: Math.max(9, Math.min(24, 8 + event.triggered_signals.length * 3))
      }}));
      const markersOnFund = events.map(event => ({{
        value: [event.trade_date, event.institution_buy_wan_shou],
        event,
        symbolSize: Math.max(9, Math.min(24, 8 + event.triggered_signals.length * 3))
      }}));
      const sharedZoom = [
        {{ type: 'inside', xAxisIndex: [0], filterMode: 'none' }},
        {{ type: 'slider', xAxisIndex: [0], height: 22, bottom: 6 }}
      ];
      priceChart.setOption({{
        animation: false,
        tooltip: {{
          trigger: 'item',
          confine: true,
          formatter: params => params.data && params.data.event
            ? tooltipEvent(params.data.event)
            : `${{params.seriesName}}<br/>${{params.value[0]}}：${{fmt(params.value[1])}}`
        }},
        legend: {{ top: 0, data: ['收盘价', '触发信号'] }},
        grid: {{ top: 42, right: 26, bottom: 52, left: 54 }},
        xAxis: {{ type: 'time', boundaryGap: false }},
        yAxis: {{ type: 'value', scale: true }},
        dataZoom: sharedZoom,
        series: [
          {{
            name: '收盘价',
            type: 'line',
            showSymbol: false,
            smooth: false,
            lineStyle: {{ width: 1.6, color: '#1f2937' }},
            data: dates.map((date, index) => [date, close[index]])
          }},
          {{
            name: '触发信号',
            type: 'scatter',
            symbol: 'pin',
            itemStyle: {{ color: '#dc2626' }},
            data: markersOnPrice
          }}
        ]
      }}, true);
      fundChart.setOption({{
        animation: false,
        tooltip: {{
          trigger: 'item',
          confine: true,
          formatter: params => params.data && params.data.event
            ? tooltipEvent(params.data.event)
            : `${{params.seriesName}}<br/>${{params.value[0]}}：${{fmt(params.value[1], 4)}}`
        }},
        legend: {{ top: 0, data: ['机构买入额', '机构卖出额', '机构净买入', '触发点'] }},
        grid: {{ top: 42, right: 26, bottom: 52, left: 62 }},
        xAxis: {{ type: 'time' }},
        yAxis: {{ type: 'value', scale: true }},
        dataZoom: sharedZoom,
        series: [
          {{
            name: '机构买入额',
            type: 'bar',
            barMaxWidth: 14,
            itemStyle: {{ color: '#2563eb' }},
            data: dates.map((date, index) => [date, buy[index]])
          }},
          {{
            name: '机构卖出额',
            type: 'bar',
            barMaxWidth: 14,
            itemStyle: {{ color: '#94a3b8' }},
            data: dates.map((date, index) => [date, sell[index]])
          }},
          {{
            name: '机构净买入',
            type: 'line',
            showSymbol: false,
            lineStyle: {{ width: 1.5, color: '#059669' }},
            data: dates.map((date, index) => [date, net[index]])
          }},
          {{
            name: '触发点',
            type: 'scatter',
            symbol: 'diamond',
            itemStyle: {{ color: '#dc2626' }},
            data: markersOnFund
          }}
        ]
      }}, true);
    }}
    function renderTable(events) {{
      const rows = events.map(event => {{
        const signals = eventSignals(event);
        const badges = signals.map(signal => `<span class="badge">${{esc(signal.signal_label)}}</span>`).join('');
        const reasons = signals.map(signal => esc(signal.summary)).join('<br/>');
        return `<tr onclick="zoomToEvent('${{esc(event.stock_code)}}','${{esc(event.trade_date)}}')">
          <td>${{esc(event.trade_date)}}</td>
          <td>${{fmt(event.close_price)}}</td>
          <td>${{badges}}</td>
          <td>${{reasons}}</td>
          <td>${{pct(event.future_returns['5d'])}}</td>
        </tr>`;
      }}).join('');
      document.getElementById('eventRows').innerHTML = rows || '<tr><td colspan="5">当前过滤条件下没有触发点</td></tr>';
      document.getElementById('tableMeta').textContent = `${{events.length}} 条`;
    }}
    function renderSidebar(stock, events) {{
      document.getElementById('stockEvents').textContent = events.length;
      document.getElementById('stockRange').textContent = `${{stock.date_range.start}} 至 ${{stock.date_range.end}}`;
      document.getElementById('chartHint').textContent = `${{stock.stock_code}}，图上红色标记为当前过滤后的触发点`;
      document.getElementById('signalCounts').innerHTML = data.signals.map(signal => {{
        const count = stock.signal_counts[signal.signal] || 0;
        return `<div class="signal-count"><span>${{esc(signal.signal_label)}}</span><strong>${{count}}</strong></div>`;
      }}).join('');
    }}
    function render() {{
      const stock = activeStock();
      const events = filteredEvents(stock);
      renderSidebar(stock, events);
      renderCharts(stock, events);
      renderTable(events);
    }}
    window.zoomToEvent = function(stockCode, tradeDate) {{
      const stock = byCode.get(stockCode);
      if (!stock) return;
      const index = stock.series.trade_date.indexOf(tradeDate);
      const start = stock.series.trade_date[Math.max(0, index - 30)];
      const end = stock.series.trade_date[Math.min(stock.series.trade_date.length - 1, index + 30)];
      [priceChart, fundChart].forEach(chart => {{
        chart.dispatchAction({{ type: 'dataZoom', startValue: start, endValue: end }});
      }});
    }};
    renderControls();
    render();
    stockSelect.addEventListener('change', render);
    signalSelect.addEventListener('change', render);
    searchInput.addEventListener('input', render);
    window.addEventListener('resize', () => {{
      priceChart.resize();
      fundChart.resize();
    }});
  </script>
</body>
</html>
"""


def write_signal_inspection_files(
    enriched_rows: list[dict],
    stats_by_stock: dict[str, dict[str, MetricStats]],
) -> None:
    data = build_signal_inspection_data(enriched_rows, stats_by_stock)
    (OUTPUT_DIR / "signal_inspection.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False),
        encoding="utf-8",
    )
    (OUTPUT_DIR / "signal_inspection.html").write_text(
        signal_inspection_html(data),
        encoding="utf-8",
    )


def write_outputs(
    stats_by_stock: dict[str, dict[str, MetricStats]],
    enriched_rows: list[dict],
    signal_summary_rows: list[dict],
    first_signal_summary_rows: list[dict],
    first_quiet_summary_rows: list[dict],
    correlation_rows: list[dict],
    positive_net_attention_rows: list[dict],
    positive_net_buy_jump_rows: list[dict],
) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    threshold_rows = []
    for stock_metrics in stats_by_stock.values():
        for stats in stock_metrics.values():
            threshold_rows.append(
                {
                    "stock_code": stats.stock_code,
                    "metric": stats.metric,
                    "metric_label": METRIC_LABELS[stats.metric],
                    "count": stats.count,
                    "min_value": stats.min_value,
                    "max_value": stats.max_value,
                    "mean": stats.mean,
                    "p95": stats.p95,
                    "q1": stats.q1,
                    "q3": stats.q3,
                    "iqr": stats.iqr,
                    "median": stats.median,
                    "mad": stats.mad,
                    "mad_scaled": stats.mad_scaled,
                    "iqr_threshold": stats.iqr_threshold,
                    "mad_threshold": stats.mad_threshold,
                    "anomaly_threshold": stats.anomaly_threshold,
                    "event_count": stats.event_count,
                }
            )
    threshold_fields = list(threshold_rows[0].keys()) if threshold_rows else []
    write_csv(OUTPUT_DIR / "metric_thresholds.csv", threshold_rows, threshold_fields)
    write_csv(
        OUTPUT_DIR / "stock_thresholds.csv",
        [
            row
            for row in threshold_rows
            if row["metric"] == "net_inflow_wan_shou"
        ],
        threshold_fields,
    )

    event_fields = [
        "stock_code",
        "trade_date",
        "stock_row_index",
        "institution_buy_wan_shou",
        "institution_sell_wan_shou",
        "net_inflow_wan_shou",
        "institution_activity_wan_shou",
        "net_activity_ratio",
        "has_previous_fund_day",
        "previous_institution_buy_wan_shou",
        "previous_5day_buy_mean_wan_shou",
        "institution_buy_delta_wan_shou",
        "institution_buy_ratio",
        "institution_buy_vs_prev5_mean",
        "close_price",
    ]
    for metric in METRICS:
        event_fields.extend(
            [
                f"{metric}_p95",
                f"{metric}_threshold",
                f"{metric}_score",
                f"{metric}_percentile",
            ]
        )
    event_fields.extend([signal for signal, _ in SIGNALS])
    for horizon in HORIZONS:
        event_fields.extend(
            [
                f"future_close_{horizon}d",
                f"future_return_{horizon}d",
                f"future_up_{horizon}d",
            ]
        )

    event_rows = [
        row for row in enriched_rows if any(row[signal] == 1 for signal, _ in SIGNALS)
    ]
    write_csv(OUTPUT_DIR / "events.csv", event_rows, event_fields)
    write_signal_inspection_files(enriched_rows, stats_by_stock)

    signal_summary_fields = list(signal_summary_rows[0].keys()) if signal_summary_rows else []
    write_csv(
        OUTPUT_DIR / "signal_summary_by_horizon.csv",
        signal_summary_rows,
        signal_summary_fields,
    )
    write_csv(
        OUTPUT_DIR / "summary_by_horizon.csv",
        [
            row
            for row in signal_summary_rows
            if row["signal"] == "net_anomaly"
        ],
        signal_summary_fields,
    )

    first_signal_summary_fields = (
        list(first_signal_summary_rows[0].keys()) if first_signal_summary_rows else []
    )
    write_csv(
        OUTPUT_DIR / "first_signal_summary_by_cooldown.csv",
        first_signal_summary_rows,
        first_signal_summary_fields,
    )

    first_quiet_summary_fields = (
        list(first_quiet_summary_rows[0].keys()) if first_quiet_summary_rows else []
    )
    write_csv(
        OUTPUT_DIR / "first_quiet_signal_summary_by_cooldown.csv",
        first_quiet_summary_rows,
        first_quiet_summary_fields,
    )

    correlation_fields = list(correlation_rows[0].keys()) if correlation_rows else []
    write_csv(
        OUTPUT_DIR / "continuous_correlation_by_horizon.csv",
        correlation_rows,
        correlation_fields,
    )

    attention_fields = (
        list(positive_net_attention_rows[0].keys()) if positive_net_attention_rows else []
    )
    write_csv(
        OUTPUT_DIR / "positive_net_attention_groups.csv",
        positive_net_attention_rows,
        attention_fields,
    )

    jump_fields = (
        list(positive_net_buy_jump_rows[0].keys()) if positive_net_buy_jump_rows else []
    )
    write_csv(
        OUTPUT_DIR / "positive_net_buy_jump_groups.csv",
        positive_net_buy_jump_rows,
        jump_fields,
    )

    quiet_start_event_rows: list[dict] = []
    for quiet_days in COOLDOWN_WINDOWS:
        for row in first_trigger_after_quiet_rows(
            enriched_rows,
            "positive_net_buy_ratio_2_to_3x",
            "positive_net_buy_ratio_2x",
            quiet_days,
        ):
            event_row = {
                "quiet_days": quiet_days,
                "stock_code": row["stock_code"],
                "trade_date": row["trade_date"],
                "stock_row_index": row["stock_row_index"],
                "institution_buy_wan_shou": row["institution_buy_wan_shou"],
                "previous_institution_buy_wan_shou": row[
                    "previous_institution_buy_wan_shou"
                ],
                "institution_buy_ratio": row["institution_buy_ratio"],
                "previous_5day_buy_mean_wan_shou": row[
                    "previous_5day_buy_mean_wan_shou"
                ],
                "institution_buy_vs_prev5_mean": row[
                    "institution_buy_vs_prev5_mean"
                ],
                "institution_sell_wan_shou": row["institution_sell_wan_shou"],
                "net_inflow_wan_shou": row["net_inflow_wan_shou"],
                "net_activity_ratio": row["net_activity_ratio"],
                "close_price": row["close_price"],
            }
            for horizon in HORIZONS:
                event_row[f"future_return_{horizon}d"] = row[
                    f"future_return_{horizon}d"
                ]
                event_row[f"future_up_{horizon}d"] = row[f"future_up_{horizon}d"]
            quiet_start_event_rows.append(event_row)
    quiet_start_event_fields = (
        list(quiet_start_event_rows[0].keys()) if quiet_start_event_rows else []
    )
    write_csv(
        OUTPUT_DIR / "first_quiet_start_events.csv",
        quiet_start_event_rows,
        quiet_start_event_fields,
    )


def markdown_table(headers: list[str], rows: list[list[str]]) -> str:
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join(["---"] * len(headers)) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(row) + " |")
    return "\n".join(lines)


def rows_for_horizon(rows: list[dict], horizon: int) -> list[dict]:
    return [row for row in rows if row["horizon_days"] == horizon]


def row_by_key(rows: list[dict], key: str, value: str) -> dict | None:
    for row in rows:
        if row[key] == value:
            return row
    return None


def best_signal_rows(signal_summary_rows: list[dict], horizon: int) -> tuple[dict, dict]:
    rows = rows_for_horizon(signal_summary_rows, horizon)
    best_mean = max(
        rows,
        key=lambda row: row["event_vs_baseline_mean_diff"]
        if row["event_vs_baseline_mean_diff"] is not None
        else float("-inf"),
    )
    best_up = max(
        rows,
        key=lambda row: row["event_vs_baseline_up_rate_diff"]
        if row["event_vs_baseline_up_rate_diff"] is not None
        else float("-inf"),
    )
    return best_mean, best_up


def generate_report(
    conn: sqlite3.Connection,
    stats_by_stock: dict[str, dict[str, MetricStats]],
    signal_summary_rows: list[dict],
    first_signal_summary_rows: list[dict],
    first_quiet_summary_rows: list[dict],
    correlation_rows: list[dict],
    positive_net_attention_rows: list[dict],
    positive_net_buy_jump_rows: list[dict],
) -> str:
    fund_meta = conn.execute(
        """
        SELECT COUNT(*) AS row_count,
               COUNT(DISTINCT stock_code) AS stock_count,
               MIN(trade_date) AS min_date,
               MAX(trade_date) AS max_date
        FROM ths_fund_flow
        """
    ).fetchone()
    daily_meta = conn.execute(
        """
        SELECT COUNT(*) AS row_count,
               COUNT(DISTINCT stock_code) AS stock_count,
               MIN(trade_date) AS min_date,
               MAX(trade_date) AS max_date
        FROM stock_daily
        WHERE adjust = ?
        """,
        (ADJUST,),
    ).fetchone()

    five_day_rows = rows_for_horizon(signal_summary_rows, 5)
    first_five_day_rows = rows_for_horizon(first_signal_summary_rows, 5)
    quiet_five_day_rows = rows_for_horizon(first_quiet_summary_rows, 5)
    jump_signal_keys = {
        "positive_net_buy_ratio_2x",
        "positive_net_buy_ratio_2_to_3x",
        "positive_net_buy_ratio_3x",
        "positive_net_buy_vs_prev5_2x",
        "positive_net_buy_delta_anomaly",
        "positive_net_buy_ratio_top10",
    }
    signal_table = markdown_table(
        [
            "5日信号",
            "事件数",
            "事件均值收益",
            "基准均值收益",
            "均值差",
            "事件上涨率",
            "基准上涨率",
            "上涨率差",
        ],
        [
            [
                row["signal_label"],
                str(row["event_count"]),
                pct(row["event_mean_return"]),
                pct(row["baseline_mean_return"]),
                pct(row["event_vs_baseline_mean_diff"]),
                pct(row["event_up_rate"]),
                pct(row["baseline_up_rate"]),
                pct(row["event_vs_baseline_up_rate_diff"]),
            ]
            for row in five_day_rows
        ],
    )

    start_signal_key = "positive_net_buy_ratio_2_to_3x"
    start_cooldown_rows = [
        row
        for row in first_five_day_rows
        if row["signal"] == start_signal_key
    ]
    start_cooldown_table = markdown_table(
        [
            "冷却窗口",
            "原始信号数",
            "启动信号数",
            "事件均值收益",
            "均值差",
            "事件上涨率",
            "上涨率差",
        ],
        [
            [
                str(row["cooldown_days"]),
                str(row["raw_event_count"]),
                str(row["first_event_count"]),
                pct(row["event_mean_return"]),
                pct(row["event_vs_baseline_mean_diff"]),
                pct(row["event_up_rate"]),
                pct(row["event_vs_baseline_up_rate_diff"]),
            ]
            for row in start_cooldown_rows
        ],
    )
    best_start_cooldown = max(
        start_cooldown_rows,
        key=lambda row: row["event_vs_baseline_up_rate_diff"]
        if row["event_vs_baseline_up_rate_diff"] is not None
        else float("-inf"),
    )
    quiet_cooldown_table = markdown_table(
        [
            "前置静默窗口",
            "原始2-3倍信号数",
            "真正启动信号数",
            "事件均值收益",
            "均值差",
            "事件上涨率",
            "上涨率差",
        ],
        [
            [
                str(row["quiet_days"]),
                str(row["raw_event_count"]),
                str(row["first_event_count"]),
                pct(row["event_mean_return"]),
                pct(row["event_vs_baseline_mean_diff"]),
                pct(row["event_up_rate"]),
                pct(row["event_vs_baseline_up_rate_diff"]),
            ]
            for row in quiet_five_day_rows
        ],
    )
    best_quiet_cooldown = max(
        quiet_five_day_rows,
        key=lambda row: row["event_vs_baseline_up_rate_diff"]
        if row["event_vs_baseline_up_rate_diff"] is not None
        else float("-inf"),
    )

    jump_signal_table = markdown_table(
        [
            "5日买入暴增信号",
            "事件数",
            "事件均值收益",
            "基准均值收益",
            "均值差",
            "事件上涨率",
            "上涨率差",
        ],
        [
            [
                row["signal_label"],
                str(row["event_count"]),
                pct(row["event_mean_return"]),
                pct(row["baseline_mean_return"]),
                pct(row["event_vs_baseline_mean_diff"]),
                pct(row["event_up_rate"]),
                pct(row["event_vs_baseline_up_rate_diff"]),
            ]
            for row in five_day_rows
            if row["signal"] in jump_signal_keys
        ],
    )

    attention_table = markdown_table(
        [
            "未来交易日",
            "买入关注度分组",
            "样本数",
            "均值收益",
            "中位收益",
            "上涨率",
            "相对正净买入均值差",
            "相对正净买入上涨率差",
        ],
        [
            [
                str(row["horizon_days"]),
                row["group_label"],
                str(row["sample_count"]),
                pct(row["mean_return"]),
                pct(row["median_return"]),
                pct(row["up_rate"]),
                pct(row["mean_diff_vs_positive_net_baseline"]),
                pct(row["up_rate_diff_vs_positive_net_baseline"]),
            ]
            for row in positive_net_attention_rows
            if row["horizon_days"] in (3, 5, 10)
        ],
    )

    jump_group_table = markdown_table(
        [
            "未来交易日",
            "买入环比分组",
            "样本数",
            "均值收益",
            "中位收益",
            "上涨率",
            "相对正净买入均值差",
            "相对正净买入上涨率差",
        ],
        [
            [
                str(row["horizon_days"]),
                row["group_label"],
                str(row["sample_count"]),
                pct(row["mean_return"]),
                pct(row["median_return"]),
                pct(row["up_rate"]),
                pct(row["mean_diff_vs_positive_net_baseline"]),
                pct(row["up_rate_diff_vs_positive_net_baseline"]),
            ]
            for row in positive_net_buy_jump_rows
            if row["horizon_days"] in (3, 5, 10)
        ],
    )

    corr_table = markdown_table(
        [
            "未来交易日",
            "指标",
            "Pearson",
            "Spearman",
        ],
        [
            [
                str(row["horizon_days"]),
                row["feature_label"],
                num(row["pearson"], 4),
                num(row["spearman"], 4),
            ]
            for row in correlation_rows
            if row["horizon_days"] == 5
            and row["feature"]
            in (
                "net_inflow_wan_shou_percentile",
                "institution_buy_wan_shou_percentile",
                "institution_activity_wan_shou_percentile",
                "institution_buy_ratio",
                "institution_buy_vs_prev5_mean",
                "institution_buy_delta_wan_shou_percentile",
                "institution_buy_ratio_percentile",
                "net_activity_ratio",
            )
        ],
    )

    net_old = row_by_key(five_day_rows, "signal", "net_anomaly")
    top20_buy = row_by_key(five_day_rows, "signal", "positive_net_top20_buy")
    positive_buy_attention = row_by_key(
        five_day_rows,
        "signal",
        "positive_net_buy_attention",
    )
    best_mean, best_up = best_signal_rows(signal_summary_rows, 5)

    stock_count = len(stats_by_stock)
    net_event_counts = [
        metrics["net_inflow_wan_shou"].event_count for metrics in stats_by_stock.values()
    ]
    buy_event_counts = [
        metrics["institution_buy_wan_shou"].event_count
        for metrics in stats_by_stock.values()
    ]
    activity_event_counts = [
        metrics["institution_activity_wan_shou"].event_count
        for metrics in stats_by_stock.values()
    ]

    old_vs_top20 = ""
    if net_old and top20_buy:
        old_vs_top20 = (
            f"旧口径 5 日均值差为 {pct(net_old['event_vs_baseline_mean_diff'])}，"
            f"上涨率差为 {pct(net_old['event_vs_baseline_up_rate_diff'])}；"
            f"`净买入为正 + 买入额前20%` 的 5 日均值差为 "
            f"{pct(top20_buy['event_vs_baseline_mean_diff'])}，上涨率差为 "
            f"{pct(top20_buy['event_vs_baseline_up_rate_diff'])}。"
        )

    strict_attention = ""
    if positive_buy_attention:
        strict_attention = (
            f"更严格的 `净买入为正 + 买入额异常` 5 日样本数为 "
            f"{positive_buy_attention['event_count']}，均值差为 "
            f"{pct(positive_buy_attention['event_vs_baseline_mean_diff'])}，"
            f"上涨率差为 "
            f"{pct(positive_buy_attention['event_vs_baseline_up_rate_diff'])}。"
        )

    return f"""# 机构买入关注度与未来短期涨幅统计实验

## 实验目的

这次实验继续验证一个更贴近图表观察的判断：不能只看机构净买入，也不能只看买入额绝对值；更关键的可能是“机构买入额相对昨天突然暴增，并且当天净买入仍然为正”。

你举的例子是典型启动形态：前一天机构买入额 1.4、净买入 0.2，第二天买入额突然到 9.4、净买入仍为正 0.1。净买入本身没有变大，但买入额从低位突然放大，说明机构参与强度发生突变。

所以这版代码把信号拆成两层：

- 方向：`net_inflow_wan_shou`，也就是机构净买入。
- 关注度/参与强度：`institution_buy_wan_shou` 和 `institution_buy_wan_shou + institution_sell_wan_shou`。
- 突变：`institution_buy_wan_shou / yesterday_buy`、`institution_buy_wan_shou / previous_5day_buy_mean`、`institution_buy_wan_shou - yesterday_buy`。

## 数据说明

- 数据库：`{DB_PATH}`
- 资金流表：`ths_fund_flow`，使用 `institution_buy_wan_shou`、`institution_sell_wan_shou`、`net_inflow_wan_shou`。
- 日线表：`stock_daily`，使用 `adjust=''` 的 `close_price`。
- 资金流样本：{fund_meta["row_count"]} 行，{fund_meta["stock_count"]} 只股票，日期范围 {fund_meta["min_date"]} 到 {fund_meta["max_date"]}。
- 日线样本：{daily_meta["row_count"]} 行，{daily_meta["stock_count"]} 只股票，日期范围 {daily_meta["min_date"]} 到 {daily_meta["max_date"]}。

## 方法

每只股票分别计算以下指标的历史分布：机构净买入、机构买入额、机构卖出额、机构买卖总额、机构买入额较昨日增量、机构买入额较昨日倍数、机构买入额相对前 5 日均值倍数。每个指标都使用同一套稳健异常阈值：

`max(P95, Q3 + 1.5 * IQR, median + 3 * 1.4826 * MAD)`

这样可以避免不同股票资金规模不同造成的不可比问题。除异常阈值外，代码还计算了每个交易日该指标在本股票历史里的分位数，例如“机构买入额环比倍数处于本股前 10%”。

输出文件包括：

- `metric_thresholds.csv`：每只股票、每个指标的阈值。
- `events.csv`：触发任一信号的事件明细和未来收益。
- `signal_summary_by_horizon.csv`：不同信号在 3/5/7/10/14 日的效果。
- `continuous_correlation_by_horizon.csv`：连续指标与未来收益的相关性。
- `positive_net_attention_groups.csv`：只看净买入为正的日子，再按买入关注度分组。
- `positive_net_buy_jump_groups.csv`：只看净买入为正的日子，再按买入额较昨日倍数分组。
- `first_quiet_signal_summary_by_cooldown.csv`：信号族前置静默后的启动信号汇总。
- `first_quiet_start_events.csv`：信号族前置静默后的启动信号明细，可直接回图表核对。

## 阈值事件概况

本次覆盖 {stock_count} 只股票。按单指标异常统计：

- 净买入异常：每只股票 {min(net_event_counts)} 到 {max(net_event_counts)} 次，平均 {sum(net_event_counts) / len(net_event_counts):.2f} 次。
- 买入额异常：每只股票 {min(buy_event_counts)} 到 {max(buy_event_counts)} 次，平均 {sum(buy_event_counts) / len(buy_event_counts):.2f} 次。
- 买卖总额异常：每只股票 {min(activity_event_counts)} 到 {max(activity_event_counts)} 次，平均 {sum(activity_event_counts) / len(activity_event_counts):.2f} 次。

## 5 日信号对照

{signal_table}

其中，和这次假设最相关的是下面这组“买入额突然暴增，并且净买入为正”的信号：

{jump_signal_table}

## 只保留一波行情的第一个启动信号

上面的事件数仍然偏多，因为同一只股票在一波上涨里可能连续多天触发信号。这里对目前最强的 `净买入为正 + 买入额为昨日2-3倍` 做去重：同一只股票第一次触发后，在冷却窗口内再次触发的都视为同一波行情的延续，不再当成新的启动点。

{start_cooldown_table}

按 5 日上涨率差看，当前最好的启动口径是冷却 {best_start_cooldown["cooldown_days"]} 个交易日：启动信号数 {best_start_cooldown["first_event_count"]}，5 日均值收益 {pct(best_start_cooldown["event_mean_return"])}，上涨率 {pct(best_start_cooldown["event_up_rate"])}，上涨率差 {pct(best_start_cooldown["event_vs_baseline_up_rate_diff"])}。

更严格一点：如果前面已经出现过任意 `净买入为正 + 买入额较昨日>=2倍`，后面的 `2-3倍` 也视为同一族信号的延续。下面只保留“前面一段时间没有任何 >=2 倍暴增信号”的 `2-3倍` 启动点。

{quiet_cooldown_table}

按 5 日上涨率差看，信号族去重后最好的口径是前置静默 {best_quiet_cooldown["quiet_days"]} 个交易日：真正启动信号数 {best_quiet_cooldown["first_event_count"]}，5 日均值收益 {pct(best_quiet_cooldown["event_mean_return"])}，上涨率 {pct(best_quiet_cooldown["event_up_rate"])}，上涨率差 {pct(best_quiet_cooldown["event_vs_baseline_up_rate_diff"])}。

{old_vs_top20}

{strict_attention}

5 日均值差最好的信号是 `{best_mean["signal_label"]}`，均值差为 {pct(best_mean["event_vs_baseline_mean_diff"])}。5 日上涨率差最好的信号是 `{best_up["signal_label"]}`，上涨率差为 {pct(best_up["event_vs_baseline_up_rate_diff"])}。

## 净买入为正时，买入关注度是否有区分度

下面这张表只保留 `net_inflow_wan_shou > 0` 的交易日，再按 `institution_buy_wan_shou` 在本股票历史中的分位数分组。这个分组最接近你提出的问题：方向同样是净买入为正，但买入额大小不同，后续表现是否不同。

{attention_table}

## 净买入为正时，买入额环比暴增是否有区分度

下面这张表只保留 `net_inflow_wan_shou > 0` 且有前一交易日资金流数据的交易日，再按“今天机构买入额 / 昨天机构买入额”分组。这一组更贴近你在图表软件里看到的形态。

{jump_group_table}

## 连续相关性

这里只展示 5 日维度。相关系数越接近 0，说明单独线性/单调关系越弱；正值表示指标越高，未来收益倾向越高。

{corr_table}

## 结论

这版实验把你观察到的“买入额突然暴增 + 净买入为正”单独拆出来验证，并且增加了“同一波行情只取第一个信号”的启动口径。这个调整很重要，因为连续触发的第二、第三个信号往往已经不是买点，而是同一波行情的延续。

如果环比暴增组明显强于“买入额绝对高”组，说明原来的统计方法确实漏掉了启动前的边际变化；如果 2 倍、3 倍组仍然不强，则说明肉眼看到的案例可能还需要叠加位置、趋势、板块或后续连续买入来过滤。

当前代码已经把这条路径拆开了：后续可以继续沿着“买入额暴增 + 净买入为正 + 只取第一信号 + 价格未大涨/突破均线/次日继续净买入”等组合去找更接近图表经验的信号。真正可交易的启动点应该是稀疏的，如果某个口径一年每只股票触发十几次，它就更像噪声或延续信号，而不是启动信号。
"""


def print_summary(signal_summary_rows: list[dict]) -> None:
    print(f"Database: {DB_PATH}")
    print(f"Output: {OUTPUT_DIR}")
    print()
    rows = rows_for_horizon(signal_summary_rows, 5)
    header = "signal | events | event_mean | baseline_mean | mean_diff | event_up | up_diff"
    print(header)
    print("-" * len(header))
    for row in rows:
        print(
            f"{row['signal']:<32} | "
            f"{row['event_count']:>6} | "
            f"{pct(row['event_mean_return']):>10} | "
            f"{pct(row['baseline_mean_return']):>13} | "
            f"{pct(row['event_vs_baseline_mean_diff']):>9} | "
            f"{pct(row['event_up_rate']):>8} | "
            f"{pct(row['event_vs_baseline_up_rate_diff']):>7}"
        )


def main() -> None:
    if not DB_PATH.exists():
        raise FileNotFoundError(f"Database not found: {DB_PATH}")

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        fund_rows = read_fund_rows(conn)
        add_buy_jump_features(fund_rows)
        daily_rows = read_daily_rows(conn)
        stats_by_stock = build_metric_stats(fund_rows)
        prices_by_stock, index_by_stock_date = build_price_lookup(daily_rows)
        enriched_rows = enrich_rows(
            fund_rows,
            stats_by_stock,
            prices_by_stock,
            index_by_stock_date,
        )
        signal_summary_rows = summarize_signals(enriched_rows)
        first_signal_summary_rows = summarize_first_signals(enriched_rows)
        first_quiet_summary_rows = summarize_first_trigger_after_quiet(enriched_rows)
        correlation_rows = summarize_correlations(enriched_rows)
        positive_net_attention_rows = summarize_positive_net_attention(enriched_rows)
        positive_net_buy_jump_rows = summarize_positive_net_buy_jump(enriched_rows)
        write_outputs(
            stats_by_stock,
            enriched_rows,
            signal_summary_rows,
            first_signal_summary_rows,
            first_quiet_summary_rows,
            correlation_rows,
            positive_net_attention_rows,
            positive_net_buy_jump_rows,
        )

        report = generate_report(
            conn,
            stats_by_stock,
            signal_summary_rows,
            first_signal_summary_rows,
            first_quiet_summary_rows,
            correlation_rows,
            positive_net_attention_rows,
            positive_net_buy_jump_rows,
        )
        (OUTPUT_DIR / "report.md").write_text(report, encoding="utf-8")
        print_summary(signal_summary_rows)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
