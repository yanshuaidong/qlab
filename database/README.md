# local_fut_pulse.sqlite

本地期货相关 SQLite 数据库，路径：`database/local_fut_pulse.sqlite`。

## 数据概览

以下指标描述「当前库里有什么、规模多大」。

| 指标 | 含义 | 当前快照（本机库） |
|------|------|-------------------|
| 品种数 | `fut_variety` 行数 | 55 |
| 有强弱数据的品种数 | `fut_strength` 中不同 `variety_id` | 55（与品种表一致） |
| 交易日数 | `fut_strength` 中不同 `trade_date` | 180 |
| 强弱记录数 | `fut_strength` 总行数 | 9900（≈ 55×180） |
| 收盘价记录数 | `fut_daily_close` 总行数 | 9900（与 `fut_strength` 对齐后应一致） |
| 强弱/收盘日期范围 | `MIN(trade_date)` ~ `MAX(trade_date)` | 2025-07-22 ~ 2026-04-20 |

上表数字为文档更新当日从本地 `local_fut_pulse.sqlite` 查询结果，仅作量级参考。

---

## 表一览

| 表名 | 说明 |
|------|------|
| `fut_variety` | 期货品种主数据（id、名称、业务 key） |
| `fut_strength` | 按品种、交易日的多空/强弱类指标（主散等） |
| `fut_daily_close` | 按品种、交易日的主连收盘价，供与 `fut_strength` 对齐 |

`fut_strength` 与 `fut_daily_close` 通过 `variety_id` + `trade_date` 与品种、日期关联；逻辑上 `variety_id` 应对应 `fut_variety.id`（库内未声明外键约束）。

---

## fut_variety

期货品种字典表。

| 列名 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `id` | INTEGER | NOT NULL, PRIMARY KEY | 品种内部编号 |
| `name` | TEXT | NOT NULL | 显示名称 |
| `key` | TEXT | NOT NULL, UNIQUE | 业务键（如 `rbm`、`cum`） |

---

## fut_strength

按品种、交易日的强度/持仓结构类数据（示例列名：`main_force`、`retail`）。

| 列名 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `id` | INTEGER | PRIMARY KEY, AUTOINCREMENT | 自增主键 |
| `variety_id` | INTEGER | NOT NULL | 对应 `fut_variety.id` |
| `trade_date` | TEXT | NOT NULL | 交易日，格式一般为 `YYYY-MM-DD` |
| `main_force` | REAL | 可空 | 主力/大资金侧指标（依上游定义） |
| `retail` | REAL | 可空 | 散户侧指标（依上游定义） |
| `collected_at` | TEXT | NOT NULL | 采集时间 |
| | | UNIQUE (`variety_id`, `trade_date`) | 同一品种同一交易日一行 |

**索引**

- `idx_fut_strength_variety_date`：`(`variety_id`, `trade_date`)`
- `idx_fut_strength_date`：`(`trade_date`)`

---

## fut_daily_close

| 列名 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `variety_id` | INTEGER | NOT NULL | 对应 `fut_variety.id` |
| `trade_date` | TEXT | NOT NULL | 交易日 `YYYY-MM-DD` |
| `close_price` | REAL | NOT NULL | 收盘价 |
| `collected_at` | TEXT | NOT NULL, DEFAULT `datetime('now')` | 写入/更新时间 |
| | | PRIMARY KEY (`variety_id`, `trade_date`) | 复合主键；冲突时执行 UPSERT 更新收盘价与 `collected_at` |

**索引**

- `idx_fut_daily_close_trade_date`：`(`trade_date`)`

---

## 系统表

SQLite 内部表 `sqlite_sequence` 用于 AUTOINCREMENT 序列，一般无需业务读写。
