# storage/stock/data.sqlite

本地 Tushare SQLite，路径：`storage/stock/data.sqlite`。资金流向与 A 股未复权日线写在同一库。

- 日线采集：`python collect/daily.py`（默认近 365 个自然日；可用 `--days 5` 试跑）
- 资金流向：`python collect/main.py`（默认近 365 个自然日；可用 `--days 30` 改窗口，也可跟接口名只跑某一个，例如 `python collect/main.py --days 365 moneyflow_dc`）

数据来源为 Tushare Pro，token 从仓库根目录 `.env` 的 `TUSHARE_TOKEN` 读取。冲突时 UPSERT，可重复跑。

下文中的行数、日期范围、文件大小在文档编写时由数据库实际查询得到；后续追加导入请以库里为准。

## 文件概览

| 项目 | 值 |
|------|-----|
| 路径 | `storage/stock/data.sqlite` |
| 约大小 | 约 1227.8 MiB（1,287,389,184 字节） |
| 引擎 | SQLite 3 |
| 采集窗口 | 2025-09-15 ~ 2026-09-15（近 365 个自然日） |
| 日线交易日 | 2025-09-15 ~ 2026-09-15，共 243 个开市日 |
| 资金流交易日 | 2025-09-15 ~ 2026-09-14，共 242 个开市日 |
| 最近一次日线采集 | 2026-09-15 约 20:23～20:27 |

2026-09-15 当天在交易日历中为开市日，但盘后资金流尚未发布，各接口该日返回 0 行，属正常情况。

`moneyflow_dc` 单日超过 6000 行上限，采集脚本用 `offset/limit` 分页补全；当前单日约 5866～6106 行。

`moneyflow_hsgt` 只有 235 个交易日（少于 A 股 242 天），是港股通休市日缺失，不是截断（单次上限 300 行，本次一次拉完）。

## 表一览

| 表名 | 行数 | 交易日数 | 主键 | 简要说明 |
|------|------|----------|------|----------|
| `daily` | 1,332,015 | 243 | `(ts_code, trade_date)` | A 股未复权日线（Tushare `daily`） |
| `moneyflow` | 1,263,693 | 242 | `(ts_code, trade_date)` | 个股资金流向（Tushare L2 主动买卖单） |
| `moneyflow_dc` | 1,438,347 | 242 | `(ts_code, trade_date)` | 东财个股资金流向 |
| `moneyflow_ths` | 1,245,815 | 242 | `(ts_code, trade_date)` | 同花顺个股资金流向 |
| `moneyflow_mkt_dc` | 242 | 242 | `(trade_date)` | 东财大盘资金流向 |
| `moneyflow_ind_dc` | 242,752 | 242 | `(ts_code, trade_date, content_type)` | 东财板块资金流向（行业/概念/地域） |
| `moneyflow_ind_ths` | 21,780 | 242 | `(ts_code, trade_date)` | 同花顺行业资金流向 |
| `moneyflow_cnt_ths` | 93,384 | 242 | `(ts_code, trade_date)` | 同花顺概念板块资金流向 |
| `moneyflow_hsgt` | 235 | 235 | `(trade_date)` | 沪深港通资金流向 |
| `import_log` | 20 | — | `id` | 采集任务日志 |

`moneyflow_ind_dc` 按 `content_type`：行业 121,374、概念 113,876、地域 7,502。各业务表主键无重复。

日期字段入库为 `YYYY-MM-DD`。每张业务表都有 `updated_at`（本地写入时间，ISO 8601）。

---

## `daily`

接口：`daily`。A 股未复权日线，停牌日无记录。交易日每天 15 点～16 点之间入库。当前单日约 5420～5550 行，未超过 6000 上限；脚本仍保留 `offset/limit` 分页。`ah_vol` / `ah_amount` 自 2026-07-06 起才有数据（当前 52 个交易日、269,763 行非空）。

采集入口：`python collect/daily.py`。2026-09-15 当天日线已入库。

| 列名 | 类型 | 说明 |
|------|------|------|
| `ts_code` | TEXT | TS 代码 |
| `trade_date` | TEXT | 交易日 |
| `open` / `high` / `low` / `close` | REAL | 开高低收（未复权） |
| `pre_close` | REAL | 昨收价（除权价） |
| `change` | REAL | 涨跌额 |
| `pct_chg` | REAL | 涨跌幅（%），基于除权后昨收 |
| `vol` | REAL | 成交量（手） |
| `amount` | REAL | 成交额（千元） |
| `ah_vol` / `ah_amount` | REAL | 盘后成交量（手）/ 成交额（千元） |
| `updated_at` | TEXT | 本地写入时间 |

索引：`idx_daily_trade_date`、`idx_daily_ts_code`。

---

## `moneyflow`

接口：`moneyflow`。小单 5 万以下、中单 5～20 万、大单 20～100 万、特大单 ≥100 万；净流入基于 L2 主动买卖单，不能把大小单简单相减。

| 列名 | 类型 | 说明 |
|------|------|------|
| `ts_code` | TEXT | TS 代码 |
| `trade_date` | TEXT | 交易日 |
| `buy_sm_vol` / `buy_sm_amount` | INTEGER / REAL | 小单买入量（手）/ 金额（万元） |
| `sell_sm_vol` / `sell_sm_amount` | INTEGER / REAL | 小单卖出量（手）/ 金额（万元） |
| `buy_md_vol` / `buy_md_amount` | INTEGER / REAL | 中单买入量（手）/ 金额（万元） |
| `sell_md_vol` / `sell_md_amount` | INTEGER / REAL | 中单卖出量（手）/ 金额（万元） |
| `buy_lg_vol` / `buy_lg_amount` | INTEGER / REAL | 大单买入量（手）/ 金额（万元） |
| `sell_lg_vol` / `sell_lg_amount` | INTEGER / REAL | 大单卖出量（手）/ 金额（万元） |
| `buy_elg_vol` / `buy_elg_amount` | INTEGER / REAL | 特大单买入量（手）/ 金额（万元） |
| `sell_elg_vol` / `sell_elg_amount` | INTEGER / REAL | 特大单卖出量（手）/ 金额（万元） |
| `net_mf_vol` / `net_mf_amount` | INTEGER / REAL | 净流入量（手）/ 净流入额（万元） |
| `net_mf_amount_rate` | REAL | 净流入额占当日成交额（%），本地计算 |
| `buy_elg_amount_rate` / `buy_lg_amount_rate` / `buy_md_amount_rate` / `buy_sm_amount_rate` | REAL | 特大/大/中/小单净流入占比（%），本地计算：`(买-卖)×1000/daily.amount` |
| `updated_at` | TEXT | 本地写入时间 |

占比与东财同一分母：`daily.amount` 为千元、资金流为万元，故 `占比 = 净额 × 1000 / daily.amount`。官方 `net_mf_amount` 不把各档简单相加；各档净额仍用买减卖。成交额为空或 0 则占比为空。采集 `moneyflow` 当日写入后会按日回填；全量重算：`python collect/moneyflow_rates.py`。

主力净流入 = 特大单净额 + 大单净额，主力占比 = `(buy_elg − sell_elg + buy_lg − sell_lg) × 1000 / daily.amount`。`net_mf_amount_rate` 是 L2 主动买卖总净额占比，不是主力占比；一字涨跌停时会接近 ±100%。K 线页 L2「主力净流入占比」用主力口径；主动买卖总净额另列。

索引：`idx_moneyflow_trade_date`、`idx_moneyflow_ts_code`。

---

## `moneyflow_dc`

接口：`moneyflow_dc`。东财个股资金流向，每日盘后更新。

| 列名 | 类型 | 说明 |
|------|------|------|
| `ts_code` / `trade_date` / `name` | TEXT | 代码、交易日、名称 |
| `pct_change` / `close` | REAL | 涨跌幅、收盘价 |
| `net_amount` / `net_amount_rate` | REAL | 主力净流入额（万元）/ 占比（%） |
| `buy_elg_amount` / `buy_elg_amount_rate` | REAL | 超大单净流入额（万元）/ 占比（%） |
| `buy_lg_amount` / `buy_lg_amount_rate` | REAL | 大单净流入额（万元）/ 占比（%） |
| `buy_md_amount` / `buy_md_amount_rate` | REAL | 中单净流入额（万元）/ 占比（%） |
| `buy_sm_amount` / `buy_sm_amount_rate` | REAL | 小单净流入额（万元）/ 占比（%） |
| `updated_at` | TEXT | 本地写入时间 |

索引：`idx_moneyflow_dc_trade_date`、`idx_moneyflow_dc_ts_code`。

---

## `moneyflow_ths`

接口：`moneyflow_ths`。同花顺个股资金流向，每日盘后更新。

| 列名 | 类型 | 说明 |
|------|------|------|
| `ts_code` / `trade_date` / `name` | TEXT | 代码、交易日、名称 |
| `pct_change` / `latest` | REAL | 涨跌幅、最新价 |
| `net_amount` | REAL | 资金净流入（万元） |
| `net_d5_amount` | REAL | 5 日主力净额（万元） |
| `buy_lg_amount` / `buy_lg_amount_rate` | REAL | 大单净流入额（万元）/ 占比（%） |
| `buy_md_amount` / `buy_md_amount_rate` | REAL | 中单净流入额（万元）/ 占比（%） |
| `buy_sm_amount` / `buy_sm_amount_rate` | REAL | 小单净流入额（万元）/ 占比（%） |
| `updated_at` | TEXT | 本地写入时间 |

索引：`idx_moneyflow_ths_trade_date`、`idx_moneyflow_ths_ts_code`。

---

## `moneyflow_mkt_dc`

接口：`moneyflow_mkt_dc`。东财大盘资金流向。金额字段单位为元。

| 列名 | 类型 | 说明 |
|------|------|------|
| `trade_date` | TEXT | 交易日 |
| `close_sh` / `pct_change_sh` | REAL | 上证收盘、涨跌幅（%） |
| `close_sz` / `pct_change_sz` | REAL | 深证收盘、涨跌幅（%） |
| `net_amount` / `net_amount_rate` | REAL | 主力净流入净额（元）/ 占比（%） |
| `buy_elg_amount` / `buy_elg_amount_rate` | REAL | 超大单净流入净额（元）/ 占比（%） |
| `buy_lg_amount` / `buy_lg_amount_rate` | REAL | 大单净流入净额（元）/ 占比（%） |
| `buy_md_amount` / `buy_md_amount_rate` | REAL | 中单净流入净额（元）/ 占比（%） |
| `buy_sm_amount` / `buy_sm_amount_rate` | REAL | 小单净流入净额（元）/ 占比（%） |
| `updated_at` | TEXT | 本地写入时间 |

---

## `moneyflow_ind_dc`

接口：`moneyflow_ind_dc`。东财板块资金流向。`content_type` 为 `行业`、`概念` 或 `地域`。金额字段单位为元。

| 列名 | 类型 | 说明 |
|------|------|------|
| `ts_code` / `trade_date` / `content_type` / `name` | TEXT | 板块代码、交易日、类型、名称 |
| `pct_change` / `close` | REAL | 板块涨跌幅（%）、最新指数 |
| `net_amount` / `net_amount_rate` | REAL | 主力净流入净额（元）/ 占比（%） |
| `buy_elg_amount` / `buy_elg_amount_rate` | REAL | 超大单净流入净额（元）/ 占比（%） |
| `buy_lg_amount` / `buy_lg_amount_rate` | REAL | 大单净流入净额（元）/ 占比（%） |
| `buy_md_amount` / `buy_md_amount_rate` | REAL | 中单净流入净额（元）/ 占比（%） |
| `buy_sm_amount` / `buy_sm_amount_rate` | REAL | 小单净流入净额（元）/ 占比（%） |
| `buy_sm_amount_stock` | TEXT | 今日主力净流入最大股 |
| `rank` | INTEGER | 序号 |
| `updated_at` | TEXT | 本地写入时间 |

索引：`idx_moneyflow_ind_dc_trade_date`、`idx_moneyflow_ind_dc_type_date`。

---

## `moneyflow_ind_ths`

接口：`moneyflow_ind_ths`。同花顺行业资金流向。资金字段单位为亿元。

| 列名 | 类型 | 说明 |
|------|------|------|
| `ts_code` / `trade_date` / `industry` | TEXT | 板块代码、交易日、板块名称 |
| `lead_stock` | TEXT | 领涨股票名称 |
| `close` / `pct_change` | REAL | 收盘指数、指数涨跌幅 |
| `company_num` | INTEGER | 公司数量 |
| `pct_change_stock` / `close_price` | REAL | 领涨股涨跌幅、领涨股最新价 |
| `net_buy_amount` / `net_sell_amount` / `net_amount` | REAL | 流入 / 流出 / 净额（亿元） |
| `updated_at` | TEXT | 本地写入时间 |

索引：`idx_moneyflow_ind_ths_trade_date`。

---

## `moneyflow_cnt_ths`

接口：`moneyflow_cnt_ths`。同花顺概念板块资金流向。资金字段单位为亿元。

| 列名 | 类型 | 说明 |
|------|------|------|
| `ts_code` / `trade_date` / `name` | TEXT | 板块代码、交易日、板块名称 |
| `lead_stock` | TEXT | 领涨股票名称 |
| `close_price` / `pct_change` / `industry_index` | REAL | 最新价、涨跌幅、板块指数点位 |
| `company_num` | INTEGER | 公司数量 |
| `pct_change_stock` | REAL | 领涨股涨跌幅 |
| `net_buy_amount` / `net_sell_amount` / `net_amount` | REAL | 流入 / 流出 / 净额（亿元） |
| `updated_at` | TEXT | 本地写入时间 |

索引：`idx_moneyflow_cnt_ths_trade_date`。

---

## `moneyflow_hsgt`

接口：`moneyflow_hsgt`。沪股通、深股通、港股通每日资金流向。`hgt` / `sgt` / `north_money` / `south_money` 单位为百万元。

| 列名 | 类型 | 说明 |
|------|------|------|
| `trade_date` | TEXT | 交易日 |
| `ggt_ss` | REAL | 港股通（上海） |
| `ggt_sz` | REAL | 港股通（深圳） |
| `hgt` | REAL | 沪股通（百万元） |
| `sgt` | REAL | 深股通（百万元） |
| `north_money` | REAL | 北向资金（百万元） |
| `south_money` | REAL | 南向资金（百万元） |
| `updated_at` | TEXT | 本地写入时间 |

---

## `import_log`

每次采集每个接口写一行（重跑会追加，不覆盖历史）。

| 列名 | 类型 | 说明 |
|------|------|------|
| `id` | INTEGER | 自增主键 |
| `api_name` | TEXT | 接口名 |
| `start_date` / `end_date` | TEXT | 本次请求的自然日区间 |
| `rows_saved` | INTEGER | 写入/更新行数 |
| `status` | TEXT | `ok` / `partial` / `failed` |
| `message` | TEXT | 失败或部分失败时的错误信息 |
| `started_at` / `finished_at` | TEXT | 起止时间 |

当前库内日志包含 30 日试跑与 365 日全量各一次；最近一次 8 个接口均为 `ok`（2025-09-15 ~ 2026-09-15）。
