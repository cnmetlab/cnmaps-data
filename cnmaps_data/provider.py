"""Provider implementation for the official cnmaps data package."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class CnmapsDataProvider:
    """File-system provider for packaged cnmaps datasets."""

    package_root: Path

    @property
    def manifest_path(self) -> Path:
        return self.package_root / "manifest.json"

    @property
    def manifest(self) -> dict:
        with self.manifest_path.open(encoding="utf-8") as f:
            return json.load(f)

    @property
    def name(self) -> str:
        return self.manifest["name"]

    @property
    def version(self) -> str:
        return self.manifest["version"]

    def get_dataset_root(self, dataset: str) -> str:
        dataset_meta = self.manifest["datasets"][dataset]
        return str((self.package_root / dataset_meta["root"]).resolve())

    def get_index_db(self, dataset: str = "administrative") -> str:
        dataset_meta = self.manifest["datasets"][dataset]
        return str((self.package_root / dataset_meta["index_db"]).resolve())

    def get_sample_path(self, filename: str) -> str:
        return str((Path(self.get_dataset_root("sample")) / filename).resolve())

    def resolve_dataset_path(self, dataset: str, relative_path: str) -> str:
        relative = Path(relative_path)
        relative_parts = relative.parts
        if relative_parts and relative_parts[0] == dataset:
            relative = Path(*relative_parts[1:])
        return str((Path(self.get_dataset_root(dataset)) / relative).resolve())


def get_provider() -> CnmapsDataProvider:
    """Return the official cnmaps data provider."""

    return CnmapsDataProvider(package_root=Path(__file__).resolve().parent)
