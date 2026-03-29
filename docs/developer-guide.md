# cnmaps-data 开发者手册

本文档面向希望开发 `cnmaps` 兼容数据包的开发者。

目标是把“`cnmaps` 可消费的数据包”需要满足的协议、目录约定和校验规则写清楚，避免第三方开发者只能读源码猜实现。

如果你只是想了解官方数据包本身的用途、安装方式和发布方式，请先看：

- [README](../README.md)

## 设计原则

一个 `cnmaps` 兼容数据包建议具备以下特征：

- 是一个独立的 Python 包
- 安装后能被 `cnmaps` 自动发现
- 明确声明自己提供哪些数据集
- 提供稳定的索引方式和数据目录组织
- 能通过自动检查脚本验证基本正确性

## 推荐目录结构

推荐采用如下结构：

```text
your-data-package/
├── pyproject.toml
├── README.md
├── cnmaps_data_xxx/
│   ├── __init__.py
│   ├── provider.py
│   ├── manifest.json
│   └── data/
│       ├── index/
│       │   └── administrative.db
│       └── datasets/
│           ├── administrative/
│           ├── geography/
│           └── sample/
```

说明：

- 包名不要求一定叫 `cnmaps_data`
- 但建议目录中保留一个 manifest 和 provider 模块
- `cnmaps` 真正依赖的是 provider 协议，而不是某个固定包名

## provider 协议

`cnmaps` 当前期望 provider 对象至少提供这些方法：

- `get_dataset_root(dataset: str) -> str`
- `get_index_db(dataset: str = "administrative") -> str`
- `get_sample_path(filename: str) -> str`
- `resolve_dataset_path(dataset: str, relative_path: str) -> str`

推荐 provider 还提供这些属性：

- `name`
- `version`
- `manifest`

### 参考实现

一个最小 provider 可以类似这样：

```python
from pathlib import Path


class MyProvider:
    def __init__(self, package_root: Path):
        self.package_root = package_root
        self.name = "my-data-package"
        self.version = "1.0.0"

    def get_dataset_root(self, dataset: str) -> str:
        return str((self.package_root / "data" / "datasets" / dataset).resolve())

    def get_index_db(self, dataset: str = "administrative") -> str:
        return str((self.package_root / "data" / "index" / "administrative.db").resolve())

    def get_sample_path(self, filename: str) -> str:
        return str((self.package_root / "data" / "datasets" / "sample" / filename).resolve())

    def resolve_dataset_path(self, dataset: str, relative_path: str) -> str:
        relative = Path(relative_path)
        if relative.parts and relative.parts[0] == dataset:
            relative = Path(*relative.parts[1:])
        return str((Path(self.get_dataset_root(dataset)) / relative).resolve())


def get_provider():
    return MyProvider(Path(__file__).resolve().parent)
```

## entry point 规则

第三方数据包推荐通过 Python entry point 暴露 provider。

entry point group 名称固定为：

```text
cnmaps.data_providers
```

例如在 `pyproject.toml` 中：

```toml
[tool.poetry.plugins."cnmaps.data_providers"]
my_data = "my_data_package.provider:get_provider"
```

或 PEP 621 风格：

```toml
[project.entry-points."cnmaps.data_providers"]
my_data = "my_data_package.provider:get_provider"
```

`cnmaps` 会读取这个 group 下的 provider。

## manifest.json 规则

建议每个数据包都提供一个 `manifest.json`，用于声明自己的数据集和路径。

当前官方包的最小结构如下：

```json
{
  "name": "cnmaps-data",
  "provider": "official",
  "version": "1.0.0",
  "cnmaps_data_api_version": "1",
  "datasets": {
    "administrative": {
      "kind": "boundary",
      "description": "Administrative boundary datasets and indexes",
      "index_db": "data/index/administrative.db",
      "root": "data/datasets/administrative"
    },
    "geography": {
      "kind": "boundary",
      "description": "Geography boundary datasets",
      "root": "data/datasets/geography"
    },
    "sample": {
      "kind": "sample",
      "description": "Sample gridded datasets for demos and tests",
      "root": "data/datasets/sample"
    }
  }
}
```

### 必填字段

- 顶层：
  - `name`
  - `provider`
  - `version`
  - `cnmaps_data_api_version`
  - `datasets`
- `datasets.administrative`：
  - `kind`
  - `root`
  - `index_db`
- `datasets.geography`：
  - `kind`
  - `root`
- `datasets.sample`：
  - `kind`
  - `root`

## SQLite 索引规则

当前 `cnmaps` 对行政区数据索引的读取逻辑基于 SQLite，并假设至少存在一张名为 `ADMINISTRATIVE` 的表。

### 当前要求的 schema

```sql
CREATE TABLE ADMINISTRATIVE
(
  id text,
  country text,
  province text,
  city text,
  district text,
  path text,
  level text,
  source text,
  kind text
);
```

并建议：

- `id` 唯一
- 对 `id` 建唯一索引

### 字段语义

- `id`: 唯一标识
- `country`: 国家名称
- `province`: 省级名称
- `city`: 市级名称
- `district`: 区县名称
- `path`: 相对数据路径
- `level`: 行政等级，当前 `cnmaps` 识别 `国/省/市/区县`
- `source`: 数据源，如 `高德`
- `kind`: 数据类型，如 `陆地/海域` 等

### path 规则

`path` 应写成相对于数据集根目录或带数据集前缀的相对路径。

当前兼容这两类写法：

- `amap/land/110000.geojson`
- `administrative/amap/land/110000.geojson`

## GeoJSON 规则

当前 `cnmaps` 的 `read_mapjson()` 读取逻辑对 GeoJSON 有比较明确的要求。

### 允许的顶层结构

可以是：

- 直接是 `geometry` 对象
- 或者是包含 `geometry` 字段的 Feature 风格对象

### 当前支持的 geometry type

- `Polygon`
- `MultiPolygon`
- `MultiLineString`

对于行政区边界，建议使用 Polygon / MultiPolygon。

### 坐标要求

- 坐标需为标准 GeoJSON 坐标数组
- 行政区数据当前默认假设其来源可与 `cnmaps` 的坐标转换逻辑配合工作

## sample 数据规则

当前 `cnmaps` 官方样例数据使用 netCDF 文件。

如果你提供 sample 数据，建议：

- DEM 样例：`china-dem.nc`
- 气温样例：`china-temp.nc`
- 风场样例：`china-wind.nc`

当前官方 `cnmaps` 对样例文件的变量名假设为：

- `lon`
- `lat`
- `dem`
- `temp`
- `u`
- `v`

## 检查脚本

本仓库提供了一个检查脚本：

```bash
cnmaps-data-check
```

或者：

```bash
python -m cnmaps_data.checker
```

它会检查：

- manifest 是否存在且字段完整
- 数据集目录是否存在
- 行政区索引库是否存在
- `ADMINISTRATIVE` 表及列是否完整
- `path` 指向的 GeoJSON 文件是否存在
- GeoJSON 的顶层结构和 geometry type 是否符合要求

第三方开发者建议在发布前至少跑一遍。

如果命令行里暂时没有 `cnmaps-data-check`，也可以始终使用：

```bash
python -m cnmaps_data.checker /path/to/your-data-package
```

## 当前协议边界

请注意，当前这份文档描述的是 **cnmaps_data_api_version = 1** 的约定。

这意味着：

- SQLite 仍是官方推荐索引方式
- 行政区索引当前仍以 `ADMINISTRATIVE` 表为核心
- provider 协议主要围绕文件系统路径解析

未来如果 `cnmaps` 支持新的索引后端或新的几何格式，建议通过升级 `cnmaps_data_api_version` 来演进，而不是直接破坏现有字段定义。
