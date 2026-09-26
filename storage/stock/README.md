# storage/stock/data.sqlite

本地 Tushare SQLite，路径：`storage/stock/data.sqlite`。资金流向、A 股未复权日线、大宗交易与打板专题写在同一库。

- 打板专题：`python collect/board_topic.py`（默认近 365 个自然日；支持 `--days`、`--start-date`、`--end-date`，也可只跟接口名，例如 `python collect/board_topic.py limit_list_d top_list`）
- 大宗交易：`python collect/block_trade.py`（默认近 365 个自然日；支持 `--days 30` 或 `--start-date 2025-09-26 --end-date 2026-09-26`）
- 日线采集：`python collect/daily.py`（默认近 365 个自然日；可用 `--days 5` 试跑）
- 资金流向：`python collect/main.py`（默认近 365 个自然日；可用 `--days 30` 改窗口，也可跟接口名只跑某一个，例如 `python collect/main.py --days 365 moneyflow_dc`）

数据来源为 Tushare Pro，token 从仓库根目录 `.env` 的 `TUSHARE_TOKEN` 读取。日线及资金流冲突时 UPSERT；大宗交易按日事务替换，均可重复跑。此处使用本地 SQLite，不使用 `.env` 中的 MySQL 配置。

下文“文件概览”及“表一览”里的日线/资金流仍是 2026-09-15 的采集快照。2026-09-26 新增大宗交易，见“大宗交易”章节；同日新增打板专题，行数见“打板专题”章节，统计时刻为 17:52。

本次大宗交易入库：请求区间 2025-09-26～2026-09-26，实际数据 2025-09-26～2026-09-24，共 39,882 行、241 个交易日、3,090 个证券代码。

## 文件概览

| 项目 | 值 |
|------|-----|
| 路径 | `storage/stock/data.sqlite` |
| 约大小 | 约 8551.6 MiB（8,966,078,464 字节，2026-09-26 17:52；`ths_daily` 仍在写入） |
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
| `hm_list` | 117 | — | `(name)` | 游资名录，当前快照 |
| `ths_index` | 2,517 | — | `(ts_code)` | 同花顺板块列表，当前快照 |
| `ths_member` | 341,887 | — | `(ts_code, con_code)` | 同花顺最新成分，1,998 / 2,517 个板块，仍在采集 |
| `ths_daily` | 482 | 241 | `(trade_date, ts_code)` | 同花顺板块行情，仅 2 个板块，仍在采集 |
| `limit_list_d` | 26,357 | 241 | `(trade_date, ts_code, limit_flag)` | 涨跌停和炸板 |
| `limit_list_ths` | 42,771 | 241 | `(trade_date, ts_code, limit_type)` | 同花顺涨跌停榜单 |
| `limit_step` | 4,235 | 241 | `(trade_date, ts_code)` | 连板天梯 |
| `limit_cpt_list` | 4,831 | 241 | `(trade_date, ts_code)` | 涨停最强板块 |
| `kpl_list` | 97,107 | 241 | `(trade_date, ts_code, tag)` | 开盘啦榜单 |
| `kpl_concept_cons` | 2,577,725 | 240 | `(trade_date, ts_code, con_code)` | 开盘啦题材成分 |
| `top_list` | 19,066 | 241 | `(trade_date, record_no)` | 龙虎榜每日统计 |
| `top_inst` | 202,116 | 241 | `(trade_date, record_no)` | 龙虎榜机构明细 |
| `hm_detail` | 62,934 | 241 | `(trade_date, record_no)` | 游资每日明细 |
| `ths_hot` | 1,868,354 | 240 | `(trade_date, market, data_type, ts_code, rank_time)` | 同花顺热榜 |
| `dc_hot` | 3,229,360 | 208 | `(trade_date, market, hot_type, ts_code, rank_time)` | 东财热榜 |
| `dc_index` | 202,110 | 241 | `(trade_date, ts_code)` | 东财板块 |
| `dc_daily` | 242,206 | 241 | `(trade_date, ts_code)` | 东财板块行情 |
| `dc_member` | 12,977,289 | 173 | `(trade_date, ts_code, con_code)` | 东财成分，已中止，至 2026-06-22 |
| `tdx_index` | 147,297 | 241 | `(trade_date, ts_code)` | 通达信板块 |
| `tdx_daily` | 148,247 | 241 | `(trade_date, ts_code)` | 通达信板块行情 |
| `tdx_member` | 10,195,198 | 107 | `(trade_date, ts_code, con_code)` | 通达信成分，已中止，至 2026-03-16 |
| `stk_auction` | 0 | 0 | `(trade_date, ts_code)` | 开盘竞价，无单独权限，未入库 |
| `board_topic_slice` | — | — | `(api_name, slice_key)` | 打板采集断点 |
| `import_log` | 70 | — | `id` | 采集任务日志 |

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

## `block_trade`（大宗交易）

接口：`block_trade`，大宗交易逐笔明细。采集入口：`python collect/block_trade.py`。
使用官方 HTTPS 接口，按交易日历逐日请求，每页最多 1000 行，通过 `offset/limit` 拉取后续页。

字段：

- `trade_date`（TEXT）：成交日期，格式为 `YYYY-MM-DD`。
- `record_no`（INTEGER）：本地当日记录序号，从 1 开始；不是交易所成交编号。
- `ts_code`（TEXT）：TS 证券代码，保留接口返回的全部代码。
- `price`（REAL）：成交价，原样保留接口数值。
- `vol`（REAL）：成交量，单位为万股。
- `amount`（REAL）：成交金额，原样保留接口数值；引用的接口文档没有显式标注单位。
- `buyer` / `seller`（TEXT）：买方 / 卖方营业部。
- `updated_at`（TEXT）：本地写入时间，ISO 8601。

主键为 `(trade_date, record_no)`；另建索引 `idx_block_trade_ts_code_trade_date`，用于按证券和日期查询。
同一股票同一天可能有多笔成交，因此不能以 `(ts_code, trade_date)` 去重；即使全部接口字段相同，也保留其出现次数。
当日全部分页抓取并通过校验后，在一个事务中替换该日记录，重跑不会累加重复数据，并可同步源数据修订。
请求失败、分页重复、字段缺失、日期异常或写入失败时保留该日原数据；空响应也不会覆盖已有记录。
采集日志写入 `import_log`，部分失败时返回非零退出码，可指定失败日期区间重跑。

2026-09-26 实际入库与核验结果：

- 请求区间：2025-09-26～2026-09-26；实际成交日期：2025-09-26～2026-09-24。
- 写入 39,882 行，覆盖 241 个交易日、3,090 个证券代码；与 SSE 交易日历完全一致，无缺失或额外日期。
- 单日最多 424 行（2025-12-12），本次各交易日均未触及 1000 行分页上限。
- 全字段相同记录的额外出现次数为 3,907，均按源接口保留，未擅自合并成交。
- 主键无重复、必填字段无异常；SQLite `PRAGMA quick_check` 返回 `ok`。
- 抽查 2025-09-26、2025-12-31、2026-09-24，与源接口逐笔一致（包括相同明细出现次数）。
- 成功任务时间：2026-09-26 15:26:11～15:29:42；`import_log.status = 'ok'`，写入行数与表内一致。
- 首次调用曾因 SDK 与 HTTPS 地址格式不匹配返回空日历，未写入成交；改用官方 HTTPS JSON 接口后全量成功。失败日志保留以便追溯。

测试：`python -m unittest collect.test_block_trade -v`，12 项通过。

---

## 打板专题

采集入口：`python collect/board_topic.py`。请求窗口 2025-09-26～2026-09-26，上交所开市日 241 天，实际行情日期 2025-09-26～2026-09-24。有业务主键的表按主键 UPSERT；`top_list`、`top_inst`、`hm_detail` 按日整表替换，`record_no` 只是当日序号。已成功的日期或代码记在 `board_topic_slice`，重跑会跳过。

列名与接口不一致的地方：`limit_list_d.limit` 入库为 `limit_flag`；`hm_list.desc`、`kpl_concept_cons.desc` 入库为 `intro`；`tdx_daily` 的 `3day/5day/10day/20day/60day/1year` 入库为 `pct_3d/pct_5d/pct_10d/pct_20d/pct_60d/pct_1y`。日期为 `YYYY-MM-DD`。每张表都有 `updated_at`。

`hm_list`、`ths_index`、`ths_member` 没有历史日期，只存当前快照。`stk_auction` 需要单独开权限，两次调用均为 `import_log.status = 'failed'`，表是空的。

`dc_member`、`tdx_member` 单日成分约 8 万～10 万行，2026-09-26 决定不再继续拉。已写入的部分保留：东财 12,977,289 行、173 个交易日（至 2026-06-22）；通达信 10,195,198 行、107 个交易日（至 2026-03-16）。

统计于 2026-09-26 17:52。当时 `ths_member` 完成 1,998 / 2,517 个板块（341,887 行），`ths_daily` 完成 2 / 2,517 个板块（482 行，这两个板块自身覆盖 241 个交易日）。这两张表仍在采集，行数还会增加。

`kpl_concept_cons`、`ths_hot` 缺 2025-10-28，当天接口没有记录。`dc_hot` 有 33 个交易日（集中在 2025-10-27～2025-12-15）返回的行没有证券代码，这些行已丢弃，所以表内只有 208 天。

分类行数：`limit_list_d` 涨停 16,692、炸板 6,165、跌停 3,500。`limit_list_ths` 涨停池 19,309、炸板池 7,283、连扳池 5,936、跌停池 5,596、冲刺涨停 4,647。`kpl_list` 竞价 47,091、涨停 19,324、自然涨停 17,919、炸板 7,193、跌停 5,580。`ths_index` 行业 1,121、概念 899、主题 250、特色 113、宽基 75、地域 33、风格 26。`dc_index` 概念 113,414、行业 81,225、地域 7,471。`tdx_index` 概念 64,921、行业 44,166、风格 30,498、地区 7,712。

### `hm_list`

游资名录。接口字段 `desc` 入库为 `intro`。主键 `(name)`。

| 列名 | 类型 | 说明 |
|------|------|------|
| `name` | TEXT | 游资名称 |
| `intro` | TEXT | 说明（接口字段 `desc`） |
| `orgs` | TEXT | 关联机构 |

### `ths_index` / `ths_member` / `ths_daily`

`ths_index` 按类型 N/I/R/S/ST/TH/BB 各拉一次，主键 `(ts_code)`。`list_date` 为上市日期。`count` 为成分个数。

`ths_member` 是最新成分，不是近一年历史。主键 `(ts_code, con_code)`。`weight` 权重，`in_date` / `out_date` 纳入和剔除日期，`is_new` 是否最新。

`ths_daily` 按板块代码拉区间行情，避免按日一次拉全市场时被 3000 行截断。主键 `(trade_date, ts_code)`。价格为点位；`vol` 成交量（手）；`turnover_rate` 换手率（%）；`total_mv` / `float_mv` 总市值 / 流通市值（元）。

### 涨跌停与开盘啦榜单

`limit_list_d` 按 U/D/Z 分三次拉取。主键 `(trade_date, ts_code, limit_flag)`。`amount` 成交额，`limit_amount` 板上成交金额，`float_mv` / `total_mv` 流通市值和总市值，`turnover_ratio` 换手率，`fd_amount` 封单金额，`open_times` 炸板或开板次数，`up_stat` 为 N/T（T 天有 N 次涨停），`limit_times` 连板数。

`limit_list_ths` 按涨停池、连扳池、冲刺涨停、炸板池、跌停池分拉取。主键 `(trade_date, ts_code, limit_type)`。`price` 收盘价（元），`pct_chg` 涨跌幅（%），`open_num` 打开次数，`lu_desc` 涨停原因，`tag` / `status` 标签和状态。封板时间、封单、换手、流通市值、封板率、成交额、涨速、总市值（亿元）和 `market_type` 按接口原样保存。

`limit_step` 主键 `(trade_date, ts_code)`。`nums` 为连板次数。

`limit_cpt_list` 主键 `(trade_date, ts_code)`。`days` 上榜天数，`up_stat` 连板高度，`cons_nums` 连板家数，`up_nums` 涨停家数，`pct_chg` 涨跌幅（%），`rank` 板块热点排名。

`kpl_list` 按涨停、炸板、跌停、自然涨停、竞价分拉取。主键 `(trade_date, ts_code, tag)`。时间字段为涨停、跌停、开板和最后涨停时间；金额字段（主力净额、竞价成交额、封单、成交额等）单位为元；涨跌幅和换手为 %。

### `kpl_concept_cons`

开盘啦题材成分。主键 `(trade_date, ts_code, con_code)`。接口字段 `desc` 入库为 `intro`。`hot_num` 为人气值。240 个交易日有记录。

### 龙虎榜与游资明细

`top_list`、`top_inst`、`hm_detail` 主键都是 `(trade_date, record_no)`。同一天同一股票可以有多行，全字段相同的行也保留。

`top_list`：收盘价、涨跌幅、换手率，以及总成交额、龙虎榜买卖额、净买入额、占比、流通市值和上榜理由。金额单位按接口原样，文档未另行换算。

`top_inst`：`exalter` 营业部，`side` 为 0（买入额前 5）或 1（卖出额前 5）。`buy` / `sell` / `net_buy` 单位为元，`buy_rate` / `sell_rate` 为占总成交比例。`reason` 为上榜理由。

`hm_detail`：`buy_amount` / `sell_amount` / `net_amount` 单位为元。`hm_name` 游资名称，`hm_orgs` 关联机构，`tag` 标签。

### 热榜

`ths_hot` 按热股、ETF、可转债、行业板块、概念板块、期货、港股、热基、美股拉取，`is_new='N'`，保留每个 `rank_time`。主键 `(trade_date, market, data_type, ts_code, rank_time)`。`rank` 排行，`hot` 热度值，`pct_change` 涨跌幅（%），`current_price` 当前价，`concept` 标签，`rank_reason` 上榜解读。

`dc_hot` 按 A股市场、ETF基金、港股市场、美股市场，以及人气榜、飙升榜拉取，同样保留每个 `rank_time`。主键 `(trade_date, market, hot_type, ts_code, rank_time)`。`data_type` 为接口返回的数据类型。没有证券代码的行不入库。

### 东财与通达信板块

`dc_index` 按行业、概念、地域拉取。主键 `(trade_date, ts_code)`。`total_mv` 总市值（万元），`turnover_rate` 换手率，`up_num` / `down_num` 上涨和下跌家数，`level` 行业层级。

`dc_daily` 主键 `(trade_date, ts_code)`。点位为开高低收；`vol` 成交量（股），`amount` 成交额（元），`swing` 振幅，`turnover_rate` 换手率，`category` 分类板块。

`dc_member` 主键 `(trade_date, ts_code, con_code)`。只保留已拉取的 173 个交易日。

`tdx_index` 按概念、行业、风格、地区拉取。主键 `(trade_date, ts_code)`。股本和市值单位为亿，`idx_count` 为成分个数。

`tdx_daily` 主键 `(trade_date, ts_code)`。`vol` 成交量（手），`amount` 成交额（万元）。涨跌幅、换手、振幅、量比为 %。`pct_3d` 至 `pct_1y`、`mtd`、`ytd` 为对应区间涨幅（%）。`pe` / `pb` 按文本保存。`float_mv` 流通市值（亿），`ab_total_mv` 为 AB 股总市值（亿）。`bm_buy_net` 主买净额（元）。

`tdx_member` 主键 `(trade_date, ts_code, con_code)`。只保留已拉取的 107 个交易日。

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

2026-09-15 的资金流采集日志包含 30 日试跑与 365 日全量各一次，当时最近一次 8 个接口均为 `ok`（2025-09-15 ~ 2026-09-15）。2026-09-26 新增两条 `block_trade` 日志：首次失败未写入成交，随后全年采集成功，写入 39,882 行。同日打板专题有多条日志；`stk_auction` 因没有单独权限，两条均为 `failed`、写入 0 行。
