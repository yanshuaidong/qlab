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

### `ths_fund_flow` 表（摘要）

主键 `(stock_code, trade_date)`。字段包括：机构买/卖（万手）、净流入（万手）、换手率（仅最新交易日可能有值）、来源 run、柱状图源图路径、`estimated`（非最新交易日多为估算）等。

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
