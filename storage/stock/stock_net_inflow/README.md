## 数据库表说明

数据库地址：D:\ysd\qlab\storage\stock\stock_net_inflow\data.sqlite


库中主要有两张表：
主力相关数据 `ths_fund_flow`；
日线`stock_daily`。

### 表一：`ths_fund_flow`（同花顺主力柱状图解析结果）

主键：`(stock_code, trade_date)`。

| 字段 | 类型 | 含义 |
|------|------|------|
| `stock_code` | TEXT | 股票代码，6 位数字字符串 |
| `trade_date` | TEXT | 交易日，格式 `YYYY-MM-DD` |
| `institution_buy_wan_shou` | REAL | 机构买入量（万手） |
| `institution_sell_wan_shou` | REAL | 机构卖出量（万手） |
| `net_inflow_wan_shou` | REAL | 净流入（万手），一般为买入减卖出 |
| `turnover_ratio_percent` | REAL | 换手率（%）；界面比例尺上通常仅最新交易日有值，历史日多为空 |
| `source_run_id` | TEXT | 对应一次采集的 run 标识（与 `runs/<run_id>/` 目录名一致） |
| `source_bar_image` | TEXT | 生成该批记录时所依据的柱状图截图文件路径 |
| `estimated` | INTEGER | `0` 表示最新交易日，买卖量等主要取自比例尺 OCR；`1` 表示更早的交易日，由柱高像素按比例推算 |
| `updated_at` | TEXT | 本条记录写入/更新的本地时间（ISO 8601） |

### 表二：`stock_daily`（A 股日线行情，akshare 补充）

主键：`(stock_code, trade_date, adjust)`。同一股票同一日可因复权方式不同存多行。

| 字段 | 类型 | 含义 |
|------|------|------|
| `stock_code` | TEXT | 股票代码，6 位 |
| `trade_date` | TEXT | 交易日 `YYYY-MM-DD` |
| `open_price` | REAL | 开盘价 |
| `close_price` | REAL | 收盘价 |
| `high_price` | REAL | 最高价 |
| `low_price` | REAL | 最低价 |
| `volume_shou` | INTEGER | 成交量（手） |
| `amount_yuan` | REAL | 成交额（元） |
| `amplitude_percent` | REAL | 振幅（%） |
| `change_percent` | REAL | 涨跌幅（%） |
| `change_amount` | REAL | 涨跌额（元） |
| `turnover_rate_percent` | REAL | 换手率（%） |
| `source` | TEXT | 数据来源标识，如 `akshare.stock_zh_a_hist` 或 `akshare.stock_zh_a_hist_tx` |
| `adjust` | TEXT | 复权方式：`''` 不复权、`qfq` 前复权、`hfq` 后复权 |
| `updated_at` | TEXT | 本条写入/更新时间（ISO 8601） |