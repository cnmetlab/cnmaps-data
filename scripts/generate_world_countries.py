"""Generate non-neighbor world country boundaries for cnmaps-data."""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from pathlib import Path

import geopandas as gpd
import pandas as pd
from shapely import snap
from shapely.geometry import box, mapping
from shapely.geometry import shape
from tqdm import tqdm


SOURCE_NAME = "世界银行"
LEVEL_NAME = "国"
KIND_NAME = "陆地"
SNAP_TOLERANCE = 1e-8
CLIP_WINDOW_MARGIN = 2.0
SNAP_REFERENCE_SIMPLIFY_TOLERANCE = 0.01
PATH_PREFIX = "administrative/world-countries/land/"
WB_STATUS_MEMBER_LIKE = {
    "Member State",
    "Territory",
    "Non Member State",
    "Special Administrative Region",
}
EXCLUDED_ISO3 = {
    "CHN",
    "TWN",
    "HKG",
    "MAC",
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

CHINA_RELATED_DISPUTED_ASSIGNMENTS = {
    "Aksai Chin",
    "Arunachal Pradesh",
    "Chumar East",
    "Chumar West",
    "Demchok",
    "Doklam",
    "Jadh Ganga Valley",
    "Karakoram Range",
    "Lapthal",
    "Shipki Pass",
}

CHINA_DISPUTED_DEDUCTION_NAMES = set(CHINA_RELATED_DISPUTED_ASSIGNMENTS)

NON_CHINA_DISPUTED_AREAS = {
    "Abyei": ("SDN-SSD", "Abyei"),
    "Gilgit Baltistan": ("IND-PAK-GB", "Gilgit Baltistan"),
    "Golan Heights": ("ISR-SYR", "Golan Heights"),
    "Ilemi Triangle": ("KEN-SSD", "Ilemi Triangle"),
    "Jammu and Kashmir": ("IND-PAK-JK", "Jammu and Kashmir"),
    "Kalapani": ("IND-NPL", "Kalapani"),
    "Kauirik\r\n": ("GUY-VEN", "Kauirik"),
    "No Man's Land": ("EGY-SDN", "No Man's Land"),
    "Shebaa Farms Dispute": ("ISR-LBN", "Shebaa Farms Dispute"),
    "UN Buffer Zone": ("CYP-TUR", "UN Buffer Zone"),
}

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


def _load_china_geometry(package_root: Path):
    china_path = package_root / "data" / "datasets" / "administrative" / "amap" / "land" / "100000.geojson"
    with china_path.open(encoding="utf-8") as f:
        return shape(json.load(f))


def _build_row_id(country_name: str, iso3: str, path: str) -> str:
    key = f"{country_name}|{iso3}|{LEVEL_NAME}|{SOURCE_NAME}|{KIND_NAME}|{path}"
    return hashlib.md5(key.encode("utf-8")).hexdigest()


def _load_member_states(world_shp: Path) -> gpd.GeoDataFrame:
    gdf = gpd.read_file(world_shp)
    base = gdf[gdf["WB_STATUS"].isin(WB_STATUS_MEMBER_LIKE)].copy()
    base = base[base["ISO_A3"].notna()].copy()
    base = base[~base["ISO_A3"].isin(EXCLUDED_ISO3)].copy()
    base = base[["ISO_A3", "NAM_0", "geometry"]].rename(columns={"ISO_A3": "iso3", "NAM_0": "name"})

    disputed = gdf[gdf["WB_STATUS"] == "Non-determined legal status area"].copy()
    disputed = disputed[~disputed["NAM_0"].isin(CHINA_RELATED_DISPUTED_ASSIGNMENTS)].copy()

    dispute_rows = []
    for row in disputed.itertuples():
        if pd.notna(row.ISO_A3) and row.ISO_A3 not in EXCLUDED_ISO3:
            dispute_rows.append({"iso3": row.ISO_A3, "name": row.NAM_0, "geometry": row.geometry})
            continue
        mapped = NON_CHINA_DISPUTED_AREAS.get(row.NAM_0)
        if mapped is None:
            continue
        dispute_rows.append({"iso3": mapped[0], "name": mapped[1], "geometry": row.geometry})

    if dispute_rows:
        dispute_gdf = gpd.GeoDataFrame(dispute_rows, crs=gdf.crs)
        gdf = gpd.GeoDataFrame(
            pd.concat([base, dispute_gdf], ignore_index=True),
            crs=gdf.crs,
        )
    else:
        gdf = gpd.GeoDataFrame(base, crs=gdf.crs)

    return _merge_by_iso3(gdf)


def _merge_by_iso3(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    rows = []
    grouped = list(gdf.groupby("iso3", sort=True))
    for iso3, group in tqdm(
        grouped,
        total=len(grouped),
        desc="合并世界国家几何",
        unit="country",
    ):
        display_name = sorted(group["name"].dropna().astype(str))[0]
        rows.append(
            {
                "iso3": iso3,
                "name": display_name,
                "geometry": group.geometry.union_all(),
            }
        )
    return gpd.GeoDataFrame(rows, crs=gdf.crs)


def _load_china_claims_geometry(world_shp: Path, china_geom):
    gdf = gpd.read_file(world_shp)[["WB_STATUS", "NAM_0", "geometry"]].copy()
    disputed = gdf[
        (gdf["WB_STATUS"] == "Non-determined legal status area")
        & (gdf["NAM_0"].isin(CHINA_DISPUTED_DEDUCTION_NAMES))
    ].copy()
    if disputed.empty:
        return china_geom
    return china_geom.union(disputed.geometry.union_all())


def _apply_china_difference(gdf: gpd.GeoDataFrame, china_claims_geom) -> gpd.GeoDataFrame:
    gdf = gdf.copy()
    china_bounds = china_claims_geom.bounds
    clip_window = _build_clip_window(china_bounds)
    snap_reference = china_claims_geom.simplify(SNAP_REFERENCE_SIMPLIFY_TOLERANCE, preserve_topology=True)
    geometries = []
    for geom in tqdm(
        gdf.geometry,
        total=len(gdf),
        desc="裁剪与吸附世界边界",
        unit="country",
    ):
        if _intersects_bounds(geom, china_bounds):
            near = geom.intersection(clip_window)
            if near.is_empty:
                geometries.append(geom)
                continue
            far = geom.difference(clip_window)
            near = snap(near, snap_reference, SNAP_TOLERANCE).difference(china_claims_geom)
            geom = far.union(near)
        geometries.append(geom)
    gdf["geometry"] = geometries
    gdf = gdf[~gdf.geometry.is_empty].copy()
    return gdf


def _write_geojson(output_dir: Path, gdf: gpd.GeoDataFrame) -> list[tuple[str, str, str]]:
    records = []
    for fp in output_dir.glob("*.geojson"):
        fp.unlink()
    for row in tqdm(
        gdf.itertuples(),
        total=len(gdf),
        desc="写出世界 GeoJSON",
        unit="country",
    ):
        out_fp = output_dir / f"{row.iso3}.geojson"
        payload = {
            "type": "Feature",
            "properties": {
                "iso3": row.iso3,
                "name": row.name,
                "name_en": row.name,
                "source": SOURCE_NAME,
                "kind": KIND_NAME,
                "level": LEVEL_NAME,
            },
            "geometry": mapping(row.geometry),
        }
        payload = _round_geojson_value(payload)
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
                desc="写入世界索引",
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
    china_claims_geom = _load_china_claims_geometry(world_shp, china_geom)
    gdf = _load_member_states(world_shp)
    gdf = _apply_china_difference(gdf, china_claims_geom)
    output_dir = _ensure_output_dir(package_root)
    records = _write_geojson(output_dir, gdf)
    _update_index_db(package_root, records)

    print(f"Generated {len(records)} world-countries records into {output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
