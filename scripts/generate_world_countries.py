"""Generate non-neighbor world country boundaries for cnmaps-data."""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from pathlib import Path

import geopandas as gpd
from shapely import snap
from shapely.geometry import mapping
from shapely.geometry import shape


SOURCE_NAME = "WORLD_COUNTRIES"
LEVEL_NAME = "国"
KIND_NAME = "陆地"
SNAP_TOLERANCE = 1e-8
EXCLUDED_ISO3 = {
    "CHN",
    "HKG",
    "MAC",
    "TWN",
    "AFG",
    "BTN",
    "IND",
    "KAZ",
    "KGZ",
    "LAO",
    "MNG",
    "MMR",
    "NPL",
    "PAK",
    "PRK",
    "RUS",
    "TJK",
    "VNM",
}


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate world-countries dataset")
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


def _ensure_output_dir(package_root: Path) -> Path:
    out_dir = package_root / "data" / "datasets" / "administrative" / "world-countries" / "land"
    out_dir.mkdir(parents=True, exist_ok=True)
    return out_dir


def _load_country_name_map(package_root: Path) -> dict[str, dict[str, str]]:
    mapping_path = package_root / "data" / "reference" / "country-name-map.json"
    with mapping_path.open(encoding="utf-8") as f:
        items = json.load(f)
    return {item["iso3"]: item for item in items}


def _load_china_geometry(package_root: Path):
    china_path = package_root / "data" / "datasets" / "administrative" / "amap" / "land" / "100000.geojson"
    with china_path.open(encoding="utf-8") as f:
        return shape(json.load(f))


def _build_row_id(country_name: str, path: str) -> str:
    key = f"{country_name}|{LEVEL_NAME}|{SOURCE_NAME}|{KIND_NAME}|{path}"
    return hashlib.md5(key.encode("utf-8")).hexdigest()


def _load_member_states(world_shp: Path) -> gpd.GeoDataFrame:
    gdf = gpd.read_file(world_shp)
    gdf = gdf[gdf["status"] == "Member State"].copy()
    gdf = gdf[gdf["iso3"].notna()].copy()
    gdf = gdf[~gdf["iso3"].isin(EXCLUDED_ISO3)].copy()
    return gdf[["iso3", "name", "geometry"]].copy()


def _apply_china_difference(gdf: gpd.GeoDataFrame, china_geom) -> gpd.GeoDataFrame:
    gdf = gdf.copy()
    gdf["geometry"] = [snap(geom, china_geom, SNAP_TOLERANCE).difference(china_geom) for geom in gdf.geometry]
    gdf = gdf[~gdf.geometry.is_empty].copy()
    return gdf


def _apply_chinese_names(gdf: gpd.GeoDataFrame, country_name_map: dict[str, dict[str, str]]) -> gpd.GeoDataFrame:
    gdf = gdf.copy()
    gdf = gdf.rename(columns={"name": "name_en"})
    missing = sorted({iso3 for iso3 in gdf["iso3"] if iso3 not in country_name_map})
    if missing:
        raise KeyError(f"Missing Chinese country names for ISO3 codes: {', '.join(missing)}")
    gdf["name"] = [country_name_map[iso3]["name"] for iso3 in gdf["iso3"]]
    return gdf


def _write_geojson(output_dir: Path, gdf: gpd.GeoDataFrame) -> list[tuple[str, str, str]]:
    records = []
    for row in gdf.itertuples():
        out_fp = output_dir / f"{row.iso3}.geojson"
        payload = {
            "type": "Feature",
            "properties": {
                "iso3": row.iso3,
                "name": row.name,
                "name_en": row.name_en,
                "source": SOURCE_NAME,
                "kind": KIND_NAME,
                "level": LEVEL_NAME,
            },
            "geometry": mapping(row.geometry),
        }
        with out_fp.open("w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, separators=(",", ":"))

        relative_path = f"administrative/world-countries/land/{row.iso3}.geojson"
        records.append((row.iso3, row.name, relative_path))
    return records


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

    country_name_map = _load_country_name_map(package_root)
    china_geom = _load_china_geometry(package_root)
    gdf = _load_member_states(world_shp)
    gdf = _apply_china_difference(gdf, china_geom)
    gdf = _apply_chinese_names(gdf, country_name_map)
    output_dir = _ensure_output_dir(package_root)
    records = _write_geojson(output_dir, gdf)
    _update_index_db(package_root, records)

    print(f"Generated {len(records)} world-countries records into {output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
