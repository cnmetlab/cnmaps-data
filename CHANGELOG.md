# 更新日志

`cnmaps-data` 的重要变更会记录在这里。

## 1.1.0

- 新增 `cn-neighbors` 数据集，提供基于中国边界口径整理的邻国国家级边界。
- 新增 `world-countries` 数据集，补充全球其他国家与重要海外领地的国家级边界。
- 统一补充国家中文名，并提供国家名称与 `ISO3` 的对照文档。
- 增加国家名称同步脚本与数据校验能力，便于后续维护 SQLite 与 GeoJSON 记录。
- 增加 README 视觉资源与更完整的开发者文档。

## 1.0.0

- 首次发布 `cnmaps-data` 独立数据包。
- 提供 `cnmaps.data_providers` provider 接口与官方数据 provider。
- 内置中国行政区边界索引、GeoJSON 数据与示例样例数据。
- 提供基础 checker、CI 和 PyPI 发布工作流。
