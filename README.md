# qlab
a project


qlab/
  collect/
    experimental/      # 采集实验，验证接口、字段、频率、稳定性
    production/        # 稳定后的工程化采集脚本
    tests/             # 针对采集逻辑的测试
    fixtures/          # 采集测试样本、响应样例、临时验证数据
    docs/              # 采集说明、字段核对、踩坑记录

  storage/
    raw/               # 原始落地数据，尽量少改
    processed/         # 清洗/标准化后数据
    db/                # 本地数据库文件
    schema/            # 表结构、字段说明、约束说明
    registry/          # 数据集清单、版本说明、来源说明

  research/
    <topic-a>/         # 一个研究主题一个目录，内部自治
      data_note.md     # 使用的是哪份数据
      method.md        # 研究方法
      experiments/     # 研究过程脚本
      outputs/         # 图表、结果表
      report.md        # 结论与总结

    <topic-b>/
      ...
