from datetime import datetime, timezone
from pathlib import Path
import sys
import pandas as pd
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.glm_aws import satellite_for_datetime, parse_key_start_time
from src.statistics import monthly_anomalies


def test_satellite_transition():
    assert satellite_for_datetime(datetime(2025,4,7,15,9,59,tzinfo=timezone.utc)) == "16"
    assert satellite_for_datetime(datetime(2025,4,7,15,10,0,tzinfo=timezone.utc)) == "19"


def test_parse_filename_timestamp():
    k="GLM-L2-LCFA/2025/317/03/OR_GLM-L2-LCFA_G19_s20253170330200_e20253170330220_c20253170330230.nc"
    dt=parse_key_start_time(k)
    assert dt.year==2025 and dt.timetuple().tm_yday==317 and dt.hour==3 and dt.minute==30 and dt.second==20


def test_anomaly_formula():
    keys=dict(code_muni="1",name_muni="A",abbrev_state="XX",area_muni_km2=100.0,month=1)
    monthly=pd.DataFrame([{**keys,"year":2025,"flash_count":120,"flash_density_km2":1.2}])
    clim=pd.DataFrame([{**keys,"flash_count_mean":100,"flash_count_std":10,
                        "flash_density_km2_mean":1.0,"flash_density_km2_std":0.1}])
    out=monthly_anomalies(monthly,clim).iloc[0]
    assert out.flash_count_anom == 20
    assert out.flash_count_anom_pct == 20
    assert out.flash_count_z == 2


def test_area_m2_to_km2():
    import numpy as np
    from src.glm_reader import _normalize_area
    out = _normalize_area(np.array([1_000_000.0, 2_500_000.0]), "square meters")
    assert np.allclose(out, [1.0, 2.5])
