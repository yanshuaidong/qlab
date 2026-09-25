# 本地原因标签向量 worker

本目录是独立 Python 持久进程，只接收归一化后的标签名，不读取 SQLite，不负责标记统计。使用 `sentence-transformers` 本地加载 `BAAI/bge-m3` 的 1024 维稠密向量，默认 CPU；Qdrant 使用本地持久化模式，无需启动服务器。

## 部署配置

建议独立 Python 3.11/3.12 虚拟环境，具体平台需有兼容的 PyTorch wheel。以下仅为部署命令，本次实现未安装依赖或下载模型。

在仓库根目录单次使用清华镜像安装运行依赖，不修改全局 pip 配置：

```powershell
python -m pip install -r research/stock/reason_vector/requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
```

部署需要设置：

- `REASON_VECTOR_PYTHON`：Node 启动 worker 使用的 Python 可执行文件路径，可选，默认 `python`。可指定独立虚拟环境的解释器，例如 `D:\venvs\reason-vector\Scripts\python.exe`；运行依赖应安装到该解释器对应的环境中。修改此项或以下环境变量后，需重启 Node 服务，使其使用新配置重新启动 worker。

- `REASON_VECTOR_MODEL_PATH`：已完整下载的本地模型快照目录，必填。内部转换为绝对路径写入 manifest。
- `REASON_VECTOR_MODEL_VERSION`：该快照对应的已核实固定 commit 标识，必填。不要填 `master`、`main`、`latest` 或自行猜测的版本。worker 不联网验证版本的真实性，部署人员负责保证该标识与快照内容一致；不要在同一路径和版本标识下覆盖权重。
- `REASON_VECTOR_INDEX_PATH`：持久化根目录，可选；默认是仓库根目录下 `storage/stock/reason_vectors`，与工作目录无关。该目录下有 `manifest.json` 和 `qdrant/`。

### 从 ModelScope 准备固定快照

2026-09-25 已通过 [ModelScope 模型元数据 API](https://modelscope.cn/api/v1/models/BAAI/bge-m3) 核实仓库 `BAAI/bge-m3` 存在，模型卡说明稠密向量为 1024 维并支持 sentence-transformers。模型页面为 <https://modelscope.cn/models/BAAI/bge-m3>。元数据默认分支显示为 `master`，它不是固定版本；本说明不提供未经核实的 commit。

1. 在 ModelScope 模型仓库的文件/版本历史中核实并记录固定 commit，确认快照确属目标模型。若网页只显示可变分支，先取得实际 commit，再继续。
2. 在允许联网的部署准备环境安装下载工具（非 worker 运行依赖）：`python -m pip install modelscope -i https://pypi.tuna.tsinghua.edu.cn/simple`。
3. 使用已核实 commit 下载完整快照。以下两个环境变量必须由部署人员填入真实值；不会回退到默认分支：

```powershell
$env:REASON_VECTOR_MODEL_VERSION = '<已核实的固定commit>'
$env:REASON_VECTOR_MODEL_PATH = 'D:\models\bge-m3-fixed-snapshot'
python -c "import os; from modelscope import snapshot_download; snapshot_download('BAAI/bge-m3', revision=os.environ['REASON_VECTOR_MODEL_VERSION'], local_dir=os.environ['REASON_VECTOR_MODEL_PATH'])"
```

4. 核实下载结果和版本，保留完整配置、分词器、权重及 sentence-transformers 模块文件。准备完毕后可断网运行。版本占位符不是有效版本，不可原样执行。

worker 仅加载本地目录，使用 `local_files_only=True`、`trust_remote_code=False`，并在加载前设置 `HF_HUB_OFFLINE=1`、`TRANSFORMERS_OFFLINE=1`。缺少路径、版本、依赖或本地模型文件时会返回中文错误，不自动下载安装。空标签初始化仍要求明确的模型路径及版本，并需要 Qdrant；无需导入或运行模型。

## Node 进程与 JSONL 协议

Node 使用 `spawn(pythonExecutable, ['-u', absoluteWorkerPath], {env: ...})` 启动一个长期存活的进程。 stdin/stdout 使用 UTF-8，每行一个完整 JSON 对象；逐行缓冲解析，不应假设一次 stdout data 事件对应一个响应。请求串行执行；同一个持久化目录只能由一个 worker 持有。日志写 stderr，stdout 只写响应。关闭 stdin 后释放存储并退出。

刷新请求：`{"id":"r1","action":"refresh","labels":["AI","芯片"]}`。

刷新成功：`{"id":"r1","result":{"indexedCount":2,"updatedAt":"2026-09-25T09:00:00+00:00"}}`。时间为示例；实际为 UTC ISO 8601。标签不变且模型身份一致时不创建新集合，时间保持上次成功刷新值。

搜索请求：`{"id":"s1","action":"search","text":"人工智能芯片","limit":10,"minScore":null,"labels":["AI","芯片"]}`。

搜索成功：`{"id":"s1","result":{"items":[{"label":"芯片","score":0.8}]}}`。示例分数不代表实际模型结果。

失败：`{"id":"s1","error":"向量索引尚未初始化，请先执行 refresh"}`。无效 JSON 的 id 为 null；失败后进程仍可接收下一行。建议 id 使用字符串或整数。

- `labels` 必须为字符串数组；worker 额外去首尾空白、去重、忽略空字符串、排序，不替调用方做同义词或大小写归一化。
- refresh 的 `labels` 是完整有效标签集合，不是增量补丁；未列出的标签从新索引删除。
- search 的 `labels` 是搜索时当前有效标签，用来立即过滤已失效标签；新标签需 refresh 后才能检索到。
- `text` 必须为非空字符串；`limit` 为正整数；`minScore` 为 null 或 [-1, 1] 有限数字（省略时等同 null）。
- 按余弦相似度降序，同分按标签名升序；先过滤当前有效标签及阈值，再截取前 limit 条。实现查询整个已索引集合后过滤，避免先取前 k 条导致有效结果不足；适合标签级规模，集合很大时应优化为存储端过滤。
- 查询与标签使用相同模型，不附加 BGE-M3 不要求的检索指令；每个标签的点 ID 是固定命名空间内的 UUIDv5。
- 不提供 status action。Node 直接读取 manifest 获取当前状态；文件不存在表示尚未初始化。

## manifest 与失败安全

`manifest.json` 严格输出以下字段：

```json
{
  "schemaVersion": 1,
  "modelId": "BAAI/bge-m3",
  "modelVersion": "实际固定commit",
  "modelPath": "模型绝对路径",
  "dimensions": 1024,
  "collection": "reason_vectors_本次集合UUID",
  "labels": ["AI", "芯片"],
  "updatedAt": "UTC ISO 8601时间"
}
```

模型 ID、版本、绝对路径、维度、协议任一变化时，搜索要求先 refresh；refresh 会全量重建，不复用其他模型的向量。改变环境变量后需重启 worker。

标签改变时，刷新创建新的 Qdrant collection，仅从当前兼容 collection 复用保留标签的向量，仅为新增/缺失标签嵌入，持久写入完成后通过同目录临时文件、flush/fsync、`os.replace` 原子发布 manifest。发布成功后再清理旧集合。写入、推理、发布失败均保留旧 manifest 及其集合；首次刷新失败仍未初始化。旧集合清理失败只记 stderr，不撤销成功发布的新索引。

仅标记次数/统计变化而标签集合不变时完全复用索引。空集合可以正常发布，检索返回空数组。进程被强制终止可能留下未引用集合，可在停止 worker 后备份并人工维护；它们不会被 manifest 引用或用于搜索。本实现没有多进程并发写入支持；也不承诺任意断电/磁盘损坏场景的恢复。禁止 Node 同时以另一个 Qdrant 客户端打开目录。

## 测试

在仓库根目录运行，无需第三方依赖或模型：

```powershell
python -B -m unittest discover -s research/stock/reason_vector -p test_worker.py -v
```

测试通过注入 fake 模型及存储，覆盖去重、UUID、标签不变复用、增删标签、过滤后 top k、排序阈值、余弦分数、版本/路径/维度变化、空索引、参数错误、推理/存储/原子发布失败恢复、清理失败以及多请求 JSONL，也验证离线加载参数、缺依赖错误、manifest 字段和 stdout 隔离。2026-09-25 本地执行结果：22 项测试全部通过（0.154 秒）。真实模型与真实 Qdrant 的集成验证需在部署环境准备完成后另行执行。



$env:REASON_VECTOR_MODEL_PATH = 'D:\ysd\qlab\storage\models\bge-m3'
$env:REASON_VECTOR_MODEL_VERSION = ((git ls-remote https://www.modelscope.cn/BAAI/bge-m3.git HEAD) -split '\s+')[0]

cd D:\ysd\qlab\display
npm run dev