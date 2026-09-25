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

## 原因向量

导航中的“原因向量”页面（`/reason-vector`）提供好／差信号标签频次榜、关联信号原文及标签语义搜索。

- 统计和明细只读 `trend_mark`、`trend_mark_tagging`，不修改 reason、标签或人工标记；无需 Python 向量依赖即可使用。
- 仅纳入代码、交易日、reason 快照一致且标签 JSON／原文依据校验通过的记录。同一信号内的同名标签去重，组内出现率以全部有效标签信号为分母。
- 语义搜索使用本地 BGE-M3 模型和 Qdrant 持久化索引。首次使用前配置模型并点击“刷新标签索引”；模型、依赖及环境变量说明见 [`research/stock/reason_vector/README.md`](../research/stock/reason_vector/README.md)。服务不会自动联网下载模型。
- 索引刷新在独立 Python 进程中进行，页面显示进度状态和错误；标签变更后需要手动刷新索引，人工好坏标记变化无需重新嵌入。
- API：`GET /api/reason-vector/overview`、`GET /ranking`、`GET /signals`、`POST /search`、`POST /refresh`（后四项同属 `/api/reason-vector` 前缀）。刷新请求返回 202，随后查询 overview 获取结果。

基础验证（在 `display/` 目录）：`npm test`、`npm run build`。测试使用内存数据库和模拟向量引擎，不写入现有股票库，不需要下载模型。
