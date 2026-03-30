"""Generate CN-official derived neighboring country boundaries."""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from pathlib import Path

import geopandas as gpd
from shapely import snap
from shapely.geometry import box, mapping, shape
from tqdm import tqdm


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

WB_STATUS_MEMBER_LIKE = {
    "Member State",
    "Territory",
    "Non Member State",
    "Special Administrative Region",
}

CHINA_RELATED_DISPUTED_ASSIGNMENTS = {
    "Aksai Chin": "IND",
    "Arunachal Pradesh": "IND",
    "Chumar East": "IND",
    "Chumar West": "IND",
    "Demchok": "IND",
    "Doklam": "BTN",
    "Jadh Ganga Valley": "IND",
    "Karakoram Range": "IND",
    "Lapthal": "IND",
    "Shipki Pass": "IND",
}

CHINA_DISPUTED_DEDUCTION_NAMES = set(CHINA_RELATED_DISPUTED_ASSIGNMENTS)

SOURCE_NAME = "世界银行"
KIND_NAME = "陆地"
LEVEL_NAME = "国"
SNAP_TOLERANCE = 1e-8
CLIP_WINDOW_MARGIN = 2.0
SNAP_REFERENCE_SIMPLIFY_TOLERANCE = 0.01
PATH_PREFIX = "administrative/cn-neighbors/land/"
COORD_DECIMALS = 5


def _round_geojson_value(value):
    if isinstance(value, float):
        return round(value, COORD_DECIMALS)
    if isinstance(value, (list, tuple)):
        return [_round_geojson_value(item) for item in value]
    if isinstance(value, dict):
        return {key: _round_geojson_value(item) for key, item in value.items()}
    return value


def _intersects_bounds(geom, ref_bounds: tuple[float, float, float, float]) -> bool:
    minx, miny, maxx, maxy = geom.bounds
    rminx, rminy, rmaxx, rmaxy = ref_bounds
    return not (maxx < rminx or maxy < rminy or minx > rmaxx or miny > rmaxy)


def _build_clip_window(ref_bounds: tuple[float, float, float, float]):
    minx, miny, maxx, maxy = ref_bounds
    return box(
        minx - CLIP_WINDOW_MARGIN,
        miny - CLIP_WINDOW_MARGIN,
        maxx + CLIP_WINDOW_MARGIN,
        maxy + CLIP_WINDOW_MARGIN,
    )


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
    return gdf[["ISO_A3", "WB_STATUS", "SOVEREIGN", "NAM_0", "geometry"]].copy()


def _load_china_claims_geometry(gdf: gpd.GeoDataFrame, china_geom):
    disputed = gdf[
        (gdf["WB_STATUS"] == "Non-determined legal status area")
        & (gdf["NAM_0"].isin(CHINA_DISPUTED_DEDUCTION_NAMES))
    ].copy()
    if disputed.empty:
        return china_geom
    return china_geom.union(disputed.geometry.union_all())


def _build_adjusted_member_geometries(gdf: gpd.GeoDataFrame, china_claims_geom):
    members = gdf[gdf["WB_STATUS"].isin(WB_STATUS_MEMBER_LIKE)][["ISO_A3", "NAM_0", "geometry"]].copy()
    members = members[members["ISO_A3"].isin(NEIGHBOR_COUNTRIES)].copy()
    disputed = gdf[gdf["WB_STATUS"] == "Non-determined legal status area"][["NAM_0", "geometry"]].copy()
    china_bounds = china_claims_geom.bounds
    clip_window = _build_clip_window(china_bounds)
    snap_reference = china_claims_geom.simplify(SNAP_REFERENCE_SIMPLIFY_TOLERANCE, preserve_topology=True)

    adjusted = {row.ISO_A3: row.geometry for row in members.itertuples()}
    for row in tqdm(
        disputed.itertuples(),
        total=len(disputed),
        desc="合并邻国争议区",
        unit="feature",
    ):
        target_iso3 = CHINA_RELATED_DISPUTED_ASSIGNMENTS.get(row.NAM_0)
        if target_iso3 is None:
            continue
        adjusted[target_iso3] = adjusted[target_iso3].union(row.geometry)

    for row in tqdm(
        members.itertuples(),
        total=len(members),
        desc="裁剪与吸附邻国边界",
        unit="country",
    ):
        geom = adjusted[row.ISO_A3]
        if _intersects_bounds(geom, china_bounds):
            near = geom.intersection(clip_window)
            if near.is_empty:
                adjusted[row.ISO_A3] = geom
                continue
            far = geom.difference(clip_window)
            near = snap(near, snap_reference, SNAP_TOLERANCE).difference(china_claims_geom)
            geom = far.union(near)
        adjusted[row.ISO_A3] = geom
    english_names = {row.ISO_A3: row.NAM_0 for row in members.itertuples()}

    return adjusted, english_names


def _write_geojson_files(
    output_dir: Path,
    adjusted: dict,
    english_names: dict,
) -> list[tuple[str, str]]:
    records = []
    for fp in output_dir.glob("*.geojson"):
        fp.unlink()
    for iso3, country_cn in tqdm(
        sorted(NEIGHBOR_COUNTRIES.items()),
        total=len(NEIGHBOR_COUNTRIES),
        desc="写出邻国 GeoJSON",
        unit="country",
    ):
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
        payload = _round_geojson_value(payload)
        with out_fp.open("w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, separators=(",", ":"))

        relative_path = f"administrative/cn-neighbors/land/{iso3}.geojson"
        records.append((iso3, country_cn, relative_path))

    return records


def _build_row_id(country_name: str, iso3: str, path: str) -> str:
    key = f"{country_name}|{iso3}|{LEVEL_NAME}|{SOURCE_NAME}|{KIND_NAME}|{path}"
    return hashlib.md5(key.encode("utf-8")).hexdigest()


def _update_index_db(package_root: Path, records: list[tuple[str, str, str]]) -> None:
    db_path = package_root / "data" / "index" / "administrative.db"
    con = sqlite3.connect(db_path)
    try:
        cur = con.cursor()
        cur.execute("DELETE FROM ADMINISTRATIVE WHERE path LIKE ?", (f"{PATH_PREFIX}%",))
        rows = [
            (
                _build_row_id(country_name, iso3, path),
                country_name,
                iso3,
                path,
                LEVEL_NAME,
                SOURCE_NAME,
                KIND_NAME,
            )
            for iso3, country_name, path in records
        ]
        cur.executemany(
            """
            INSERT INTO ADMINISTRATIVE
            (id, country, iso3, province, city, district, path, level, source, kind)
            VALUES (?, ?, ?, NULL, NULL, NULL, ?, ?, ?, ?)
            """,
            tqdm(
                rows,
                total=len(rows),
                desc="写入邻国索引",
                unit="row",
            ),
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
    china_claims_geom = _load_china_claims_geometry(world_gdf, china_geom)
    adjusted, english_names = _build_adjusted_member_geometries(world_gdf, china_claims_geom)
    output_dir = _ensure_output_dir(package_root)
    records = _write_geojson_files(output_dir, adjusted, english_names)
    _update_index_db(package_root, records)

    print(f"Generated {len(records)} cn-neighbors records into {output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
