# 数据集覆盖范围索引

本页汇总当前官方包 **`administrative.db`** 索引中可查询到的行政区与国家名称，便于核对数据包实际收录范围。

列表由仓库内脚本读取索引库生成，与安装包内 SQLite 内容一致。

**原始数据出处**（与 [README 数据来源](../README.md#数据来源) 一致）：

- **中国**：原始数据来自 **高德（Amap）**；独立对照与引用见 [GaryBikini/ChinaAdminDivisonSHP](https://github.com/GaryBikini/ChinaAdminDivisonSHP) v2.0（2021），DOI [10.5281/zenodo.4167299](https://doi.org/10.5281/zenodo.4167299)。下列列表对应索引中 `source = 高德`（目录 `amap`）的省 / 市 / 区县，不含全国与海域单条几何。
- **国外**：世界银行（World Bank）Official Boundaries 数据集 Admin 0（来源：[World Bank Official Boundaries（World Bank Data Catalog）](https://datacatalog.worldbank.org/search/dataset/0038272/world-bank-official-boundaries)）。下列名称为国界级记录（`level = 国`）。

| 范围 | 说明 | 文档 |
| --- | --- | --- |
| 中国 | 省 / 市 / 区县名称列表（索引字段含义见上） | [dataset-index-china.md](dataset-index-china.md) |
| 国外 | 国家与地区中文名（国界级） | [dataset-index-international.md](dataset-index-international.md) |

## 重新生成列表

在仓库根目录执行：

```bash
python scripts/generate_dataset_index_docs.py
```

默认读取 `cnmaps_data/data/index/administrative.db`，并覆盖写入 `docs/dataset-index-china.md` 与 `docs/dataset-index-international.md`。

可选参数：

- `--db`：自定义索引库路径
- `--china-out` / `--international-out`：自定义输出路径

索引表结构见 [开发者手册](developer-guide.md) 中的「SQLite 索引规则」一节。
