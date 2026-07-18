from __future__ import annotations

from pathlib import Path

from ..config import settings


def bundles_dir() -> Path:
    settings.bundles_dir.mkdir(parents=True, exist_ok=True)
    return settings.bundles_dir


def bundle_path(bundle_id: str) -> Path:
    return bundles_dir() / f"{bundle_id}.zip"
