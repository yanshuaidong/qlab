# collect：同花顺主力数据采集

在 **Windows** 下通过截图与 OCR，从同花顺客户端采集「主力」双向柱状图相关数据，写入本地 SQLite；可选用 `fetch_stock_daily.py` 基于同一数据库补全 A 股日线（OHLCV）。

## 环境要求

- **操作系统**：`main.py` 依赖窗口枚举与布局，仅支持 Windows。
- **Python**：建议 3.10+。
- **主要依赖**（按脚本实际导入）：
  - 必需：`pyautogui`、`Pillow`
  - OCR：`pytesseract` 和/或 `cnocr`（程序内可选导入，按配置选择引擎）
  - 交易日历 / 日线：`akshare`（`main.py` 生成交易日历时可能用到；`fetch_stock_daily.py` 拉取日线必需）

安装示例：

```bash
pip install pyautogui Pillow akshare
# 按需
pip install pytesseract cnocr
```

Tesseract 若使用需本机安装并配置 PATH；CnOCR 首次运行会下载模型。

## 目录与数据文件

| 路径 | 说明 |
|------|------|
| `config.json` | 截图区域、导航键位、OCR 选项、`latest_trade_date` 等（菜单 **2** 生成） |
| `data/ths_fund_flow.sqlite` | 主力流水表 `ths_fund_flow` 与日线表 `stock_daily`（后者由 `fetch_stock_daily.py` 维护） |
| `runs/<run_id>/` | 单次采集输出：`stock_codes.json`、`scale_ocr.json`、柱状图截图等 |
| `config_previews/` | 配置时的区域预览图（若生成） |

## 数据库表说明（`data/ths_fund_flow.sqlite`）

库中主要有两张表：主力相关数据由 `main.py` 第 4 步写入 `ths_fund_flow`；日线由 `fetch_stock_daily.py` 维护 `stock_daily`。

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

## `main.py`：交互菜单

```bash
python collect/main.py          # 正常模式
python collect/main.py test     # 测试模式：第 3、4 步只处理前 3 只股票
```

启动后菜单：

1. **调整同花顺窗口**：按默认逻辑把标题含「同花顺」的窗口放到合适大小与位置。  
2. **框选区域并写入 `config.json`**：左侧股票列表、主力比例尺文字区、双向柱状图区域；可配置每屏行数、按键导航、`latest_trade_date` 等。  
3. **前半段采集**：自动切换股票、OCR 比例尺、截柱状图，结果写入 `runs/<run_id>/`。  
4. **后半段入库**：根据最新柱子的像素与 OCR 数值拟合比例，推算历史柱对应买卖量等，**upsert** 到 `ths_fund_flow`。

退出：选 `0`，或输入 `q` / `quit` / `exit`（配置流程中亦支持）。

### 配置要点

- `latest_trade_date`：与界面一致的最新交易日，用于对齐柱状图与交易日序列。  
- `rows_per_screen`、导航键、`settle_seconds`：控制列表滚动与等待截图稳定。  
- `ocr`：`stock_code` / `scale` 的语言与 PSM；`scale_engine` 等可选自动在引擎间切换。

## `fetch_stock_daily.py`：补全日线

以 `ths_fund_flow` 中的股票与所需 `trade_date` 区间为权威，在 `stock_daily` 表中补齐缺失的日线；数据来自 **akshare**（先东方财富接口，失败则尝试腾讯相关接口）。

```bash
python collect/fetch_stock_daily.py
python collect/fetch_stock_daily.py --stock 600000 --stock 000001 --limit 5 --dry-run
```

常用参数：

| 参数 | 说明 |
|------|------|
| `--db` | SQLite 路径，默认 `collect/data/ths_fund_flow.sqlite` |
| `--stock` | 可重复，只处理指定 6 位代码 |
| `--limit` | 只处理按代码排序后的前 N 只 |
| `--adjust` | `""`（不复权） / `qfq` / `hfq` |
| `--timeout` / `--retries` / `--sleep` | 请求超时、重试与间隔 |
| `--dry-run` | 只打印缺口，不请求、不写库 |

要求：`collect/data/ths_fund_flow.sqlite` 已存在且含 `ths_fund_flow` 数据；脚本会 `CREATE TABLE IF NOT EXISTS stock_daily` 并建立索引。

## 故障排查提示

- **非 Windows 运行 `main.py`**：会直接退出并提示仅支持 Windows。  
- **未配置先跑 3/4**：缺 `config.json` 或 `runs` 时，对应步骤会报错提示先完成前置菜单。  
- **日线拉取失败**：检查网络、akshare 版本及股票代码是否在数据源覆盖范围内；可看脚本输出的失败股票与错误信息。
