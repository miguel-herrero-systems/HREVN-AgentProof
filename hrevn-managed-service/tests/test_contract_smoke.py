from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"

if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


from hrevn_managed_service.adapters.generator_adapter import new_bundle_id
from hrevn_managed_service.config import settings
from hrevn_managed_service.services.storage import bundle_path, bundles_dir


def test_bundle_contract_smoke_paths_and_ids():
    bundle_id = new_bundle_id()

    assert bundle_id.startswith("BND-")
    assert bundles_dir().exists()
    assert bundle_path(bundle_id) == settings.bundles_dir / f"{bundle_id}.zip"
