# plan1：主力 / 散户 / 期货价格 同期共振验证

本目录为**单一品种（variety_id = 1）**小范围验证阶段的工作区。验证采用**定长跨度 S**（含 **S=2**，网格 2～7）下**整窗首尾差分**，每滑窗一行（见 `docs/validation_plan_main_force_resonance.md`）。

## 目录结构

| 路径 | 说明 |
|------|------|
| `docs/research_overview.md` | 课题目标与字段含义（`main_force`、`retail` 等） |
| `docs/validation_plan_main_force_resonance.md` | 验证假设、步骤、判定准则与交付物说明 |
| `scripts/run_cooc.py` | 同期趋势共振统计脚本（读 `../database/local_fut_pulse.sqlite`） |
| `artifacts/data/` | 脚本生成的 CSV（如 `windows_S5.csv`、`summary_pairs.csv`、`bootstrap.csv`） |
| `artifacts/charts/` | 图表等可视化产出 |

## 运行

在仓库根目录执行：

```bash
python plan1/scripts/run_cooc.py
```

产出写入 `plan1/artifacts/data/`。
