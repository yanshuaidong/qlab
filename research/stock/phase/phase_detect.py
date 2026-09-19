#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
行情阶段量化识别：三方案一次到位
====================================
目标品种：个股
时间颗粒度：日线
使用场景：回测研究
识别目标：仅识别当前阶段（不预测下一阶段）

方案A（基准）：ADX 法          period=14, threshold=25
方案D（统计）：线性回归斜率+R²  window=20, R²_threshold=0.3
方案E（进阶）：HMM              n_states=3, 全局模型

阶段编码：0=下跌  1=震荡  2=上涨
输出报告：research/stock/phase/phase_report.md
结果表：storage/stock/data.sqlite · phase_adx / phase_lr / phase_hmm
"""

from __future__ import annotations

import sqlite3
import warnings
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
from hmmlearn import hmm
from scipy import stats as scipy_stats

warnings.filterwarnings("ignore")

# ─────────────────── 路径 ───────────────────
REPO_ROOT = Path(__file__).resolve().parents[3]
DB_PATH = REPO_ROOT / "storage" / "stock" / "data.sqlite"
REPORT_PATH = Path(__file__).resolve().parent / "phase_report.md"

PHASE_TABLES = (
    ("phase_adx", "phase_adx"),
    ("phase_lr", "phase_lr"),
    ("phase_hmm", "phase_hmm"),
)

# ─────────────────── 参数 ───────────────────
# 方案A：ADX
ADX_PERIOD: int = 14
ADX_THRESHOLD: float = 25.0

# 方案D：线性回归 + R²
LR_WINDOW: int = 20
LR_R2_THRESHOLD: float = 0.3

# 方案E：HMM
HMM_N_STATES: int = 3
HMM_N_ITER: int = 100
HMM_MIN_DAYS: int = 30       # 每只股票最少交易日才参与HMM
HMM_TRAIN_STOCKS: int = 500  # 随机采样训练 HMM 的股票数（控制内存和速度）
HMM_RANDOM_SEED: int = 42

# 报告：展示后续收益的持有期（交易日数）
EVAL_HORIZONS = (1, 3, 5, 10, 20)

# 阶段标签
PHASE_LABELS = {0: "下跌", 1: "震荡", 2: "上涨"}
PHASE_ORDER = [0, 1, 2]


# ══════════════════════════════════════════
# 1. 数据加载
# ══════════════════════════════════════════

def load_daily(conn: sqlite3.Connection) -> pd.DataFrame:
    """加载 daily 表的 OHLCV + pct_chg，按 ts_code/trade_date 排序。"""
    df = pd.read_sql_query(
        """
        SELECT ts_code, trade_date, open, high, low, close, pct_chg, vol, amount
        FROM daily
        ORDER BY ts_code, trade_date
        """,
        conn,
    )
    df["trade_date"] = pd.to_datetime(df["trade_date"])
    df["pct_chg"] = df["pct_chg"].astype(float)
    df["close"] = df["close"].astype(float)
    df["high"] = df["high"].astype(float)
    df["low"] = df["low"].astype(float)
    df["vol"] = df["vol"].astype(float)
    return df


# ══════════════════════════════════════════
# 2. 方案A：ADX 法
# ══════════════════════════════════════════

def _ewm_smooth(series: np.ndarray, period: int) -> np.ndarray:
    """Wilder 平滑（等价于 EMA alpha=1/period）。"""
    alpha = 1.0 / period
    out = np.empty_like(series)
    out[:] = np.nan
    # 找第一个有效值
    start = 0
    while start < len(series) and np.isnan(series[start]):
        start += 1
    if start >= len(series):
        return out
    out[start] = series[start]
    for i in range(start + 1, len(series)):
        if np.isnan(series[i]):
            out[i] = out[i - 1]
        else:
            out[i] = out[i - 1] * (1 - alpha) + series[i] * alpha
    return out


def compute_adx_phase_for_stock(
    high: np.ndarray,
    low: np.ndarray,
    close: np.ndarray,
    period: int = ADX_PERIOD,
    threshold: float = ADX_THRESHOLD,
) -> np.ndarray:
    """对单只股票计算 ADX 阶段标签，返回与输入等长的 int8 数组（NaN 处为 -1）。"""
    n = len(close)
    phase = np.full(n, -1, dtype=np.int8)
    if n < period * 2 + 1:
        return phase

    prev_close = np.empty(n)
    prev_close[0] = np.nan
    prev_close[1:] = close[:-1]

    prev_high = np.empty(n)
    prev_high[0] = np.nan
    prev_high[1:] = high[:-1]

    prev_low = np.empty(n)
    prev_low[0] = np.nan
    prev_low[1:] = low[:-1]

    # True Range
    tr = np.maximum(
        high - low,
        np.maximum(np.abs(high - prev_close), np.abs(low - prev_close)),
    )
    tr[0] = np.nan

    # +DM, -DM
    up_move = high - prev_high
    down_move = prev_low - low
    up_move[0] = np.nan
    down_move[0] = np.nan

    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)
    plus_dm = plus_dm.astype(float)
    minus_dm = minus_dm.astype(float)
    plus_dm[0] = np.nan
    minus_dm[0] = np.nan

    # Wilder 平滑
    atr = _ewm_smooth(tr, period)
    s_plus_dm = _ewm_smooth(plus_dm, period)
    s_minus_dm = _ewm_smooth(minus_dm, period)

    # +DI, -DI
    with np.errstate(invalid="ignore", divide="ignore"):
        plus_di = 100.0 * s_plus_dm / atr
        minus_di = 100.0 * s_minus_dm / atr
        dx = 100.0 * np.abs(plus_di - minus_di) / (plus_di + minus_di)

    dx = np.where(np.isfinite(dx), dx, np.nan)
    adx = _ewm_smooth(dx, period)

    # 阶段判断
    valid = np.isfinite(adx) & np.isfinite(plus_di) & np.isfinite(minus_di)
    for i in range(n):
        if not valid[i]:
            continue
        if adx[i] < threshold:
            phase[i] = 1  # 震荡
        elif plus_di[i] > minus_di[i]:
            phase[i] = 2  # 上涨
        else:
            phase[i] = 0  # 下跌

    return phase


def compute_adx_phase(df: pd.DataFrame) -> pd.Series:
    """对 df 所有股票批量计算 ADX 阶段，返回与 df 对齐的 Series。"""
    results = np.full(len(df), -1, dtype=np.int8)
    for code, grp in df.groupby("ts_code", sort=False):
        idx = grp.index
        ph = compute_adx_phase_for_stock(
            grp["high"].to_numpy(),
            grp["low"].to_numpy(),
            grp["close"].to_numpy(),
        )
        results[idx] = ph
    return pd.Series(results, index=df.index, name="phase_adx", dtype="Int8").replace(-1, pd.NA)


# ══════════════════════════════════════════
# 3. 方案D：线性回归斜率 + R² 法
# ══════════════════════════════════════════

def _rolling_lr_phase(
    close: np.ndarray,
    window: int = LR_WINDOW,
    r2_threshold: float = LR_R2_THRESHOLD,
) -> np.ndarray:
    """对单只股票计算滚动线性回归阶段（numpy 向量化）。"""
    n = len(close)
    phase = np.full(n, -1, dtype=np.int8)
    if n < window:
        return phase

    # log(close) 对时间做 OLS，斜率 ≈ 日均对数收益率
    log_c = np.where(np.isfinite(close) & (close > 0), np.log(close), np.nan)

    # 滑动窗口视图 shape=(n-window+1, window)
    windows = np.lib.stride_tricks.sliding_window_view(log_c, window)

    x = np.arange(window, dtype=float)
    x_c = x - x.mean()
    x_sse = float((x_c ** 2).sum())

    y_means = np.nanmean(windows, axis=1)          # (n-window+1,)
    y_c = windows - y_means[:, np.newaxis]          # centered y
    slopes = (x_c * y_c).sum(axis=1) / x_sse       # (n-window+1,)

    ss_tot = (y_c ** 2).sum(axis=1)
    intercepts = y_means - slopes * x.mean()
    y_hat = slopes[:, np.newaxis] * x + intercepts[:, np.newaxis]
    ss_res = ((windows - y_hat) ** 2).sum(axis=1)

    with np.errstate(invalid="ignore", divide="ignore"):
        r2 = np.where(ss_tot < 1e-12, 1.0, 1.0 - ss_res / ss_tot)
    r2 = np.clip(r2, 0.0, 1.0)

    # 有效性：窗口内无 NaN 且首元素 > 0
    any_nan = np.any(~np.isfinite(windows), axis=1)

    ph = np.where(r2 < r2_threshold, np.int8(1),
                  np.where(slopes > 0, np.int8(2), np.int8(0)))
    ph[any_nan] = np.int8(-1)

    phase[window - 1 :] = ph
    return phase


def compute_lr_phase(df: pd.DataFrame) -> pd.Series:
    """对 df 所有股票批量计算线性回归阶段。"""
    results = np.full(len(df), -1, dtype=np.int8)
    for code, grp in df.groupby("ts_code", sort=False):
        idx = grp.index
        ph = _rolling_lr_phase(grp["close"].to_numpy())
        results[idx] = ph
    return pd.Series(results, index=df.index, name="phase_lr", dtype="Int8").replace(-1, pd.NA)


# ══════════════════════════════════════════
# 4. 方案E：HMM 隐马尔可夫模型
# ══════════════════════════════════════════

def build_hmm_features(df: pd.DataFrame) -> tuple[np.ndarray, list[int]]:
    """
    构建 HMM 观测特征矩阵。
    特征：[日收益率, 20日滚动波动率]
    为控制内存，随机采样不超过 HMM_TRAIN_STOCKS 只股票参与训练。
    返回 (X, lengths)。
    """
    all_codes = list(df["ts_code"].unique())
    rng = np.random.default_rng(HMM_RANDOM_SEED)
    if len(all_codes) > HMM_TRAIN_STOCKS:
        selected = set(rng.choice(all_codes, HMM_TRAIN_STOCKS, replace=False).tolist())
    else:
        selected = set(all_codes)

    segs: list[np.ndarray] = []
    lengths: list[int] = []

    for code, grp in df.groupby("ts_code", sort=False):
        if code not in selected:
            continue
        ret = grp["pct_chg"].to_numpy(dtype=float) / 100.0
        n = len(ret)
        if n < HMM_MIN_DAYS:
            continue

        vol_arr = _rolling_std(ret, window=20)
        feat = np.column_stack([ret, vol_arr])
        valid = np.all(np.isfinite(feat), axis=1)
        feat_clean = feat[valid]
        if len(feat_clean) < HMM_MIN_DAYS:
            continue
        segs.append(feat_clean)
        lengths.append(len(feat_clean))

    if not segs:
        return np.empty((0, 2)), []
    return np.vstack(segs), lengths


def train_hmm(X: np.ndarray, lengths: list[int]) -> hmm.GaussianHMM:
    """训练全局 3 状态高斯 HMM。"""
    print(f"  HMM 训练：{len(lengths):,} 只股票，共 {len(X):,} 个观测点…")
    model = hmm.GaussianHMM(
        n_components=HMM_N_STATES,
        covariance_type="diag",
        n_iter=HMM_N_ITER,
        random_state=HMM_RANDOM_SEED,
        verbose=False,
        tol=1e-4,
    )
    model.fit(X, lengths)
    return model


def infer_hmm_state_mapping(model: hmm.GaussianHMM) -> dict[int, int]:
    """
    按各状态均值收益率排序，映射为：
    最低均收益 → 0（下跌），中间 → 1（震荡），最高 → 2（上涨）。
    """
    means = model.means_[:, 0]  # 第 0 维是日收益率
    order = np.argsort(means)   # 从低到高排列的原始状态索引
    return {int(order[i]): i for i in range(HMM_N_STATES)}


def _rolling_std(arr: np.ndarray, window: int = 20) -> np.ndarray:
    """向量化滚动标准差，结果前 window-1 位为 NaN。"""
    n = len(arr)
    out = np.full(n, np.nan)
    if n < window:
        return out
    wins = np.lib.stride_tricks.sliding_window_view(arr, window)
    out[window - 1 :] = wins.std(axis=1, ddof=1)
    return out


def compute_hmm_phase(df: pd.DataFrame, model: hmm.GaussianHMM, state_map: dict[int, int]) -> pd.Series:
    """对每只股票用训练好的模型解码当前阶段。"""
    results = np.full(len(df), -1, dtype=np.int8)

    for code, grp in df.groupby("ts_code", sort=False):
        idx = grp.index.to_numpy()
        ret = grp["pct_chg"].to_numpy(dtype=float) / 100.0
        n = len(ret)
        if n < HMM_MIN_DAYS:
            continue

        vol_arr = _rolling_std(ret, window=20)
        feat = np.column_stack([ret, vol_arr])
        valid_mask = np.all(np.isfinite(feat), axis=1)
        valid_idx = np.where(valid_mask)[0]

        if len(valid_idx) < HMM_MIN_DAYS:
            continue

        feat_clean = feat[valid_idx]
        try:
            raw_states = model.predict(feat_clean)
        except Exception:
            continue

        mapped_states = np.array([state_map.get(int(s), -1) for s in raw_states], dtype=np.int8)
        results[idx[valid_idx]] = mapped_states

    return pd.Series(results, index=df.index, name="phase_hmm", dtype="Int8").replace(-1, pd.NA)


# ══════════════════════════════════════════
# 5. 评估：后续收益分析
# ══════════════════════════════════════════

def add_future_returns(df: pd.DataFrame) -> pd.DataFrame:
    """在 df 上添加各持有期未来收益列（基于 pct_chg 复利，向量化实现）。"""
    out = df.copy()
    log1p = np.log1p(out["pct_chg"].to_numpy(dtype=float) / 100.0)
    out["_log1p"] = log1p

    for h in EVAL_HORIZONS:
        out[f"fwd_ret_{h}d"] = np.nan

    for code, grp in out.groupby("ts_code", sort=False):
        idx = grp.index
        lr = grp["_log1p"]
        cumsum = lr.cumsum()
        for h in EVAL_HORIZONS:
            # fwd_ret[i] = exp(cumsum[i+h] - cumsum[i]) - 1
            shifted = cumsum.shift(-h)
            fwd = np.expm1((shifted - cumsum).to_numpy()) * 100.0
            # 最后 h 行没有足够未来数据，置 NaN（shift 已自动处理）
            out.loc[idx, f"fwd_ret_{h}d"] = fwd

    out.drop(columns=["_log1p"], inplace=True)
    return out


def phase_stats(df: pd.DataFrame, phase_col: str) -> dict:
    """按阶段统计后续收益均值、上涨概率。"""
    result = {}
    for ph in PHASE_ORDER:
        mask = df[phase_col] == ph
        n = int(mask.sum())
        row: dict = {"n": n, "label": PHASE_LABELS[ph]}
        for h in EVAL_HORIZONS:
            col = f"fwd_ret_{h}d"
            if col not in df.columns:
                continue
            sub = df.loc[mask, col].dropna()
            if len(sub) == 0:
                row[f"mean_{h}d"] = np.nan
                row[f"winrate_{h}d"] = np.nan
            else:
                row[f"mean_{h}d"] = float(sub.mean())
                row[f"winrate_{h}d"] = float((sub > 0).mean() * 100)
        result[ph] = row
    return result


def agreement_rate(df: pd.DataFrame, col_a: str, col_b: str) -> float:
    """计算两列阶段标签的一致率（均非 NA 的行中）。"""
    valid = df[col_a].notna() & df[col_b].notna()
    if not valid.any():
        return np.nan
    a = df.loc[valid, col_a]
    b = df.loc[valid, col_b]
    return float((a == b).mean() * 100)


# ══════════════════════════════════════════
# 6. 渲染报告
# ══════════════════════════════════════════

def fmt(v, fmt_str: str = ".2f", fallback: str = "—") -> str:
    if v is None or (isinstance(v, float) and not np.isfinite(v)):
        return fallback
    return format(v, fmt_str)


def render_phase_table(stats: dict, method_name: str) -> str:
    headers = ["阶段", "行数", *[f"均涨跌 {h}日%" for h in EVAL_HORIZONS],
               *[f"上涨率 {h}日%" for h in EVAL_HORIZONS]]
    lines = [
        f"#### {method_name}",
        "",
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join([":---"] + ["---:"] * (len(headers) - 1)) + " |",
    ]
    for ph in PHASE_ORDER:
        row = stats[ph]
        cells = [
            PHASE_LABELS[ph],
            f"{row['n']:,}",
            *[fmt(row.get(f"mean_{h}d"), "+.2f") for h in EVAL_HORIZONS],
            *[fmt(row.get(f"winrate_{h}d"), ".1f") for h in EVAL_HORIZONS],
        ]
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def render_distribution_table(df: pd.DataFrame, col: str) -> str:
    """输出按日期维度的阶段分布（每个交易日三阶段各占多少股票）。"""
    valid = df[col].notna()
    if not valid.any():
        return "（无有效数据）"
    counts = df.loc[valid].groupby(["trade_date", col]).size().unstack(fill_value=0)
    counts.columns = [PHASE_LABELS.get(int(c), str(c)) for c in counts.columns]
    total = counts.sum(axis=1)
    pct = (counts.div(total, axis=0) * 100).round(1)

    # 取最后 10 个交易日展示
    tail = pct.tail(10)
    lines = [
        "最近 10 个交易日阶段分布（各阶段占当日股票比例 %）",
        "",
        "| 日期 | " + " | ".join(pct.columns) + " |",
        "| :--- | " + " | ".join(["---:"] * len(pct.columns)) + " |",
    ]
    for date, row in tail.iterrows():
        cells = [str(date.date())] + [fmt(v, ".1f") for v in row]
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def render_current_phase_table(df: pd.DataFrame) -> str:
    """列出最新一个交易日各方案的全市场阶段分布。"""
    latest_date = df["trade_date"].max()
    latest = df[df["trade_date"] == latest_date].copy()
    total = len(latest)

    rows = []
    for col, name in [("phase_adx", "方案A ADX"), ("phase_lr", "方案D 线性回归+R²"), ("phase_hmm", "方案E HMM")]:
        if col not in latest.columns:
            continue
        valid = latest[col].notna()
        n_valid = int(valid.sum())
        phase_counts = latest.loc[valid, col].astype(int).value_counts()
        cells = [name, f"{n_valid:,}"]
        for ph in PHASE_ORDER:
            cnt = int(phase_counts.get(ph, 0))
            pct = cnt / n_valid * 100 if n_valid > 0 else 0
            cells.append(f"{cnt:,} ({pct:.1f}%)")
        rows.append("| " + " | ".join(cells) + " |")

    header = f"最新交易日：{latest_date.date()}，全市场 {total:,} 只股票"
    lines = [
        header,
        "",
        "| 方法 | 有效股数 | 下跌 | 震荡 | 上涨 |",
        "| :--- | ---: | ---: | ---: | ---: |",
    ] + rows
    return "\n".join(lines)


def render_agreement_section(df: pd.DataFrame) -> str:
    pairs = [
        ("phase_adx", "phase_lr", "方案A vs 方案D"),
        ("phase_adx", "phase_hmm", "方案A vs 方案E"),
        ("phase_lr", "phase_hmm", "方案D vs 方案E"),
    ]
    lines = [
        "| 对比 | 一致率 |",
        "| :--- | ---: |",
    ]
    for col_a, col_b, label in pairs:
        if col_a in df.columns and col_b in df.columns:
            rate = agreement_rate(df, col_a, col_b)
            lines.append(f"| {label} | {fmt(rate, '.1f')}% |")
    return "\n".join(lines)


def render_report(df: pd.DataFrame, stats_adx: dict, stats_lr: dict, stats_hmm: dict) -> str:
    generated = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    date_min = str(df["trade_date"].min().date())
    date_max = str(df["trade_date"].max().date())
    n_stocks = int(df["ts_code"].nunique())
    n_rows = len(df)

    parts = [
        "# 行情阶段量化识别报告",
        "",
        f"生成时间：{generated}",
        "",
        "## 基本信息",
        "",
        f"- 数据来源：`storage/stock/data.sqlite` · `daily` 表",
        f"- 结果表：`phase_adx` / `phase_lr` / `phase_hmm`",
        f"- 覆盖区间：{date_min} ~ {date_max}",
        f"- 股票数量：{n_stocks:,} 只",
        f"- 数据行数：{n_rows:,} 行",
        f"- 目标品种：个股",
        f"- 时间颗粒度：日线",
        f"- 识别目标：仅识别当前阶段（不预测下一阶段）",
        "",
        "## 方法参数",
        "",
        "| 方法 | 核心参数 |",
        "| :--- | :--- |",
        f"| 方案A：ADX | period={ADX_PERIOD}, threshold={ADX_THRESHOLD} |",
        f"| 方案D：线性回归+R² | window={LR_WINDOW}, R²_threshold={LR_R2_THRESHOLD}, 对 log(close) 回归 |",
        f"| 方案E：HMM | n_states={HMM_N_STATES}, 全局模型（所有股票拼接训练），特征=[日收益率, 20日滚动波动率] |",
        "",
        "---",
        "",
        "## 一、最新交易日全市场阶段分布",
        "",
        render_current_phase_table(df),
        "",
        "---",
        "",
        "## 二、三方案一致性",
        "",
        render_agreement_section(df),
        "",
        "一致率说明：两方法在同一股票同一日期给出相同阶段标签的比例。",
        "",
        "---",
        "",
        "## 三、各方案后续收益统计",
        "",
        "> 持有期收益：从阶段标签日收盘起算，持有 N 个**该股交易日**后的收益（未扣手续费、不处理停牌）。",
        "> 上涨率：该持有期内收益 > 0 的比例。",
        "",
        render_phase_table(stats_adx, "方案A：ADX 法"),
        "",
        render_phase_table(stats_lr, "方案D：线性回归+R² 法"),
        "",
        render_phase_table(stats_hmm, "方案E：HMM 法"),
        "",
        "---",
        "",
        "## 四、最近10日阶段分布趋势",
        "",
        "### 方案A：ADX",
        "",
        render_distribution_table(df, "phase_adx"),
        "",
        "### 方案D：线性回归+R²",
        "",
        render_distribution_table(df, "phase_lr"),
        "",
        "### 方案E：HMM",
        "",
        render_distribution_table(df, "phase_hmm"),
        "",
        "---",
        "",
        "## 五、方法评估小结",
        "",
        "### 阶段分布合理性",
        _render_evaluation(df, stats_adx, stats_lr, stats_hmm),
        "",
        "---",
        "",
        "## 六、参数调优建议",
        "",
        "| 方法 | 问题现象 | 建议 |",
        "| :--- | :--- | :--- |",
        "| ADX | 震荡占比过高 → 阈值调低至 20；震荡过低 → 调高至 30 | 阈值 20～30 之间搜索 |",
        "| LR+R² | 趋势识别延迟明显 | 缩短窗口至 10～15 日；或降低 R² 阈值至 0.2 |",
        "| HMM | 状态不稳定 / 频繁切换 | 增加最小持续期约束；或在训练时加 min_covar 正则 |",
        "",
        "---",
        "",
        "## 附：限制说明",
        "",
        "- 未复权收盘价：除权日附近收益失真。",
        "- HMM 为全局回看模型（用了未来数据训练），不可用于实盘信号；仅供回测研究。",
        "- ADX/LR 均为纯基于当前窗口的滚动指标，不存在未来数据泄漏，但有一定滞后。",
        "- 停牌日 `daily` 无记录，持有期天数为实际交易日数。",
        "- 涨跌停日流动性受限，实际可成交价格与收盘价有偏差。",
        "",
    ]
    return "\n".join(parts)


def _render_evaluation(df: pd.DataFrame, stats_adx: dict, stats_lr: dict, stats_hmm: dict) -> str:
    """输出三方案评估摘要。"""
    lines = []

    def phase_pct(stats: dict, ph: int) -> str:
        total = sum(s["n"] for s in stats.values())
        if total == 0:
            return "—"
        n = stats[ph]["n"]
        return f"{n / total * 100:.1f}%"

    lines.append("")
    lines.append("| 方法 | 下跌占比 | 震荡占比 | 上涨占比 | 上涨5日均涨% | 下跌5日均涨% |")
    lines.append("| :--- | ---: | ---: | ---: | ---: | ---: |")
    for label, stats in [("方案A ADX", stats_adx), ("方案D LR+R²", stats_lr), ("方案E HMM", stats_hmm)]:
        up_5 = fmt(stats[2].get("mean_5d"), "+.2f")
        dn_5 = fmt(stats[0].get("mean_5d"), "+.2f")
        lines.append(
            f"| {label} | {phase_pct(stats, 0)} | {phase_pct(stats, 1)} | {phase_pct(stats, 2)} | {up_5} | {dn_5} |"
        )

    lines.append("")
    lines.append(
        "理想情况：**上涨阶段的后续收益应明显高于下跌阶段**，震荡阶段居中；"
        "上涨阶段均涨 > 0，下跌阶段均涨 < 0。"
    )
    return "\n".join(lines)


# ══════════════════════════════════════════
# 7. 结果入库
# ══════════════════════════════════════════

def ensure_phase_tables(conn: sqlite3.Connection) -> None:
    for table, _col in PHASE_TABLES:
        conn.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {table} (
              ts_code TEXT NOT NULL,
              trade_date TEXT NOT NULL,
              phase INTEGER NOT NULL CHECK (phase IN (0, 1, 2)),
              updated_at TEXT NOT NULL,
              PRIMARY KEY (ts_code, trade_date)
            )
            """
        )
        conn.execute(
            f"CREATE INDEX IF NOT EXISTS idx_{table}_ts_code ON {table}(ts_code)"
        )
    conn.commit()


def write_phase_table(conn: sqlite3.Connection, table: str, df: pd.DataFrame, col: str) -> int:
    """整表替换写入有效阶段标签。"""
    conn.execute(f"DELETE FROM {table}")
    if col not in df.columns:
        conn.commit()
        return 0
    valid = df[col].notna()
    if not valid.any():
        conn.commit()
        return 0

    now = datetime.now().isoformat(timespec="seconds")
    codes = df.loc[valid, "ts_code"].astype(str).tolist()
    dates = df.loc[valid, "trade_date"].dt.strftime("%Y-%m-%d").tolist()
    phases = [int(v) for v in df.loc[valid, col].tolist()]
    rows = list(zip(codes, dates, phases, [now] * len(codes)))
    conn.executemany(
        f"INSERT INTO {table} (ts_code, trade_date, phase, updated_at) VALUES (?, ?, ?, ?)",
        rows,
    )
    conn.commit()
    return len(rows)


def persist_phase_tables(df: pd.DataFrame) -> None:
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = NORMAL")
        conn.execute("PRAGMA busy_timeout = 30000")
        ensure_phase_tables(conn)
        for table, col in PHASE_TABLES:
            n = write_phase_table(conn, table, df, col)
            print(f"  {table}: {n:,} 行")
    finally:
        conn.close()


# ══════════════════════════════════════════
# 8. 主程序
# ══════════════════════════════════════════

def main() -> int:
    if not DB_PATH.is_file():
        print(f"数据库不存在: {DB_PATH}")
        return 1

    print("=" * 60)
    print("行情阶段量化识别：三方案一次到位")
    print("=" * 60)

    # ── 加载数据 ──
    print("\n[1/7] 加载日线数据…")
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    try:
        df = load_daily(conn)
    finally:
        conn.close()
    print(f"  {len(df):,} 行，{df['ts_code'].nunique():,} 只股票，"
          f"{df['trade_date'].min().date()} ~ {df['trade_date'].max().date()}")

    # ── 方案A：ADX ──
    print("\n[2/7] 方案A：ADX 法计算阶段标签…")
    df["phase_adx"] = compute_adx_phase(df)
    n_adx = int(df["phase_adx"].notna().sum())
    print(f"  有效标签 {n_adx:,} 行")
    _print_phase_dist(df, "phase_adx")

    # ── 方案D：LR+R² ──
    print("\n[3/7] 方案D：线性回归+R² 法计算阶段标签…")
    df["phase_lr"] = compute_lr_phase(df)
    n_lr = int(df["phase_lr"].notna().sum())
    print(f"  有效标签 {n_lr:,} 行")
    _print_phase_dist(df, "phase_lr")

    # ── 方案E：HMM ──
    print("\n[4/7] 方案E：HMM 法训练 & 解码…")
    X, lengths = build_hmm_features(df)
    if len(lengths) == 0:
        print("  警告：无足够数据训练 HMM，跳过。")
        df["phase_hmm"] = pd.NA
    else:
        model = train_hmm(X, lengths)
        state_map = infer_hmm_state_mapping(model)
        print(f"  状态映射（原始→语义）：{state_map}")
        for s in range(HMM_N_STATES):
            mean_ret = model.means_[s][0] * 100
            print(f"    原始状态 {s} → {PHASE_LABELS.get(state_map[s], '?')}，均日收益率 {mean_ret:+.3f}%")
        df["phase_hmm"] = compute_hmm_phase(df, model, state_map)
        n_hmm = int(df["phase_hmm"].notna().sum())
        print(f"  有效标签 {n_hmm:,} 行")
        _print_phase_dist(df, "phase_hmm")

    # ── 后续收益计算 ──
    print("\n[5/7] 计算后续收益（持有期 " + ", ".join(str(h) + "日" for h in EVAL_HORIZONS) + "）…")
    df = add_future_returns(df)
    print("  完成")

    # ── 生成报告 ──
    print("\n[6/7] 生成报告…")
    stats_adx = phase_stats(df, "phase_adx")
    stats_lr = phase_stats(df, "phase_lr")
    stats_hmm = phase_stats(df, "phase_hmm")

    # 一致性
    for pair, label in [
        (("phase_adx", "phase_lr"), "A vs D"),
        (("phase_adx", "phase_hmm"), "A vs E"),
        (("phase_lr", "phase_hmm"), "D vs E"),
    ]:
        rate = agreement_rate(df, pair[0], pair[1])
        print(f"  一致率 {label}: {rate:.1f}%")

    report = render_report(df, stats_adx, stats_lr, stats_hmm)
    REPORT_PATH.write_text(report, encoding="utf-8")
    print(f"\n✓ 报告已写入：{REPORT_PATH}")

    print("\n[7/7] 写入阶段结果表…")
    persist_phase_tables(df)
    print("✓ 已写入 phase_adx / phase_lr / phase_hmm")
    return 0


def _print_phase_dist(df: pd.DataFrame, col: str) -> None:
    valid = df[col].notna()
    total = int(valid.sum())
    if total == 0:
        print("  （无有效数据）")
        return
    counts = df.loc[valid, col].astype(int).value_counts().sort_index()
    parts = []
    for ph in PHASE_ORDER:
        cnt = int(counts.get(ph, 0))
        pct = cnt / total * 100
        parts.append(f"{PHASE_LABELS[ph]}: {cnt:,} ({pct:.1f}%)")
    print("  " + "，".join(parts))


if __name__ == "__main__":
    raise SystemExit(main())
