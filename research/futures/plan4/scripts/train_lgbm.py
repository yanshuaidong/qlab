"""
Plan 4 — LightGBM 训练：预测严格 7 日开仓样本是否盈利。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from common import (  # noqa: E402
    ARTIFACT_DATA,
    ARTIFACT_MODELS,
    FEATURE_COLUMNS,
    TRAIN_RATIO,
    build_all_entry_samples,
    load_signal_map,
    resolve_db,
    save_json,
)

from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import (  # noqa: E402
    accuracy_score,
    f1_score,
    roc_auc_score,
)


def time_split(samples: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.Timestamp]:
    dates = pd.DatetimeIndex(sorted(samples["trade_date"].unique()))
    split_idx = max(1, int(len(dates) * TRAIN_RATIO))
    train_end = dates[split_idx - 1]
    train = samples[samples["trade_date"] <= train_end].copy()
    valid = samples[samples["trade_date"] > train_end].copy()
    return train, valid, train_end


def _make_model(backend: str):
    if backend == "lightgbm":
        import lightgbm as lgb

        return lgb.LGBMClassifier(
            objective="binary",
            n_estimators=200,
            learning_rate=0.05,
            max_depth=5,
            num_leaves=15,
            min_child_samples=8,
            subsample=0.85,
            colsample_bytree=0.85,
            class_weight="balanced",
            random_state=42,
            verbosity=-1,
        )
    return HistGradientBoostingClassifier(
        max_depth=5,
        max_iter=200,
        learning_rate=0.05,
        random_state=42,
    )


def train_model(train: pd.DataFrame, valid: pd.DataFrame, backend: str):
    X_train = train[FEATURE_COLUMNS].astype(float)
    y_train = train["y"].astype(int)
    X_valid = valid[FEATURE_COLUMNS].astype(float)
    y_valid = valid["y"].astype(int)

    model = _make_model(backend)
    if backend == "lightgbm":
        model.fit(X_train, y_train, eval_set=[(X_valid, y_valid)], eval_metric="auc")
    else:
        model.fit(X_train, y_train)
    return model


def evaluate_split(name: str, model, df: pd.DataFrame) -> dict:
    if df.empty:
        return {"split": name, "n": 0}
    X = df[FEATURE_COLUMNS].astype(float)
    y = df["y"].astype(int)
    prob = model.predict_proba(X)[:, 1]
    pred = (prob >= 0.5).astype(int)
    out = {
        "split": name,
        "n": int(len(df)),
        "positive_rate": float(y.mean()),
        "accuracy": float(accuracy_score(y, pred)),
        "f1": float(f1_score(y, pred, zero_division=0)),
    }
    if y.nunique() > 1:
        out["auc"] = float(roc_auc_score(y, prob))
    else:
        out["auc"] = None
    return out


def main() -> None:
    print(f"数据库: {resolve_db()}")
    signal_map, train_end = load_signal_map()
    samples = build_all_entry_samples(signal_map)
    train_df, valid_df, train_end = time_split(samples)

    ARTIFACT_DATA.mkdir(parents=True, exist_ok=True)
    samples.to_csv(ARTIFACT_DATA / "entry_samples.csv", index=False)
    train_df.to_csv(ARTIFACT_DATA / "entry_samples_train.csv", index=False)
    valid_df.to_csv(ARTIFACT_DATA / "entry_samples_valid.csv", index=False)

    print(f"开仓样本: {len(samples)} 笔 | 训练 {len(train_df)} | 验证 {len(valid_df)}")
    print(f"训练截止日: {train_end.date()} | 正样本率(全): {samples['y'].mean():.2%}")

    backend = "lightgbm"
    try:
        _make_model("lightgbm")
    except Exception as exc:
        print(f"LightGBM 不可用 ({exc})，回退 HistGradientBoosting")
        backend = "sklearn"

    model = train_model(train_df, valid_df, backend)

    metrics = {
        "backend": backend,
        "train_end": str(train_end.date()),
        "train_ratio": TRAIN_RATIO,
        "feature_columns": FEATURE_COLUMNS,
        "metrics": [
            evaluate_split("train", model, train_df),
            evaluate_split("valid", model, valid_df),
        ],
    }

    if hasattr(model, "feature_importances_"):
        imp = model.feature_importances_
    else:
        imp = np.zeros(len(FEATURE_COLUMNS))
    importance = pd.DataFrame({"feature": FEATURE_COLUMNS, "importance": imp}).sort_values(
        "importance", ascending=False
    )
    importance.to_csv(ARTIFACT_DATA / "feature_importance.csv", index=False)

    ARTIFACT_MODELS.mkdir(parents=True, exist_ok=True)
    if backend == "lightgbm":
        model.booster_.save_model(str(ARTIFACT_MODELS / "lgbm_entry.txt"))

    import joblib

    joblib.dump({"backend": backend, "model": model}, ARTIFACT_MODELS / "lgbm_entry.pkl")
    save_json(ARTIFACT_MODELS / "feature_meta.json", {"feature_columns": FEATURE_COLUMNS})
    save_json(ARTIFACT_MODELS / "metrics.json", metrics)

    print("\n=== 验证集指标 ===")
    valid_metrics = metrics["metrics"][1]
    for k, v in valid_metrics.items():
        print(f"  {k}: {v}")

    print("\n特征重要性 Top 5:")
    print(importance.head().to_string(index=False))
    print(f"\n模型已保存: {ARTIFACT_MODELS / 'lgbm_entry.pkl'}")


if __name__ == "__main__":
    main()
