# coll2 个股资金流向采集（`main.py`）

使用 [akshare](https://github.com/akfamily/akshare) 的 `stock_individual_fund_flow` 拉取东方财富**个股日级资金流向**，写入本地 SQLite。

## 依赖

```bash
pip install akshare pandas
```

## 运行

在仓库根目录执行：

```bash
python collect/coll2/main.py
```

或使用绝对路径：

```bash
python D:\ysd\qlab\collect\coll2\main.py
```

查看参数说明：

```bash
python collect/coll2/main.py -h
```

## 默认行为

| 项 | 默认值 |
|----|--------|
| 数据库 | `collect/coll2/data/qlab_coll2_stock.sqlite` |
| 股票池表 | `stock_basic_info` |
| 交易所过滤 | `SSE,SZSE,BSE` |
| 证券类型过滤 | `A股` |
| 已拉取跳过 | 是：跳过 `stock_individual_fund_flow_import_log` 中 `status=ok` 的股票 |
| 请求间隔 | 每只股票之间休眠 **1 秒** |

## 写入的表

- **`stock_individual_fund_flow`**：日级资金流向明细（主键 `exchange, code, trade_date`）。
- **`stock_individual_fund_flow_import_log`**：按证券的导入日志（主键 `exchange, code`）。

表结构说明见 `collect/coll2/data/README.md`。

## 常用参数

| 参数 | 说明 |
|------|------|
| `--db PATH` | 指定其它 SQLite 路径 |
| `--stock-table NAME` | 指定股票池表（需含 `exchange, code, name`，且 `exchange` 可映射到沪/深/北） |
| `--exchanges A,B` | 逗号分隔，如 `SSE,SZSE` |
| `--security-types A,B` | 逗号分隔，如 `A股` |
| `--limit N` | 只处理前 N 只股票（调试用） |
| `--sleep SEC` | 每只股票之间的休眠秒数（默认 `1`） |
| `--no-skip` | 不跳过已成功导入的股票，全量重拉（同一天数据会按主键 upsert 覆盖） |

## 示例

```bash
# 默认：qlab_coll2_stock.sqlite，跳过已 ok
python collect/coll2/main.py

# 试运行 10 只
python collect/coll2/main.py --limit 10

# 全量重拉（不跳过已成功）
python collect/coll2/main.py --no-skip

# 自定义休眠 2 秒
python collect/coll2/main.py --sleep 2

# 改用其它库或其它股票池表
python collect/coll2/main.py --db D:\path\to\other.sqlite --stock-table stock_basic_info
```

## 前置条件

- SQLite 中需存在所选 **`--stock-table`**（默认 `stock_basic_info`），且包含可用的 `exchange` / `code` / `name`。
- 单只股票请求失败时会记录 `failed` 并退出进程，下一轮可重新运行；默认仍会跳过已 `ok` 的股票（除非你加了 `--no-skip`）。
