"""Update packaged country names from the reference mapping table."""

from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path


SOURCE_NAME = "世界银行"


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Update country names from mapping table")
    parser.add_argument(
        "--package-root",
        default=str(Path(__file__).resolve().parents[1] / "cnmaps_data"),
        help="Path to the cnmaps_data package root",
    )
    return parser


def _load_country_name_map(package_root: Path) -> dict[str, dict[str, str]]:
    mapping_path = package_root / "data" / "reference" / "country-name-map.json"
    with mapping_path.open(encoding="utf-8") as f:
        items = json.load(f)
    return {item["iso3"]: item for item in items}


def _update_geojson_names(package_root: Path, mapping_table: dict[str, dict[str, str]]) -> int:
    updated = 0
    datasets_root = package_root / "data" / "datasets" / "administrative"
    for source_dir in ("cn-neighbors", "world-countries"):
        land_dir = datasets_root / source_dir / "land"
        for fp in land_dir.glob("*.geojson"):
            payload = json.loads(fp.read_text(encoding="utf-8"))
            props = payload.get("properties", {})
            iso3 = props.get("iso3") or fp.stem
            mapping_info = mapping_table.get(iso3)
            if mapping_info is None:
                continue
            props["name"] = mapping_info["name"]
            props["name_en"] = mapping_info["name_en"]
            payload["properties"] = props
            fp.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
            updated += 1
    return updated


def _update_index_db(package_root: Path, mapping_table: dict[str, dict[str, str]]) -> int:
    db_path = package_root / "data" / "index" / "administrative.db"
    con = sqlite3.connect(db_path)
    updated = 0
    try:
        cur = con.cursor()
        rows = cur.execute(
            "SELECT rowid, iso3, path FROM ADMINISTRATIVE WHERE source = ? AND path LIKE 'administrative/%/land/%.geojson'",
            (SOURCE_NAME,),
        ).fetchall()
        for rowid, iso3, path in rows:
            iso3 = (iso3 or Path(path).stem).upper()
            mapping_info = mapping_table.get(iso3)
            if mapping_info is None:
                continue
            cur.execute("UPDATE ADMINISTRATIVE SET country = ? WHERE rowid = ?", (mapping_info["name"], rowid))
            updated += 1
        con.commit()
    finally:
        con.close()
    return updated


def main() -> int:
    parser = build_arg_parser()
    args = parser.parse_args()

    package_root = Path(args.package_root).expanduser().resolve()
    mapping_table = _load_country_name_map(package_root)
    geojson_updates = _update_geojson_names(package_root, mapping_table)
    db_updates = _update_index_db(package_root, mapping_table)

    print(f"Updated {geojson_updates} GeoJSON files and {db_updates} SQLite rows")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
