from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import os

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = Path(os.getenv("GLM_DATA_DIR", ROOT / "data"))
RAW_DIR = DATA_DIR / "raw"
PROCESSED_DIR = DATA_DIR / "processed"
MUNICIPALITIES_DIR = DATA_DIR / "municipalities"

GLM_PRODUCT = "GLM-L2-LCFA"
GOES19_OPERATIONAL_UTC = datetime(2025, 4, 7, 15, 10, tzinfo=timezone.utc)
DEFAULT_MUNICIPALITY_YEAR = int(os.getenv("GLM_MUNICIPALITY_YEAR", "2025"))
DEFAULT_COMPLETENESS_THRESHOLD = float(os.getenv("GLM_COMPLETENESS_THRESHOLD", "0.90"))


@dataclass(frozen=True)
class EarthEngineSettings:
    project: str | None = os.getenv("EE_PROJECT")
    municipalities_asset: str | None = os.getenv("EE_MUNICIPALITIES_ASSET")
    service_account: str | None = os.getenv("EE_SERVICE_ACCOUNT")
    private_key_json: str | None = os.getenv("EE_PRIVATE_KEY_JSON")


EE_SETTINGS = EarthEngineSettings()
