# 本地库 `stock.sqlite` 说明

本文档描述 `storage/stock/stock_capital_flow/stock.sqlite` 的用途、表结构、索引与数据量级，便于快速了解本地 SQLite 中的数据结构。**下文中的行数与时间范围在文档编写时由数据库实际查询得到**（若你后续追加导入，请以库里为准）。

## 文件概览

| 项目 | 值 |
|------|-----|
| 路径 | `storage/stock/stock_capital_flow/stock.sqlite` |
| 约大小 | 约 297 MiB（310,804,480 字节） |
| 引擎 | SQLite 3 |

## 表一览

| 表名 | 行数 | 简要说明 |
|------|------|----------|
| `stock_basic_info` | 5,280 | 证券基础信息（代码、名称、板块、行业等） |
| `stock_daily` | 1,032,705 | 日行情（OHLC、成交量额、涨跌幅等），含复权维度 |
| `stock_daily_import_log` | 5,201 | 日线导入任务日志（每股一条汇总记录） |
| `stock_individual_fund_flow` | 121,138 | 个股资金流向（主力/超大单/大单/中单/小单等） |
| `stock_individual_fund_flow_import_log` | 1,011 | 资金流向导入日志 |
| `stock_limit_up_candidates_120` | 964 | 近 120 交易日涨停候选/统计衍生结果 |

## 数据时间范围（编写时统计）

| 数据集 | 日期字段 | 最小值 | 最大值 |
|--------|----------|--------|--------|
| 日线 | `trade_date` | 2025-04-29 | 2026-04-30 |
| 个股资金流 | `trade_date` | 2025-09-26 | 2026-04-30 |

`stock_daily.adjust`：当前库内该字段均为**空字符串** `''`（行数 1,032,705，无其他取值），与主键中 `adjust` 列共同标识一条日线记录。

`stock_basic_info.updated_at` 样例范围：约 `2026-05-02T21:38:42` ～ `2026-05-02T21:38:46`。

## 各表字段与主键

### `stock_basic_info`

主板/创业板等交易所证券静态信息。

**主键：** `(exchange, code)`

| 列名 | 类型 | 说明 |
|------|------|------|
| `exchange` | TEXT | 交易所标识（NOT NULL） |
| `code` | TEXT | 证券代码（NOT NULL） |
| `name` | TEXT | 简称（NOT NULL） |
| `full_name` | TEXT | 全称 |
| `board` | TEXT | 板块 |
| `security_type` | TEXT | 证券类型（NOT NULL） |
| `listing_date` | TEXT | 上市日期 |
| `total_shares` | INTEGER | 总股本 |
| `circulating_shares` | INTEGER | 流通股本 |
| `industry` | TEXT | 行业 |
| `source` | TEXT | 数据来源（NOT NULL） |
| `updated_at` | TEXT | 更新时间（NOT NULL） |

---

### `stock_daily`

日 K 线及行情指标；同一证券在不同 `adjust` 下为不同主键行。

**主键：** `(exchange, stock_code, adjust, trade_date)`

| 列名 | 类型 | 说明 |
|------|------|------|
| `exchange` | TEXT | 交易所 |
| `stock_code` | TEXT | 股票代码 |
| `stock_name` | TEXT | 股票名称 |
| `trade_date` | TEXT | 交易日 |
| `open` / `close` / `high` / `low` | REAL | 开收高低 |
| `volume` | INTEGER | 成交量 |
| `amount` | REAL | 成交额 |
| `amplitude` | REAL | 振幅 |
| `pct_change` | REAL | 涨跌幅（% 等，与源数据一致） |
| `change_amount` | REAL | 涨跌额 |
| `turnover_rate` | REAL | 换手率 |
| `adjust` | TEXT | 复权类型（当前库为 `''`） |
| `source` | TEXT | 数据来源 |
| `updated_at` | TEXT | 更新时间 |

---

### `stock_daily_import_log`

日线批量导入的**按证券**汇总日志。

**主键：** `(exchange, code)`

| 列名 | 类型 | 说明 |
|------|------|------|
| `exchange` / `code` / `name` | TEXT | 证券标识与名称 |
| `table_name` | TEXT | 目标表名 |
| `rows_saved` | INTEGER | 写入行数 |
| `status` | TEXT | 状态 |
| `message` | TEXT | 说明或错误信息 |
| `started_at` / `finished_at` | TEXT | 起止时间 |

---

### `stock_individual_fund_flow`

个股日级资金流向（东方财富等源常见字段结构）。

**主键：** `(exchange, code, trade_date)`

| 列名 | 类型 | 说明 |
|------|------|------|
| `exchange` / `code` / `name` | TEXT | 证券 |
| `market` | TEXT | 市场（NOT NULL） |
| `trade_date` | TEXT | 交易日 |
| `close` / `pct_change` | REAL | 收盘、涨跌幅 |
| `main_net_inflow_amount` / `main_net_inflow_ratio` | REAL | 主力净流入额/占比 |
| `super_large_net_inflow_*` | REAL | 超大单净流入额/占比 |
| `large_net_inflow_*` | REAL | 大单净流入额/占比 |
| `medium_net_inflow_*` | REAL | 中单净流入额/占比 |
| `small_net_inflow_*` | REAL | 小单净流入额/占比 |
| `source` / `updated_at` | TEXT | 来源与更新时间 |

---

### `stock_individual_fund_flow_import_log`

资金流向导入的**按证券**日志。

**主键：** `(exchange, code)`

| 列名 | 类型 | 说明 |
|------|------|------|
| `exchange` / `code` / `name` | TEXT | 证券 |
| `market` | TEXT | 市场 |
| `rows_saved` | INTEGER | 写入行数 |
| `status` / `message` | TEXT | 状态与信息 |
| `started_at` / `finished_at` | TEXT | 起止时间 |

---

### `stock_limit_up_candidates_120`

基于约 120 交易日窗口的涨停相关统计与候选列表（含窗口排名、涨跌区间等）。

**主键：** `(exchange, code)`

| 列名 | 类型 | 说明 |
|------|------|------|
| `exchange` / `code` / `name` | TEXT | 证券 |
| `board` / `security_type` | TEXT | 板块、证券类型 |
| `limit_up_count_120` | INTEGER | 窗口内涨停相关计数 |
| `first_limit_up_date` / `last_limit_up_date` | TEXT | 首次/末次相关日期 |
| `max_pct_change` / `min_pct_change` | REAL | 窗口内涨跌幅极值 |
| `hit_dates` | TEXT | 命中日期序列（一般为文本编码） |
| `recent_days` | INTEGER | 统计用近期天数 |
| `window_index` / `window_size` | INTEGER | 窗口序号与长度 |
| `window_start_rank` / `window_end_rank` | INTEGER | 窗口内排名 |
| `min_pct` / `max_pct` | REAL | 筛选用涨跌幅边界 |
| `adjust` | TEXT | 与日线复权维度对齐用 |
| `updated_at` | TEXT | 更新时间 |

---

## 索引（除主键外）

| 索引名 | 定义 |
|--------|------|
| `idx_stock_basic_info_code` | `(code)` |
| `idx_stock_daily_code_date` | `(stock_code, trade_date)` |
| `idx_stock_daily_exchange_code_date` | `(exchange, stock_code, trade_date)` |
| `idx_stock_daily_trade_date` | `(trade_date)` |
| `idx_stock_individual_fund_flow_code_date` | `(code, trade_date)` |
| `idx_stock_limit_up_candidates_120_last_limit_up_date` | `(last_limit_up_date)` |

主键对应的 `sqlite_autoindex_*` 由 SQLite 自动维护，此处不单独列出。

