# stock_capital_flow 本地查看（FastAPI + 单页 HTML）

开发自用：读取仓库内 `storage/stock/stock_capital_flow/stock.sqlite`，在浏览器里按证券查看日 K（蜡烛图 + 成交量），避免在数据库面板里逐行翻数据。

## 结构

| 文件 | 说明 |
|------|------|
| `app.py` | FastAPI：首页 + `/api/stocks` 证券列表 + `/api/kline` 日线 |
| `static/index.html` | 单页前端：筛选、下拉选证券、Lightweight Charts 画 K 线 |
| `requirements.txt` | `fastapi`、`uvicorn` |

## 安装与启动

在任意目录先安装依赖（建议虚拟环境）：

```bash
pip install -r D:\ysd\qlab\display\stock_capital_flow\requirements.txt
```

**方式 A（推荐）**：在仓库根目录 `D:\ysd\qlab` 下执行，这样模块名与文档一致：

```bash
cd /d D:\ysd\qlab
python -m uvicorn display.stock_capital_flow.app:app --reload --host 127.0.0.1 --port 8000
```

**方式 B**：在本目录下直接写 `app:app`：

```bash
cd /d D:\ysd\qlab\display\stock_capital_flow
python -m uvicorn app:app --reload --host 127.0.0.1 --port 8000
```

浏览器打开：<http://127.0.0.1:8000/>

- 顶部「筛选」可输入代码或名称，缩小下拉列表；不输入时默认加载前 400 条基础信息（可通过改 URL 参数调大，见 `app.py`）。
- 选好证券后点「加载 K 线」。当前库 `adjust` 多为空字符串，接口已按 `adjust=''` 查询。

## API 说明（可选）

- `GET /api/stocks?q=…&limit=…`：证券列表（来自 `stock_basic_info`）。
- `GET /api/kline?exchange=…&stock_code=…&adjust=`：日 K 序列（来自 `stock_daily`），按 `trade_date` 升序。

## 说明

- 需本机已存在 `stock.sqlite`；若路径不同，可改 `app.py` 中 `DB_PATH`（相对仓库根 `D:\ysd\qlab`）。
- 图表库通过 CDN 加载，首次打开需能访问公网；若需纯离线，可再改 `index.html` 为本地静态资源。
