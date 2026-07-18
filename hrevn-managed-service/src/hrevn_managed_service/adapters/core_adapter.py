from __future__ import annotations

from pathlib import Path
import sys

from ..config import settings


def _ensure_core_path() -> None:
    core_src = str(Path(settings.core_src))
    if core_src not in sys.path:
        sys.path.insert(0, core_src)


def build_baseline_engine():
    _ensure_core_path()
    from hrevn_core.baseline import BaselineEngine

    return BaselineEngine()


def get_core_version() -> str:
    _ensure_core_path()
    try:
        import hrevn_core
        return getattr(hrevn_core, "__version__", "unknown")
    except Exception:
        return "unknown"

