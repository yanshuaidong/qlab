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

## 涨停跌停

导航中的“涨停跌停”页面（`/limit-analysis`）展示近一年每日收盘涨停／跌停数量：红柱从零轴向上、绿柱从零轴向下，同一日期上下对齐，悬停数量始终以正数显示。

- 默认以库内最新日线日期为截止日，范围为包含截止日在内的 365 个自然日；横轴只展示有行情的日期，不将缺失行情补成 0。支持调整截止日期、刷新、回到最新一年和日期缩放。
- 当前库没有官方涨跌停价／标记，因此页面明确标注为**收盘估算**，并非官方全市场统计。按主板 10%、主板 ST 5%、创业板／科创板 20%、北交所 30% 计算限制价并四舍五入至分；创业板 2020-08-24 前按原主板规则处理。
- 使用 `daily` 未复权收盘价与前收盘价，ST 状态仅取同一交易日的 `moneyflow_dc`／`moneyflow_ths` 名称。主板缺少当日名称、停牌、无效价格和不支持的代码不计入，摘要显示参与估算的股票数。全天没有可估算记录时保留缺口，不显示为零涨跌停。
- 新股无涨跌幅限制期、退市整理等特殊规则无法准确识别；盘中触及但收盘未封板不计入。数据不完整时结果可能低于实际市场数量。
- 只读 API：`GET /api/limit-analysis?endDate=YYYY-MM-DD`，返回起止日期、最新行情日期、`estimated: true` 及按日期升序排列的 `rows`；每项包含 `date`、`up`、`down`、`totalStocks` 和 `eligibleStocks`。
- 同一页下方的「主力风向表」先按当日 `daily_basic.total_mv` 保留总市值大于等于门槛的股票（默认 400 亿），再统计其中至少命中一个已开启净流入条件的股票只数。同一只股票当天只计 1 只。三个条件默认开启：东财超大单净流入占比、同花顺大单净流入占比、L2 主动超大单净流入占比，门槛默认都是 20%。关闭的条件不参与；占比为空或低于门槛不算命中。横轴与上方图表同一段近一年，只展示有行情的日期。
- 只读 API：`GET /api/limit-analysis/main-force?endDate=YYYY-MM-DD&minMvYi=400&dc=1&dcRate=20&ths=1&thsRate=20&l2=1&l2Rate=20`。`minMvYi` 缺省 400，三个开关缺省为开且只接受 `0`/`1`，三个占比缺省 20。返回按日期升序的 `rows`，每项为 `date` 和 `count`。

## 信号分析

导航中的“信号分析”页面（`/signal-analysis`）展示所有股票每日信号发生次数柱状图。

- 按 `trend_mark.trade_date` 汇总，每条标记计 1 次；全部信号 = 好信号（`correct`）+ 差信号（`fail`），不依赖原因或标签是否完整。
- 默认以最新信号日期为截止日；没有信号时使用当天。可以更改截止日期，始终展示包含截止日在内的连续 365 个自然日，周末、节假日和无信号日期补 0。
- 支持全部信号、仅好信号、仅差信号切换，鼠标悬停查看日期和次数，底部滑块缩放日期范围；点击刷新可读取最新标记。
- 点击柱子后，下方按股票展示当日信号明细，并遵循当前好／差信号筛选；每页 10 只，K 线默认展开，可逐项或整页收起／展开，支持查看原始信号原因。
- K 线复用个股日线接口，展示未复权价格，按好／差信号颜色在准确日期绘制箭头和日期文字。默认定位信号前约 20、后最多 80 个交易日，支持拖动／缩放、“定位信号”和“查看全部走势”；后续行情不受柱状图截止日期限制。缺少当天或后续行情时明确提示，不将标记移到其他日期。
- 只读 API：`GET /api/signal-analysis?endDate=YYYY-MM-DD`，返回起止日期及 365 天的每日全部／好／差信号次数。`endDate` 可省略。
- 股票明细 API：`GET /api/signal-analysis/signals?date=YYYY-MM-DD&group=total&page=1&pageSize=10`。`date` 必填，`group` 支持 `total/correct/fail`，`pageSize` 最大 50；返回股票名称、代码、信号日期、类型、原因和分页总数。

## 原因向量

导航中的“原因向量”页面（`/reason-vector`）提供好／差信号标签频次榜、关联信号原文及标签语义搜索。

- 统计和明细只读 `trend_mark`、`trend_mark_tagging`，不修改 reason、标签或人工标记；无需 Python 向量依赖即可使用。
- 仅纳入代码、交易日、reason 快照一致且标签 JSON／原文依据校验通过的记录。同一信号内的同名标签去重，组内出现率以全部有效标签信号为分母。
- 语义搜索使用本地 BGE-M3 模型和 Qdrant 持久化索引。首次使用前配置模型并点击“刷新标签索引”；模型、依赖及环境变量说明见 [`research/stock/reason_vector/README.md`](../research/stock/reason_vector/README.md)。服务不会自动联网下载模型。
- 索引刷新在独立 Python 进程中进行，页面显示进度状态和错误；标签变更后需要手动刷新索引，人工好坏标记变化无需重新嵌入。
- API：`GET /api/reason-vector/overview`、`GET /ranking`、`GET /signals`、`POST /search`、`POST /refresh`（后四项同属 `/api/reason-vector` 前缀）。刷新请求返回 202，随后查询 overview 获取结果。

基础验证（在 `display/` 目录）：`npm test`、`npm run build`。测试使用内存数据库和模拟向量引擎，不写入现有股票库，不需要下载模型。
