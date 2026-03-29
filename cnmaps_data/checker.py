"""Validation helpers for cnmaps-compatible data packages."""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path


REQUIRED_MANIFEST_FIELDS = {
    "name",
    "provider",
    "version",
    "cnmaps_data_api_version",
    "datasets",
}

REQUIRED_DATASETS = {
    "administrative": {"kind", "root", "index_db"},
    "geography": {"kind", "root"},
    "sample": {"kind", "root"},
}

ADMIN_COLUMNS = (
    "id",
    "country",
    "province",
    "city",
    "district",
    "path",
    "level",
    "source",
    "kind",
)

SUPPORTED_GEOMETRY_TYPES = {"Polygon", "MultiPolygon", "MultiLineString"}


def _load_manifest(package_root: Path) -> dict:
    manifest_path = package_root / "manifest.json"
    if not manifest_path.exists():
        raise ValueError(f"未找到 manifest.json: {manifest_path}")

    with manifest_path.open(encoding="utf-8") as f:
        manifest = json.load(f)

    missing = REQUIRED_MANIFEST_FIELDS - set(manifest)
    if missing:
        raise ValueError(f"manifest.json 缺少顶层字段: {sorted(missing)}")

    for dataset_name, required_fields in REQUIRED_DATASETS.items():
        if dataset_name not in manifest["datasets"]:
            raise ValueError(f"manifest.json 缺少 datasets.{dataset_name}")
        dataset_meta = manifest["datasets"][dataset_name]
        missing_fields = required_fields - set(dataset_meta)
        if missing_fields:
            raise ValueError(
                f"manifest.json 中 datasets.{dataset_name} 缺少字段: {sorted(missing_fields)}"
            )

    return manifest


def _resolve_package_root(path: Path) -> Path:
    path = path.expanduser().resolve()
    if (path / "manifest.json").exists():
        return path

    nested = path / "cnmaps_data"
    if (nested / "manifest.json").exists():
        return nested

    raise ValueError(f"无法在 {path} 下找到 manifest.json")


def _dataset_root(package_root: Path, manifest: dict, dataset_name: str) -> Path:
    return (package_root / manifest["datasets"][dataset_name]["root"]).resolve()


def _index_db_path(package_root: Path, manifest: dict, dataset_name: str) -> Path:
    return (package_root / manifest["datasets"][dataset_name]["index_db"]).resolve()


def _check_geojson_file(path: Path) -> None:
    if not path.exists():
        raise ValueError(f"GeoJSON 文件不存在: {path}")

    with path.open(encoding="utf-8") as f:
        payload = json.load(f)

    geometry = payload.get("geometry", payload)
    if "type" not in geometry:
        raise ValueError(f"GeoJSON 缺少 type 字段: {path}")

    geometry_type = geometry["type"]
    if geometry_type not in SUPPORTED_GEOMETRY_TYPES:
        raise ValueError(f"GeoJSON geometry type 不受支持: {path} -> {geometry_type}")

    if "coordinates" not in geometry:
        raise ValueError(f"GeoJSON 缺少 coordinates 字段: {path}")


def _resolve_relative_geojson_path(administrative_root: Path, relative_path: str) -> Path:
    relative = Path(relative_path)
    if relative.parts and relative.parts[0] == "administrative":
        relative = Path(*relative.parts[1:])
    return (administrative_root / relative).resolve()


def _check_administrative_index(package_root: Path, manifest: dict, sample_limit: int | None = None) -> int:
    index_db = _index_db_path(package_root, manifest, "administrative")
    if not index_db.exists():
        raise ValueError(f"行政区索引库不存在: {index_db}")

    administrative_root = _dataset_root(package_root, manifest, "administrative")
    if not administrative_root.exists():
        raise ValueError(f"行政区数据目录不存在: {administrative_root}")

    con = sqlite3.connect(index_db)
    try:
        cur = con.cursor()

        tables = {row[0] for row in cur.execute("SELECT name FROM sqlite_master WHERE type='table';")}
        if "ADMINISTRATIVE" not in tables:
            raise ValueError("索引库缺少 ADMINISTRATIVE 表")

        pragma_rows = list(cur.execute("PRAGMA table_info(ADMINISTRATIVE);"))
        columns = tuple(row[1] for row in pragma_rows)
        if columns != ADMIN_COLUMNS:
            raise ValueError(f"ADMINISTRATIVE 表字段不符合要求: {columns}")

        rows = list(cur.execute("SELECT id, path FROM ADMINISTRATIVE;"))
    finally:
        con.close()

    if not rows:
        raise ValueError("ADMINISTRATIVE 表为空")

    seen_ids = set()
    for idx, (row_id, relative_path) in enumerate(rows):
        if row_id in seen_ids:
            raise ValueError(f"ADMINISTRATIVE 表存在重复 id: {row_id}")
        seen_ids.add(row_id)

        if not relative_path:
            raise ValueError(f"ADMINISTRATIVE 表存在空 path: id={row_id}")

        geojson_path = _resolve_relative_geojson_path(administrative_root, relative_path)
        _check_geojson_file(geojson_path)

        if sample_limit is not None and idx + 1 >= sample_limit:
            break

    return len(rows)


def _check_directory_exists(path: Path, label: str) -> None:
    if not path.exists():
        raise ValueError(f"{label} 不存在: {path}")
    if not path.is_dir():
        raise ValueError(f"{label} 不是目录: {path}")


def validate_package(package_root: Path, sample_limit: int | None = None) -> list[str]:
    package_root = _resolve_package_root(package_root)
    manifest = _load_manifest(package_root)

    messages = []
    messages.append(f"provider={manifest['provider']}")
    messages.append(f"name={manifest['name']}")
    messages.append(f"version={manifest['version']}")
    messages.append(f"api_version={manifest['cnmaps_data_api_version']}")

    administrative_root = _dataset_root(package_root, manifest, "administrative")
    geography_root = _dataset_root(package_root, manifest, "geography")
    sample_root = _dataset_root(package_root, manifest, "sample")

    _check_directory_exists(administrative_root, "administrative 数据目录")
    _check_directory_exists(geography_root, "geography 数据目录")
    _check_directory_exists(sample_root, "sample 数据目录")

    row_count = _check_administrative_index(package_root, manifest, sample_limit=sample_limit)
    messages.append(f"administrative_rows={row_count}")

    geography_files = sorted(geography_root.glob("*.geojson"))
    if not geography_files:
        raise ValueError("geography 数据目录下未找到任何 .geojson 文件")
    for fp in geography_files:
        _check_geojson_file(fp)
    messages.append(f"geography_files={len(geography_files)}")

    sample_files = sorted(sample_root.glob("*"))
    if not sample_files:
        raise ValueError("sample 数据目录为空")
    messages.append(f"sample_files={len(sample_files)}")

    return messages


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="检查 cnmaps 兼容数据包的结构和索引")
    parser.add_argument(
        "path",
        nargs="?",
        default=str(Path(__file__).resolve().parent),
        help="要检查的包根目录，默认检查当前已安装/源码目录下的 cnmaps_data",
    )
    parser.add_argument(
        "--sample-limit",
        type=int,
        default=None,
        help="只检查前 N 条 ADMINISTRATIVE 记录，默认检查全部",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    try:
        messages = validate_package(Path(args.path), sample_limit=args.sample_limit)
    except Exception as exc:
        print(f"[FAIL] {exc}", file=sys.stderr)
        return 1

    print("[OK] cnmaps data package validation passed")
    for message in messages:
        print(f" - {message}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
