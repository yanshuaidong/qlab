# display 股票数据展示

Express + Vue3，展示 `storage/stock/data.sqlite`。K 线正确点 / 失败点标记写入同库 `trend_mark` 表，可附原因。后端使用 Node 内置 `node:sqlite`，需要 Node 22+（推荐 24）。

## 启动

在 `display/` 目录：

```bash
npm install
npm run dev
```

- 前端：http://127.0.0.1:5173 （Vite，`/api` 代理到后端）
- 后端：http://127.0.0.1:3001

生产模式：

```bash
npm run build
npm start
```

然后打开 http://127.0.0.1:3001 。

## 数据库

默认读取仓库根目录 `storage/stock/data.sqlite`。可用环境变量覆盖：

```bash
set STOCK_DB_PATH=D:\ysd\qlab\storage\stock\data.sqlite
npm run dev
```

相对路径相对仓库根解析。
