# storage

`storage/` 主要负责存放项目中采集、整理、研究会用到的数据文件。

数据目录按「数据大类 / 数据集或主题 / 具体数据文件」组织。也就是说，先区分资产或业务大类，再区分同一大类下的具体数据集，最后落到实际的数据文件。

## 目录结构

```text
storage/
  futures/                         # 期货数据大类
    futures_main_retail/            # 期货主力与散户相关数据
      data.sqlite        # 具体数据文件
      varieties.json                # 品种配置或辅助数据
      README.md                     # 该数据集的字段、表结构、使用说明
```

## 命名约定

- 第一层目录表示数据大类，例如 `futures` 表示期货数据。
- 第二层目录表示具体数据集或数据主题，例如 `futures_main_retail` 表示期货主力和散户数据。
- 第三层存放实际数据文件、配置文件和该数据集自己的说明文档。

## 示例

`storage/futures/futures_main_retail/data.sqlite` 表示：

- `futures`：期货大类数据。
- `futures_main_retail`：期货主力与散户数据集。
- `data.sqlite`：该数据集下的本地 SQLite 数据文件。

## 维护原则

- 新增数据时，优先按已有层级放入对应大类目录。
- 如果是一个新的数据主题，在对应大类下新增一个独立目录。
- 每个数据集目录建议保留自己的 `README.md`，说明数据来源、字段含义、更新时间、表结构或文件格式。
- 大型本地数据文件一般不直接提交到 Git，是否忽略以 `.gitignore` 为准。
