"""Generate CN-official derived neighboring country boundaries."""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from pathlib import Path

import geopandas as gpd
from shapely import snap
from shapely.geometry import mapping, shape


NEIGHBOR_COUNTRIES = {
    "AFG": "阿富汗",
    "BTN": "不丹",
    "IND": "印度",
    "KAZ": "哈萨克斯坦",
    "KGZ": "吉尔吉斯斯坦",
    "LAO": "老挝",
    "MNG": "蒙古国",
    "MMR": "缅甸",
    "NPL": "尼泊尔",
    "PAK": "巴基斯坦",
    "PRK": "朝鲜",
    "RUS": "俄罗斯",
    "TJK": "塔吉克斯坦",
    "VNM": "越南",
}

MANUAL_DISPUTED_ASSIGNMENTS = {
    "Jammu-Kashmir": "PAK",
    "Aksai Chin": "IND",
    "Arunachal Pradesh": "IND",
}

SOURCE_NAME = "CN_NEIGHBORS"
KIND_NAME = "陆地"
LEVEL_NAME = "国"
SNAP_TOLERANCE = 1e-8


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate cn-neighbors dataset")
    parser.add_argument(
        "--package-root",
        default=str(Path(__file__).resolve().parents[1] / "cnmaps_data"),
        help="Path to the cnmaps_data package root",
    )
    parser.add_argument(
        "--world-shp",
        required=True,
        help="Path to the world administrative boundaries shapefile",
    )
    return parser


def _load_china_geometry(package_root: Path):
    china_path = package_root / "data" / "datasets" / "administrative" / "amap" / "land" / "100000.geojson"
    with china_path.open(encoding="utf-8") as f:
        return shape(json.load(f))


def _ensure_output_dir(package_root: Path) -> Path:
    out_dir = package_root / "data" / "datasets" / "administrative" / "cn-neighbors" / "land"
    out_dir.mkdir(parents=True, exist_ok=True)
    return out_dir


def _load_world(world_shp: Path) -> gpd.GeoDataFrame:
    gdf = gpd.read_file(world_shp)
    return gdf[["iso3", "name", "status", "geometry"]].copy()


def _build_adjusted_member_geometries(gdf: gpd.GeoDataFrame, china_geom):
    members = gdf[gdf["status"] == "Member State"][["iso3", "name", "geometry"]].copy()
    members = members[members["iso3"].notna()].copy()
    members = members[members["iso3"] != "CHN"].copy()

    adjusted = {
        row.iso3: snap(row.geometry, china_geom, SNAP_TOLERANCE).difference(china_geom)
        for row in members.itertuples()
    }
    english_names = {row.iso3: row.name for row in members.itertuples()}

    for disputed_name, target_iso3 in MANUAL_DISPUTED_ASSIGNMENTS.items():
        disputed = gdf[gdf["name"] == disputed_name]
        if disputed.empty:
            continue
        residual = snap(disputed.geometry.iloc[0], china_geom, SNAP_TOLERANCE).difference(china_geom)
        if residual.is_empty:
            continue
        adjusted[target_iso3] = adjusted[target_iso3].union(residual)

    return adjusted, english_names


def _write_geojson_files(output_dir: Path, adjusted: dict, english_names: dict) -> list[tuple[str, str]]:
    records = []
    for iso3, country_cn in sorted(NEIGHBOR_COUNTRIES.items()):
        geom = adjusted[iso3]
        if geom.is_empty:
            continue

        out_fp = output_dir / f"{iso3}.geojson"
        payload = {
            "type": "Feature",
            "properties": {
                "iso3": iso3,
                "name": country_cn,
                "name_en": english_names[iso3],
                "source": SOURCE_NAME,
                "kind": KIND_NAME,
                "level": LEVEL_NAME,
            },
            "geometry": mapping(geom),
        }
        with out_fp.open("w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, separators=(",", ":"))

        relative_path = f"administrative/cn-neighbors/land/{iso3}.geojson"
        records.append((iso3, country_cn, relative_path))

    return records


def _build_row_id(country_name: str, path: str) -> str:
    key = f"{country_name}|{LEVEL_NAME}|{SOURCE_NAME}|{KIND_NAME}|{path}"
    return hashlib.md5(key.encode("utf-8")).hexdigest()


def _update_index_db(package_root: Path, records: list[tuple[str, str, str]]) -> None:
    db_path = package_root / "data" / "index" / "administrative.db"
    con = sqlite3.connect(db_path)
    try:
        cur = con.cursor()
        cur.execute("DELETE FROM ADMINISTRATIVE WHERE source = ?", (SOURCE_NAME,))
        cur.executemany(
            """
            INSERT INTO ADMINISTRATIVE
            (id, country, province, city, district, path, level, source, kind)
            VALUES (?, ?, NULL, NULL, NULL, ?, ?, ?, ?)
            """,
            [
                (_build_row_id(country_name, path), country_name, path, LEVEL_NAME, SOURCE_NAME, KIND_NAME)
                for _, country_name, path in records
            ],
        )
        con.commit()
    finally:
        con.close()


def main() -> int:
    parser = build_arg_parser()
    args = parser.parse_args()

    package_root = Path(args.package_root).expanduser().resolve()
    world_shp = Path(args.world_shp).expanduser().resolve()

    china_geom = _load_china_geometry(package_root)
    world_gdf = _load_world(world_shp)
    adjusted, english_names = _build_adjusted_member_geometries(world_gdf, china_geom)
    output_dir = _ensure_output_dir(package_root)
    records = _write_geojson_files(output_dir, adjusted, english_names)
    _update_index_db(package_root, records)

    print(f"Generated {len(records)} cn-neighbors records into {output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
