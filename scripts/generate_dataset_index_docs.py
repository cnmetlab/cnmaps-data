"""根据 administrative.db 生成数据集覆盖范围文档（中国省 / 市 / 县与国外名称列表）。"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from datetime import datetime, timezone


def _escape_md_cell(value: str | None) -> str:
    if value is None:
        return ""
    text = str(value).replace("|", "\\|")
    return text.replace("\n", " ")


def _repo_root() -> str:
    script_dir = os.path.dirname(os.path.abspath(__file__))
    return os.path.dirname(script_dir)


def _default_db_path() -> str:
    return os.path.join(_repo_root(), "cnmaps_data", "data", "index", "administrative.db")


def _write_china_markdown(cur: sqlite3.Cursor, out_path: str) -> None:
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    provinces = [
        row[0]
        for row in cur.execute(
            "SELECT province FROM ADMINISTRATIVE WHERE source = '高德' AND level = '省' ORDER BY path"
        )
    ]
    city_rows = list(
        cur.execute(
            "SELECT a.province, a.city FROM ADMINISTRATIVE AS a "
            "JOIN ADMINISTRATIVE AS p ON p.province = a.province AND p.source = '高德' AND p.level = '省' "
            "WHERE a.source = '高德' AND a.level = '市' "
            "ORDER BY p.path, a.city"
        )
    )
    district_rows = list(
        cur.execute(
            "SELECT d.province, d.city, d.district FROM ADMINISTRATIVE AS d "
            "JOIN ADMINISTRATIVE AS p ON p.province = d.province AND p.source = '高德' AND p.level = '省' "
            "JOIN ADMINISTRATIVE AS c ON c.province = d.province AND c.city = d.city "
            "AND c.source = '高德' AND c.level = '市' "
            "WHERE d.source = '高德' AND d.level = '区县' "
            "ORDER BY p.path, c.path, d.district"
        )
    )

    districts_by_province: dict[str, dict[str, list[str]]] = {}
    for prov, city, dist in district_rows:
        if prov not in districts_by_province:
            districts_by_province[prov] = {}
        if city not in districts_by_province[prov]:
            districts_by_province[prov][city] = []
        districts_by_province[prov][city].append(dist)

    lines: list[str] = [
        "<!-- 本文件由 scripts/generate_dataset_index_docs.py 根据 administrative.db 自动生成，请勿手改 -->",
        "",
        "# 数据集索引：中国行政区",
        "",
        "## 数据来源",
        "",
        "中国行政区原始数据来自 **高德（Amap）**。",
        "独立对照与学术引用可使用 [GaryBikini/ChinaAdminDivisonSHP](https://github.com/GaryBikini/ChinaAdminDivisonSHP) "
        "**v2.0**（2021），Zenodo DOI [10.5281/zenodo.4167299](https://doi.org/10.5281/zenodo.4167299)。",
        "",
        "## 索引说明",
        "",
        "以下为当前官方数据包中 **`source = 高德`**（目录 `amap`）在 `ADMINISTRATIVE` 表中的省 / 市 / 区县记录。",
        "全国级边界（`level = 国`）与海域几何未列入下表。",
        "",
        f"**生成时间**：{generated_at}",
        "",
        "## 统计",
        "",
        f"- 省级行政区：**{len(provinces)}**",
        f"- 地级行政区：**{len(city_rows)}**",
        f"- 区县级行政区：**{len(district_rows)}**",
        "",
        "## 省级行政区",
        "",
    ]

    for name in provinces:
        lines.append(f"- {name}")

    lines.extend(
        [
            "",
            "## 地级行政区",
            "",
            "| 省级行政区 | 地级行政区 |",
            "| --- | --- |",
        ]
    )
    for prov, city in city_rows:
        lines.append(f"| {_escape_md_cell(prov)} | {_escape_md_cell(city)} |")

    lines.extend(
        [
            "",
            "## 区县级行政区",
            "",
            "按省级行政区折叠，便于浏览。",
            "",
        ]
    )

    for prov in provinces:
        cities_map = districts_by_province.get(prov, {})
        total_districts = sum(len(v) for v in cities_map.values())
        lines.append("<details>")
        lines.append("")
        lines.append(f"<summary><strong>{_escape_md_cell(prov)}</strong>（{total_districts} 个区县）</summary>")
        lines.append("")
        lines.append("| 地级行政区 | 区 / 县 |")
        lines.append("| --- | --- |")
        for city_name, dist_names in cities_map.items():
            for dist_name in dist_names:
                lines.append(
                    f"| {_escape_md_cell(city_name)} | {_escape_md_cell(dist_name)} |"
                )
        lines.append("")
        lines.append("</details>")
        lines.append("")

    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines).rstrip() + "\n")


def _write_international_markdown(cur: sqlite3.Cursor, out_path: str) -> None:
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    countries = [
        row[0]
        for row in cur.execute(
            "SELECT country FROM ADMINISTRATIVE "
            "WHERE source = '世界银行' "
            "AND path LIKE 'administrative/%/land/%.geojson' "
            "ORDER BY country"
        )
    ]

    lines: list[str] = [
        "<!-- 本文件由 scripts/generate_dataset_index_docs.py 根据 administrative.db 自动生成，请勿手改 -->",
        "",
        "# 数据集索引：国外国家与地区",
        "",
        "## 数据来源",
        "",
        "国界级几何当前参考 **World Bank Official Boundaries - Admin 0** 数据。",
        "包内产物可能经过裁剪、与中国边界做几何扣除、争议区分类整理及中文名映射等处理。",
        "",
        "## 索引说明",
        "",
        "以下为 **`ADMINISTRATIVE`** 表中收录的国家 / 地区级记录（`level = 国`），",
        "名称取自 **`country` 列**（中文名，与 GeoJSON `properties.name` 一致）。",
        "",
        f"**生成时间**：{generated_at}",
        "",
        "## 统计",
        "",
        f"- **合计**：{len(countries)} 个国家与地区",
        "",
        "## 名称列表",
        "",
    ]
    for name in countries:
        lines.append(f"- {_escape_md_cell(name)}")

    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines).rstrip() + "\n")


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="从 administrative.db 生成 docs 数据集索引页面")
    parser.add_argument(
        "--db",
        default=_default_db_path(),
        help="administrative.db 路径，默认指向仓库内 cnmaps_data 包索引库",
    )
    parser.add_argument(
        "--china-out",
        default=os.path.join(_repo_root(), "docs", "dataset-index-china.md"),
        help="中国行政区列表输出路径",
    )
    parser.add_argument(
        "--international-out",
        default=os.path.join(_repo_root(), "docs", "dataset-index-international.md"),
        help="国外名称列表输出路径",
    )
    return parser


def main(argv: list[str] | None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    db_path = os.path.abspath(os.path.expanduser(args.db))
    if not os.path.isfile(db_path):
        print(f"[FAIL] 未找到索引库: {db_path}", file=sys.stderr)
        return 1

    con = sqlite3.connect(db_path)
    try:
        cur = con.cursor()
        _write_china_markdown(cur, args.china_out)
        _write_international_markdown(cur, args.international_out)
    finally:
        con.close()

    print(f"[OK] 已写入: {args.china_out}")
    print(f"[OK] 已写入: {args.international_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
